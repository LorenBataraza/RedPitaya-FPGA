"""Hilo escritor: un .npz por chunk de N eventos.

Decisiones, todas apoyadas en medicion (ver docs/arquitectura_adquisicion_software.md):

- **Sin comprimir.** Medido en la placa: `savez` 86 ms para 1.07 MB (12.4 MB/s)
  contra `savez_compressed` 628 ms para 0.95 MB. **7.3x mas tiempo por 12% de
  espacio.** Ademas comprimir es CPU con el GIL disputado, mientras que escribir
  es I/O con el GIL suelto.
- **float32 -> int16 aca, no en el lector.** La API del `rp` solo entrega volts
  en float (no hay variantes *NP y el binding de `rp_AcqGetDataPosRaw` esta
  roto), pero el ADC es de 14 bits: guardar float32 seria el doble de disco por
  nada. La conversion vive en este hilo, que tiene tiempo de sobra.
- **Escritura atomica** (`.tmp` + `os.replace`): todo archivo visible en el
  directorio esta completo. Es la condicion para que el futuro *file pusher*
  pueda consumir el directorio sin carreras.
"""

import os
import queue
import threading
import time

import numpy as np

from .events import SCHEMA_VERSION

MIN_FREE_MB = 200.0            # margen de disco antes de parar limpio


def free_space_mb(path):
    st = os.statvfs(path)
    return (st.f_bavail * st.f_frsize) / 1024**2


def load_chunk(path):
    """Lee un chunk y devuelve (arrays, meta) con la onda ya en volts.

    Puente de compatibilidad: el formato guarda `wave` como (eventos, canal,
    muestra) en cuentas, mientras que `datos/plot_datos.py` y el tooling viejo
    esperan un array por canal en volts. Esto expone las dos vistas.
    """
    z    = np.load(path, allow_pickle=True)
    meta = z['meta'].item() if 'meta' in z.files else {}
    out  = {k: z[k] for k in z.files if k not in ('meta',)}
    scale = meta.get('adc_cnt_per_V') or 8192
    if 'wave' in out and np.issubdtype(out['wave'].dtype, np.integer):
        out['wave_V'] = out['wave'].astype(np.float32) / scale
    else:
        out['wave_V'] = out.get('wave')
    for k, ch in enumerate(meta.get('channels', [])):
        out[f'd{ch}'] = out['wave_V'][:, k, :]
    return out, meta


class ChunkWriter(threading.Thread):
    """Consumidor: batches de `full_q` -> chunk_%06d.npz -> batch a `free_q`."""

    def __init__(self, run_dir, free_q, full_q, stats, meta_base=None,
                 compress=False, wave_dtype=np.int16, wave_scale=8192,
                 min_free_mb=MIN_FREE_MB, disk_check_every=8,
                 name='mca-writer'):
        super().__init__(name=name, daemon=True)
        self.run_dir    = str(run_dir)
        self.free_q     = free_q
        self.full_q     = full_q
        self.stats      = stats
        self.meta_base  = dict(meta_base or {})
        self.compress   = compress
        self.wave_dtype = wave_dtype
        self.wave_scale = wave_scale
        self.min_free_mb = min_free_mb
        self.disk_check_every = disk_check_every

        self.index      = 0
        self.error      = None
        self.disk_full  = threading.Event()   # lo mira la sesion para parar
        os.makedirs(self.run_dir, exist_ok=True)

    def run(self):
        try:
            self._loop()
        except BaseException as exc:
            self.error = exc
            self.stats['error'] = repr(exc)

    def _loop(self):
        while True:
            batch = self.full_q.get()
            if batch is None:                  # centinela del lector
                break
            try:
                if batch.n:
                    self._write(batch)
            finally:
                batch.reset()
                self.free_q.put(batch)         # devolver SIEMPRE, aun si fallo

            if (self.index % self.disk_check_every == 0
                    and free_space_mb(self.run_dir) < self.min_free_mb):
                self.stats['disk_full'] = True
                self.disk_full.set()
                break

        # Si se corta por disco, hay que seguir drenando o el lector se traba
        # esperando lugar en full_q.
        while True:
            try:
                b = self.full_q.get_nowait()
            except queue.Empty:
                break
            if b is not None:
                b.reset()
                self.free_q.put(b)

    def _write(self, batch):
        t0      = time.perf_counter_ns()
        payload = batch.payload(wave_dtype=self.wave_dtype,
                                wave_scale=self.wave_scale)
        meta    = dict(self.meta_base)
        meta.update(
            schema_version = SCHEMA_VERSION,
            fields         = list(batch.field_names),
            chunk_index    = self.index,
            chunk_events   = int(batch.n),
            # Exacto aunque `gap` sature: el lector lo acumula sin techo.
            chunk_dropped  = int(batch.dropped),
            chunk_gap_sum  = int(batch.gap[:batch.n].sum()),
            t_first_ns     = int(batch.t_ns[0]),
            t_last_ns      = int(batch.t_ns[batch.n - 1]),
            t_wall         = time.time(),
            wave_dtype     = np.dtype(self.wave_dtype).name,
            adc_cnt_per_V  = self.wave_scale,
            # snapshot acumulado: diferenciando entre chunks se ve donde hubo
            # descartes aunque no se abra el archivo entero.
            n_read         = int(self.stats.get('n_read', 0)),
            n_dropped      = int(self.stats.get('n_dropped', 0)),
            n_timeouts     = int(self.stats.get('n_timeouts', 0)),
        )
        payload['meta'] = np.array(meta, dtype=object)   # dict -> array 0-d

        name = f'chunk_{self.index:06d}.npz'
        path = os.path.join(self.run_dir, name)
        tmp  = path + '.tmp'
        save = np.savez_compressed if self.compress else np.savez
        try:
            # Se le pasa un HANDLE y no el path: np.savez le agrega '.npz' al
            # nombre si no termina asi, y terminariamos con 'chunk.npz.tmp.npz'.
            with open(tmp, 'wb') as fh:
                save(fh, **payload)
            os.replace(tmp, path)              # atomico: nunca un .npz a medias
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

        self.index += 1
        self.stats['n_written']   += int(batch.n)
        self.stats['chunks']       = self.index
        self.stats['last_write_ms'] = (time.perf_counter_ns() - t0) / 1e6

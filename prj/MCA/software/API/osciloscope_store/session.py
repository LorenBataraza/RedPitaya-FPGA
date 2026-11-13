"""Orquestador: arma el pipeline, lo corre y lo cierra limpio.

    fuente + annotators
        -> esquema del batch
        -> pool preasignado (derivado de un presupuesto de RAM)
        -> hilo lector  --full_q-->  hilo escritor
                        <--free_q--

Sin `os.chdir` (lo usa `guardado_mariana.py:106`): cambia estado global del
proceso y es incompatible con hilos. Todo con rutas absolutas.
"""

import os
import queue
import sys
import threading
import time

import numpy as np

from API.multitrigger import (R_FLAGS, R_OR_MASK_CH0, R_OR_MASK_CH1,
                              R_SHIELD_CFG, R_SHIELD_RUN, R_TRIG_SNAP)

from .annotators import merge_fields
from .events import batches_for_budget, bytes_per_event, make_pool
from .reader import ReaderThread
from .storage import ChunkWriter

# Stall maximo del lector medido con el escritor de fondo: 5288 us, que es
# exactamente sys.getswitchinterval() (5000 us por default). Es la firma de
# libro de la contencion de GIL: un hilo que lo toma solo lo suelta al vencer el
# intervalo. Bajarlo acota el stall al valor elegido; el costo son mas cambios
# de contexto, irrelevante con dos hilos. Ver el doc, Parte 3.
SWITCH_INTERVAL_S = 0.001


def scope_regs(sc):
    """Snapshot de los registros clave del scope, para la meta de la corrida.

    Estaba duplicado en tres notebooks (multitrigger_test_adq_dg4162,
    multitrigger_test_deadtime, _pitaya_run); vive aca y se importa.

    El shield, el snapshot, las banderas y las mascaras estan en el slot 3
    (`sc.mt`); en el slot 1 esas direcciones leen 0 sin dar error. `mask_ch*` es
    lo escrito (`trg_src_stored`), no la mascara activa: esa se borra al disparar.

    Lleva tambien lo que deja `rp_Init()` y el armado no toca: el filtro de
    ecualizacion (`filt_*`, con los coeficientes de la EEPROM para LV), su bypass,
    el promediado y la calibracion en la FPGA. Con el bitstream del MCA el
    ecualizador no esta en el camino (EN_FILT = 0): sus coeficientes no cambian
    las muestras.
    """
    mt = sc.mt
    return dict(
        adc_state=sc.r32(0x00),  trg_state=sc.r32(0x04),
        thr_ch0=sc.r32(0x08),    thr_ch1=sc.r32(0x0C),
        dly_ch0=sc.r32(0x10),    dly_ch1=sc.r32(0x110),
        dec_ch0=sc.r32(0x14),    dec_ch1=sc.r32(0x114),
        hyst_ch0=sc.r32(0x20),   hyst_ch1=sc.r32(0x24),
        shield=mt.r32(R_SHIELD_CFG),    shield_rt=mt.r32(R_SHIELD_RUN),
        snapshot=mt.r32(R_TRIG_SNAP),   dis_we=mt.r32(R_FLAGS),
        mask_ch0=mt.r32(R_OR_MASK_CH0), mask_ch1=mt.r32(R_OR_MASK_CH1),
        wp_trig0=sc.r32(0x1C),   wp_trig1=sc.r32(0x11C),
        wp_cur0=sc.r32(0x18),    wp_cur1=sc.r32(0x118),
        we_cnt0=sc.r32(0x02C),   we_cnt1=sc.r32(0x12C),
        deb_len=sc.r32(0x90),
        avg_en=sc.r32(0x28),     filt_byp=sc.r32(0x98),
        filt_aa_ch0=sc.r32(0x30), filt_bb_ch0=sc.r32(0x34),
        filt_kk_ch0=sc.r32(0x38), filt_pp_ch0=sc.r32(0x3C),
        filt_aa_ch1=sc.r32(0x40), filt_bb_ch1=sc.r32(0x44),
        filt_kk_ch1=sc.r32(0x48), filt_pp_ch1=sc.r32(0x4C),
        calib_off_ch0=sc.r32(0x200), calib_gain_ch0=sc.r32(0x204),
        calib_off_ch1=sc.r32(0x208), calib_gain_ch1=sc.r32(0x20C),
    )


class AcquisitionSession:
    """Una corrida completa: pool, hilos, estadisticas y apagado ordenado.

    Uso:
        with AcquisitionSession(source, run_dir) as s:
            s.wait(duration_s=30)
        print(s.stats)
    """

    def __init__(self, source, run_dir, capacity=4096, ram_budget_mb=64,
                 annotators=(), compress=False, wave_dtype=np.int16,
                 meta=None, poll_timeout_s=1.0, set_switch_interval=True,
                 verbose=True, formato='npz'):
        self.source     = source
        self.run_dir    = os.path.abspath(str(run_dir))
        self.annotators = tuple(annotators)
        self.verbose    = verbose

        fields = merge_fields(source, self.annotators)
        n_ch, S = source.n_ch, source.samples
        # El tipo de la onda EN RAM es el de la fuente: `BramSource` entrega cuentas
        # calibradas en int16, y entonces el escritor no convierte nada. `FakeSource`
        # entrega volts en float32, que el escritor pasa a cuentas como siempre.
        onda = np.dtype(getattr(source, 'wave_dtype', np.float32))
        n_batches = batches_for_budget(ram_budget_mb, capacity, n_ch, S, fields, onda)

        self.capacity  = capacity
        self.n_batches = n_batches
        self.b_ev      = bytes_per_event(n_ch, S, fields, onda)

        self.free_q = queue.Queue()
        self.full_q = queue.Queue()
        for b in make_pool(n_batches, capacity, n_ch, S, fields, onda):
            self.free_q.put(b)

        self.stats = dict(n_read=0, n_dropped=0, n_timeouts=0, n_written=0,
                          chunks=0)

        meta_base = dict(meta or {})
        meta_base.setdefault('source', source.meta())
        meta_base.setdefault('channels', list(range(1, n_ch + 1)))
        meta_base.setdefault('annotators',
                             [a.meta() for a in self.annotators])
        meta_base.setdefault('capacity', capacity)

        self.writer = ChunkWriter(self.run_dir, self.free_q, self.full_q,
                                  self.stats, meta_base=meta_base,
                                  compress=compress, wave_dtype=wave_dtype,
                                  wave_scale=source.meta().get('adc_cnt_per_V',
                                                               8192),
                                  formato=formato)
        self.reader = ReaderThread(source, self.free_q, self.full_q, self.stats,
                                   annotators=self.annotators,
                                   poll_timeout_s=poll_timeout_s)

        self._prev_switch = sys.getswitchinterval()
        self._set_switch  = set_switch_interval
        self._started     = False

    # -- ciclo de vida ------------------------------------------------------

    def describe(self, rate_hz=None):
        """Texto con el presupuesto real, para imprimir al arrancar.

        La linea que importa es la profundidad de cola EN SEGUNDOS: es cuanto
        puede atrasarse el escritor sin que se pierda un solo evento.
        """
        depth = self.n_batches * self.capacity
        mb    = depth * self.b_ev / 1024**2
        txt = (f'  pool: {self.n_batches} batches x {self.capacity} ev = '
               f'{depth} eventos en vuelo ({mb:.2f} MB, {self.b_ev} B/ev)')
        if rate_hz:
            txt += f'\n  margen del escritor: {depth / rate_hz:.2f} s @ {rate_hz:.0f} ev/s'
        return txt

    def start(self):
        if self._started:
            return self
        if self._set_switch:
            sys.setswitchinterval(SWITCH_INTERVAL_S)
        os.makedirs(self.run_dir, exist_ok=True)
        for a in self.annotators:
            a.start()
        self.source.arm()
        self.writer.start()
        self.reader.start()
        self._started = True
        if self.verbose:
            print(f'  corriendo -> {self.run_dir}')
        return self

    def wait(self, duration_s=None, n_events=None, poll_s=0.2, on_tick=None):
        """Bloquea hasta cumplir la condicion, o hasta que algo falle.

        Devuelve el motivo de corte: 'duration' | 'events' | 'disk' | 'error' |
        'source'.
        """
        t0 = time.perf_counter()
        while True:
            m = self.motivo()
            if m in ('error', 'disk'):
                return m
            if duration_s is not None and time.perf_counter() - t0 >= duration_s:
                return 'duration'
            if n_events is not None and self.stats['n_read'] >= n_events:
                return 'events'
            if m is not None:              # el lector terminó solo
                return m
            if on_tick:
                on_tick(self.stats)
            time.sleep(poll_s)

    def motivo(self):
        """Por qué la corrida no puede seguir, sin bloquear: None mientras corre;
        'error' si se cayó un hilo, 'disk' si el escritor paró por falta de lugar,
        'source' si el lector terminó solo. Es lo que mira `wait`, y lo que consulta
        quien no se puede quedar esperando (el servidor, entre dos pedidos)."""
        if self.reader.error or self.writer.error:
            return 'error'
        if self.writer.disk_full.is_set():
            return 'disk'
        if not self.reader.is_alive():
            return 'error' if self.reader.error else 'source'
        return None

    def stop(self):
        """Apagado ordenado: lector -> centinela -> escritor -> HW."""
        if not self._started:
            return self.stats
        self.reader.stop()
        self.reader.join(timeout=10)       # el lector pone el centinela al salir
        self.writer.join(timeout=60)
        for a in self.annotators:
            a.stop()
        try:
            self.source.close()
        finally:
            if self._set_switch:
                sys.setswitchinterval(self._prev_switch)
        self._started = False

        t0, t1 = self.stats.get('t_start_ns'), self.stats.get('t_end_ns')
        if t0 and t1:
            self.stats['duration_s'] = (t1 - t0) / 1e9
            if self.stats['duration_s'] > 0:
                self.stats['rate_ev_s'] = (self.stats['n_read']
                                           / self.stats['duration_s'])
        self._write_summary()
        return self.stats

    def _write_summary(self):
        """`run_summary.json` con los totales finales de la corrida.

        Existe por una razon concreta: la columna `gap` cuenta los descartes que
        ocurrieron ENTRE dos eventos guardados, asi que los del FINAL de la
        corrida no tienen ningun evento posterior donde anotarse. El invariante
        completo es

            sum(gap sobre todos los chunks) + trailing_dropped == n_dropped

        y `trailing_dropped` sale de aca. Sin este archivo, una corrida que
        termina en medio de una rafaga de descartes no cierra las cuentas.
        """
        import json

        s = dict(self.stats)
        s['trailing_dropped'] = int(s.pop('pending_tail', 0))
        s['run_dir']  = self.run_dir
        s['source']   = self.source.meta()
        s['formato']  = self.writer.formato
        s['capacity'] = self.capacity
        s['n_batches'] = self.n_batches
        path = os.path.join(self.run_dir, 'run_summary.json')
        tmp  = path + '.tmp'
        try:
            with open(tmp, 'w') as fh:
                json.dump(s, fh, indent=2, default=str)
            os.replace(tmp, path)
        except OSError:
            pass                     # un resumen que no se puede escribir no
                                     # debe tumbar el cierre de la corrida

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False

    # -- reporte ------------------------------------------------------------

    def summary(self):
        s = self.stats
        dur = s.get('duration_s', 0.0)
        lines = [
            f'  eventos leidos   : {s["n_read"]}',
            f'  eventos escritos : {s["n_written"]} en {s["chunks"]} chunks',
            f'  descartados (SW) : {s["n_dropped"]}',
            f'  timeouts         : {s["n_timeouts"]}',
            f'  duracion         : {dur:.2f} s',
        ]
        if dur:
            lines.append(f'  tasa             : {s["n_read"]/dur:.0f} ev/s')
        if s['n_read'] + s['n_dropped']:
            frac = s['n_dropped'] / (s['n_read'] + s['n_dropped'])
            lines.append(f'  fraccion perdida : {frac*100:.2f} %'
                         + ('   <-- normalizar por tiempo vivo' if frac else ''))
        if s.get('error'):
            lines.append(f'  ERROR            : {s["error"]}')
        return '\n'.join(lines)

#!/usr/bin/env python3
"""`.npz` contra LH5: lo que cuesta escribir una corrida y lo que cuesta leerla.

`bench_escritura.py` mide un lote con un lector compitiendo por el GIL, que es lo que
decide los descartes. Este mide lo demás, para elegir formato por lo que se hace con
los archivos después. **No toca la PL**: escribe con el `ChunkWriter` real.

Cuatro variantes: `.npz` y LH5, cada uno sin comprimir (el default) y comprimido
(`savez_compressed` y gzip por dataset). La onda es sintética pero con la forma de la
real: ruido de 4.6 cuentas (el medido en la placa) y un pulso por evento de amplitud
al azar, en int16. El ruido uniforme de `bench_escritura.py` no se comprime, y esto sí.

Por cada largo de ventana, escribe una corrida de `--lotes` archivos y la lee de cuatro
maneras:

  todo      cada archivo entero, como `load_chunk`
  columnas  sólo `t_ns`, `snap` y `gap`, sin la onda: lo que usa un análisis de tasa
  pocos     `--pocos` eventos al azar de cada archivo, con su onda
  oficial   la corrida entera con `lh5.read` (sólo LH5, si está `legend-lh5io`)

La lectura es con los archivos en el caché del sistema, recién escritos: mide lo que
cuesta el formato, no el disco.

    python3 API/bench/bench_formatos.py --dir datos/bench_formatos
    python3 API/bench/bench_formatos.py --muestras 32,256,2048 --lotes 10
"""

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import time

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

from API.osciloscope_store.events import BASE_FIELDS, EventBatch     # noqa: E402
from API.osciloscope_store.storage import (ChunkWriter,              # noqa: E402
                                           archivos_de_corrida)

VARIANTES = (('npz', False), ('npz', True), ('lh5', False), ('lh5', True))
COLUMNAS = ('t_ns', 'snap', 'gap')
RUIDO_CUENTAS = 4.6
PERIODO_NS = 8.0


def nombre(formato, comprimir):
    return f'{formato}{"+gzip" if comprimir else ""}'


def lote(capacidad, n_ch, pre, post, semilla=1):
    """Ruido de la placa más un pulso por evento, disparado en `pre`."""
    muestras = pre + post
    b = EventBatch(capacidad, n_ch, muestras, BASE_FIELDS, wave_dtype=np.int16)
    rng = np.random.default_rng(semilla)
    t = np.arange(muestras) - pre
    forma = np.where(t >= 0, np.exp(-np.clip(t, 0, None) / 250.0)
                     - np.exp(-np.clip(t, 0, None) / 12.0), 0.0)
    forma /= max(forma.max(), 1e-9)
    amp = rng.uniform(300.0, 6000.0, (capacidad, n_ch, 1))
    w = amp * forma + rng.normal(0.0, RUIDO_CUENTAS, (capacidad, n_ch, muestras))
    b.wave[:] = np.clip(np.rint(w), -8192, 8191).astype(np.int16)
    b.t_ns[:] = np.cumsum(rng.exponential(50_000.0, capacidad)).astype(np.int64)
    b.wp[:] = np.arange(capacidad) % 16384
    b.snap[:] = 2
    b.gap[:] = rng.integers(0, 3, capacidad)
    b.n = capacidad
    return b


def escritor(carpeta, formato, comprimir, n_ch, pre, post):
    meta = dict(channels=list(range(1, n_ch + 1)), capacity=0,
                source=dict(kind='bench', pre=pre, post=post, samples=pre + post,
                            n_ch=n_ch, thr_V=0.2, hyst_V=0.02, mask=2, set_dly=post,
                            adc_cnt_per_V=8192, dt_ns=PERIODO_NS))
    return ChunkWriter(carpeta, None, None,
                       dict(n_read=0, n_dropped=0, n_timeouts=0, n_written=0, chunks=0),
                       meta_base=meta, formato=formato, compress=comprimir)


def escribir(carpeta, formato, comprimir, b, lotes, n_ch, pre, post):
    w = escritor(carpeta, formato, comprimir, n_ch, pre, post)
    tiempos = []
    for _ in range(lotes):
        t0 = time.perf_counter()
        w._write(b)
        tiempos.append(time.perf_counter() - t0)
    return tiempos


# ---- las cuatro lecturas ---------------------------------------------------------

def _npz(p):
    # sin allow_pickle: las columnas y la onda se leen sin él; sólo `meta` lo necesita
    return np.load(p, allow_pickle=False)


def leer_todo(archivos):
    n = 0
    for p in archivos:
        if p.endswith('.lh5'):
            from API.osciloscope_store import formato_lh5
            out, _ = formato_lh5.leer(p)
        else:
            z = np.load(p, allow_pickle=True)
            out = {k: z[k] for k in z.files}
            out['meta'].item()
        n += len(out['wave'])
    return n


def leer_columnas(archivos):
    n = 0
    for p in archivos:
        if p.endswith('.lh5'):
            import h5py
            with h5py.File(p, 'r') as f:
                cols = [f['raw'][c][()] for c in COLUMNAS]
        else:
            z = _npz(p)
            cols = [z[c] for c in COLUMNAS]
        n += len(cols[0])
    return n


def leer_pocos(archivos, k, rng):
    n = 0
    for p in archivos:
        if p.endswith('.lh5'):
            import h5py
            with h5py.File(p, 'r') as f:
                raw = f['raw']
                total = raw['t_ns'].shape[0]
                idx = np.sort(rng.choice(total, size=min(k, total), replace=False))
                ondas = [raw[g]['values'][idx] for g in raw
                         if g.startswith('waveform_in')]
        else:
            z = _npz(p)
            w = z['wave']               # el miembro entero: el zip no lee por partes
            idx = np.sort(rng.choice(len(w), size=min(k, len(w)), replace=False))
            ondas = [w[idx]]
        n += len(ondas[0])
    return n


def leer_oficial(archivos):
    try:
        import lh5
    except ImportError:
        return None
    t = lh5.read('raw', archivos)
    return len(t['t_ns'].nda)


def cronometrar(fn, *args, reps=3):
    """La mediana de `reps` corridas: la primera ya encuentra el caché caliente."""
    mejor = []
    n = None
    for _ in range(reps):
        t0 = time.perf_counter()
        n = fn(*args)
        mejor.append(time.perf_counter() - t0)
    return statistics.median(mejor), n


def medir(base, formato, comprimir, b, lotes, n_ch, pre, post, pocos):
    carpeta = tempfile.mkdtemp(prefix=f'bench_{nombre(formato, comprimir)}_', dir=base)
    try:
        esc = escribir(carpeta, formato, comprimir, b, lotes, n_ch, pre, post)
        archivos = archivos_de_corrida(carpeta)
        tam = sum(os.path.getsize(p) for p in archivos)
        n_ev = b.n * len(archivos)
        r = dict(variante=nombre(formato, comprimir), muestras=pre + post, n_ch=n_ch,
                 eventos=n_ev, lote_eventos=b.n, bytes_por_evento=tam / n_ev,
                 escribir_ms=statistics.median(esc) * 1e3,
                 escribir_kev_s=b.n / statistics.median(esc) / 1e3)
        rng = np.random.default_rng(7)
        for clave, fn, args in (('todo', leer_todo, (archivos,)),
                                ('columnas', leer_columnas, (archivos,)),
                                ('pocos', leer_pocos, (archivos, pocos, rng)),
                                ('oficial', leer_oficial, (archivos,))):
            if clave == 'oficial' and formato != 'lh5':
                r[clave + '_s'] = None
                continue
            s, n = cronometrar(fn, *args)
            r[clave + '_s'] = None if n is None else s
        return r
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)


def _fmt(v, f):
    return '—' if v is None else format(v, f)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--dir', default=None, help='dónde escribir: el disco que se va a usar')
    p.add_argument('--muestras', default='32,256,2048',
                   help='largos de ventana por canal, separados por coma (32,256,2048)')
    p.add_argument('--canales', type=int, default=2, choices=(1, 2))
    p.add_argument('--capacidad', type=int, default=4096,
                   help='eventos por lote, como el default de la sesión (4096)')
    p.add_argument('--lote-mb', type=float, default=8.0,
                   help='lo más que ocupa la onda de un lote: con ventanas largas '
                        'achica la capacidad (8 MB)')
    p.add_argument('--lotes', type=int, default=20, help='archivos por corrida (20)')
    p.add_argument('--pocos', type=int, default=10,
                   help='eventos por archivo en la lectura de unos pocos (10)')
    p.add_argument('--json', default=None, help='además, guardar los resultados acá')
    args = p.parse_args(argv)

    base = args.dir or tempfile.gettempdir()
    os.makedirs(base, exist_ok=True)
    try:
        import h5py
        version = f'h5py {h5py.__version__}, HDF5 {h5py.version.hdf5_version}'
    except ImportError:
        print('  falta h5py: sólo se mide .npz')
        h5py, version = None, 'sin h5py'
    try:
        import lh5
        version += f', lh5 {getattr(lh5, "__version__", "?")}'
    except ImportError:
        version += ', sin legend-lh5io (no hay lectura oficial)'
    print(f'  python {sys.version.split()[0]}, numpy {np.__version__}, {version}')
    print(f'  {args.canales} canales, {args.lotes} archivos por corrida, en {base}; '
          f'lectura con el caché caliente\n')

    filas = []
    for muestras in (int(m) for m in args.muestras.split(',')):
        pre = max(1, muestras // 4)
        post = muestras - pre
        cap = max(1, min(args.capacidad,
                         int(args.lote_mb * 2**20 // (2 * args.canales * muestras))))
        b = lote(cap, args.canales, pre, post)
        print(f'  ventana de {muestras} muestras, {cap} eventos por lote')
        print(f'    {"variante":9s} {"B/ev":>7s} {"escribir ms":>12s} {"kev/s":>8s} '
              f'{"todo s":>8s} {"columnas s":>11s} {"pocos s":>8s} {"oficial s":>10s}')
        for formato, comprimir in VARIANTES:
            if formato == 'lh5' and h5py is None:
                continue
            r = medir(base, formato, comprimir, b, args.lotes, args.canales, pre, post,
                      args.pocos)
            filas.append(r)
            print(f'    {r["variante"]:9s} {r["bytes_por_evento"]:7.0f} '
                  f'{r["escribir_ms"]:12.1f} {r["escribir_kev_s"]:8.1f} '
                  f'{_fmt(r["todo_s"], "8.3f")} {_fmt(r["columnas_s"], "11.4f")} '
                  f'{_fmt(r["pocos_s"], "8.4f")} {_fmt(r["oficial_s"], "10.3f")}')
        print()
    if args.json:
        with open(args.json, 'w') as fh:
            json.dump(dict(version=version, python=sys.version.split()[0],
                           numpy=np.__version__, filas=filas), fh, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())

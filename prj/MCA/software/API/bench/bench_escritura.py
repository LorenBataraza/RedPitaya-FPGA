#!/usr/bin/env python3
"""Cuánto cuesta escribir un lote de eventos, en `.npz` y en `.lh5`.

Es la comprobación de que `h5py` sirve en la placa, y **no toca la PL**: sólo escribe
archivos, con el `ChunkWriter` real y lotes del tamaño real. Responde tres preguntas:

  1. ¿Está `h5py`? Sin él, sale con código 1 y dice cómo instalarlo.
  2. ¿Cuánto tarda un lote? Solo y con un lector compitiendo por el GIL, que es el caso
     real: `wait_event` gira sin soltarlo, y cada vez que el escritor lo suelta espera
     hasta un intervalo de cambio para recuperarlo.
  3. ¿Frena al lector? `hueco` es la mayor demora de un hilo de Python mientras el otro
     escribe. Si el escritor retuviera el GIL durante el I/O, se iría a la duración de la
     escritura. Cada microsegundo de hueco es tiempo muerto del método.

`techo` es lo más que aguanta el disco sin quedarse atrás: eventos por lote sobre el
tiempo de un lote. Hay que compararlo con la tasa del lector, 3.7 kev/s medidos.

Esto NO reemplaza medir los descartes con la señal real: eso es `run_poisson_loss.py
--formato lh5`, que necesita el generador.

    python3 API/bench/bench_escritura.py --dir /home/jupyter/RedPitaya/DATOS
"""

import argparse
import os
import shutil
import statistics
import sys
import tempfile
import threading
import time

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

from API.osciloscope_store.events import BASE_FIELDS, EventBatch     # noqa: E402
from API.osciloscope_store.formato_lh5 import exigir_h5py            # noqa: E402
from API.osciloscope_store.session import SWITCH_INTERVAL_S          # noqa: E402
from API.osciloscope_store.storage import ChunkWriter                # noqa: E402


def lote(capacidad, n_ch, muestras):
    """Un lote lleno de ruido: no se comprime, como una señal con pulsos arriba."""
    b = EventBatch(capacidad, n_ch, muestras, BASE_FIELDS)
    rng = np.random.default_rng(1)
    b.wave[:] = rng.uniform(-1.0, 1.0, b.wave.shape)
    b.t_ns[:] = np.arange(capacidad) * 90_000
    b.wp[:] = np.arange(capacidad) % 16384
    b.snap[:] = 2
    b.n = capacidad
    return b


def escritor(formato, carpeta, n_ch, pre, post):
    meta = dict(channels=list(range(1, n_ch + 1)), capacity=0,
                source=dict(kind='bench', pre=pre, post=post, samples=pre + post,
                            n_ch=n_ch, thr_V=0.2, hyst_V=0.02, mask=2, set_dly=post,
                            adc_cnt_per_V=8192, dt_ns=8.0))
    return ChunkWriter(carpeta, None, None,
                       dict(n_read=0, n_dropped=0, n_timeouts=0, n_written=0, chunks=0),
                       meta_base=meta, formato=formato)


def _solo(w, b, reps):
    pc = time.perf_counter
    tiempos = []
    for _ in range(reps):
        t0 = pc()
        w._write(b)
        tiempos.append(pc() - t0)
    return tiempos


def _con_lector(w, b, reps):
    """El lector gira en este hilo, y el escritor corre en otro, como en la corrida."""
    pc = time.perf_counter
    tiempos, huecos = [], []
    for _ in range(reps):
        fin = threading.Event()

        def escribir():
            t0 = pc()
            w._write(b)
            tiempos.append(pc() - t0)
            fin.set()

        th = threading.Thread(target=escribir)
        hueco, prev = 0.0, pc()
        th.start()
        while not fin.is_set():
            t = pc()
            hueco = max(hueco, t - prev)
            prev = t
        th.join()
        huecos.append(hueco)
    return tiempos, huecos


def medir(formato, b, base, reps, n_ch, pre, post):
    carpeta = tempfile.mkdtemp(prefix=f'bench_{formato}_', dir=base)
    try:
        w = escritor(formato, carpeta, n_ch, pre, post)
        solo = _solo(w, b, reps)
        con, huecos = _con_lector(w, b, reps)
        nombres = sorted(os.listdir(carpeta))
        tam = os.path.getsize(os.path.join(carpeta, nombres[0]))
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)
    return dict(tam=tam, solo=solo, con=con, huecos=huecos)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--dir', default=None, help='dónde escribir: el disco que se va a usar')
    p.add_argument('--reps', type=int, default=30, help='lotes por medición (30)')
    p.add_argument('--capacidad', type=int, default=4096, help='eventos por lote (4096)')
    p.add_argument('--canales', type=int, default=2, choices=(1, 2))
    p.add_argument('--pre', type=int, default=8)
    p.add_argument('--post', type=int, default=24)
    args = p.parse_args(argv)

    base = args.dir or tempfile.gettempdir()
    os.makedirs(base, exist_ok=True)
    sys.setswitchinterval(SWITCH_INTERVAL_S)

    print(f'  python {sys.version.split()[0]}, numpy {np.__version__}, '
          f'intervalo de GIL {SWITCH_INTERVAL_S * 1e3:g} ms')
    try:
        h5py = exigir_h5py()
    except ImportError as e:
        h5py = None
        print(f'  FALTA h5py: {e}')
    else:
        print(f'  h5py {h5py.__version__}, HDF5 {h5py.version.hdf5_version}')
    print(f'  {args.capacidad} eventos x {args.canales} canales x '
          f'{args.pre + args.post} muestras, {args.reps} lotes, en {base}\n')

    b = lote(args.capacidad, args.canales, args.pre + args.post)
    print(f'  {"formato":8s} {"B/ev":>6s} {"solo ms":>8s} {"con lector ms":>14s} '
          f'{"p95 ms":>8s} {"hueco máx ms":>13s} {"techo kev/s":>12s}')
    for formato in ('npz', 'lh5') if h5py else ('npz',):
        r = medir(formato, b, base, args.reps, args.canales, args.pre, args.post)
        con = sorted(r['con'])
        med = statistics.median(con)
        print(f'  {formato:8s} {r["tam"] / args.capacidad:6.0f} '
              f'{statistics.median(r["solo"]) * 1e3:8.2f} {med * 1e3:14.2f} '
              f'{con[int(0.95 * (len(con) - 1))] * 1e3:8.2f} '
              f'{max(r["huecos"]) * 1e3:13.2f} {args.capacidad / med / 1e3:12.1f}')
    return 0 if h5py else 1


if __name__ == '__main__':
    sys.exit(main())

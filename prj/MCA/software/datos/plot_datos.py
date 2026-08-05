#!/usr/bin/env python3
"""Mini-graficador de las capturas .npz de esta carpeta.

Uso:
    python3 plot_datos.py                 # grafica el ultimo *first_capture*
    python3 plot_datos.py <archivo.npz>   # grafica ese archivo (nombre o ruta)
    python3 plot_datos.py --list          # lista los .npz disponibles

Corre en la Pitaya (headless -> guarda PNG) o en tu PC (muestra la figura).
Guarda un <archivo>.png al lado del .npz.
"""
import sys, os, glob
import numpy as np
import matplotlib
if not os.environ.get('DISPLAY'):
    matplotlib.use('Agg')          # headless (ej. por SSH en la Pitaya)
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))


def latest():
    fs = sorted(glob.glob(os.path.join(HERE, '*first_capture*.npz')), key=os.path.getmtime)
    fs = fs or sorted(glob.glob(os.path.join(HERE, '*.npz')), key=os.path.getmtime)
    return fs[-1] if fs else None


def plot_file(path):
    z = np.load(path, allow_pickle=True)
    fs = float(z['fs']) if 'fs' in z.files else 125e6
    meta = z['meta'].item() if 'meta' in z.files else {}
    name = os.path.basename(path)

    if 'd1' in z.files:                              # captura de scope (buffers)
        d1 = z['d1']
        d2 = z['d2'] if 'd2' in z.files else None
        t = z['t_us'] if 't_us' in z.files else np.arange(len(d1)) / fs * 1e6
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(t, d1, lw=0.8, label='IN1')
        if d2 is not None:
            ax.plot(t, d2, lw=0.8, alpha=0.8, label='IN2')
        ax.axhline(0.5, color='gray', ls=':', lw=0.7)   # umbral tipico
        ax.set_xlabel('t (us)'); ax.set_ylabel('V')
        ax.grid(True, alpha=0.3); ax.legend(loc='upper right')
        ax.set_title(f'{name}   wp_trig={meta.get("wp_trig0")}  snapshot={meta.get("snapshot")}')
    elif 'dts_us' in z.files:                        # loop de triggers (casoC)
        dts = z['dts_us']
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.plot(dts, 'o-'); ax.set_xlabel('evento #'); ax.set_ylabel('dt (us)')
        ax.grid(True, alpha=0.3); ax.set_title(name)
    else:
        print('no hay arrays graficables en', name, '->', z.files); return

    out = os.path.splitext(path)[0] + '.png'
    fig.tight_layout(); fig.savefig(out, dpi=110)
    print('guardado:', out)
    try:
        plt.show()
    except Exception:
        pass


if __name__ == '__main__':
    args = sys.argv[1:]
    if args and args[0] == '--list':
        for f in sorted(glob.glob(os.path.join(HERE, '*.npz'))):
            print(os.path.basename(f))
        sys.exit()
    path = args[0] if args else latest()
    if path and not os.path.isabs(path) and not os.path.exists(path):
        path = os.path.join(HERE, path)          # permitir pasar solo el nombre
    if not path or not os.path.exists(path):
        print('archivo no encontrado. Usa --list para ver los disponibles.'); sys.exit(1)
    plot_file(path)

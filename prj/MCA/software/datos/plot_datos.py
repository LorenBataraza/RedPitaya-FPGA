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

    if 'efficiency' in z.files:                      # resumen del barrido de periodos
        exp = z['expected_dt_us']
        fig, ax = plt.subplots(1, 2, figsize=(13, 4))
        ax[0].semilogx(exp, z['efficiency'] * 100, 'o-')
        ax[0].axhline(95, color='orange', ls='--')
        if 'hw_alive' in z.files and (~z['hw_alive']).any():
            m = ~z['hw_alive']
            ax[0].semilogx(exp[m], z['efficiency'][m] * 100, 'rx', ms=10,
                           label='FPGA sin disparar')
            ax[0].legend()
        ax[0].set_xlabel('distancia entre pulsos (us)'); ax[0].set_ylabel('eficiencia SW (%)')
        ax[0].invert_xaxis(); ax[0].grid(True, which='both', alpha=0.3)
        ax[1].loglog(exp, z['mean_dt_us'], 'o-', label='dt SW')
        ax[1].loglog(exp, z['hw_dt_med_us'], 's-', label='dt HW (dwp)')
        ax[1].plot(exp, exp, 'k--', alpha=0.5, label='ideal')
        ax[1].set_xlabel('dt esperado (us)'); ax[1].set_ylabel('dt medido (us)')
        ax[1].grid(True, which='both', alpha=0.3); ax[1].legend()
        fig.suptitle(name)
    elif 'resuelto' in z.files:                      # resumen del barrido de ancho
        w_ns = z['width_s'] * 1e9
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.semilogx(w_ns, z['resuelto'].astype(float), 'o-', label='resuelto (snap=adc_n0)')
        if 'frac_n0' in z.files:
            ax.semilogx(w_ns, z['frac_n0'], 's--', alpha=0.7, label='fraccion adc_n0')
        ax.set_xlabel('ancho del pulso W (ns) = separacion entre flancos')
        ax.set_ylabel('resuelto'); ax.set_ylim(-0.05, 1.05)
        ax.grid(True, which='both', alpha=0.3); ax.legend(loc='center left')
        if 'v_max' in z.files:
            ax2 = ax.twinx()
            ax2.semilogx(w_ns, z['v_max'], '^:', color='tab:red', alpha=0.6)
            ax2.set_ylabel('v_max (V)', color='tab:red')
        ax.set_title(name)
    elif 'dt_hw_us' in z.files:                      # un punto del barrido de dead-time
        # dt HW (dwp_trig, 8 ns) vs dt SW (reloj de Python, ~us) + la senal cruda
        dt_hw = z['dt_hw_us']
        dt_sw = z['dt_sw_us'] if 'dt_sw_us' in z.files else np.array([])
        per_us = float(meta.get('period_s', 0) or 0) * 1e6
        has_raw = 'd1' in z.files
        fig, ax = plt.subplots(1, 2 + int(has_raw),
                               figsize=(6 * (2 + int(has_raw)), 3.6), squeeze=False)
        ax = ax[0]
        if dt_sw.size:
            ax[0].plot(dt_sw, 'o-', ms=3, alpha=0.7, label='dt SW (Python)')
        ax[0].plot(dt_hw, 's-', ms=3, alpha=0.8, label='dt HW (dwp)')
        if per_us:
            ax[0].axhline(per_us, color='r', ls='--', lw=0.8, label=f'periodo {per_us:g} us')
        ax[0].set_xlabel('evento #'); ax[0].set_ylabel('dt (us)')
        ax[0].grid(True, alpha=0.3); ax[0].legend(fontsize=8)
        if dt_hw.size:
            ax[1].hist(dt_hw, bins=40, alpha=0.8, label='dt HW')
            if dt_sw.size:
                ax[1].hist(dt_sw, bins=40, alpha=0.5, label='dt SW')
            if per_us:
                ax[1].axvline(per_us, color='r', ls='--', lw=0.8)
            ax[1].set_xlabel('dt (us)'); ax[1].set_ylabel('cuentas')
            ax[1].grid(True, alpha=0.3); ax[1].legend(fontsize=8)
        if has_raw:
            d1 = z['d1']
            ax[2].plot(np.arange(len(d1)) / fs * 1e6, d1, lw=0.8, label='IN1')
            ax[2].axhline(0.5, color='gray', ls=':', lw=0.7)
            ax[2].set_xlabel('t (us)'); ax[2].set_ylabel('V')
            ax[2].grid(True, alpha=0.3); ax[2].legend(fontsize=8)
        fig.suptitle(f'{name}   n={len(dt_hw)+1}  eff={meta.get("efficiency", float("nan")):.2f}')
    elif 'd1' in z.files:                            # captura de scope (buffers)
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

#!/usr/bin/env python3
"""Versiones ESTÁTICAS de la figura 7, para el informe impreso.

Los tres videos de [`animacion_cadena_mca.py`](animacion_cadena_mca.py) no se
pueden poner en un informe, así que cada uno tiene acá su gemelo estático:

  07a_senal.png       una ventana de la señal con el umbral y la segmentación
  07b_cadena.png      el camino de datos y el tren de registros de evento
  07c_histograma.png  el espectro en tres momentos de la acumulación
  07_cadena.png       las tres cosas en una sola figura (la que va al informe)

Salen de la MISMA simulación que los videos —`simular()` con la semilla y el
número de cuadros por omisión—, así que los pulsos, las amplitudes y el espectro
final son los mismos; lo que cambia es cómo se muestra el paso del tiempo. El
video lo muestra avanzando, el estático lo muestra desplegado: 07a elige una
ventana donde se ven todos los casos a la vez, y 07c elige tres cuadros en vez
de uno.

Como en el resto de las figuras, los números que se muestran son los del RTL:
la amplitud es la muestra de pico sobre la línea de base y el canal es
`amp >> h_shift`, igual que en `mca_top.sv`.

    python3 figuras_cadena_estatica.py [--frames 700] [--out DIR]
"""

import argparse
import os

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.ticker import MaxNLocator

from figuras_resolucion import (SUP, TINTA, TINTA2, MUDO, AZUL, NARAN, ROJO,
                                _limpiar, _panel)
from animacion_cadena_mca import (DT_TRAZA, VENTANA, UMBRAL, H_SHIFT,
                                  N_CANALES, simular)

_AQUI = os.path.dirname(os.path.abspath(__file__))

# cuántas cuentas lleva acumuladas cada panel de 07c (el último es el final)
HITOS = (12, 64)


# =============================================================================
# Lo que el video muestra con el tiempo y acá hay que elegir
# =============================================================================
def medir_pico(sim, tk):
    """Muestra de pico del pulso que empieza en tk: índice y valor en la traza.

    Es lo que mide el RTL con `amp_src = 0`, y por eso puede diferir de la
    amplitud generada: el ruido de línea de base y la cola del pulso anterior
    también entran en la muestra.
    """
    i0 = int(tk / DT_TRAZA)
    i1 = min(i0 + int(2.0 / DT_TRAZA), sim['traza'].size)
    j = i0 + int(np.argmax(sim['traza'][i0:i1]))
    return j, float(sim['traza'][j])


def segmento(sim, j):
    """Tramo contiguo sobre el umbral que contiene a la muestra j.

    Es la ventana que `pulse_feature` abre y cierra por comparación con `thr`;
    acá se dibuja sombreada para que se vea que el módulo SEGMENTA antes de
    medir.
    """
    sobre = sim['traza'] >= UMBRAL
    a = b = j
    while a > 0 and sobre[a - 1]:
        a -= 1
    while b < sobre.size - 1 and sobre[b + 1]:
        b += 1
    return sim['grid'][a], sim['grid'][b]


def _traza_en(sim, t):
    return float(sim['traza'][int(np.clip(t / DT_TRAZA, 0, sim['grid'].size - 1))])


def elegir_ventana(sim):
    """Ventana que muestra todos los casos a la vez, cortada en los huecos.

    Pide al menos un pulso que NO cruza el umbral —el caso que hay que ver— y
    entre cuatro y seis que sí. Los dos bordes caen donde la traza está bajo el
    umbral y entre dos pulsos, así que NO queda ningún pulso a medio dibujar ni
    sin etiquetar: todo lo que cruza el umbral adentro de la ventana está en la
    tabla de la figura 7b.

    Devuelve (t0, t1, eventos), con los eventos numerados en orden y cada uno
    descripto por lo que el MCA mediría de él.
    """
    t_ev, a_ev, ok = sim['t_ev'], sim['a_ev'], sim['aceptado']
    n = t_ev.size

    for k0 in range(1, n - 2):
        t0 = float(t_ev[k0]) - 1.6
        if t0 <= t_ev[k0 - 1] or _traza_en(sim, t0) >= UMBRAL:
            continue                       # el pulso anterior sigue a la vista

        k1 = k0                            # estirar mientras entre el siguiente
        while k1 + 2 < n and float(t_ev[k1 + 2]) - 0.35 - t0 <= VENTANA:
            k1 += 1
        t1 = float(t_ev[k1 + 1]) - 0.35     # justo antes de que arranque el que sigue
        if not (20.0 <= t1 - t0 <= VENTANA) or _traza_en(sim, t1) >= UMBRAL:
            continue

        idx = range(k0, k1 + 1)
        if not (4 <= sum(int(ok[k]) for k in idx) <= 6
                and not all(ok[k] for k in idx)):
            continue

        eventos = []
        for i, k in enumerate(idx, start=1):
            j, amp = medir_pico(sim, t_ev[k])
            eventos.append(dict(n=i, t=float(sim['grid'][j]), amp=amp,
                                canal=min(int(amp) >> H_SHIFT, N_CANALES - 1),
                                gen=float(a_ev[k]), j=j, ok=bool(ok[k])))
        return t0, t1, eventos

    raise RuntimeError('ninguna ventana cumple; probá otro --frames')


def cuadro_con(sim, n):
    """Primer cuadro que llegó a n cuentas acumuladas."""
    for f, e in enumerate(sim['estados']):
        if e['emitidos'] >= n:
            return f
    return len(sim['estados']) - 1


# =============================================================================
# Panel A — la señal
# =============================================================================
def panel_senal(ax, sim, t0, t1, eventos):
    i0, i1 = int(t0 / DT_TRAZA), int(t1 / DT_TRAZA) + 1
    acep = [e for e in eventos if e['ok']]
    rech = [e for e in eventos if not e['ok']]

    for ev in acep:                      # la ventana que abre pulse_feature
        ta, tb = segmento(sim, ev['j'])
        ax.axvspan(ta, min(tb, t1), color=AZUL, alpha=0.10, lw=0, zorder=1)

    ax.plot(sim['grid'][i0:i1], sim['traza'][i0:i1], lw=1.4, color=AZUL,
            zorder=3)
    ax.axhline(UMBRAL, color=ROJO, lw=1.1, ls='--', zorder=2)
    ax.text(0.008, UMBRAL, 'umbral', color=ROJO, va='bottom', ha='left',
            fontsize=9, transform=ax.get_yaxis_transform())

    ax.plot([e['t'] for e in acep], [e['amp'] for e in acep], 'o', ms=7,
            color=NARAN, zorder=5)
    for ev in acep:
        ax.annotate(f"{ev['amp']:.0f}", (ev['t'], ev['amp']),
                    textcoords='offset points', xytext=(0, 9), ha='center',
                    color=NARAN, fontweight='bold', fontsize=9.5)

    ax.plot([e['t'] for e in rech], [e['amp'] for e in rech], 'o', ms=6,
            mfc=SUP, mec=MUDO, mew=1.4, zorder=5)

    # el número con el que cada pulso va a la tabla de 07b, al pie del eje:
    # ahí abajo no hay traza que tapar y el renglón entra igual aunque el panel
    # se achique dentro de la figura completa
    for ev in eventos:
        ax.annotate(f"#{ev['n']}" if ev['ok'] else f"#{ev['n']}  no cuenta",
                    (ev['t'], 0), xycoords=('data', 'axes fraction'),
                    textcoords='offset points', xytext=(0, 6), ha='center',
                    color=MUDO, fontsize=8.5,
                    style='normal' if ev['ok'] else 'italic')

    ax.set_xlim(t0, t1)
    ax.set_ylim(-260, 3350)
    ax.set_xlabel('Tiempo [µs]')
    ax.set_ylabel('Amplitud sobre la base\n[cuentas de ADC]')
    _limpiar(ax)


# =============================================================================
# Panel B — la cadena
# =============================================================================
def panel_cadena(ax, eventos):
    ax.set_xlim(0, 10)
    ax.set_ylim(0.58, 2.88)
    ax.axis('off')

    def caja(x, w, etiqueta, sub, color):
        ax.add_patch(FancyBboxPatch(
            (x, 1.15), w, 1.15,
            boxstyle='round,pad=0.06,rounding_size=0.12',
            fc=SUP, ec=color, lw=2.0))
        ax.text(x + w / 2, 1.88, etiqueta, ha='center', va='center',
                fontsize=12.5, fontweight='bold', color=color)
        ax.text(x + w / 2, 1.45, sub, ha='center', va='center', fontsize=9,
                color=TINTA2)

    caja(0.55, 2.9, 'pulse_feature', 'segmenta el pulso\ny mide su amplitud',
         AZUL)
    caja(6.55, 2.9, 'histograma', 'incrementa el canal\ncorrespondiente',
         NARAN)
    for x0, x1 in ((0.0, 0.50), (3.50, 6.50), (9.50, 10.0)):
        ax.add_patch(FancyArrowPatch((x0, 1.72), (x1, 1.72), arrowstyle='-|>',
                                     mutation_scale=13, lw=1.6, color=MUDO,
                                     shrinkA=0, shrinkB=0))
    ax.text(0.25, 2.42, 'señal', ha='center', fontsize=9, color=TINTA2)
    ax.text(5.0, 2.52, 'un registro de evento por pulso', ha='center',
            fontsize=9, color=TINTA2)
    ax.text(9.75, 2.42, 'espectro', ha='center', fontsize=9, color=TINTA2)
    ax.text(5.0, 0.74, f'canal = amp >> {H_SHIFT}', ha='center', fontsize=9,
            color=MUDO, style='italic')

    # el tren de números que viaja por el cable: los del panel A, en orden
    acep = [e for e in eventos if e['ok']]
    for ev, x in zip(acep, np.linspace(3.95, 5.65, 3)):
        ax.text(x, 1.72, f"{ev['amp']:.0f}", ha='center', va='center',
                fontsize=10.5, fontweight='bold', color=NARAN,
                bbox=dict(fc=SUP, ec=NARAN, lw=1.2,
                          boxstyle='round,pad=0.26'))
    if len(acep) > 3:
        ax.text(6.2, 1.72, '…', ha='center', va='center', fontsize=13,
                color=MUDO)


def panel_tabla(ax, eventos):
    """Los eventos del panel A, como los ve el histograma."""
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 1)
    ax.axis('off')

    cols = ((0.6, 'pulso', 'left'), (3.0, 't [µs]', 'right'),
            (5.8, 'amp [cuentas]', 'right'), (9.3, f'canal = amp >> {H_SHIFT}',
                                              'right'))
    dy = 0.86 / (len(eventos) + 1)
    y = 0.93

    for x, txt, ha in cols:
        ax.text(x, y, txt, ha=ha, va='center', fontsize=9, color=TINTA2,
                fontweight='bold')
    ax.plot([0.4, 9.4], [y - dy * 0.5] * 2, lw=0.8, color=MUDO, clip_on=False)

    for i, ev in enumerate(eventos, start=1):
        y = 0.93 - i * dy
        ok = ev['ok']
        color = TINTA if ok else MUDO
        ax.text(cols[0][0], y, f"#{ev['n']}", ha='left', va='center',
                fontsize=9.5, color=color)
        ax.text(cols[1][0], y, f"{ev['t']:.1f}", ha='right', va='center',
                fontsize=9.5, color=color)
        ax.text(cols[2][0], y, f"{ev['amp']:.0f}", ha='right', va='center',
                fontsize=9.5, color=color,
                fontweight='bold' if ok else 'normal')
        ax.text(cols[3][0], y,
                f"{ev['canal']}" if ok else 'rechazado: amp < thr',
                ha='right', va='center', fontsize=9.5, color=color,
                fontweight='bold' if ok else 'normal',
                style='normal' if ok else 'italic')


# =============================================================================
# Panel C — el histograma
# =============================================================================
def panel_histograma(ax, cuentas, n, ejex=True):
    ax.bar(np.arange(N_CANALES), cuentas, width=0.88, color=AZUL, linewidth=0)
    ax.axvline(UMBRAL >> H_SHIFT, color=ROJO, lw=1.1, ls='--', zorder=1)
    if ejex:                             # el mismo umbral del panel (a)
        ax.text(UMBRAL >> H_SHIFT, 0.96, ' umbral', color=ROJO, va='top',
                ha='left', fontsize=9, transform=ax.get_xaxis_transform())
    ax.set_xlim(-0.5, N_CANALES - 0.5)
    ax.set_ylim(0, max(4.0, cuentas.max() * 1.25))
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))
    ax.text(0.985, 0.92, f'{n} cuentas', transform=ax.transAxes, ha='right',
            va='top', fontsize=11, fontweight='bold', color=TINTA)
    ax.set_ylabel('Cuentas')
    if ejex:
        ax.set_xlabel(f'Canal  (amp >> {H_SHIFT})')
    else:
        ax.tick_params(labelbottom=False)
    _limpiar(ax)


# =============================================================================
# Las cuatro figuras
# =============================================================================
def fig_senal(sim, win, out):
    fig, ax = plt.subplots(figsize=(9.6, 4.4))
    panel_senal(ax, sim, *win)
    fig.tight_layout()
    return _guardar(fig, out, '07a_senal.png')


def fig_cadena(win, out):
    eventos = win[2]
    fig = plt.figure(figsize=(9.6, 4.8))
    gs = GridSpec(2, 1, height_ratios=[1.25, 1.0], hspace=0.05, figure=fig)
    panel_cadena(fig.add_subplot(gs[0]), eventos)
    panel_tabla(fig.add_subplot(gs[1]), eventos)
    return _guardar(fig, out, '07b_cadena.png')


def fig_histograma(sim, out):
    cuadros = [cuadro_con(sim, n) for n in HITOS] + [len(sim['estados']) - 1]
    fig, axs = plt.subplots(len(cuadros), 1, figsize=(7.6, 6.6), sharex=True)
    for i, (ax, f) in enumerate(zip(axs, cuadros)):
        e = sim['estados'][f]
        panel_histograma(ax, e['cuentas'], e['emitidos'],
                         ejex=(i == len(cuadros) - 1))
        _panel(ax, f"({'abc'[i]})")
    fig.tight_layout()
    return _guardar(fig, out, '07c_histograma.png')


def fig_completa(sim, win, out):
    """Las tres etapas en una sola figura: es la que va al informe.

    Acá va el resumen; el detalle evento por evento queda en 07b.
    """
    fig = plt.figure(figsize=(9.6, 9.2))
    gs = GridSpec(3, 1, height_ratios=[1.35, 1.05, 1.20], hspace=0.40,
                  figure=fig)

    ax = fig.add_subplot(gs[0])
    panel_senal(ax, sim, *win)
    _panel(ax, '(a)  la señal: un pulso por evento')

    ax = fig.add_subplot(gs[1])
    panel_cadena(ax, win[2])
    _panel(ax, '(b)  el camino de datos: un número por pulso')

    ax = fig.add_subplot(gs[2])
    e = sim['estados'][-1]
    panel_histograma(ax, e['cuentas'], e['emitidos'])
    _panel(ax, '(c)  el espectro: una cuenta por número')

    return _guardar(fig, out, '07_cadena.png')


def _guardar(fig, out, nombre):
    destino = os.path.join(out, nombre)
    fig.savefig(destino, bbox_inches='tight')
    plt.close(fig)
    print(f'  {nombre}')
    return destino


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--frames', type=int, default=700,
                    help='los mismos que animacion_cadena_mca.py, para que '
                         'estático y video salgan de la misma simulación')
    ap.add_argument('--out', default=_AQUI)
    args = ap.parse_args()

    sim = simular(args.frames)
    win = elegir_ventana(sim)
    t0, t1, eventos = win

    fig_senal(sim, win, args.out)
    fig_cadena(win, args.out)
    fig_histograma(sim, args.out)
    fig_completa(sim, win, args.out)

    ult = sim['estados'][-1]
    pico = int(np.argmax(ult['cuentas']))
    acep = [e for e in eventos if e['ok']]
    print(f"ventana [{t0:.1f}, {t1:.1f}] µs: {len(acep)} pulsos sobre el "
          f"umbral y {len(eventos) - len(acep)} bajo el umbral")
    print('  amplitudes y canales: ' +
          ', '.join(f"{e['amp']:.0f}→{e['canal']}" for e in acep))
    print(f"espectro: {ult['emitidos']} cuentas, hitos en "
          f"{', '.join(str(n) for n in HITOS)}, canal más poblado {pico} "
          f"({int(ult['cuentas'][pico])} cuentas)")


if __name__ == '__main__':
    main()

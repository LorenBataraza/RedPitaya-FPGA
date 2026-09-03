#!/usr/bin/env python3
"""Animación de la cadena del MCA, en tres videos separados y sincronizados.

  07a_senal.mp4       la señal: pulsos de distinta altura y el umbral
  07b_cadena.mp4      pulse_feature emite UN número por pulso y viaja al histograma
  07c_histograma.mp4  el espectro que se acumula, una barra por cuenta

Los tres salen de la MISMA simulación, precalculada cuadro a cuadro, así que se
pueden reproducir en paralelo y siguen sincronizados: el cuadro f de uno
corresponde al cuadro f de los otros dos.

El número que viaja entre los bloques es el registro de evento real del RTL
(`ev_amp`), y el canal es `amp >> h_shift`, igual que en `mca_top.sv`.

    python3 animacion_cadena_mca.py [--fps 30] [--frames 700] [--gif]
"""

import argparse
import os

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, FFMpegWriter, PillowWriter
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.ticker import MaxNLocator

from figuras_resolucion import (SUP, TINTA, TINTA2, MUDO, AZUL, NARAN, ROJO,
                                _limpiar)

_AQUI = os.path.dirname(os.path.abspath(__file__))

# --- geometría temporal (en µs) ---------------------------------------------
DT_TRAZA   = 0.02        # paso de la traza dibujada
VENTANA    = 30.0        # ancho de la ventana visible
DT_BASE    = 0.25        # avance por cuadro a velocidad ×1
T_CIERRE   = 3.0         # desde el pico hasta que el evento se emite
VIAJE      = 8           # cuadros que tarda el número en cruzar el diagrama
FLASH      = 5           # cuadros que queda resaltada la barra que creció

# --- el estímulo -------------------------------------------------------------
UMBRAL    = 300          # cuentas de ADC
H_SHIFT   = 6            # canal = amp >> 6  →  64 canales sobre 4096 cuentas
N_CANALES = 4096 >> H_SHIFT
LINEAS    = ((1250, 105, 0.42), (2620, 130, 0.33))  # (amplitud, sigma, peso)


def velocidad(f):
    """×1 al principio para ver el mecanismo, y después acelera."""
    if f < 120:
        return 1.0
    if f < 280:
        return 1.0 + 7.0 * (f - 120) / 160.0
    return 8.0


def forma_pulso(t, t_rise=0.35, tau=1.15):
    """Pulso de detector: subida suave y cola exponencial, pico = 1."""
    y = np.where(t < 0, 0.0,
                 (1 - np.exp(-t / t_rise)) * np.exp(-t / max(tau, 1e-9)))
    return y / y.max() if y.max() > 0 else y


def generar_eventos(t_total, rng):
    """Tiempos y amplitudes: dos líneas, un continuo y algo bajo el umbral."""
    t, amps = [], []
    tk = 4.0
    while tk < t_total:
        u = rng.random()
        acc = 0.0
        for centro, sigma, peso in LINEAS:
            acc += peso
            if u < acc:
                a = rng.normal(centro, sigma)
                break
        else:
            a = (rng.uniform(400, 2900) if u < acc + 0.15
                 else rng.uniform(90, UMBRAL * 0.85))   # bajo umbral: no cuenta
        t.append(tk)
        amps.append(float(np.clip(a, 60, 4000)))
        tk += rng.uniform(3.0, 5.5)
    return np.array(t), np.array(amps)


def construir_traza(t_ev, a_ev, t_total, rng):
    grid = np.arange(0.0, t_total + 10.0, DT_TRAZA)
    y = rng.normal(0.0, 9.0, grid.size)              # ruido de línea de base
    plantilla = forma_pulso(np.arange(0, 9.0, DT_TRAZA))
    for tk, ak in zip(t_ev, a_ev):
        i0 = int(tk / DT_TRAZA)
        i1 = min(i0 + plantilla.size, grid.size)
        y[i0:i1] += ak * plantilla[:i1 - i0]
    return grid, y


# =============================================================================
# La simulación, una sola vez para los tres videos
# =============================================================================
def simular(n_frames, semilla=11):
    rng = np.random.default_rng(semilla)
    t_frame = np.concatenate(([0.0], np.cumsum(
        [DT_BASE * velocidad(f) for f in range(n_frames)])))
    t_total = float(t_frame[-1])

    t_ev, a_ev = generar_eventos(t_total, rng)
    grid, traza = construir_traza(t_ev, a_ev, t_total, rng)
    aceptado = a_ev >= UMBRAL
    canal_ev = np.minimum(a_ev.astype(int) >> H_SHIFT, N_CANALES - 1)

    cuentas = np.zeros(N_CANALES)
    tokens, flash, ultimo, emitidos = [], [], None, 0
    estados = []
    for f in range(n_frames):
        t_now = t_frame[f]

        for k in np.nonzero((t_ev + T_CIERRE > t_frame[max(f - 1, 0)]) &
                            (t_ev + T_CIERRE <= t_now) & aceptado)[0]:
            tokens.append([f, int(canal_ev[k]), float(a_ev[k])])
            ultimo = (float(t_ev[k]), float(a_ev[k]))

        quedan = []
        for f0, canal, amp in tokens:
            if f - f0 >= VIAJE:                       # llegó: la barra crece
                cuentas[canal] += 1
                emitidos += 1
                flash.append((canal, f))
            else:
                quedan.append([f0, canal, amp])
        tokens = quedan
        flash = [(c, f0) for (c, f0) in flash if f - f0 < FLASH]

        estados.append(dict(
            t=t_now, vel=velocidad(f),
            ultimo=ultimo if (ultimo and ultimo[0] > t_now - VENTANA) else None,
            tokens=[((f - f0) / VIAJE, amp) for f0, _, amp in tokens],
            cuentas=cuentas.copy(), flash={c for c, _ in flash},
            emitidos=emitidos))

    return dict(estados=estados, grid=grid, traza=traza, t_ev=t_ev, a_ev=a_ev,
                aceptado=aceptado, t_total=t_total)


# =============================================================================
# Video A — la señal
# =============================================================================
def video_senal(sim):
    fig, ax = plt.subplots(figsize=(9.6, 5.4), dpi=100)
    (linea,) = ax.plot([], [], lw=1.4, color=AZUL)
    ax.axhline(UMBRAL, color=ROJO, lw=1.1, ls='--')
    ax.text(0.995, UMBRAL, ' umbral', color=ROJO, va='bottom', ha='right',
            fontsize=9, transform=ax.get_yaxis_transform())
    (pico,) = ax.plot([], [], 'o', ms=7, color=NARAN, zorder=5)
    etiqueta = ax.text(0, 0, '', color=NARAN, fontweight='bold', ha='center',
                       va='bottom')
    vel = ax.text(0.995, 0.95, '', transform=ax.transAxes, ha='right', va='top',
                  fontsize=9, color=MUDO)
    ax.set_ylim(-260, 3350)
    ax.set_xlabel('Tiempo [µs]')
    ax.set_ylabel('Amplitud sobre la base [cuentas de ADC]')
    _limpiar(ax)
    fig.tight_layout()

    def dibujar(f):
        e = sim['estados'][f]
        t0 = max(0.0, e['t'] - VENTANA)
        i0, i1 = int(t0 / DT_TRAZA), int(e['t'] / DT_TRAZA) + 1
        linea.set_data(sim['grid'][i0:i1], sim['traza'][i0:i1])
        ax.set_xlim(t0, max(VENTANA, e['t']))
        vel.set_text(f"×{e['vel']:.0f}" if e['vel'] > 1.5 else '×1')
        if e['ultimo']:
            tp, ap = e['ultimo']
            pico.set_data([tp], [ap])
            etiqueta.set_position((tp, ap + 90))
            etiqueta.set_text(f'{ap:.0f}')
        else:
            pico.set_data([], [])
            etiqueta.set_text('')
        return []

    return fig, dibujar


# =============================================================================
# Video B — la cadena
# =============================================================================
def video_cadena(sim):
    fig, ax = plt.subplots(figsize=(9.6, 3.6), dpi=100)
    ax.set_xlim(0, 10)
    ax.set_ylim(0.3, 3.0)
    ax.axis('off')

    def caja(x, w, etiqueta, sub, color):
        ax.add_patch(FancyBboxPatch(
            (x, 1.15), w, 1.15,
            boxstyle='round,pad=0.06,rounding_size=0.12',
            fc=SUP, ec=color, lw=2.0))
        ax.text(x + w / 2, 1.88, etiqueta, ha='center', va='center',
                fontsize=13, fontweight='bold', color=color)
        ax.text(x + w / 2, 1.45, sub, ha='center', va='center', fontsize=9,
                color=TINTA2)

    caja(0.9, 3.1, 'pulse_feature', 'segmenta el pulso\ny mide su amplitud', AZUL)
    caja(6.0, 3.1, 'histograma', 'incrementa el canal\ncorrespondiente', NARAN)
    for x0, x1 in ((0.0, 0.85), (4.05, 5.95), (9.15, 10.0)):
        ax.add_patch(FancyArrowPatch((x0, 1.72), (x1, 1.72), arrowstyle='-|>',
                                     mutation_scale=13, lw=1.6, color=MUDO,
                                     shrinkA=0, shrinkB=0))
    ax.text(0.42, 2.5, 'señal', ha='center', fontsize=9, color=TINTA2)
    ax.text(5.0, 2.62, 'un número por pulso', ha='center', fontsize=9,
            color=TINTA2)
    ax.text(9.6, 2.5, 'espectro', ha='center', fontsize=9, color=TINTA2)
    ax.text(5.0, 0.72, 'canal = amp >> h_shift', ha='center', fontsize=9,
            color=MUDO, style='italic')

    token = ax.text(0, 1.72, '', ha='center', va='center', fontsize=12,
                    fontweight='bold', color=NARAN,
                    bbox=dict(fc=SUP, ec=NARAN, lw=1.2,
                              boxstyle='round,pad=0.28'))
    fig.tight_layout()

    def dibujar(f):
        e = sim['estados'][f]
        if e['tokens']:
            u, amp = e['tokens'][-1]
            token.set_position((4.72 + 0.58 * u, 1.72))
            token.set_text(f'amp = {amp:.0f}')
        else:
            token.set_text('')
        return []

    return fig, dibujar


# =============================================================================
# Video C — el histograma
# =============================================================================
def video_histograma(sim):
    fig, ax = plt.subplots(figsize=(9.6, 5.4), dpi=100)
    barras = ax.bar(np.arange(N_CANALES), np.zeros(N_CANALES), width=0.88,
                    color=AZUL, linewidth=0)
    ax.set_xlim(-0.5, N_CANALES - 0.5)
    ax.set_xlabel(f'Canal  (amp >> {H_SHIFT})')
    ax.set_ylabel('Cuentas')
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    total = ax.text(0.985, 0.95, '', transform=ax.transAxes, ha='right',
                    va='top', fontsize=12, fontweight='bold', color=TINTA)
    _limpiar(ax)
    fig.tight_layout()

    def dibujar(f):
        e = sim['estados'][f]
        cuentas, flash = e['cuentas'], e['flash']
        for j, barra in enumerate(barras):
            barra.set_height(cuentas[j])
            barra.set_color(NARAN if j in flash else AZUL)
        ax.set_ylim(0, max(4.0, cuentas.max() * 1.18))
        total.set_text(f"{e['emitidos']} cuentas")
        return []

    return fig, dibujar


# =============================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--frames', type=int, default=700)
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--gif', action='store_true')
    ap.add_argument('--out', default=_AQUI)
    args = ap.parse_args()

    sim = simular(args.frames)
    ext = 'gif' if args.gif else 'mp4'
    salidas = (('07a_senal', video_senal),
               ('07b_cadena', video_cadena),
               ('07c_histograma', video_histograma))

    for nombre, constructor in salidas:
        fig, dibujar = constructor(sim)
        anim = FuncAnimation(fig, dibujar, frames=args.frames,
                             interval=1000 / args.fps, blit=False)
        destino = os.path.join(args.out, f'{nombre}.{ext}')
        if args.gif:
            anim.save(destino, writer=PillowWriter(fps=args.fps))
        else:
            anim.save(destino, writer=FFMpegWriter(
                fps=args.fps, codec='libx264',
                extra_args=['-pix_fmt', 'yuv420p', '-crf', '24',
                            '-preset', 'slow']))
        plt.close(fig)
        print(f'  {os.path.basename(destino)}')

    ult = sim['estados'][-1]
    print(f"{args.frames} cuadros a {args.fps} fps "
          f"({args.frames / args.fps:.1f} s), {sim['t_total']:.0f} µs simulados, "
          f"{len(sim['t_ev'])} pulsos ({int(sim['aceptado'].sum())} sobre el "
          f"umbral), {ult['emitidos']} cuentas acumuladas")


if __name__ == '__main__':
    main()

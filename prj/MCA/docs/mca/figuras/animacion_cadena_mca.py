#!/usr/bin/env python3
"""Animación de la cadena del MCA: pulsos → pulse_feature → valor → histograma.

Muestra las tres cosas al mismo tiempo:

  1. la señal con pulsos de distintas alturas pasando por la entrada,
  2. el bloque `pulse_feature`, que por cada pulso emite UN número (la amplitud),
  3. el módulo `histograma`, donde ese número incrementa la barra de su canal.

El número que viaja entre los dos bloques es el registro de evento real del RTL
(`ev_amp`), y el canal es `amp >> h_shift`, igual que en `mca_top.sv`.

    python3 animacion_cadena_mca.py [--fps 30] [--frames 700] [--gif]

Salida: `07_cadena_mca.mp4` (o `.gif` con --gif).
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

# --- el estímulo -------------------------------------------------------------
UMBRAL   = 300           # cuentas de ADC
H_SHIFT  = 6             # canal = amp >> 6  →  64 canales sobre 4096 cuentas
N_CANALES = 4096 >> H_SHIFT
LINEAS   = ((1250, 105, 0.42), (2620, 130, 0.33))  # (amplitud, sigma, peso)


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
def construir_figura(t_ev, a_ev, grid, traza, n_frames):
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100)
    gs = fig.add_gridspec(2, 2, width_ratios=[1.55, 1], height_ratios=[1.3, 1],
                          left=0.055, right=0.985, top=0.90, bottom=0.075,
                          wspace=0.16, hspace=0.30)
    ax_sig = fig.add_subplot(gs[0, 0])
    ax_dia = fig.add_subplot(gs[1, 0])
    ax_his = fig.add_subplot(gs[:, 1])

    fig.suptitle('Cómo un pulso se convierte en una cuenta del espectro',
                 x=0.055, ha='left', fontsize=14, fontweight='bold')

    # ---------------- señal ----------------
    (ln_sig,) = ax_sig.plot([], [], lw=1.4, color=AZUL)
    ax_sig.axhline(UMBRAL, color=ROJO, lw=1.1, ls='--')
    ax_sig.text(0.995, UMBRAL, ' umbral', color=ROJO, fontsize=8.5,
                va='bottom', ha='right', transform=ax_sig.get_yaxis_transform())
    (pt_pico,) = ax_sig.plot([], [], 'o', ms=7, color=NARAN, zorder=5)
    txt_pico = ax_sig.text(0, 0, '', color=NARAN, fontsize=9.5,
                           fontweight='bold', ha='center', va='bottom')
    ax_sig.set_ylim(-260, 3350)
    ax_sig.set_ylabel('amplitud sobre la base  (cuentas de ADC)')
    ax_sig.set_xlabel('tiempo  (µs)')
    ax_sig.set_title('1 · La señal: pulsos de distinta altura', loc='left',
                     fontsize=10.5, fontweight='bold', pad=6)
    txt_vel = ax_sig.text(0.995, 0.94, '', transform=ax_sig.transAxes,
                          ha='right', va='top', fontsize=9, color=MUDO)
    _limpiar(ax_sig)

    # ---------------- diagrama ----------------
    ax_dia.set_xlim(0, 10)
    ax_dia.set_ylim(0, 3.2)
    ax_dia.axis('off')
    ax_dia.set_title('2 · La cadena', loc='left', fontsize=10.5,
                     fontweight='bold', pad=6)

    def caja(x, w, etiqueta, sub, color):
        ax_dia.add_patch(FancyBboxPatch((x, 1.15), w, 1.15,
                                        boxstyle='round,pad=0.06,rounding_size=0.12',
                                        fc=SUP, ec=color, lw=2.0))
        ax_dia.text(x + w / 2, 1.86, etiqueta, ha='center', va='center',
                    fontsize=12, fontweight='bold', color=color)
        ax_dia.text(x + w / 2, 1.45, sub, ha='center', va='center',
                    fontsize=8.5, color=TINTA2)

    caja(0.9, 3.1, 'pulse_feature', 'segmenta el pulso\ny mide su amplitud', AZUL)
    caja(6.0, 3.1, 'histograma', 'incrementa el canal\ncorrespondiente', NARAN)
    for x0, x1 in ((0.0, 0.85), (4.05, 5.95), (9.15, 10.0)):
        ax_dia.add_patch(FancyArrowPatch((x0, 1.72), (x1, 1.72),
                                         arrowstyle='-|>', mutation_scale=13,
                                         lw=1.6, color=MUDO, shrinkA=0, shrinkB=0))
    ax_dia.text(0.42, 2.45, 'señal', ha='center', fontsize=9, color=TINTA2)
    ax_dia.text(5.0, 2.62, 'UN número por pulso', ha='center', fontsize=9,
                color=TINTA2)
    ax_dia.text(9.6, 2.45, 'espectro', ha='center', fontsize=9, color=TINTA2)
    ax_dia.text(5.0, 0.62, 'canal = amp >> h_shift', ha='center', fontsize=8.5,
                color=MUDO, style='italic')

    tokens_art = [(ax_dia.text(0, 1.72, '', ha='center', va='center',
                               fontsize=11, fontweight='bold', color=NARAN,
                               bbox=dict(fc=SUP, ec=NARAN, lw=1.2,
                                         boxstyle='round,pad=0.28')))
                  for _ in range(1)]

    # ---------------- histograma ----------------
    canales = np.arange(N_CANALES)
    barras = ax_his.bar(canales, np.zeros(N_CANALES), width=0.88, color=AZUL,
                        linewidth=0)
    ax_his.set_xlim(-0.5, N_CANALES - 0.5)
    ax_his.set_xlabel(f'canal  ({N_CANALES} canales = amp >> {H_SHIFT})')
    ax_his.set_ylabel('cuentas')
    ax_his.set_title('3 · El espectro que se acumula', loc='left',
                     fontsize=10.5, fontweight='bold', pad=6)
    ax_his.yaxis.set_major_locator(MaxNLocator(integer=True))
    txt_cnt = ax_his.text(0.985, 0.965, '', transform=ax_his.transAxes,
                          ha='right', va='top', fontsize=11, fontweight='bold',
                          color=TINTA)
    _limpiar(ax_his)

    return fig, dict(ax_sig=ax_sig, ln_sig=ln_sig, pt_pico=pt_pico,
                     txt_pico=txt_pico, txt_vel=txt_vel, tokens=tokens_art,
                     ax_his=ax_his, barras=barras, txt_cnt=txt_cnt)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--frames', type=int, default=700)
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--gif', action='store_true')
    ap.add_argument('--out', default=_AQUI)
    args = ap.parse_args()

    rng = np.random.default_rng(11)

    # tiempo total que barre la animación con el perfil de velocidad
    t_frame = np.concatenate(([0.0], np.cumsum(
        [DT_BASE * velocidad(f) for f in range(args.frames)])))
    t_total = float(t_frame[-1])

    t_ev, a_ev = generar_eventos(t_total, rng)
    grid, traza = construir_traza(t_ev, a_ev, t_total, rng)
    aceptado = a_ev >= UMBRAL
    canal_ev = np.minimum(a_ev.astype(int) >> H_SHIFT, N_CANALES - 1)

    fig, art = construir_figura(t_ev, a_ev, grid, traza, args.frames)
    cuentas = np.zeros(N_CANALES)
    estado = dict(emitidos=0, tokens=[], flash=[], ultimo=None)

    def dibujar(f):
        t_now = t_frame[f]
        vel = velocidad(f)

        # --- señal: ventana deslizante ---
        t0 = max(0.0, t_now - VENTANA)
        i0, i1 = int(t0 / DT_TRAZA), int(t_now / DT_TRAZA) + 1
        art['ln_sig'].set_data(grid[i0:i1], traza[i0:i1])
        art['ax_sig'].set_xlim(t0, max(VENTANA, t_now))
        art['txt_vel'].set_text(f'×{vel:.0f} velocidad' if vel > 1.5 else
                                'tiempo real del gráfico')

        # --- eventos que se cierran en este cuadro ---
        nuevos = np.nonzero((t_ev + T_CIERRE > t_frame[max(f - 1, 0)]) &
                            (t_ev + T_CIERRE <= t_now) & aceptado)[0]
        for k in nuevos:
            estado['tokens'].append([f, int(canal_ev[k]), float(a_ev[k])])
            estado['ultimo'] = (float(t_ev[k]), float(a_ev[k]))

        # --- marca del último pico detectado ---
        if estado['ultimo'] and estado['ultimo'][0] > t_now - VENTANA:
            tp, ap_ = estado['ultimo']
            art['pt_pico'].set_data([tp], [ap_])
            art['txt_pico'].set_position((tp, ap_ + 90))
            art['txt_pico'].set_text(f'{ap_:.0f}')
        else:
            art['pt_pico'].set_data([], [])
            art['txt_pico'].set_text('')

        # --- llegada al histograma: la barra crece ---
        quedan = []
        for f0, canal, amp in estado['tokens']:
            if f - f0 >= VIAJE:
                cuentas[canal] += 1
                estado['emitidos'] += 1
                estado['flash'].append((canal, f))
            else:
                quedan.append([f0, canal, amp])
        estado['tokens'] = quedan
        estado['flash'] = [(c, f0) for (c, f0) in estado['flash'] if f - f0 < 5]
        recientes = {c for (c, _) in estado['flash']}

        # --- el número viajando de un bloque al otro ---
        for art_tok in art['tokens']:
            art_tok.set_text('')
        for i, (f0, canal, amp) in enumerate(estado['tokens'][-1:]):
            u = (f - f0) / VIAJE
            art['tokens'][i].set_position((4.72 + 0.58 * u, 1.72))
            art['tokens'][i].set_text(f'amp = {amp:.0f}')

        alto = max(cuentas.max(), 1.0)
        for j, barra in enumerate(art['barras']):
            barra.set_height(cuentas[j])
            barra.set_color(NARAN if j in recientes else AZUL)
        art['ax_his'].set_ylim(0, max(4.0, alto * 1.18))
        art['txt_cnt'].set_text(f"{estado['emitidos']} cuentas")
        return []

    anim = FuncAnimation(fig, dibujar, frames=args.frames, interval=1000 / args.fps,
                         blit=False)

    if args.gif:
        destino = os.path.join(args.out, '07_cadena_mca.gif')
        anim.save(destino, writer=PillowWriter(fps=args.fps))
    else:
        destino = os.path.join(args.out, '07_cadena_mca.mp4')
        anim.save(destino, writer=FFMpegWriter(
            fps=args.fps, codec='libx264',
            extra_args=['-pix_fmt', 'yuv420p', '-crf', '24', '-preset', 'slow']))
    plt.close(fig)
    print(f'{args.frames} cuadros, {t_total:.0f} µs simulados, '
          f'{len(t_ev)} pulsos ({int(aceptado.sum())} sobre el umbral)')
    print(destino)


if __name__ == '__main__':
    main()

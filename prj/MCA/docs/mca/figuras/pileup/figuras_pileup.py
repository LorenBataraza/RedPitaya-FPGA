#!/usr/bin/env python3
"""Figura del apilamiento de cola (Knoll fig. 17.17): cómo una cola o un
undershoot del primer pulso corren la altura del segundo y deforman el pico.

Misma convención que [`../figuras_resolucion.py`](../figuras_resolucion.py):
sin texto adentro de la figura, sólo ejes, leyenda y las marcas
imprescindibles. Paleta y rcParams se importan de ahí.

  01_cola_undershoot.png
      Dos filas, dos columnas. A la izquierda la señal en el tiempo: un pulso
      grande seguido de otro más chico que llega antes de que el primero
      vuelva a la línea de base. A la derecha el espectro dN/dH que resulta
      de medir muchas veces la altura del segundo pulso con tiempos de
      llegada al azar.

        fila 1  —  el primer pulso deja una COLA positiva (la forma del
                   estímulo de la campaña: subida suave y cola exponencial).
                   El segundo se mide de más: el pico gana una cola hacia
                   la derecha (rayado).
        fila 2  —  el mismo pulso pasado por una diferenciación CR sin
                   cancelación polo-cero deja UNDERSHOOT. El segundo se mide
                   de menos: la cola del pico va hacia la izquierda.

      El rayado es la diferencia entre el espectro deformado y el pico
      limpio que se mediría si el segundo pulso llegara siempre sobre la
      línea de base. No es un esquema dibujado a mano: el espectro sale de
      sumar la altura residual del primer pulso en el instante de llegada
      del segundo, con ese instante uniforme desde que ambos se separan
      hasta mucho después de extinguido el residuo, y luego convolucionar
      con la resolución gaussiana del pico.

    python3 figuras_pileup.py [--out DIR]
"""

import argparse
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_AQUI))

from figuras_resolucion import (TINTA2, MUDO,           # noqa: E402
                               AZUL, NARAN, ROJO, _limpiar)


# =============================================================================
# Señales en el tiempo
# =============================================================================

def pulso(t, t_subida=0.12, tau=1.6):
    """Subida exponencial y cola exponencial, normalizado al pico.

    Misma forma que `detector_pulse` del estímulo de la campaña; los tiempos
    están en unidades arbitrarias (la figura es un esquema).
    """
    y = np.where(t >= 0, (1.0 - np.exp(-t / t_subida)) * np.exp(-t / tau), 0.0)
    return y / y.max()


def diferenciador_cr(x, dt, tau_cr):
    """CR de un polo sin cancelación polo-cero: convierte la cola larga en
    un undershoot que dura del orden de la cola original."""
    a = tau_cr / (tau_cr + dt)
    y = np.empty_like(x)
    y[0] = 0.0
    for n in range(1, x.size):
        y[n] = a * (y[n - 1] + x[n] - x[n - 1])
    return y / y.max()


def formas(dt=0.002, t_fin=40.0):
    """Devuelve t y las dos formas unitarias: con cola y con undershoot."""
    t = np.arange(0.0, t_fin, dt)
    con_cola = pulso(t)
    con_under = diferenciador_cr(pulso(t, tau=3.0), dt, tau_cr=0.5)
    return t, con_cola, con_under


# =============================================================================
# Espectro de la altura del segundo pulso
# =============================================================================

def espectro(t, forma, a1, a2, ventana, sigma=0.02, h=None):
    """dN/dH del segundo pulso cuando llega en un instante uniforme dentro de
    `ventana` = (t_min, t_max) después del primero.

    Su altura medida es a2 + a1·forma(Δt): el residuo del primero en el
    momento de llegada del segundo. Se histograma sobre el eje `h` y se
    convoluciona con una gaussiana de ancho `sigma` (la resolución del pico).
    Devuelve h, el pico limpio y el espectro deformado, ambos normalizados a
    la misma área.
    """
    if h is None:
        h = np.linspace(0.0, 1.0, 2001)
    dh = h[1] - h[0]
    delta = np.linspace(*ventana, 20001)
    residuo = np.interp(delta, t, forma)
    medida = a2 + a1 * residuo

    cuentas, _ = np.histogram(medida, bins=np.append(h - dh / 2, h[-1] + dh / 2))
    kernel_x = np.arange(-5 * sigma, 5 * sigma + dh, dh)
    kernel = np.exp(-0.5 * (kernel_x / sigma) ** 2)
    kernel /= kernel.sum()
    deformado = np.convolve(cuentas.astype(float), kernel, mode='same')
    limpio = np.exp(-0.5 * ((h - a2) / sigma) ** 2)

    deformado /= deformado.sum() * dh
    limpio /= limpio.sum() * dh
    return h, limpio, deformado


# =============================================================================
# Figura
# =============================================================================

def fig_cola_undershoot(out):
    t, con_cola, con_under = formas()
    a1, a2 = 1.0, 0.62          # amplitudes del primer y segundo pulso
    t2 = 5.6                    # llegada del segundo pulso que se dibuja
    t_fin = 10.0                # hasta dónde se dibuja el tiempo
    # llegadas que alimentan el espectro: uniformes desde que el segundo
    # pulso se separa del primero hasta mucho después de que el residuo se
    # extinguió, así buena parte cae sobre la línea de base y el pico limpio
    # se conserva; la cola del espectro la ponen las llegadas tempranas
    ventana = (2.5, 14.0)

    filas = ((con_cola, 'cola'), (con_under, 'undershoot'))

    fig, axs = plt.subplots(2, 2, figsize=(8.4, 5.4), layout='constrained',
                            gridspec_kw={'width_ratios': (1.7, 1.0)})

    for (forma, _), (ax_t, ax_h) in zip(filas, axs):
        # --- tiempo -----------------------------------------------------
        primero = a1 * forma
        segundo = a2 * np.interp(t - t2, t, forma, left=0.0)
        suma = primero + segundo
        residuo = primero[np.searchsorted(t, t2)]

        ax_t.plot(t, primero, color=TINTA2, lw=1.0, ls='--',
                  label='primer pulso solo')
        ax_t.plot(t, suma, color=AZUL, lw=1.6, label='señal medida')
        ax_t.axhline(0.0, color=MUDO, lw=0.8)
        # altura que se mide para el segundo pulso: desde el residuo del
        # primero hasta el pico, no desde la línea de base
        i_pico = np.searchsorted(t, t2) + np.argmax(segundo[t >= t2])
        ax_t.annotate('', xy=(t[i_pico], suma[i_pico]),
                      xytext=(t[i_pico], residuo),
                      arrowprops=dict(arrowstyle='<->', color=NARAN, lw=1.2,
                                      shrinkA=0, shrinkB=0))
        # el residuo del primero en el momento de llegada del segundo
        ax_t.annotate('', xy=(t2, residuo), xytext=(t2, 0.0),
                      arrowprops=dict(arrowstyle='-|>', color=ROJO, lw=1.2,
                                      shrinkA=0, shrinkB=0, mutation_scale=9))
        ax_t.set_xlim(t[0], t_fin)
        ax_t.set_ylim(-0.32, 1.08)
        ax_t.set_ylabel('$H$')
        _limpiar(ax_t)

        # --- espectro ---------------------------------------------------
        h, limpio, deformado = espectro(t, forma, a1, a2, ventana)
        ax_h.plot(h, limpio, color=TINTA2, lw=1.0, ls='--', label='pico limpio')
        ax_h.plot(h, deformado, color=AZUL, lw=1.6, label='con apilamiento')
        ax_h.fill_between(h, limpio, deformado, where=deformado > limpio,
                          facecolor='none', edgecolor=ROJO, hatch='////',
                          lw=0.0, label='exceso por apilamiento')
        ax_h.set_xlim(0.35, 0.95)
        ax_h.set_ylim(0.0, 1.55 * limpio.max())   # aire para la leyenda
        ax_h.set_yticks([])
        ax_h.set_ylabel(r'$\dfrac{dN}{dH}$', rotation=0, labelpad=14)
        ax_h.axvline(a2, color=MUDO, lw=0.6, ls=':')
        _limpiar(ax_h)

    axs[0, 0].legend(loc='upper right', fontsize=8.5)
    axs[0, 1].legend(loc='upper right', fontsize=8.5)
    axs[1, 0].set_xlabel('tiempo')
    axs[1, 1].set_xlabel('$H$  (altura medida del segundo pulso)')

    fig.savefig(os.path.join(out, '01_cola_undershoot.png'))
    plt.close(fig)
    print('  01_cola_undershoot.png')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=_AQUI, help='dónde dejar los PNG')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print(f'figuras en {os.path.relpath(a.out)}:')
    fig_cola_undershoot(a.out)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Monte-Carlo pico contra carga para eventos dobles y triples, familia CR-RC^4.

Corre en la PC, sin placa.

QUÉ PREGUNTA CONTESTA
---------------------
El gráfico pico-vs-carga compara DOS estimadores internos del mismo evento, así
que no depende de la exactitud del generador — por eso la campaña de formas lo
usa para medir el factor de forma. Para un pulso limpio los dos estimadores son
proporcionales y todos los eventos caen sobre una recta de pendiente
`factor_forma · FWHM`.

Un evento apilado ROMPE esa proporcionalidad, y de una manera que depende del
espaciamiento: dos pulsos separados suman carga sin sumar pico, así que el
evento se despega de la recta hacia arriba. Este script mide cuánto, para los
espaciamientos pedidos.

    Δt = 4, 20, 150 y 600 muestras (32 ns, 160 ns, 1.2 µs, 4.8 µs)
    más un triple con Δt = 120 y 320

POR QUÉ CR-RC^4
---------------
Es la forma habitual en espectroscopía (cuatro integraciones: la más simétrica y
la más parecida a una gaussiana del catálogo unipolar) y la campaña de INL midió
su factor de forma en la placa: **1.0764**. `forma_knoll` lo reproduce exacto,
así que la recta de eventos limpios de este Monte-Carlo es contrastable contra
una medición.

Ojo con una particularidad de la familia: pica en u=4, o sea que su tiempo de
colección es LARGO —el pico cae en la muestra 210 de 1180— y eso cambia el
régimen de apilamiento respecto de la semi-gaussiana del resto del estudio.

    python3 pico_vs_carga.py
    python3 pico_vs_carga.py --familia cr_rc --n 4000
    python3 pico_vs_carga.py --out DIR
"""
import argparse
import glob
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                              # noqa: E402

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
import pileup as pu                                          # noqa: E402

# --- paleta (la misma del resto del estudio) ---------------------------------
SUP    = '#fcfcfb'
TINTA  = '#0b0b0b'
TINTA2 = '#52514e'
MUDO   = '#898781'
GRILLA = '#e1e0d9'
ROJO   = '#d03b3b'

plt.rcParams.update({
    'figure.facecolor': SUP, 'axes.facecolor': SUP, 'savefig.facecolor': SUP,
    'font.size': 10, 'axes.titlesize': 10, 'axes.labelsize': 10,
    'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': TINTA2,
    'text.color': TINTA, 'xtick.color': MUDO, 'ytick.color': MUDO,
    'axes.grid': True, 'grid.color': GRILLA, 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'legend.frameon': False, 'figure.dpi': 140,
})

# (etiqueta, retardos en muestras respecto del primer pulso, color)
CASOS = [
    ('limpio (1 pulso)',        [],              '#2a78d6'),
    ('doble  Δt = 4  (32 ns)',  [4],             '#2e8b57'),
    ('doble  Δt = 20 (160 ns)', [20],            '#c9a227'),
    ('doble  Δt = 150 (1.2 µs)', [150],          '#eb6834'),
    ('doble  Δt = 600 (4.8 µs)', [600],          '#d03b3b'),
    ('triple Δt = 120 y 320',   [120, 320],      '#7a5bbd'),
]

A_MIN, A_MAX = 200.0, 2600.0     # amplitud de CADA pulso, en cuentas de ADC

# Conversión a unidades físicas. 1 cuenta = 1/8192 V, 1 muestra = 8 ns, así que
# la carga en mV·µs es q_tot * (1000/8192) * 0.008 = q_tot / 1024.
MV_POR_CUENTA = 1000.0 / pu.ADC_CNT_PER_V
CARGA_A_MVUS  = MV_POR_CUENTA * 1e6 / pu.FS_HZ


def _limpiar(ax):
    for lado in ('top', 'right'):
        ax.spines[lado].set_visible(False)


def simular(forma, retardos, n, modo, rng, a_min=A_MIN, a_max=A_MAX):
    """N realizaciones de un evento con `retardos`, amplitudes al azar y ruido.

    Todos los pulsos del evento llevan la MISMA amplitud: la variable que se
    barre acá es el espaciamiento, así que dejar las amplitudes independientes
    sólo agregaría dispersión sin agregar información. Lo que sí es aleatorio en
    cada realización es la amplitud común (pulser deslizante, para que el
    resultado cubra todo el rango dinámico) y el ruido de la cadena.

    Se descartan los eventos que tocan la saturación del ADC: ahí el pico deja
    de crecer con la amplitud y el punto no informa sobre la forma.
    """
    amps = rng.uniform(a_min, a_max, int(n))
    dt = np.array([0] + list(retardos), dtype=np.int64)
    picos, cargas, largos, n_ev = [], [], [], 0

    for a in amps:
        t = 400 + dt
        dat, _ = pu.render(t, np.full(dt.size, a), forma, rng=rng)
        if dat.max() >= pu.SAT_ADC:          # saturó: no informa sobre la forma
            continue
        ev = (pu.segmentar_rapido(dat, **pu.CFG_MODO0) if modo == 0
              else pu.compuertas_rapido(dat, **pu.CFG_MODO1))
        m = ev['cerrado']
        if not m.any():
            continue
        n_ev += int(m.sum())
        # el evento principal: el de mayor carga. Con Δt grande el segundo pulso
        # puede abrir su PROPIA ventana, y eso también es un resultado.
        k = int(np.argmax(np.where(m, ev['q_tot'], -1)))
        picos.append(int(ev['pico'][k]))
        cargas.append(int(ev['q_tot'][k]))
        largos.append(int(ev['largo'][k]))

    return (np.array(picos, dtype=float), np.array(cargas, dtype=float),
            np.array(largos, dtype=float), n_ev)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--familia', default='cr_rc4')
    ap.add_argument('--n', type=int, default=2500, help='realizaciones por caso')
    ap.add_argument('--semilla', type=int, default=0)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    forma, info = pu.forma_knoll(a.familia)
    print(f'=== pico vs carga, familia {a.familia} ===')
    print(f'  FWHM {info["fwhm_pts"]:.0f} muestras ({info["fwhm_pts"]*1e6/pu.FS_HZ:.2f} µs), '
          f'pico en la muestra {info["i_pico"]}, template {info["n"]}')
    print(f'  factor de forma de la familia: {info["factor_forma"]:.4f}')
    print(f'  {a.n} realizaciones por caso, amplitud uniforme en '
          f'[{A_MIN:.0f}, {A_MAX:.0f}] cuentas\n')

    out = a.out
    if out is None:
        c = sorted(glob.glob(os.path.join(_RAIZ, 'datos',
                                          'pileup_*')))
        out = c[-1] if c else _AQUI
    os.makedirs(out, exist_ok=True)

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.4))
    resultados = {}

    for modo, ax in zip((0, 1), axes):
        rng = np.random.default_rng(a.semilla + modo)
        print(f'--- modo {modo} '
              f'({"histéresis" if modo == 0 else "compuerta fija 384"}) ---')
        print(f'  {"caso":<26} {"Q/pico [µs]":>12} {"pendiente":>10} '
              f'{"ventana":>9} {"ev/real":>8}')

        pend_limpio = None
        for etiqueta, retardos, color in CASOS:
            pico, carga, largo, n_ev = simular(forma, retardos, a.n, modo, rng)
            if pico.size == 0:
                continue
            x = pico * MV_POR_CUENTA                 # mV
            y = carga * CARGA_A_MVUS                 # mV·µs
            razon = y / x                            # µs  (= Q/pico físico)

            # Si el MCA separó los pulsos en más de un evento, decirlo en la
            # etiqueta: si no, el lector ve una nube partida en dos y no tiene
            # cómo saber que la mitad de abajo son pulsos que NO se apilaron.
            ev_real = n_ev / float(a.n)
            et = etiqueta
            if retardos and ev_real > 1.02:
                et += f'  — {100*(ev_real-1)/len(retardos):.0f} % se separan'
            ax.scatter(x, y, s=3.0, alpha=.28, color=color, linewidths=0,
                       label=et)

            # pendiente por cuadrados mínimos forzada por el origen: es la
            # cantidad que el gráfico pico-vs-carga define
            pend = float((x * y).sum() / (x * x).sum())
            if pend_limpio is None:
                pend_limpio = pend
            # Eventos por realización: 1.0 significa que el MCA los fundió en
            # uno solo (apilamiento); 2.0 que los separó y midió los dos bien.
            # Es la lectura que la mediana sola esconde, porque a Δt grande la
            # ventana —que crece con la amplitud— separa los pulsos chicos y
            # funde los grandes, y el conjunto queda con DOS poblaciones.
            print(f'  {etiqueta:<26} {np.median(razon):12.3f} '
                  f'{pend/pend_limpio:9.3f}x {np.median(largo):8.0f} '
                  f'{ev_real:8.2f}')
            resultados[(modo, etiqueta)] = (float(np.median(razon)), pend)

        # la recta de eventos limpios, extendida sobre todo el rango
        xl = np.array([0, ax.get_xlim()[1]])
        ax.plot(xl, pend_limpio * xl, color=TINTA, lw=1.1, ls='--',
                label=f'recta de limpios ({pend_limpio:.2f} µs)')

        ax.set_xlabel('pico [mV]')
        ax.set_ylabel('carga [mV·µs]')
        ax.set_title(f'modo {modo} — '
                     f'{"ventana por histéresis" if modo == 0 else "compuerta fija de 384"}',
                     loc='left', color=TINTA2)
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
        _limpiar(ax)
        ax.legend(fontsize=7.5, loc='upper left', markerscale=4)
        print()

    # --- contraste contra la medición -------------------------------------
    # Con integración COMPLETA la pendiente vale factor_forma * FWHM. La ventana
    # por histéresis corta la cola por debajo de thr-hyst, así que la pendiente
    # medida tiene que quedar por DEBAJO de ese techo, y la compuerta fija de
    # 384 muestras más abajo todavía. Que el orden se cumpla es el chequeo.
    fwhm_us = info['fwhm_pts'] * 1e6 / pu.FS_HZ
    techo = info['factor_forma'] * fwhm_us
    p0 = resultados[(0, CASOS[0][0])][1]
    p1 = resultados[(1, CASOS[0][0])][1]
    print(f'  techo teórico (integración completa) = factor_forma x FWHM = '
          f'{info["factor_forma"]:.4f} x {fwhm_us:.2f} µs = {techo:.3f} µs')
    print(f'  pendiente medida, modo 0 (histéresis): {p0:.3f} µs  '
          f'({100*p0/techo:.1f} % del techo)')
    print(f'  pendiente medida, modo 1 (compuerta 384 = '
          f'{384e6/pu.FS_HZ:.2f} µs):   {p1:.3f} µs  ({100*p1/techo:.1f} %)')
    ok = p1 < p0 <= techo * 1.001
    print(f'  [{"PASS" if ok else "FAIL"}] compuerta fija < histéresis <= '
          f'integración completa')

    fig.suptitle(f'Pico contra carga, familia {a.familia} — eventos dobles y '
                 f'triples.  La recta punteada son los eventos limpios.',
                 x=0.008, ha='left', fontsize=10, color=TINTA2)
    fig.tight_layout(rect=(0, 0, 1, 0.955))
    p = os.path.join(out, f'pico_vs_carga_{a.familia}.png')
    fig.savefig(p, dpi=120, bbox_inches='tight')
    plt.close(fig)
    print(f'\nfigura: {os.path.relpath(p)}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

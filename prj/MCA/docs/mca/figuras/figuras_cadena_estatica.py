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
import json
import os
import sys

_AQUI_LIB = os.path.dirname(os.path.abspath(__file__))

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Patch
from matplotlib.ticker import MaxNLocator

from figuras_resolucion import (SUP, TINTA, TINTA2, MUDO, AZUL, NARAN, ROJO,
                                _limpiar, _panel)
sys.path.insert(0, os.path.join(_AQUI_LIB, '..', '..', 'figuras'))
import transacciones as T                                       # noqa: E402
from animacion_cadena_mca import (DT_TRAZA, VENTANA, UMBRAL, H_SHIFT,
                                  N_CANALES, simular)

_AQUI = os.path.dirname(os.path.abspath(__file__))

# cuántas cuentas lleva acumuladas cada panel de 07c (el último es el final)
HITOS = (12, 64)

# Histéresis de la ilustración: el módulo cierra al bajar de thr - hyst, no de
# thr, y sólo vuelve a disparar después de haberse re-armado por debajo de ese
# mismo nivel. El umbral de la simulación es 300 y no los 100 del default, así
# que la histéresis se escala igual para conservar la proporción hyst/thr = 1/2
# de `mca_top.sv` (cfg_thr = 100, cfg_hyst = 50). La ventana en serio —las dos
# reglas de cierre y lo que cada una le hace a la medida— está en
# ventana_de_medicion.md y sus figuras en figuras/ventana/.
HYST = UMBRAL // 2
THR_LO = UMBRAL - HYST


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


def ventana(sim, j):
    """(disparo, cierre) de la ventana del evento cuyo pico está en la muestra j.

    Igual que `mca_pulse_feature.sv` en modo histéresis: abre al cruzar `cfg_thr`
    hacia arriba y cierra recién al bajar de `cfg_thr - cfg_hyst`, no de
    `cfg_thr`. Esa asimetría es la que hace que la ventana termine bastante
    después del pico, sobre la cola.
    """
    y = sim['traza']
    a = b = j
    while a > 0 and y[a - 1] >= UMBRAL:
        a -= 1                                 # atrás hasta el cruce de thr
    while b < y.size - 1 and y[b + 1] >= THR_LO:
        b += 1                                 # adelante hasta bajar de thr-hyst
    return sim['grid'][a], sim['grid'][b]


def _traza_en(sim, t):
    return float(sim['traza'][int(np.clip(t / DT_TRAZA, 0, sim['grid'].size - 1))])


def elegir_ventana(sim):
    """Ventana que muestra todos los casos a la vez, cortada en los huecos.

    Pide al menos un pulso que NO cruza el umbral —el caso que hay que ver— y
    entre cuatro y seis que sí. Los dos bordes caen entre dos pulsos y por debajo
    de thr - hyst, así que NO queda ningún pulso a medio dibujar ni sin
    etiquetar: todo lo que dispara adentro de la ventana está en la tabla de la
    figura 7b.

    Pide además que ninguna ventana abierta se trague el disparo siguiente. Eso
    PUEDE pasar —es el apilamiento, y entonces dos pulsos caen en una sola
    ventana y en una sola cuenta—, pero acá se busca el caso limpio, porque el
    apilamiento tiene sus propias figuras en pileup/.

    Devuelve (t0, t1, eventos), con los eventos numerados en orden y cada uno
    descripto por lo que el MCA mediría de él.
    """
    t_ev, a_ev, ok = sim['t_ev'], sim['a_ev'], sim['aceptado']
    n = t_ev.size

    for k0 in range(1, n - 2):
        t0 = float(t_ev[k0]) - 1.6
        if t0 <= t_ev[k0 - 1] or _traza_en(sim, t0) >= THR_LO:
            continue                       # el pulso anterior sigue a la vista

        k1 = k0                            # estirar mientras entre el siguiente
        while k1 + 2 < n and float(t_ev[k1 + 2]) - 0.35 - t0 <= VENTANA:
            k1 += 1
        t1 = float(t_ev[k1 + 1]) - 0.35     # justo antes de que arranque el que sigue
        if not (20.0 <= t1 - t0 <= VENTANA) or _traza_en(sim, t1) >= THR_LO:
            continue

        idx = range(k0, k1 + 1)
        if not (4 <= sum(int(ok[k]) for k in idx) <= 6
                and not all(ok[k] for k in idx)):
            continue

        eventos = []
        for i, k in enumerate(idx, start=1):
            j, amp = medir_pico(sim, t_ev[k])
            ev = dict(n=i, t=float(sim['grid'][j]), amp=amp,
                      canal=min(int(amp) >> H_SHIFT, N_CANALES - 1),
                      gen=float(a_ev[k]), j=j, ok=bool(ok[k]))
            if ev['ok']:
                ev['disparo'], ev['cierre'] = ventana(sim, j)
            eventos.append(ev)

        cierres = [e['cierre'] for e in eventos if e['ok']]
        disparos = [e['disparo'] for e in eventos if e['ok']]
        if any(c >= d for c, d in zip(cierres, disparos[1:])):
            continue                       # una ventana se come el disparo siguiente
        if cierres[-1] >= t1:
            continue                       # la última no cierra adentro del gráfico

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

    # Los dos estados de pulse_feature, que entre los dos cubren todo el eje: la
    # ventana ABIERTA y el reposo PREVIO al disparo. El reposo no es tiempo
    # perdido —ahí el módulo se re-arma y el seguidor sigue la línea de base
    # contra la que después se mide la amplitud—, y por eso también va marcado.
    activas = [(e['disparo'], e['cierre']) for e in acep]
    reposo, cursor = [], t0
    for ta, tb in activas:
        if ta > cursor:
            reposo.append((cursor, ta))
        cursor = tb
    if cursor < t1:
        reposo.append((cursor, t1))

    for ta, tb in reposo:
        ax.axvspan(ta, tb, color=MUDO, alpha=0.07, lw=0, zorder=1)
    for ta, tb in activas:
        ax.axvspan(ta, min(tb, t1), color=AZUL, alpha=0.14, lw=0, zorder=1)

    ax.plot(sim['grid'][i0:i1], sim['traza'][i0:i1], lw=1.4, color=AZUL,
            zorder=3)
    ax.axhline(UMBRAL, color=ROJO, lw=1.1, ls='--', zorder=2)
    ax.axhline(THR_LO, color=ROJO, lw=1.0, ls=':', alpha=0.85, zorder=2)
    ax.text(0.008, UMBRAL, 'umbral (thr)', color=ROJO, va='bottom', ha='left',
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
    ax.set_ylim(-260, 3700)
    ax.set_xlabel('Tiempo [µs]')
    ax.set_ylabel('Amplitud sobre la base\n[cuentas de ADC]')
    ax.legend(handles=[
        Patch(fc=AZUL, alpha=0.14, ec='none', label='ventana abierta'),
        Patch(fc=MUDO, alpha=0.07, ec='none',
              label='reposo: sigue la línea de base'),
        Line2D([], [], color=ROJO, ls=':', lw=1.0,
               label='thr − hyst: cierra y re-arma')],
        loc='upper center', ncol=3, fontsize=8.5, handlelength=1.6,
        handleheight=0.9, borderpad=0.1, columnspacing=1.6,
        labelcolor=TINTA2)
    _limpiar(ax)


# =============================================================================
# Panel B — la cadena
# =============================================================================
def panel_cadena(ax, eventos):
    """El panel (b): los dos bloques y el tren de amplitudes en el cable.

    Las primitivas --la caja, el cable, la ficha del valor que viaja-- estan en
    `docs/figuras/transacciones.py`, que es de donde las toman las figuras de
    transacciones de los otros modulos. Las coordenadas quedan explicitas acá
    porque esta composicion ya estaba ajustada a mano.
    """
    ax.set_xlim(0, 10)
    ax.set_ylim(0.58, 2.88)
    ax.axis('off')

    T.caja(ax, 1.05, 2.70, 'pulse_feature',
           'abre una ventana con thr\ny mide la amplitud', AZUL)
    T.caja(ax, 6.45, 2.70, 'histograma',
           'incrementa el canal\ncorrespondiente', NARAN)

    T.cable(ax, 0.30, 1.00, 1.72, etiqueta='señal')
    T.cable(ax, 9.15, 9.85, 1.72, etiqueta='espectro')

    # el tren de números que viaja por el cable: los del panel A, en orden
    acep = [e for e in eventos if e['ok']]
    T.cable(ax, 3.75, 6.40, 1.72,
            etiqueta='un registro de evento por pulso',
            tren=[f"{e['amp']:.0f}" for e in acep],
            xs=np.linspace(4.28, 5.62, 3), xpuntos=6.05, dy=0.70,
            xetq=5.05)
    ax.text(7.80, 0.90, f'canal = amp >> {H_SHIFT}', ha='center', fontsize=9,
            color=MUDO, style='italic')


def panel_tabla(ax, eventos):
    """Los eventos del panel A, como los ve el histograma."""
    cols = ((0.6, 'pulso', 'left'), (3.0, 't [µs]', 'right'),
            (5.8, 'amp [cuentas]', 'right'),
            (9.3, f'canal = amp >> {H_SHIFT}', 'right'))
    filas = []
    for ev in eventos:
        ok = ev['ok']
        col = TINTA if ok else MUDO
        filas.append([
            {'t': f"#{ev['n']}", 'color': col},
            {'t': f"{ev['t']:.1f}", 'color': col},
            {'t': f"{ev['amp']:.0f}", 'color': col, 'bold': ok},
            {'t': f"{ev['canal']}" if ok else 'rechazado: amp < thr',
             'color': col, 'bold': ok, 'italic': not ok},
        ])
    T.panel_tabla(ax, cols, filas)


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


# =============================================================================
# Manifiesto
#
# Las figuras del MCA son ANTERIORES a la convencion de
# `docs/<m>/figuras/transacciones/`, y mover cuatro PNG versionados para que la
# ruta quede prolija no vale la pena. Lo que se escribe es el manifiesto, en el
# lugar donde `datasheet.py` lo busca, apuntando a los archivos donde estan.
# =============================================================================

MANIFIESTO = os.path.join(_AQUI, 'transacciones', 'transacciones.json')

ITEMS = [
    dict(archivo='../07_cadena.png',
         titulo='LA CADENA DE UN EVENTO  -  senal, registro y espectro',
         origen='simulacion con semilla fija (`animacion_cadena_mca.py`), '
                'los mismos cuadros que los videos',
         nota='La transaccion del MCA es UN EVENTO, y la figura la sigue '
              'entera: (a) la senal de entrada con el umbral y la ventana que '
              '`pulse_feature` abre y cierra, (b) el camino de datos, donde '
              'entre los dos bloques no va una flecha pelada sino el tren de '
              'amplitudes concretas que viaja --un registro de evento por '
              'pulso--, y (c) el espectro que se acumula del otro lado, una '
              'cuenta por numero. Los numeros de los tres paneles son los '
              'mismos: la amplitud que se mide en (a) es la que viaja en (b) '
              'y la que cae en un canal en (c), con el mismo `amp >> h_shift` '
              'que hace el RTL. Es la unica figura del proyecto que muestra '
              'la cuenta completa de punta a punta.'),
    dict(archivo='../07a_senal.png',
         titulo='(a) LA SENAL: UN PULSO POR EVENTO',
         origen='la misma simulacion, panel (a) suelto',
         nota='Las bandas parten el eje de TIEMPO en estados --ventana '
              'abierta, reposo-- y no la senal en eventos. La ventana abre al '
              'cruzar `thr` y cierra recien al bajar de `thr - hyst`, que es '
              'lo que hace que termine bastante despues del pico.'),
    dict(archivo='../07b_cadena.png',
         titulo='(b) EL CAMINO DE DATOS: UN NUMERO POR PULSO',
         origen='la misma simulacion, panel (b) suelto',
         nota='`pulse_feature` emite un registro de evento por pulso y el '
              'histograma lo convierte en una cuenta. La tabla de abajo son '
              'los mismos pulsos como los ve el histograma, incluido el que '
              'no cruza el umbral y no produce nada.'),
    dict(archivo='../07c_histograma.png',
         titulo='(c) EL ESPECTRO: UNA CUENTA POR NUMERO',
         origen='la misma simulacion, panel (c) suelto',
         nota='El mismo espectro en tres momentos de la acumulacion (12, 64 y '
              '227 cuentas): la forma aparece recien cuando hay estadistica.'),
]


def escribir_manifiesto():
    os.makedirs(os.path.dirname(MANIFIESTO), exist_ok=True)
    with open(MANIFIESTO, 'w', encoding='utf-8') as fh:
        json.dump(ITEMS, fh, ensure_ascii=False, indent=2)
        fh.write('\n')
    print('  transacciones/transacciones.json')


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
    escribir_manifiesto()


if __name__ == '__main__':
    main()

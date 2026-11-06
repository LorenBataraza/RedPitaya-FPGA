#!/usr/bin/env python3
"""Figuras del Monte-Carlo de apilamiento, desde los .npz que dejó montecarlo.py.

Corre en la PC y NO vuelve a simular: todo sale de los archivos guardados, así
que rehacer una figura cuesta segundos y no minutos. Es el mismo reparto que usa
`testbench_mca.plot_all`.

    python3 monte-carlo/graficar.py [directorio]      # por defecto, la corrida más reciente
"""
import glob
import json
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

# --- paleta (la misma de docs/mca/figuras/figuras_resolucion.py) -------------
SUP    = '#fcfcfb'
TINTA  = '#0b0b0b'
TINTA2 = '#52514e'
MUDO   = '#898781'
GRILLA = '#e1e0d9'
AZUL   = '#2a78d6'   # la verdad / la referencia
NARAN  = '#eb6834'   # lo medido, deformado
ROJO   = '#d03b3b'   # lo que se está señalando
VERDE  = '#2e8b57'   # lo recuperado por el corte
RAMPA  = ['#86b6ef', '#5598e7', '#2a78d6', '#1c5cab', '#104281']

plt.rcParams.update({
    'figure.facecolor': SUP, 'axes.facecolor': SUP, 'savefig.facecolor': SUP,
    'font.size': 10, 'axes.titlesize': 10, 'axes.labelsize': 10,
    'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': TINTA2,
    'text.color': TINTA, 'xtick.color': MUDO, 'ytick.color': MUDO,
    'axes.grid': True, 'grid.color': GRILLA, 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'legend.frameon': False, 'figure.dpi': 140,
})

MODO = {0: 'histéresis', 1: 'compuertas fijas'}
RAZON = {'q_pico': 'Q/pico', 'psd': 'Q_cola/Q_tot (en HW)'}

# Una configuración tiene su color y su marcador en TODAS las figuras, en este
# orden fijo. El orden pasa las pruebas de color entre vecinos (ΔE CVD >= 8), pero
# con seis líneas que se cruzan cualquiera puede quedar al lado de cualquiera: el
# marcador y el nombre al final de la línea son los que aseguran que se distingan.
PALETA = ('#2a78d6', '#eb6834', '#c2417e', '#a5820f', '#7a5bbd', '#2e8b57')
MARCAS = ('o', 's', '^', 'D', 'v', 'P')


def _es_mca2(res):
    return res.get('mapa') == 'MCA2'


def _indice(res, c):
    """La posición fija de la configuración: el color sigue a la configuración."""
    if _es_mca2(res):
        return list(res['configs']).index(c['modo'])
    return next(i for i, x in enumerate(res['combinaciones']) if x is c)


def _color(res, c):
    return PALETA[_indice(res, c) % len(PALETA)]


def _marca(res, c):
    return MARCAS[_indice(res, c) % len(MARCAS)]


def _corta(res, c):
    """La etiqueta corta de una combinación, para las leyendas."""
    return f'{c["espectro"]} {c["modo"]}' if _es_mca2(res) else f'{c["espectro"]} m{c["modo"]}'


def _titulo(res, c):
    if _es_mca2(res):
        return f'{c["espectro"]} — {res["configs"][c["modo"]]["etiqueta"]}'
    return f'{c["espectro"]} — modo {c["modo"]} ({MODO[c["modo"]]})'


def _para_superponer(res):
    """Las combinaciones que entran en una misma figura de líneas: en el MCA2 son
    doce, así que se dibuja un espectro solo (el otro cuenta la misma historia)."""
    combos = res['combinaciones']
    if not _es_mca2(res):
        return combos
    esp = 'linea' if any(c['espectro'] == 'linea' for c in combos) else combos[0]['espectro']
    return [c for c in combos if c['espectro'] == esp]


def _grilla(n):
    filas = max(1, (n + 1) // 2)
    return plt.subplots(filas, 2 if n > 1 else 1, figsize=(11, 3.6 * filas), squeeze=False)


def _limpiar(ax):
    for lado in ('top', 'right'):
        ax.spines[lado].set_visible(False)


def _guardar(fig, out, nombre):
    p = os.path.join(out, nombre)
    fig.savefig(p, dpi=120, bbox_inches='tight')
    plt.close(fig)
    print(f'  {nombre}')


def _suavizar(h, f=8):
    """Reagrupa para que las figuras muestren forma y no ruido de Poisson."""
    return pu.rebin(h, f), f


# =============================================================================
def fig_espectros(d, res, out):
    """Los tres espectros superpuestos: qué le hace el apilamiento al histograma."""
    combos = res['combinaciones']
    fig, axes = _grilla(len(combos))
    axes = axes.ravel()

    for ax, c in zip(axes, combos):
        z = np.load(os.path.join(d, f'{c["espectro"]}_modo{c["modo"]}.npz'))
        tasas = z['tasas']
        roi = res['espectros'][c['espectro']]
        # la tasa más alta que todavía deja estadística para ver la forma
        it = int(np.argmin(np.abs(tasas - 1e5)))

        h_ver, h_ref, h_med = z['h_ver'], z['h_ref'], z['h_med'][it]
        g_ver, f = _suavizar(h_ver)
        g_ref, _ = _suavizar(h_ref)
        g_med, _ = _suavizar(h_med)
        x = (np.arange(g_ver.size) + 0.5) * f

        # normalizados al número de eventos generados: comparables entre sí
        ax.step(x, g_ver / h_ver.sum(), where='mid', color=MUDO, lw=1.0,
                label='verdad (fuente)')
        ax.step(x, g_ref / h_ver.sum(), where='mid', color=AZUL, lw=1.3,
                label='referencia (tasa cero)')
        ax.step(x, g_med / h_ver.sum(), where='mid', color=NARAN, lw=1.3,
                label=f'medido a {tasas[it]/1e3:.0f} kcps')
        ax.axvline(roi['tope'], color=ROJO, lw=1.0, ls=':')
        ax.set_yscale('log')
        ax.set_xlim(0, min(2.6 * roi['tope'], z['h_ver'].size))
        ax.set_ylim(1e-6, None)
        ax.set_xlabel('canal (= cuentas de amplitud verdadera)')
        ax.set_ylabel('fracción por canal')
        ax.set_title(_titulo(res, c), loc='left', color=TINTA2)
        _limpiar(ax)
        ax.legend(loc='upper right', fontsize=8)

    fig.tight_layout()
    _guardar(fig, out, 'espectros.png')


def fig_distorsion(d, res, out):
    """Las métricas de distorsión contra la tasa, con el modelo de tiempo muerto."""
    combos = _para_superponer(res)
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))

    for i, c in enumerate(combos):
        roi = res['espectros'][c['espectro']]
        p = roi['picos'][0]
        tasas = np.array([f['tasa'] for f in c['filas']])
        col, mk = _color(res, c), _marca(res, c)
        et = _corta(res, c)

        area = np.array([f[f'm{p}']['area_rel'] for f in c['filas']])
        cont = np.array([f[f'm{p}']['continuo'] for f in c['filas']])
        l1   = np.array([f[f'm{p}']['l1'] for f in c['filas']])
        thru = np.array([f['n_det'] / f['n_gen'] for f in c['filas']])

        # Dos pérdidas distintas, y la diferencia entre ellas ES el apilamiento:
        #   - el THROUGHPUT (línea fina) pierde por tiempo muerto y nada más, y
        #     por eso sigue al modelo paralizable;
        #   - el FOTOPICO (línea gruesa) pierde eso MÁS los eventos que el
        #     apilamiento se llevó fuera del pico. Comparar el fotopico contra el
        #     modelo de tiempo muerto sería mezclar las dos cosas.
        axes[0].plot(tasas / 1e3, thru, '-', color=col, lw=0.9, alpha=.55)
        axes[0].plot(tasas / 1e3, area, '-', marker=mk, color=col, ms=3.5, lw=1.6, label=et)
        axes[1].plot(tasas / 1e3, 100 * cont, '-', marker=mk, color=col, ms=3.5, lw=1.3,
                     label=et)
        axes[2].plot(tasas / 1e3, l1, '-', marker=mk, color=col, ms=3.5, lw=1.3, label=et)

        # modelo paralizable con la ventana medida: m/n = exp(-lambda*L0). El MCA2
        # no paraliza: la pérdida por ranuras va aparte, en perdida_y_buenos.png.
        if i < 2 and not _es_mca2(res):
            L0 = c['L0'] / pu.FS_HZ
            axes[0].plot(tasas / 1e3, np.exp(-tasas * L0), ls='--', lw=1.0,
                         color=MUDO,
                         label='exp(-λL₀) paralizable' if i == 0 else None)

    for ax, t, yl in ((axes[0], 'fotopico (grueso) contra throughput (fino)',
                       'fracción de lo incidente'),
                      (axes[1], 'continuo por encima del tope', '% de las cuentas'),
                      (axes[2], 'deformación global', 'distancia L1')):
        ax.set_xscale('log')
        ax.set_xlabel('tasa incidente [kcps]')
        ax.set_ylabel(yl)
        ax.set_title(t, loc='left', color=TINTA2)
        _limpiar(ax)
    axes[0].legend(fontsize=7.5, loc='lower left')
    fig.tight_layout()
    _guardar(fig, out, 'distorsion_vs_tasa.png')


def fig_mapa(d, res, out):
    """Amplitud contra factor de forma: dónde se separan limpios y apilados."""
    combos = res['combinaciones']
    if _es_mca2(res):                  # doce filas no se leen: lo que hay para decir
        combos = [c for c in _para_superponer(res) if c['modo'] in ('r1', 'r4', 'banco')]
    fig, axes = plt.subplots(len(combos), 2, figsize=(10.5, 3.3 * len(combos)),
                             squeeze=False)

    for fila, c in zip(axes, combos):
        z = np.load(os.path.join(d, f'{c["espectro"]}_modo{c["modo"]}.npz'))
        if 'mapa_amp' not in z:
            continue
        amp = z['mapa_amp'].astype(float)
        n_arr = z['mapa_n_arr']
        cal = z['cal']
        a_true = (amp - cal[1]) / cal[0]           # eje en amplitud verdadera

        for ax, rz in zip(fila, res['razones']):
            r = z[f'mapa_r_{rz}'].astype(float)
            lim = n_arr <= 1
            ax.scatter(a_true[lim], r[lim], s=1.2, alpha=.18, color=AZUL,
                       linewidths=0, label='limpio (1 pulso)')
            ax.scatter(a_true[~lim], r[~lim], s=1.2, alpha=.30, color=ROJO,
                       linewidths=0, label='apilado (>1 pulso)')

            ce, me, si = z[f'locus_{rz}']
            ce_t = (ce - cal[1]) / cal[0]
            ax.plot(ce_t, me, color=TINTA, lw=1.2, label='lugar geométrico')
            ax.plot(ce_t, me + 3 * si, color=TINTA, lw=1.0, ls='--',
                    label='banda k=3')

            fin = np.isfinite(r)
            if fin.any():
                ax.set_ylim(np.nanpercentile(r[fin], 0.5),
                            np.nanpercentile(r[fin], 99.5))
            ax.set_xlim(0, np.percentile(a_true, 99.8))
            ax.set_xlabel('amplitud verdadera equivalente [cuentas]')
            ax.set_ylabel(RAZON[rz])
            ax.set_title(f'{_corta(res, c)} — {RAZON[rz]}',
                         loc='left', color=TINTA2, fontsize=9)
            _limpiar(ax)
    axes[0][0].legend(fontsize=7, loc='upper left', markerscale=6)
    fig.tight_layout()
    _guardar(fig, out, 'mapa_forma.png')


def fig_corte(d, res, out):
    """El espectro antes y después del corte, contra la referencia."""
    combos = res['combinaciones']
    ks = res['ks']
    ik = int(np.argmin(np.abs(np.array(ks) - 3.0)))
    fig, axes = _grilla(len(combos))
    axes = axes.ravel()

    for ax, c in zip(axes, combos):
        z = np.load(os.path.join(d, f'{c["espectro"]}_modo{c["modo"]}.npz'))
        tasas = z['tasas']
        roi = res['espectros'][c['espectro']]
        it = int(np.argmin(np.abs(tasas - 1e5)))
        ir = res['razones'].index('q_pico')

        h_ref, h_med = z['h_ref'], z['h_med'][it]
        h_cut = z['h_cortes'][it, ir, ik]
        n = h_ref.sum()
        for h, col, et in ((h_ref, AZUL, 'referencia (tasa cero)'),
                           (h_med, NARAN, f'medido a {tasas[it]/1e3:.0f} kcps'),
                           (h_cut, VERDE, f'medido + corte Q/pico k={ks[ik]:g}')):
            g, f = _suavizar(h)
            ax.step((np.arange(g.size) + .5) * f, g / n, where='mid',
                    color=col, lw=1.3, label=et)
        ax.axvline(roi['tope'], color=ROJO, lw=1.0, ls=':')
        ax.set_yscale('log')
        ax.set_xlim(0, min(2.6 * roi['tope'], h_ref.size))
        ax.set_ylim(1e-6, None)
        ax.set_xlabel('canal')
        ax.set_ylabel('fracción por canal')
        ax.set_title(_titulo(res, c), loc='left', color=TINTA2)
        _limpiar(ax)
        ax.legend(loc='upper right', fontsize=8)
    fig.tight_layout()
    _guardar(fig, out, 'corte.png')


def fig_compromiso(d, res, out):
    """Eficiencia contra rechazo: lo que cuesta cada punto de corrección."""
    combos = _para_superponer(res)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.0))

    for i, c in enumerate(combos):
        roi = res['espectros'][c['espectro']]
        p = roi['picos'][0]
        tasas = np.array([f['tasa'] for f in c['filas']])
        it = int(np.argmin(np.abs(tasas - 1e5)))
        fila = c['filas'][it]
        col = _color(res, c)

        for rz, ls, mk in (('q_pico', '-', 'o'), ('psd', '--', 's')):
            sub = [x for x in fila['cortes'] if x['razon'] == rz]
            ef = np.array([x['eficiencia'] for x in sub])
            re = np.array([x['rechazo'] for x in sub])
            l1 = np.array([x[f'm{p}']['l1'] for x in sub])
            et = f'{_corta(res, c)} {RAZON[rz]}'
            axes[0].plot(100 * re, 100 * ef, ls, marker=mk, color=col, ms=3.5,
                         lw=1.2, label=et)
            axes[1].plot([x['k'] for x in sub], l1, ls, marker=mk, color=col,
                         ms=3.5, lw=1.2, label=et)
        axes[1].axhline(fila[f'm{p}']['l1'], color=col, lw=0.8, ls=':')

    axes[0].set_xlabel('apilados rechazados [%]')
    axes[0].set_ylabel('limpios conservados [%]')
    axes[0].set_title('lo que cuesta rechazar', loc='left', color=TINTA2)
    axes[1].set_xlabel('ancho de la banda, k [sigmas]')
    axes[1].set_ylabel('distancia L1 al espectro de referencia')
    axes[1].set_title('deformación que queda (punteado: sin corte)',
                      loc='left', color=TINTA2)
    for ax in axes:
        _limpiar(ax)
    axes[0].legend(fontsize=7, loc='lower left')
    fig.tight_layout()
    _guardar(fig, out, 'compromiso.png')


def fig_perdida_y_buenos(d, res, out):
    """Lo que sólo tiene el MCA2: cuánto se pierde por ranuras y cuánto sirve.

    La izquierda es la pérdida de disparos contra Erlang B, con la carga de disparos
    medida. Es un modelo de arribos de Poisson, y por eso se aparta hacia arriba: el
    disparo funde los pulsos cercanos, y los que quedan llegan más separados.

    La derecha es la pregunta de fondo: por segundo, cuántos eventos miden bien la
    amplitud del pulso que los disparó. Más ranuras dan más eventos, no más eventos
    buenos, si lo que se publica es la integral.
    """
    if not _es_mca2(res):
        return
    combos = _para_superponer(res)
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.4))
    rotulados = []
    for c in combos:
        col, mk = _color(res, c), _marca(res, c)
        tasas = np.array([f['tasa'] for f in c['filas']])
        perd = np.array([f['frac_perdidos'] for f in c['filas']])
        erl = np.array([f['erlang'] for f in c['filas']])
        buenos = np.array([f['tasa_buenos'] for f in c['filas']])
        et = f'{c["modo"]}: {res["configs"][c["modo"]]["etiqueta"]}'
        # Sin ceros en el eje log: lo que no pierde nada, simplemente no se dibuja.
        v = perd > 0
        axes[0].plot(tasas[v] / 1e3, 100 * perd[v], '-', marker=mk, color=col, ms=4.5,
                     lw=1.5, label=et)
        v = erl > 1e-4
        axes[0].plot(tasas[v] / 1e3, 100 * erl[v], ':', color=col, lw=1.1)
        v = buenos > 0
        axes[1].plot(tasas[v] / 1e3, buenos[v] / 1e3, '-', marker=mk, color=col, ms=4.5,
                     lw=1.5, label=et)
        # El nombre al final de la línea, salvo que pise al de otra: la leyenda está.
        y_fin = buenos[v][-1] / 1e3
        if all(abs(np.log10(y_fin / y)) > 0.08 for y in rotulados):
            rotulados.append(y_fin)
            axes[1].annotate(c['modo'], (tasas[v][-1] / 1e3, y_fin), xytext=(6, 0),
                             textcoords='offset points', va='center', fontsize=8,
                             color=TINTA2)
    xs = np.array([f['tasa'] for f in combos[0]['filas']]) / 1e3
    axes[1].plot(xs, xs, '--', color=MUDO, lw=1.0, label='todos los pulsos')
    axes[0].set_yscale('log')
    axes[0].set_ylabel('disparos perdidos [%]')
    axes[0].set_title('pérdida por ranuras (punteado: Erlang B)', loc='left', color=TINTA2)
    axes[1].set_yscale('log')
    axes[1].set_ylabel('eventos buenos [kcps]')
    axes[1].set_title('eventos con error < 1 % contra la amplitud verdadera',
                      loc='left', color=TINTA2)
    for ax in axes:
        ax.set_xscale('log')
        ax.set_xlabel('tasa incidente [kcps]')
        _limpiar(ax)
    axes[1].legend(fontsize=7.5, loc='upper left')
    fig.tight_layout()
    _guardar(fig, out, 'perdida_y_buenos.png')


def fig_familias_evento(d, res, out):
    """Lo que el MCA registra COMO UN SOLO EVENTO, en volts contra µs.

    Es de la réplica del MCA1, con su ventana por histéresis: es donde la familia
    de eventos se ve; con la compuerta del MCA2 todas las ventanas miden lo mismo.

    Es la figura que hace visible lo que el resto del estudio cuenta con
    números: por qué Q/pico separa las poblaciones de `mapa_forma.png`, y por
    qué hay un piso que ningún corte puede bajar.

    No usa los .npz del barrido: reconstruye seis casos con la misma `pu.render`
    y el mismo `pu.segmentar_rapido` que el Monte-Carlo, con las separaciones
    elegidas a mano para que cada panel muestre un régimen distinto.
    """
    forma, info = pu.forma_referencia()
    cfg = pu.CFG_MODO0
    A = 1920.0                                   # la línea del espectro
    rng = np.random.default_rng(4)
    V = pu.ADC_CNT_PER_V
    us = 1e6 / pu.FS_HZ                          # muestras -> µs

    #  (título, [(retardo en muestras, amplitud)])
    CASOS = [
        ('limpio — un solo pulso',            [(0, A)]),
        ('coincidencia exacta — Δt = 4 muestras (32 ns)',    [(0, A), (4, A)]),
        ('el borde — Δt = 20 muestras (160 ns)',             [(0, A), (20, A)]),
        ('solapamiento parcial — Δt = 150 (1.2 µs)',         [(0, A), (150, A)]),
        ('solapamiento en la cola — Δt = 600 (4.8 µs)',      [(0, A), (600, A)]),
        ('triple — Δt = 120 y 320',           [(0, A), (120, A), (320, A)]),
    ]

    # El lugar geométrico, calibrado con un PULSER DESLIZANTE igual que
    # `montecarlo.calibracion_pulser`. Tiene que ser dependiente de la amplitud:
    # un evento apilado de dos pulsos de la línea mide ~3840 cuentas, y el
    # Q/pico esperado ahí NO es el de 1920 —la ventana por histéresis se estira
    # con el logaritmo de la amplitud—. Comparar contra un valor fijo daría por
    # apilada a una coincidencia exacta, que es precisamente el caso que ningún
    # corte de forma puede detectar.
    a_cal = rng.uniform(110.0, 7000.0, 12000)
    d_cal, _ = pu.render_aislados(a_cal, forma, rng=rng)
    ev_cal = pu.segmentar_rapido(d_cal, **cfg)
    m = ev_cal['cerrado']
    ev_cal = {k: v[m] for k, v in ev_cal.items()}
    locus = pu.locus_forma(pu.amplitud(ev_cal, 0),
                           pu.razon_forma(ev_cal, 'q_pico'))

    fig, axes = plt.subplots(2, 3, figsize=(14, 6.8))
    thr_hi = cfg['thr'] / V
    thr_lo = (cfg['thr'] - cfg['hyst']) / V

    for ax, (titulo, pulsos) in zip(axes.ravel(), CASOS):
        t_idx = np.array([200 + p[0] for p in pulsos], dtype=np.int64)
        amps = np.array([p[1] for p in pulsos], dtype=float)
        dat, o = pu.render(t_idx, amps, forma, rng=rng)
        ev = pu.segmentar_rapido(dat, **cfg)

        x = np.arange(dat.size) * us
        ax.plot(x, dat / V, color=TINTA, lw=0.9)
        ax.axhline(thr_hi, color=ROJO, lw=0.9, ls=':')
        ax.axhline(thr_lo, color=MUDO, lw=0.9, ls=':')

        if ev['i0'].size:
            k = int(np.argmax(ev['q_tot']))
            i0, largo = int(ev['i0'][k]), int(ev['largo'][k])
            amp = pu.amplitud(ev, 0)[k:k + 1].astype(float)
            q_pico = float(pu.razon_forma(ev, 'q_pico')[k])
            esperado = float(np.interp(amp, locus[0], locus[1])[0])
            sigma = float(np.interp(amp, locus[0], locus[2])[0])
            desvio = (q_pico - esperado) / sigma
            acepta = desvio <= 3.0
            col = VERDE if acepta else ROJO
            ax.axvspan(i0 * us, (i0 + largo) * us, color=col, alpha=.10, lw=0)
            ax.axvline(i0 * us, color=col, lw=1.0)
            ax.axvline((i0 + largo) * us, color=col, lw=1.0)
            # los números del evento (ventana, amplitud, Q/pico, desvío) no
            # van en la figura: el veredicto lo dice el color del sombreado
            ax.set_xlim(0, min(dat.size, i0 + largo + 300) * us)

        ax.set_title(titulo, loc='left', color=TINTA2, fontsize=9)
        ax.set_xlabel('tiempo [µs]')
        ax.set_ylabel('tensión [V]')
        _limpiar(ax)

    fig.suptitle('Familias de evento del apilamiento (réplica del MCA1) — sombreado: '
                 'la ventana del MCA.  Punteados: thr y thr−hyst.',
                 x=0.008, ha='left', fontsize=10, color=TINTA2)
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    _guardar(fig, out, 'familias_evento.png')


def main():
    if len(sys.argv) > 1:
        d = sys.argv[1]
    else:
        cands = sorted(glob.glob(os.path.join(_RAIZ, 'datos',
                                              'pileup_*')))
        if not cands:
            raise SystemExit('no hay corridas pileup_* en software/datos/')
        d = cands[-1]

    with open(os.path.join(d, 'resumen.json')) as f:
        res = json.load(f)
    print(f'=== {os.path.relpath(d)} ===')
    print(f'{res["n_eventos"]} eventos por punto, '
          f'{len(res["tasas"])} tasas, {len(res["combinaciones"])} combinaciones')

    for fn in (fig_familias_evento, fig_espectros, fig_distorsion,
               fig_mapa, fig_corte, fig_compromiso, fig_perdida_y_buenos):
        try:
            fn(d, res, d)
        except Exception as e:                      # una figura mala no tira el resto
            print(f'  [ERROR] {fn.__name__}: {type(e).__name__}: {e}')
    print(f'\nfiguras en {d}')


if __name__ == '__main__':
    main()

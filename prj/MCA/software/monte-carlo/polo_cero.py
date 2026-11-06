#!/usr/bin/env python3
"""¿Cuánto del corrimiento con la tasa cancelaría una corrección polo-cero?

Corre en la PC, sin placa, sobre datos ya medidos.

QUEDA EN EL MCA1, A PROPÓSITO
-----------------------------
Usa la réplica del MCA1 de `pileup.py` y no la del MCA2 (`replica_mca2.py`): pone a prueba la atribución de `resultados_validacion_hw.md` §19.3 sobre mediciones hechas con ese bitstream.
Repetirlo sobre el MCA2 no explicaría esas mediciones.

LA PREGUNTA
-----------
`resultados_validacion_hw.md` §19.3 atribuye el corrimiento de centroide con la
tasa (+1.17 % entre 1995 Hz y 72 kHz, base en vuelo −60 → −101 cuentas) al
pedestal de la línea de base, y ese pedestal a un UNDERSHOOT de la cola. De ahí
concluye que la cancelación polo-cero (PZ) lo elimina. Pero el undershoot nunca
se midió: se infirió del corrimiento. Este script lo mide y pone la cadena
completa a prueba.

QUÉ HACE
--------
  1. MIDE el undershoot en capturas crudas del scope (`datos/20260527_*`):
     ajusta el modelo polo-cero y = c + p − η·LP_τ{p} (un acople AC parcial:
     ganancia de continua 1 − η) a las muestras FUERA de los pulsos.

  2. PREDICE con ese undershoot medido la base en vuelo y el corrimiento de
     centroide de la campaña de deriva (`datos/deriva_20260908_base2`): el
     mismo estímulo (rectángulos de 2 µs del DG4162 en modo PULSE, tren
     periódico), la misma configuración (`testbench_mca.DEFAULT_CFG`: thr 100,
     hyst 40, bl_k 12, holdoff 64, estimador de pico) y el mismo seguidor de
     base que el RTL. Lo compara con lo medido.

  3. AJUSTA el mejor modelo lineal (η, τ libres) a la campaña, para ver si
     ALGÚN undershoot lineal la reproduce, y con qué η.

  4. SIMULA las correcciones sobre la parte lineal: PZ exacta, PZ desajustada
     ±20 % en η o en τ, y el holdoff largo (la alternativa de "esconderse").

EL MODELO DEL SEGUIDOR
----------------------
Para barrer parámetros se usa una réplica vectorizada: con rectángulos de
~3800 cuentas y thr = 100 la ventana abre y cierra en los flancos, así que la
máscara de congelamiento NO depende de la base y el IIR queda lineal sobre las
muestras en que actualiza. Se valida contra `pileup.segmentar_base` (el
modelo fiel al RTL, muestra a muestra, con ruido) en dos tasas.

    python3 polo_cero.py                     # ~1 min
    python3 polo_cero.py --out DIR
"""
import argparse
import json
import os
import sys

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import lfilter, lfilter_zi

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)                      # software/
sys.path.insert(0, _RAIZ)
_DOCS = os.path.join(_RAIZ, '..', 'docs')
sys.path.insert(0, os.path.join(_DOCS, 'figuras'))

import matplotlib                                       # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt                         # noqa: E402
from estilo import (SUP, TINTA, TINTA2, MUDO, AZUL, NARAN, VERDE,  # noqa: E402
                    MORADO, RAMPA, limpiar, panel, escribir_epigrafes)
import pileup as pu                                     # noqa: E402

FS = 125e6
TS_US = 1e6 / FS
DATOS = os.path.join(_RAIZ, 'datos')
CAPTURAS = ('20260527_191742__sanity_in1.npz', '20260527_191742__sanity_in2.npz',
            '20260527_215917__sanity_in1.npz')
CAMPANA = os.path.join('deriva_20260908_base2', 'sweep_rate.npz')

# testbench_mca.DEFAULT_CFG, que es con lo que corrió la campaña
THR, HYST, BL_K, HOLD = 100, 40, 12, 64
W = 250                         # 2 µs: el ancho fijo hasta 72 kHz (§13.1)
SIGMA_W = 4.47                  # ruido blanco por muestra (ruido_20261009)
F_LO, F_HI = 1995.0, 72444.0    # el tramo de ancho nominal

EPIGRAFES = []


def guardar(fig, out, nombre, nota):
    fig.savefig(os.path.join(out, nombre), bbox_inches='tight')
    plt.close(fig)
    EPIGRAFES.append({'archivo': nombre, 'nota': nota})
    print(' ', nombre)


# =============================================================================
# 1. El undershoot, medido
# =============================================================================

def lp(x, tau_m, x0=None):
    """Pasabajos de un polo, ganancia de continua 1. tau en muestras."""
    a = np.exp(-1.0 / tau_m)
    zi = [a * (np.mean(x) if x0 is None else x0)]
    return lfilter([1 - a], [1, -a], x, zi=zi)[0]


def medir_undershoot(path):
    """Ajusta y = c − η·LP_τ{y} a las muestras fuera de los pulsos.

    Usa la propia señal medida como entrada del pasabajos: como η es chico, la
    diferencia con la entrada verdadera es de segundo orden.
    """
    d = np.load(path, allow_pickle=True)
    x = d['d1'] * pu.ADC_CNT_PER_V
    en_pulso = x > 200
    fuera = ~en_pulso.copy()
    for i in np.flatnonzero(en_pulso):
        fuera[max(0, i - 5):i + 15] = False
    fuera[:2500] = False                        # que el pasabajos converja

    def res(q):
        c, eta, tau = q
        return (c - eta * lp(x, tau) - x)[fuera]

    mejor = None
    for tau0 in (100, 300, 1000, 3000):
        r = least_squares(res, [0, 0.02, tau0],
                          bounds=([-500, 0, 10], [500, 1, 1e5]))
        if mejor is None or r.cost < mejor.cost:
            mejor = r
    c, eta, tau = mejor.x
    return dict(archivo=os.path.basename(path), c=float(c), eta=float(eta),
                tau_m=float(tau), rms=float(np.sqrt(np.mean(mejor.fun ** 2))),
                x=x, fuera=fuera)


# =============================================================================
# 2. La cadena: tren periódico -> polo-cero -> [PZ] -> seguidor -> pico
# =============================================================================

def tren(tasa, A, L0, eta, tau_m, n_med=12, sigma=0.0, rng=None):
    """Tren periódico de rectángulos pasado por el polo-cero."""
    P = FS / tasa
    calent = max(6 * 2 ** BL_K, 10 * tau_m)
    n_cal = int(np.ceil(calent / P)) + 1
    starts = (np.round(np.arange(n_cal + n_med) * P) + 100).astype(int)
    N = starts[-1] + int(P)
    p = np.zeros(N)
    for s in starts:
        p[s:s + W] = A
    y = L0 + p - eta * lp(p, tau_m, x0=0.0)
    if sigma:
        y = y + rng.normal(0, sigma, N)
    return y, starts, n_cal


def pz_corregir(y, eta, tau_m):
    """Inversa exacta del polo-cero: G = (1 − a z⁻¹) / ((1 − η(1−a)) − a z⁻¹).

    Estable mientras η < 1. En RTL es un acumulador y dos coeficientes.
    """
    if not eta:
        return y
    a = np.exp(-1.0 / tau_m)
    b, den = [1.0, -a], [1.0 - eta * (1 - a), -a]
    return lfilter(b, den, y, zi=lfilter_zi(b, den) * y[0])[0]


def seguidor_rapido(y, starts, n_cal, hold=HOLD, L0=0.0):
    """Base media en vuelo y amplitud media de pico (réplica vectorizada).

    La máscara de congelamiento es la ventana (los W muestras del pulso más el
    ciclo de guarda) más el holdoff, independiente de la base para estos
    rectángulos. El IIR corre sobre las muestras que actualiza.
    """
    N = y.size
    act = np.ones(N, bool)
    for s in starts:
        act[s:s + W + 1 + hold] = False
    alfa = 2.0 ** -BL_K
    yu = y[act]
    bu = lfilter([alfa], [1, -(1 - alfa)], yu, zi=[(1 - alfa) * L0])[0]
    base = np.full(N, np.nan)
    base[act] = bu
    if np.isnan(base[0]):
        base[0] = L0
    ii = np.where(~np.isnan(base), np.arange(N), 0)
    np.maximum.accumulate(ii, out=ii)
    base = base[ii]
    s0 = starts[n_cal]
    amps = np.array([(y[s:s + W] - base[s - 1]).max() for s in starts[n_cal:]])
    return float(base[s0:].mean()), float(amps.mean()), float(act[s0:].mean())


def cadena(tasas, A, L0, eta, tau_m, pz=None, hold=HOLD):
    """Base y amplitud contra la tasa. `pz` = (η_est, τ_est) o None."""
    bases, amps, frac = [], [], []
    for r in tasas:
        y, st, nc = tren(r, A, L0, eta, tau_m)
        if pz is not None:
            y = pz_corregir(y, *pz)
        b, a, f = seguidor_rapido(y, st, nc, hold=hold,
                                  L0=L0 if pz is None else L0 / (1 - pz[0]))
        bases.append(b); amps.append(a); frac.append(f)
    return np.array(bases), np.array(amps), np.array(frac)


def validar(A, L0, eta, tau_m, rng):
    """La réplica rápida contra pileup.segmentar_base (fiel al RTL, con ruido)."""
    filas = []
    for r in (12023.0, F_HI):
        y, st, nc = tren(r, A, L0, eta, tau_m, n_med=40, sigma=SIGMA_W, rng=rng)
        b_r, a_r, _ = seguidor_rapido(y, st, nc, L0=L0)
        dat = np.round(y).astype(np.int64)
        ev = pu.segmentar_base(dat, bl_auto=True, baseline=int(round(L0)),
                               bl_k=BL_K, bl_holdoff=HOLD, thr=THR, hyst=HYST,
                               maxlen=4096, traza_base=True)
        s0 = st[nc]
        b_f = float(ev['base'][s0:].mean())
        ok = ev['cerrado'] & (ev['i0'] >= s0)
        a_f = float(ev['pico'][ok].mean())
        filas.append(dict(tasa=r, base_rapido=b_r, base_rtl=b_f,
                          amp_rapido=a_r, amp_rtl=a_f, n_ev=int(ok.sum())))
    return filas


# =============================================================================
# Datos de la campaña
# =============================================================================

def campana():
    d = np.load(os.path.join(DATOS, CAMPANA))
    r = d['rates_deriva']
    bi, bv = d['baseline_ida'], d['baseline_vuelta']
    ci, cv = d['centroids_ida'], d['centroids_vuelta']
    nom = (r >= F_LO - 1) & (r <= F_HI + 1)
    i0 = np.flatnonzero(np.isclose(r, F_LO, rtol=0.01))[0]
    i72 = np.flatnonzero(np.isclose(r, F_HI, rtol=0.01))[0]
    L0 = float(np.mean(np.r_[bi[(r > 150) & (r < 1500)], bv[(r > 150) & (r < 1500)]]))
    A = 2.0 * float(ci[i0])                  # 1 canal = 2 cuentas en el eje de 8192
    return dict(r=r, bi=bi, bv=bv, ci=ci, cv=cv, nom=nom, i0=i0, i72=i72, L0=L0, A=A,
                dci=100 * (ci - ci[i0]) / ci[i0], dcv=100 * (cv - cv[i0]) / cv[i0])


def pct(amps, i0=0):
    return 100 * (amps - amps[i0]) / amps[i0]


# =============================================================================
# Figuras
# =============================================================================

def fig_undershoot(out, meds):
    m = meds[0]
    x, fuera = m['x'], m['fuera']
    hi = x > x.max() / 2
    up = np.flatnonzero(hi[1:] & ~hi[:-1]) + 1
    P = int(np.median(np.diff(up)))
    pre = 150
    segs = np.array([x[u - pre:u - pre + P] for u in up
                     if u - pre >= 2500 and u - pre + P <= x.size])
    mod = m['c'] - m['eta'] * lp(x, m['tau_m'])
    msegs = np.array([mod[u - pre:u - pre + P] for u in up
                      if u - pre >= 2500 and u - pre + P <= x.size])
    t = (np.arange(P) - pre) * TS_US

    fig, (a, b) = plt.subplots(1, 2, figsize=(10.6, 3.7))
    a.plot(t, segs.mean(0), color=AZUL, lw=2, label='medido (promedio de períodos)')
    a.axhline(0, color=MUDO, lw=0.8)
    a.set_xlabel('t desde el flanco (µs)')
    a.set_ylabel('cuentas')
    a.legend(loc='upper right', fontsize=9)
    panel(a, '(a)')

    fin = t[np.flatnonzero(segs.mean(0) > 200)[-1]] + 0.15
    sel = t > fin
    b.plot(t[sel], segs.mean(0)[sel], color=AZUL, lw=2, label='medido')
    b.plot(t[sel], msegs.mean(0)[sel], color=NARAN, lw=2, ls='--',
           label=f'polo-cero: η = {m["eta"]:.3f}, τ = {m["tau_m"] * TS_US:.1f} µs')
    b.axhline(m['c'], color=MUDO, lw=1, ls=':')
    b.set_ylim(m['c'] - 150, m['c'] + 40)
    b.set_xlabel('t desde el flanco (µs)')
    b.set_ylabel('cuentas')
    b.legend(loc='lower right', fontsize=9)
    panel(b, '(b)')
    for z in (a, b):
        limpiar(z)
    fig.tight_layout()
    filas = '\n'.join(f'| {q["archivo"]} | {q["eta"]:.4f} | {q["tau_m"] * TS_US:.2f} '
                      f'| {q["c"]:.1f} | {q["rms"]:.1f} |' for q in meds)
    guardar(fig, out, '01_undershoot_medido.png', f"""
El undershoot, medido en capturas crudas del scope (2026-05-27: tren
periódico de 100 kHz del ARB, pulsos de ~8000 cuentas y ~2 µs).

(a) Un período promediado sobre los pulsos de la captura. Después de cada
pulso la señal queda POR DEBAJO de su nivel de reposo y se recupera en
varios µs: el undershoot existe.

(b) La parte posterior al pulso, ampliada, con el ajuste del modelo
polo-cero y = c + p − η·LP_τ{{p}} (un acople de continua parcial: ganancia DC
1 − η) hecho sobre las muestras fuera de los pulsos. La punteada es c, el
nivel de reposo sin undershoot.

Ajuste sobre tres capturas independientes:

| captura | η | τ (µs) | c (cuentas) | rms (cuentas) |
{filas}

El rms queda cerca del ruido blanco (4.5 cuentas): un solo polo describe bien
el undershoot. η ≈ 0.04 quiere decir que el 4 % del área de cada pulso vuelve
como cola negativa de unos 5 µs.
""")


def fig_campana(out, C, pred, ajuste, tasas):
    fig, (a, b) = plt.subplots(1, 2, figsize=(10.6, 4.0))
    r, nom = C['r'], C['nom']
    ok_b = r > 150
    a.plot(r[ok_b], C['bi'][ok_b] - C['L0'], 'o', color=TINTA2, ms=6,
           mec=SUP, label='medido, ida')
    a.plot(r[ok_b], C['bv'][ok_b] - C['L0'], 's', color=TINTA2, ms=5,
           mfc='none', label='medido, vuelta')
    a.plot(tasas, pred['base'] - C['L0'], '-', color=AZUL, lw=2,
           label='lineal con el undershoot MEDIDO')
    a.plot(tasas, ajuste['base'] - C['L0'], '--', color=NARAN, lw=2,
           label=f'mejor lineal (η = {ajuste["eta"]:.2f}, τ = {ajuste["tau_us"]:.1f} µs)')
    a.axvspan(F_LO, F_HI, color=RAMPA[0], alpha=0.12, lw=0)
    a.set_xscale('log')
    a.set_xlabel('tasa (Hz)')
    a.set_ylabel('Δ base en vuelo (cuentas)')
    a.legend(loc='lower left', fontsize=8.5)
    panel(a, '(a)')

    b.plot(r[nom], C['dci'][nom], 'o', color=TINTA2, ms=6, mec=SUP,
           label='medido, ida')
    b.plot(r[nom], C['dcv'][nom], 's', color=TINTA2, ms=5, mfc='none',
           label='medido, vuelta')
    b.plot(tasas, pred['dc'], '-', color=AZUL, lw=2,
           label='lineal con el undershoot medido')
    b.plot(tasas, ajuste['dc'], '--', color=NARAN, lw=2, label='mejor lineal')
    b.set_xscale('log')
    b.set_xlabel('tasa (Hz)')
    b.set_ylabel('Δ centroide (%)')
    b.legend(loc='upper left', fontsize=8.5)
    panel(b, '(b)')
    for z in (a, b):
        limpiar(z)
    fig.tight_layout()
    i = -1
    guardar(fig, out, '02_campana_vs_modelo.png', f"""
La campaña de deriva (2026-09-08, rectángulos de 2 µs en modo PULSE,
16 tasas, ida y vuelta) contra la cadena simulada con el MISMO estímulo, la
MISMA configuración (thr {THR}, hyst {HYST}, bl_k {BL_K}, holdoff {HOLD},
estimador de pico) y el seguidor de base del RTL.

(a) Caída de la base en vuelo respecto del nivel a baja tasa
({C['L0']:.1f} cuentas). La franja es el tramo de ancho nominal
({F_LO:.0f}–{F_HI:.0f} Hz), el único donde se compara el centroide. Con el
undershoot medido (η = {pred['eta']:.3f}, τ = {pred['tau_us']:.1f} µs) la base
cae {pred['base'][i] - C['L0']:.1f} cuentas a 72 kHz; se midieron
{(C['bi'][C['i72']] + C['bv'][C['i72']]) / 2 - C['L0']:.1f}.

(b) Corrimiento de centroide desde {F_LO:.0f} Hz. Medido: +{C['dci'][C['i72']]:.2f} %
(ida) y +{C['dcv'][C['i72']]:.2f} % (vuelta) a 72 kHz. El undershoot
medido explica +{pred['dc'][i]:.2f} %.

En naranja, el MEJOR modelo lineal posible (η y τ libres, ajustados a las dos
curvas a la vez). Necesita η = {ajuste['eta']:.2f}, {ajuste['eta'] / pred['eta']:.1f} veces el
medido, y aun así no reproduce la FORMA: un mecanismo lineal da, con ciclo
de trabajo chico, una caída proporcional a la tasa (recta en escala log),
y la medida es cóncava — a 12 kHz la base y el centroide ya se movieron
la mitad de lo que se mueven a 72 kHz. χ²/gl = {ajuste['chi2'] / ajuste['gl']:.1f}.
""")


def fig_correcciones(out, C, tasas, escen, mapa):
    fig, (a, b) = plt.subplots(1, 2, figsize=(10.6, 4.0),
                               gridspec_kw={'width_ratios': [1.25, 1]})
    estilos = {'sin corrección (holdoff 64)': (TINTA2, '-'),
               'PZ exacta': (AZUL, '-'),
               'PZ con τ +20 %': (VERDE, '--'),
               'PZ con η +20 %': (MORADO, '--'),
               'sin PZ, holdoff 1024 (8.2 µs)': (NARAN, ':')}
    for nombre, (c, ls) in estilos.items():
        a.plot(tasas, escen[nombre], ls, color=c, lw=2, label=nombre)
    a.set_xscale('log')
    a.set_xlabel('tasa (Hz)')
    a.set_ylabel('Δ centroide por el undershoot medido (%)')
    a.legend(loc='upper left', fontsize=8.5)
    panel(a, '(a)')

    for (eje, vals, res), c in zip(mapa, (VERDE, MORADO)):
        b.plot(100 * vals, res, 'o-', color=c, lw=2, ms=6, mec=SUP,
               label=f'error en {eje}')
    b.axhline(0, color=MUDO, lw=0.8)
    b.set_xlabel('error del parámetro de la PZ (%)')
    b.set_ylabel('Δ centroide residual a 72 kHz (%)')
    b.legend(loc='upper left', fontsize=9)
    panel(b, '(b)')
    for z in (a, b):
        limpiar(z)
    fig.tight_layout()
    sc = escen['sin corrección (holdoff 64)'][-1]
    guardar(fig, out, '03_correcciones.png', f"""
Qué hace cada corrección sobre la parte LINEAL del problema (el undershoot
medido, η = {escen['eta']:.3f}, τ = {escen['tau_us']:.1f} µs), con el estímulo de la
campaña.

(a) Corrimiento de centroide contra la tasa. Sin corrección, +{sc:.2f} % a
72 kHz. La PZ exacta lo lleva a {escen['PZ exacta'][-1]:+.3f} %: es la inversa del
polo-cero y la cancelación es exacta por construcción. Desajustada un 20 %
deja {escen['PZ con τ +20 %'][-1]:+.3f} % (error en τ) y {escen['PZ con η +20 %'][-1]:+.3f} % (error en η). El
holdoff de 1024 muestras —esconder el seguidor durante 8.2 µs después de cada
pulso, sin hardware nuevo— deja {escen['sin PZ, holdoff 1024 (8.2 µs)'][-1]:+.3f} %, a costa de que el
seguidor actualice sólo el {100 * escen['frac_hold'][-1]:.0f} % del tiempo a 72 kHz.

(b) Sensibilidad de la PZ: corrimiento residual a 72 kHz contra el error de
cada parámetro. Manda η: el residuo es lineal en su error, y un 10 % de
error deja {escen['res_eta10']:+.3f} % ({100 * abs(escen['res_eta10']) / sc:.0f} % de la parte
lineal); sobreestimarlo sobrecorrige y el centroide BAJA con la tasa. τ casi
no importa: con ±30 % de error el residuo no pasa de {escen['res_tau_max']:.3f} %.

Lo que esta figura NO dice: cuánto del corrimiento MEDIDO desaparecería. Eso
es sólo la fracción lineal de la figura 02 (+{sc:.2f} de +{escen['medido_ida']:.2f} % en
la ida); el resto no responde a una PZ.
""")


# =============================================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(_DOCS, 'mca', 'figuras', 'polo_cero'))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(20261023)

    print('=== 1. undershoot medido ===')
    meds = [medir_undershoot(os.path.join(DATOS, c)) for c in CAPTURAS]
    for q in meds:
        print(f"  {q['archivo']}: eta={q['eta']:.4f} tau={q['tau_m'] * TS_US:.2f} us "
              f"rms={q['rms']:.1f}")
    eta_m = float(np.mean([q['eta'] for q in meds]))
    tau_m = float(np.mean([q['tau_m'] for q in meds]))

    C = campana()
    tasas = C['r'][C['nom']]
    print(f"\n=== 2. campaña: L0={C['L0']:.1f}  A={C['A']:.0f} cuentas ===")
    b, amp, _ = cadena(tasas, C['A'], C['L0'], eta_m, tau_m)
    pred = dict(base=b, dc=pct(amp), eta=eta_m, tau_us=tau_m * TS_US)

    print('  validación de la réplica rápida contra segmentar_base (RTL):')
    val = validar(C['A'], C['L0'], eta_m, tau_m, rng)
    for v in val:
        print(f"    {v['tasa']:8.0f} Hz: base {v['base_rapido']:7.2f} vs {v['base_rtl']:7.2f}"
              f"   amp {v['amp_rapido']:8.1f} vs {v['amp_rtl']:8.1f} (n={v['n_ev']})")

    print('\n=== 3. mejor modelo lineal ===')
    bm = (np.interp(tasas, C['r'], C['bi']) + np.interp(tasas, C['r'], C['bv'])) / 2
    dcm = (C['dci'][C['nom']] + C['dcv'][C['nom']]) / 2
    mejor = None
    for tau_us in (0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8):
        for eta in np.linspace(0.02, 0.6, 30):
            bb, aa, _ = cadena(tasas, C['A'], C['L0'], eta, tau_us / TS_US)
            chi2 = (np.sum(((bb - bm) / 3.0) ** 2)
                    + np.sum(((pct(aa) - dcm) / 0.2) ** 2))
            if mejor is None or chi2 < mejor[0]:
                mejor = (chi2, eta, tau_us, bb, pct(aa))
    ajuste = dict(chi2=mejor[0], gl=2 * tasas.size - 2, eta=mejor[1],
                  tau_us=mejor[2], base=mejor[3], dc=mejor[4])
    print(f"  eta={ajuste['eta']:.3f} tau={ajuste['tau_us']} us "
          f"chi2/gl={ajuste['chi2'] / ajuste['gl']:.1f}")

    print('\n=== 4. correcciones sobre la parte lineal ===')
    escen = {'eta': eta_m, 'tau_us': tau_m * TS_US}
    casos = {'sin corrección (holdoff 64)': dict(),
             'PZ exacta': dict(pz=(eta_m, tau_m)),
             'PZ con τ +20 %': dict(pz=(eta_m, 1.2 * tau_m)),
             'PZ con η +20 %': dict(pz=(1.2 * eta_m, tau_m)),
             'sin PZ, holdoff 1024 (8.2 µs)': dict(hold=1024)}
    for nombre, kw in casos.items():
        _, aa, ff = cadena(tasas, C['A'], C['L0'], eta_m, tau_m, **kw)
        escen[nombre] = pct(aa)
        if 'holdoff 1024' in nombre:
            escen['frac_hold'] = ff
        print(f"  {nombre:<32} {escen[nombre][-1]:+.3f} % a 72 kHz")
    escen['medido_ida'] = float(C['dci'][C['i72']])

    errores = np.array([-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3])
    mapa = []
    for eje in ('η', 'τ'):
        res = []
        for e in errores:
            pz = (eta_m * (1 + e), tau_m) if eje == 'η' else (eta_m, tau_m * (1 + e))
            _, aa, _ = cadena(np.array([F_LO, F_HI]), C['A'], C['L0'],
                              eta_m, tau_m, pz=pz)
            res.append(pct(aa)[-1])
        mapa.append((eje, errores, np.array(res)))

    escen['res_eta10'] = float(mapa[0][2][list(errores).index(0.1)])
    escen['res_tau_max'] = float(np.abs(mapa[1][2]).max())
    fig_undershoot(a.out, meds)
    fig_campana(a.out, C, pred, ajuste, tasas)
    fig_correcciones(a.out, C, tasas, escen, mapa)

    i72 = -1
    b72 = (C['bi'][C['i72']] + C['bv'][C['i72']]) / 2 - C['L0']
    resumen = dict(
        undershoot=[{k: v for k, v in q.items() if k not in ('x', 'fuera')} for q in meds],
        eta_medido=eta_m, tau_medido_us=tau_m * TS_US,
        campana=dict(L0=C['L0'], A=C['A'], base_72k_medida=float(b72),
                     dc_72k_ida=float(C['dci'][C['i72']]),
                     dc_72k_vuelta=float(C['dcv'][C['i72']])),
        prediccion_undershoot_medido=dict(base_72k=float(pred['base'][i72] - C['L0']),
                                          dc_72k=float(pred['dc'][i72])),
        mejor_lineal=dict(eta=ajuste['eta'], tau_us=ajuste['tau_us'],
                          chi2_gl=ajuste['chi2'] / ajuste['gl']),
        correcciones_72k={k: float(v[-1]) for k, v in escen.items()
                          if isinstance(v, np.ndarray) and k != 'frac_hold'},
        frac_actualiza_holdoff1024_72k=float(escen['frac_hold'][-1]),
        sensibilidad=[dict(eje=e, errores=list(map(float, v)), dc_72k=list(map(float, r)))
                      for e, v, r in mapa],
        validacion=val)
    with open(os.path.join(a.out, 'resumen.json'), 'w') as fh:
        json.dump(resumen, fh, indent=1, ensure_ascii=False)

    escribir_epigrafes(
        os.path.join(a.out, 'epigrafes.txt'),
        """Epígrafes del Monte-Carlo de cancelación polo-cero. Los escribe
        software/monte-carlo/polo_cero.py; no editar a mano. Documento:
        docs/mca/polo_cero.md.""",
        EPIGRAFES)


if __name__ == '__main__':
    main()

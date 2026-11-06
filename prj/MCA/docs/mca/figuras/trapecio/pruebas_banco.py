#!/usr/bin/env python3
"""Pruebas del banco de trapecios ANTES de escribir el RTL, sin placa.

El modelo de ranuras_y_recuperacion.md supone un pulso ideal: sube en una
muestra, el pie cae justo en la apertura de la ranura, el ruido es blanco de 4
cuentas y M es exacto. Esto lo reemplaza por lo que se puede medir o simular:

  ruido        el de la placa: canal 2 de las capturas e2e (sin senal),
               software/datos/e2e_*/*/chunk_*.npz
  subida       la de la cadena Rigol -> ADC, de los escalones de la forma
               arbitraria del Rigol en el canal 1 de esas mismas capturas
  disparo      la latencia pie -> trig_i del multitrigger REAL (mt_top, L=8,
               G=4, thr 600 como en la placa), simulada en Questa con
               tb_banco_disparo.sv -> banco_latencias.txt. Depende de la
               amplitud (walk): la ventana de cada ranura se corre con ella.
               En paralelo, otro mt_top con el disparo con polo-cero
               (mt_pz_trig: k=2, m=1)
               -> banco_latencias_pz.txt, banco_pares_pz.txt
  polo-cero    M con error residual despues de calibrar

y mide (ver pruebas_banco_trapecios.md):

  1. por forma, el sesgo contra la amplitud: la ventana tiene que quedar en la
     meseta para TODAS las amplitudes, con el walk del disparo encima;
  2. los umbrales de separacion en dt DE DISPARO (lo que ve el RTL en
     F_DTPREV/F_DTNEXT), con pares de amplitudes distintas y M errado;
  3. el ruido de cada forma con el ruido real y con uno blanco de igual sigma;
  4. el banco completo sobre pares: elige forma por dt de disparo como el RTL;
  5. los disparos en Python (Disparo: la pendiente; DisparoPZ: el de
     polo-cero), validados contra el RTL: latencia por amplitud y resolucion
     de pares;
  6. un tren de Poisson entero: disparo, ranuras, eleccion de forma y la
     contaminacion de verdad de cada pulso (buenos, apilados sin detectar,
     marcados, perdidos), con la pendiente, con la pendiente y el inspector de
     apilamiento (Inspector), y con el disparo de polo-cero.

Las secciones 1 a 4 se hacen con las latencias de cada disparo ('placa' y 'pz').

    python3 pruebas_banco.py      # ~40 s: tablas, banco_pruebas.json y banco_pruebas.{tex,pdf,svg}

Lo del RTL se rehace con Questa (tb_banco_disparo.sv, ~25 s cada corrida):
    vlib work_b && vlog -sv -work work_b <fuentes de mt_top> tb_banco_disparo.sv
    vsim -c -work work_b tb_banco_disparo -do "run -all; quit -f"          # la placa
    vsim -c -work work_b tb_banco_disparo +L=4 +G=2 +THR=420 +HYST=210 ...  # el rapido
Las fuentes de mt_top son las de `make -n -C prj/MCA/sim tb_mca_mt_latencia`
que estan en modulos/comun, modulos/mt y rtl/classic/rp_{adc,ext}_trig.v.
"""
import glob
import json
import math
import os
import sys
from dataclasses import dataclass

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from recuperacion_modelo import MQ, TAU, Forma, FORMAS          # noqa: E402

DATOS = os.path.abspath(os.path.join(AQUI, '..', '..', '..', '..', 'software', 'datos'))
CRIT_SESGO = 0.1        # % de sesgo admitido contra la amplitud (linealidad)
CRIT_PAR = 1.0          # % de error de un pulso por su vecino (el de siempre)


# ----------------------------------------------------------------- medidas
def capturas_e2e():
    fs = sorted(glob.glob(os.path.join(DATOS, 'e2e_*', '*', 'chunk_*.npz')))
    w = [np.load(f, allow_pickle=True)['wave'] for f in fs
         if 'wave' in np.load(f, allow_pickle=True).files]
    return np.concatenate(w).astype(float)          # (eventos, canal, 512)


def medir_ruido(w):
    s = w[:, 1, :] - w[:, 1, :].mean(1, keepdims=True)
    ac = [float(np.mean(s[:, :-j] * s[:, j:]) / s.var()) for j in range(1, 6)]
    return s, {'sigma': float(s.std()), 'autocorr_1_5': ac, 'segmentos': int(len(s))}


def medir_subida(w):
    """Los escalones de la forma arbitraria del Rigol (un punto cada ~4 muestras)
    vistos por el ADC: la respuesta al escalon de la cadena, promediada sobre la
    fase del escalon dentro de la muestra."""
    pre = w[:, 0, :10]
    limpios = pre.std(1, ddof=1) < 8
    esc = []
    for v in w[limpios][:3000, 0]:
        for i in np.where(np.diff(v) > 150)[0]:
            if 3 <= i <= 200:
                a, b = v[i - 2:i].mean(), v[i + 2:i + 4].mean()
                if b - a >= 200:
                    esc.append((v[i - 2:i + 4] - a) / (b - a))
    esc = np.array(esc)
    media = esc.mean(0)
    # muestras i-2..i+3: el escalon promedio; un escalon instantaneo con fase al
    # azar daria [0, 0, 0.5, 1, 1, 1]
    return {'escalones': int(len(esc)), 'escalon_medio': [round(float(x), 3) for x in media],
            'sobrepico': float(media[3:].max() - 1)}


def leer_latencias(sufijo=''):
    """La latencia simulada del RTL (tb_banco_disparo.sv): '' la pendiente de la
    placa, '_L4' la rapida, '_pz' el disparo con polo-cero."""
    d = np.loadtxt(os.path.join(AQUI, f'banco_latencias{sufijo}.txt'))
    return d[d[:, 3] >= 0]


LAT = None


def disparos(a, tr10, r, rng):
    """(fase del pie, latencia entera) de r pulsos de amplitud a: filas del TB del
    disparo que este cargado en LAT."""
    f = LAT[(LAT[:, 0] == tr10) & (LAT[:, 1] == a)]
    assert len(f), f'no hay latencias simuladas para A={a}, subida {tr10}'
    i = rng.integers(0, len(f), r)
    return f[i, 2], f[i, 3].astype(int)


# ------------------------------------------------------------------ senal
def pulso(a, pie, n, tr10, tau=TAU):
    """Preamplificador: (1 - e^(-t/tr)) e^(-t/tau) desde el pie continuo `pie`
    (un vector, uno por fila). tr10 es la subida 10-90 % en muestras."""
    t = np.arange(n)[None, :] - np.asarray(pie, float)[:, None]
    tr = tr10 / 2.197
    v = np.zeros_like(t)
    m = t > 0
    v[m] = (1 - np.exp(-t[m] / tr)) * np.exp(-t[m] / tau)
    return np.asarray(a, float).reshape(-1, 1) * v


def trap(x, f, mq=MQ):
    """mca_trap en flotante (s / 2^sh), con un M que puede no ser el exacto."""
    def ret(v, j):
        o = np.zeros_like(v)
        o[..., j:] = v[..., :v.shape[-1] - j]
        return o
    d = x - ret(x, f.k) - ret(x, f.l) + ret(x, f.k + f.l)
    p = np.cumsum(d, -1)
    return np.cumsum(16 * p + mq * d, -1) / 2.0 ** f.sh


def ventana(t, ini, w):
    idx = np.asarray(ini)[:, None] + np.arange(w)[None, :]
    return np.take_along_axis(t, idx, 1).mean(1)


def ganancia(f, tr10, n=900, t0=300):
    """Altura de la meseta para A = 1: el valor en el medio de la meseta de un
    pulso con el pie en una muestra entera."""
    t = trap(pulso([1.0], [t0], n, tr10), f)
    return float(t[0, t0 + f.k + f.m // 2])


# ------------------------------------------------- 1. sesgo contra amplitud
AMPS = [100.0, 150.0, 200.0, 300.0, 500.0, 800.0, 1200.0, 2000.0, 3000.0, 4500.0, 6000.0, 8000.0]


def sesgo(f, tr10, cs, rng, n=700, t0=300, r=60):
    """Para cada inicio de ventana c (muestras desde el disparo): el sesgo medio y
    el peor caso (%) contra la amplitud, sin ruido. Cada fila se compara contra
    la meseta del trapecio largo (64/48) en ESA fila: asi queda afuera la fase
    del pie dentro de la muestra, que mueve la altura de todas las formas por
    igual (hasta e^(1/tau) - 1 = 0.4 % con subida instantanea). Y se normaliza
    a la ganancia de las amplitudes grandes (>= 3000), donde el walk es nulo:
    lo que queda es la no linealidad que agrega la forma."""
    f64 = Forma(64, 48, 4, 80)
    g, g64 = ganancia(f, tr10), ganancia(f64, tr10)
    crudo = {c: [] for c in cs}
    for a in AMPS:
        fase, lat = disparos(a, tr10, r, rng)
        x = pulso(np.full(r, a), t0 + fase, n, tr10)
        t = trap(x, f)
        pie = (t0 + np.floor(fase)).astype(int)
        a_fila = trap(x, f64)[np.arange(r), pie + 64 + 24] / g64
        for c in cs:
            crudo[c].append(ventana(t, t0 + lat + c, f.w) / (a_fila * g))
    out = {}
    for c in cs:
        ref = np.concatenate([v for a, v in zip(AMPS, crudo[c]) if a >= 3000]).mean()
        out[c] = [(float(100 * (v.mean() / ref - 1)), float(100 * np.abs(v / ref - 1).max()))
                  for v in crudo[c]]
    return out


def a_minima(fila, crit=CRIT_SESGO):
    """La amplitud desde la que el peor caso queda dentro del criterio."""
    for i in range(len(AMPS)):
        if all(p <= crit for _, p in fila[i:]):
            return AMPS[i]
    return None


def mejor_c(f, tr10, rng):
    """El inicio de ventana: de los que dan la menor A_min, el del MEDIO (el que
    deja mas margen a los dos lados de la meseta)."""
    cs = list(range(f.k - 14, f.k + f.m - f.w + 2))
    s = sesgo(f, tr10, cs, rng)
    am = {c: a_minima(s[c]) for c in cs}
    validos = [a for a in am.values() if a is not None]
    if validos:
        mejor = [c for c in cs if am[c] == min(validos)]
        c = mejor[len(mejor) // 2]
    else:
        c = min(cs, key=lambda c: max(p for _, p in s[c][AMPS.index(1200.0):]))
    return c, s[c]


# --------------------------------------------- 2. umbrales en dt de disparo
def umbrales_reales(f, c, tr10, rng, pares=((2000.0, 2000.0), (8000.0, 300.0), (300.0, 8000.0)),
                    dmq=0.0, dmax=200, r=12, n=900, t0=300):
    """(antes, despues) en muestras de DISPARO: desde que dt_disparo el segundo
    (antes) y el primero (despues) miden con error < CRIT_PAR, para todos los
    pares de amplitudes y todas las fases. dmq: error relativo de M."""
    mq = MQ * (1 + dmq)
    peor = {'antes': 0, 'despues': 0}
    for a1, a2 in pares:
        fa, la = disparos(a1, tr10, r, rng)
        fb, lb = disparos(a2, tr10, r, rng)
        xa = pulso(np.full(r, a1), t0 + fa, n, tr10)
        ta = trap(xa, f, mq)
        ra = ventana(ta, t0 + la + c, f.w)
        dts, ea, eb = [], [], []
        for d in range(1, dmax + 1):
            xb = pulso(np.full(r, a2), t0 + d + fb, n, tr10)
            tb = trap(xb, f, mq)
            tt = ta + tb
            ib = t0 + d + lb + c
            rb = ventana(tb, ib, f.w)
            dts.append(d + lb - la)
            ea.append(np.abs(ventana(tt, t0 + la + c, f.w) / ra - 1) * 100)
            eb.append(np.abs(ventana(tt, ib, f.w) / rb - 1) * 100)
        dts, ea, eb = np.array(dts), np.array(ea), np.array(eb)
        for nombre, e in (('antes', eb), ('despues', ea)):
            malos = dts[e > CRIT_PAR]
            u = int(malos.max()) + 1 if len(malos) else 1
            peor[nombre] = max(peor[nombre], u)
    return peor['antes'], peor['despues']


def umbrales_ideales(f, a=1000.0, n=900, t0=300, dmax=200):
    """Los de ranuras_y_recuperacion.md: subida instantanea, pie en la apertura."""
    xa = np.round(pulso([a], [t0 - 1e-9], n, 1e-6))
    ta = trap(xa, f)
    ra = ventana(ta, [t0 + f.off], f.w)[0]
    ea, eb = [], []
    for d in range(1, dmax + 1):
        xb = np.round(pulso([a], [t0 + d - 1e-9], n, 1e-6))
        tb = trap(xb, f)
        tt = ta + tb
        ea.append(abs(ventana(tt, [t0 + f.off], f.w)[0] / ra - 1) * 100)
        eb.append(abs(ventana(tt, [t0 + d + f.off], f.w)[0] / ventana(tb, [t0 + d + f.off], f.w)[0] - 1) * 100)

    def desde(e):
        malos = [i + 1 for i, v in enumerate(e) if v > CRIT_PAR]
        return (max(malos) + 1) if malos else 1
    return desde(eb), desde(ea)


# ------------------------------------------------------------ 3. el ruido
def ruido_formas(formas, cs, s_real, rng, r=4000, n=1024, t0=400):
    """sigma de F para A = 1000 con ruido blanco de la misma sigma y con el real."""
    out = {}
    sig = s_real.std()
    idx = rng.integers(0, len(s_real), (r, 2))
    real = np.concatenate([s_real[idx[:, 0]], s_real[idx[:, 1]]], 1)
    blanco = rng.normal(0, sig, (r, n))
    for f, c in zip(formas, cs):
        g = ganancia(f, 1.2) * 1000
        fila = {}
        for nombre, z in (('blanco', blanco), ('real', real)):
            t = trap(np.round(z), f)
            fila[nombre] = float(100 * ventana(t, np.full(r, t0 + c), f.w).std() / g)
        out[f'{f.k}/{f.m}'] = fila
    return out


# ------------------------------------------------- 4. el banco completo
BANCOS = {
    'analisis': [Forma(64, 48, 4, 80), Forma(32, 24, 3, 39), Forma(16, 12, 2, 19), Forma(8, 8, 1, 10)],
    'ajustado': [Forma(64, 48, 4, 80), Forma(32, 24, 3, 39), Forma(16, 12, 2, 19), Forma(8, 12, 1, 10)],
}
DTS = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 23, 26, 30, 35, 40, 45, 50, 55, 60, 70, 80, 90,
       100, 110, 120, 140, 160, 200, 250]


def elegir(banco, umbr, dt, lado):
    """El indice de la forma mas larga que el vecino permite (lado 0: el anterior
    esta a dt, mira 'antes'; lado 1: el siguiente, mira 'despues')."""
    for i, f in enumerate(banco):
        if umbr[i][lado] <= dt:
            return i
    return len(banco) - 1


def pares_banco(banco, cs, umbr, a1, a2, rng, s_real=None, ideal=False, dmq=0.0, tr10=1.2,
                r=300, n=1024, t0=300):
    """Error RMS (%) de A y de B contra dt (del pie) con el banco: cada ranura elige
    su forma por el dt de DISPARO, como lo haria el RTL. ideal: subida
    instantanea, pie en muestra entera, latencia fija de 7, ruido blanco de 4,
    M exacto (el modelo de ranuras_y_recuperacion.md)."""
    mq = MQ * (1 + dmq)
    out = {'dt': [], 'A': [], 'B': [], 'forma_A': [], 'forma_B': []}
    for dt in DTS:
        if ideal:
            fa = fb = np.full(r, -1e-9)
            la = lb = np.full(r, 7)
            tr = 1e-3
            z = np.round(rng.normal(0, 4.0, (r, n)))
        else:
            fa, la = disparos(a1, tr10, r, rng)
            fb, lb = disparos(a2, tr10, r, rng)
            tr = tr10
            idx = rng.integers(0, len(s_real), (r, 2))
            z = np.concatenate([s_real[idx[:, 0]], s_real[idx[:, 1]]], 1)
        xa = pulso(np.full(r, a1), t0 + fa, n, tr)
        xb = pulso(np.full(r, a2), t0 + dt + fb, n, tr)
        x = np.round(xa + xb + z)
        dtt = dt + lb - la
        ia = np.array([elegir(banco, umbr, d, 1) for d in dtt])
        ib = np.array([elegir(banco, umbr, d, 0) for d in dtt])
        fA, fB, rA, rB = (np.zeros(r) for _ in range(4))
        for j, (f, c) in enumerate(zip(banco, cs)):
            ma, mb = ia == j, ib == j
            if not (ma.any() or mb.any()):
                continue
            t, ta, tb = trap(x, f, mq), trap(xa, f, mq), trap(xb, f, mq)
            ini_a, ini_b = t0 + la + c, t0 + dt + lb + c
            fA[ma] = ventana(t[ma], ini_a[ma], f.w)
            rA[ma] = ventana(ta[ma], ini_a[ma], f.w)
            fB[mb] = ventana(t[mb], ini_b[mb], f.w)
            rB[mb] = ventana(tb[mb], ini_b[mb], f.w)
        out['dt'].append(dt)
        out['A'].append(float(100 * np.sqrt(np.mean((fA / rA - 1) ** 2))))
        out['B'].append(float(100 * np.sqrt(np.mean((fB / rB - 1) ** 2))))
        out['forma_A'].append(int(np.bincount(ia).argmax()))
        out['forma_B'].append(int(np.bincount(ib).argmax()))
    return out


def tasa_buenos(banco, umbr, tasa_kcps, n_acc, g, rng, n_arribos=40000):
    """kcps de pulsos buenos con el banco (umbrales en dt de disparo)."""
    import recuperacion_modelo as rm
    t = rm.arribos(tasa_kcps, n_arribos, rng)
    seg = (t[-1] - t[0]) / (rm.FS * 1e6)
    med = rm.ranuras(t, n_acc, g)
    ant, sig = rm.vecinos(t)
    ok = np.zeros(len(t), bool)
    for a, b in umbr:
        ok |= (ant >= a) & (sig >= b)
    return float((med & ok).sum() / seg / 1e3)


# ------------------------------------------- 5. el disparo por pendiente
@dataclass(frozen=True)
class Disparo:
    """mt_slope_trig: s = suma de L muestras - suma de L muestras L+G atras, y un
    Schmitt (dispara en s >= thr, re-arma en s < thr - hyst). pipe: ciclos de la
    cadena hasta trig_i del MCA, ajustado contra la simulacion del RTL."""
    L: int = 8
    G: int = 4
    thr: int = 600
    hyst: int = 300
    pipe: int = 6
    lat_min: int = 5       # para atribuir cada disparo a su pulso en el tren

    def disparos(self, x):
        n = x.shape[-1]
        c = np.concatenate([[0.0], np.cumsum(x)])
        i = np.arange(n)

        def suma(d):
            hi = np.clip(i + 1 - d, 0, n)
            lo = np.clip(i + 1 - d - self.L, 0, n)
            return c[hi] - c[lo]
        s = suma(0) - suma(self.L + self.G)
        arriba = np.flatnonzero(s >= self.thr)
        abajo = np.flatnonzero(s < self.thr - self.hyst)
        out = []
        if not len(abajo):
            return np.array(out, int)
        t = abajo[0]
        while True:
            j = np.searchsorted(arriba, t)
            if j >= len(arriba):
                break
            out.append(arriba[j])
            k = np.searchsorted(abajo, arriba[j])
            if k >= len(abajo):
                break
            t = abajo[k]
        return np.array(out, int) + self.pipe


DISPARO_PLACA = Disparo(8, 4, 600, 300)
DISPARO_RAPIDO = Disparo(4, 2, 420, 210)


def validar_disparo(dsp, lat_txt, pares_txt, rng, r=40, n=1840):
    """El modelo contra el RTL: latencia media por amplitud y, en pares, desde que
    dt salen siempre dos disparos."""
    lat = np.loadtxt(lat_txt)
    fil = {}
    for a in AMPS:
        rtl = lat[(lat[:, 0] == 1.2) & (lat[:, 1] == a), 3]
        rtl = rtl[rtl >= 0]
        fase = rng.uniform(0, 1, r)
        x = np.round(pulso(np.full(r, a), 40 + fase, n, 1.2) + rng.normal(0, 4.5, (r, n)))
        mod = [dsp.disparos(v) for v in x]
        mod = np.array([m[0] - 40 for m in mod if len(m)])
        fil[a] = (float(rtl.mean()) if len(rtl) else None, float(mod.mean()) if len(mod) else None)
    p = np.loadtxt(pares_txt)
    res = {}
    for a1, a2 in ((2000.0, 1200.0), (8000.0, 300.0), (300.0, 8000.0), (300.0, 300.0)):
        m = (p[:, 0] == a1) & (p[:, 1] == a2)
        dts = np.unique(p[m, 2])
        dos = [(p[m & (p[:, 2] == d), 5] >= 2).mean() for d in dts]
        rtl = next((d for j, d in enumerate(dts) if all(q == 1 for q in dos[j:])), None)
        dm = []
        for d in dts:
            f1, f2 = rng.uniform(0, 1, 16), rng.uniform(0, 1, 16)
            x = np.round(pulso(np.full(16, a1), 40 + f1, n, 1.2) + pulso(np.full(16, a2), 40 + d + f2, n, 1.2)
                         + rng.normal(0, 4.5, (16, n)))
            dm.append(np.mean([len(dsp.disparos(v)) >= 2 for v in x]))
        mod = next((d for j, d in enumerate(dts) if all(q == 1 for q in dm[j:])), None)
        res[f'{a1:.0f}->{a2:.0f}'] = (float(rtl) if rtl is not None else None,
                                     float(mod) if mod is not None else None)
    return fil, res


@dataclass(frozen=True)
class Inspector:
    """Inspector de apilamiento: un trapecio RAPIDO con polo-cero (k=2, m=1) y un
    Schmitt sobre su salida, en unidades de amplitud. Con el polo-cero la cola de
    un pulso grande no tapa a uno chico (es lo que le pasa al disparo por
    pendiente). No abre ranuras: solo dice donde hay pulsos, para F_DTPREV y
    F_DTNEXT. lat: muestras del pie al cruce en un pulso grande."""
    k: int = 2
    m: int = 1
    thr: float = 50.0
    hyst: float = 25.0
    lat: int = 1

    def pies(self, x):
        f = Forma(self.k, self.m, 0, 0)
        t = trap(x[None], f)[0] / ganancia(f, 1.2)
        arriba = np.flatnonzero(t >= self.thr)
        abajo = np.flatnonzero(t < self.thr - self.hyst)
        out, u = [], (abajo[0] if len(abajo) else None)
        while u is not None:
            j = np.searchsorted(arriba, u)
            if j >= len(arriba):
                break
            out.append(arriba[j])
            q = np.searchsorted(abajo, arriba[j])
            u = abajo[q] if q < len(abajo) else None
        return np.array(out, int) - self.lat


INSPECTOR = Inspector()


@dataclass(frozen=True)
class DisparoPZ:
    """La fuente de disparo con polo-cero del multitrigger (mt_pz_trig): un
    mca_trap con k = 2, m = 1 y polo-cero, y un Schmitt sobre su salida, en
    unidades de amplitud. Es el inspector usado como disparo. pipe: ciclos del
    cruce al flanco de daisy_trig_o, lo que le llega al MCA (la LAT de 8 de
    mca_trap, el registro del Schmitt, el del flanco y el de mt_trig_src),
    ajustado contra tb_banco_disparo.sv: con la fuente del RTL da los mismos
    disparos que el Schmitt suelto de antes, un ciclo despues."""
    k: int = 2
    m: int = 1
    thr: float = 50.0
    hyst: float = 25.0
    pipe: int = 11
    lat_min: int = 10

    def disparos(self, x):
        return Inspector(self.k, self.m, self.thr, self.hyst, lat=-self.pipe).pies(x)


DISPARO_PZ = DisparoPZ()
# nombre: (modelo de Python, sufijo de los archivos del RTL)
DISPAROS = {'placa': (DISPARO_PLACA, ''), 'rapido': (DISPARO_RAPIDO, '_L4'),
            'pz': (DISPARO_PZ, '_pz')}


# ------------------------------------------- 6. tren de Poisson completo
def tren(tasa_kcps, n, rng, tr10=1.2, amp=(100.0, 8000.0)):
    """Pulsos de Poisson con amplitud log-uniforme en amp (muchos chicos: es el
    caso dificil para el disparo) y el pie en cualquier fase."""
    rho = tasa_kcps * 1e3 / 125e6
    pies = np.cumsum(rng.exponential(1.0 / rho, int(n * rho * 1.2) + 10))
    pies = pies[(pies > 400) & (pies < n - 400)]
    a = np.exp(rng.uniform(np.log(amp[0]), np.log(amp[1]), len(pies)))
    x = np.zeros(n)
    tr = tr10 / 2.197
    largo = 3000
    t = np.arange(largo)
    for p, ai in zip(pies, a):
        i0 = int(np.floor(p))
        u = t + i0 + 1 - p
        seg = ai * (1 - np.exp(-u / tr)) * np.exp(-u / TAU)
        fin = min(n, i0 + 1 + largo)
        x[i0 + 1:fin] += seg[:fin - i0 - 1]
    return pies, a, x


def clasificar(pies, a, x_limpio, x, dsp, banco, cs, umbr, n_acc, g, solo=None, insp=None):
    """Para cada pulso de verdad: 'perdido' (sin disparo o sin ranura),
    'marcado' (su vecino de disparo esta mas cerca que la forma mas corta: el
    discriminador lo saca), 'bueno' (aceptado y |error| < 1 %) o 'malo'
    (aceptado y contaminado: apilamiento NO detectado). solo: usar solo esa
    forma del banco (el trapecio de hoy). insp: los vecinos salen del inspector
    (sus pies estimados, sin el propio) en vez de los disparos."""
    import recuperacion_modelo as rm
    trig = dsp.disparos(x)
    med = rm.ranuras(trig, n_acc, g)
    ant, sig = rm.vecinos(trig)
    if insp is not None:
        # El evento PROPIO es el ultimo del inspector entre 16 y 4 muestras antes
        # del disparo (la latencia del disparo va de 6 a 14 con el walk): en el
        # RTL, el que la ranura ve en sus primeras muestras. Los vecinos son los
        # eventos de al lado del propio; sin propio, se mide desde trig - 7.
        ev = np.concatenate([[-10 ** 9], insp.pies(x), [10 ** 12]])
        h = np.searchsorted(ev, trig - 4, 'right') - 1
        propio = ev[h] >= trig - 16
        ref = np.where(propio, ev[h], trig - 7)
        prev = np.where(propio, ev[np.maximum(h - 1, 0)], ev[h])
        ant_i = ref - prev
        sig_i = ev[np.minimum(h + 1, len(ev) - 1)] - ref
        ant, sig = np.minimum(ant, ant_i), np.minimum(sig, sig_i)
    gan = ganancia(banco[0], 1.2)
    salidas = [trap(x_limpio[None], f)[0] for f in banco]
    # cada disparo es del ultimo pie anterior a el con la latencia minima del disparo
    j = np.searchsorted(pies, trig - dsp.lat_min) - 1
    clase = np.array(['perdido'] * len(pies), dtype=object)
    for t_i, ji, m_i, d_a, d_s in zip(trig, j, med, ant, sig):
        if ji < 0 or not m_i or clase[ji] != 'perdido':
            continue
        if solo is not None:
            ok = umbr[solo][0] <= d_a and umbr[solo][1] <= d_s
            ia = solo
        else:
            ok = umbr[-1][0] <= d_a and umbr[-1][1] <= d_s
            ia = next((q for q in range(len(banco)) if umbr[q][0] <= d_a and umbr[q][1] <= d_s),
                      len(banco) - 1)
        if not ok:
            clase[ji] = 'marcado'
            continue
        f, c = banco[ia], cs[ia]
        v = salidas[ia][t_i + c:t_i + c + f.w].mean()
        clase[ji] = 'bueno' if abs(v / (a[ji] * gan) - 1) < CRIT_PAR / 100 else 'malo'
    return clase


def resolucion(rng, pares=((2000.0, 1200.0), (8000.0, 300.0))):
    """Fraccion de pares con dos disparos contra dt, del RTL (banco_pares*.txt): la
    pendiente de la placa, la rapida y el disparo con polo-cero."""
    out = {}
    for nombre, sufijo in (('placa', ''), ('rapido', '_L4'), ('pz', '_pz')):
        p = np.loadtxt(os.path.join(AQUI, f'banco_pares{sufijo}.txt'))
        out[nombre] = {}
        for a1, a2 in pares:
            m = (p[:, 0] == a1) & (p[:, 1] == a2)
            dts = np.unique(p[m, 2])
            out[nombre][f'{a1:.0f}->{a2:.0f}'] = [
                (float(d), float((p[m & (p[:, 2] == d), 5] >= 2).mean())) for d in dts]
    return out


# ----------------------------------------------------------------- figura
PLANTILLA = r"""%% %s. GENERADO por pruebas_banco.py: no editar a mano.
\documentclass[border=0pt,tikz]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[none]{hyphenat}
\input{../../../figuras/estilo_tikz.tex}
\begin{document}
\begin{tikzpicture}[fondo]
%s
\end{tikzpicture}
\end{document}
"""


def figura(res):
    import shutil
    import subprocess
    import tempfile
    from figuras_mejora import Ejes
    L = []

    ROT_B = []

    def titulo(e, txt):
        L.append(f"\\node[anchor=south west, font=\\scriptsize\\bfseries, inner sep=0pt] at "
                 f"({e.x0:.3f},{e.y0 + e.alto + 0.18:.3f}) {{{txt}}};")

    def rot(e, x, y, txt, color, ancla='west'):
        L.append(f"\\node[nodo, anchor={ancla}, text={color}, fill=white, inner sep=1pt] at "
                 f"({e.X(x):.3f},{e.Y(y):.3f}) {{{txt}}};")

    # (a) latencia del disparo contra amplitud (RTL)
    e = Ejes(0.0, 5.2, 6.2, 3.3, (100, 8000), (5, 15), xlog=True, ylog=False)
    titulo(e, "a) Latencia pie $\\to$ disparo (RTL)")
    L += e.marco([100, 300, 1000, 3000, 8000], [6, 8, 10, 12, 14], "amplitud, cuentas",
                 "latencia, ciclos")
    for sufijo, estilo, color, txt, yy in (('', 'azul!85!black, line width=1.2pt', 'azul!85!black',
                                            'placa: $L$ = 8, $G$ = 4, umbral 600', 12.6),
                                           ('_L4', 'verde!55!black, line width=1.2pt', 'verde!55!black',
                                            'rápido: $L$ = 4, $G$ = 2, umbral 420', 13.4),
                                           ('_pz', 'rojo!75!black, line width=1.2pt', 'rojo!75!black',
                                            'polo-cero: $k$ = 2, $m$ = 1, umbral 50', None)):
        d = np.loadtxt(os.path.join(AQUI, f'banco_latencias{sufijo}.txt'))
        d = d[(d[:, 0] == 1.2) & (d[:, 3] >= 0)]
        xs = [a for a in AMPS if (d[:, 1] == a).any()]
        ys = [d[d[:, 1] == a, 3].mean() for a in xs]
        L.append(e.curva(xs, ys, estilo))
        if yy is None:
            rot(e, 330, 10.2, txt, color)
        else:
            rot(e, 330, yy, txt, color)
    rot(e, 330, 14.3, 'con pendiente, el corrimiento sigue umbral$/A$', 'black!70')

    # (b) peor error contra amplitud por forma (subida 1.2)
    e = Ejes(7.6, 5.2, 6.2, 3.3, (100, 8000), (0.001, 30), xlog=True, ylog=True)
    titulo(e, "b) Linealidad de la forma más corta")
    L += e.marco([100, 300, 1000, 3000, 8000], [0.001, 0.01, 0.1, 1, 10], "amplitud, cuentas",
                 "", fmt_y=lambda v: f"{v:g}")
    L.append(f"\\node[font=\\scriptsize, anchor=south, rotate=90] at ({e.x0 - 0.80:.3f},"
             f"{e.y0 + e.alto / 2:.3f}) {{peor error, \\%}};")
    L.append(f"\\draw[black!45, dashed] ({e.x0:.3f},{e.Y(0.1):.3f}) -- ({e.x0 + e.ancho:.3f},{e.Y(0.1):.3f});")
    for disp, clave, estilo, color, txt in (
            ('placa', '8/8/2', 'azul!85!black, line width=1.2pt', 'azul!85!black', '8/8, pendiente'),
            ('placa', '8/12/2', 'verde!55!black, line width=1.2pt', 'verde!55!black', '8/12, pendiente'),
            ('pz', '8/8/2', 'rojo!75!black, line width=1.2pt, dash pattern=on 2pt off 1.2pt',
             'rojo!75!black', '8/8, polo-cero')):
        f = res['formas'][disp][clave]['1.2']
        ys = [max(p, 0.001) for _, p in f['sesgo']]
        L.append(e.curva(AMPS, ys, estilo))
        ROT_B.append((ys[-1], txt, color))
    # rotulos a la derecha, separados si caen juntos
    ys_r = []
    for y, txt, color in sorted(ROT_B):
        yy = e.Y(y)
        if ys_r and yy - ys_r[-1] < 0.22:
            yy = ys_r[-1] + 0.22
        ys_r.append(yy)
        L.append(f"\\node[nodo, anchor=west, text={color}, inner sep=1pt] at "
                 f"({e.x0 + e.ancho + 0.05:.3f},{yy:.3f}) {{{txt}}};")
    rot(e, 1200, 0.16, 'criterio 0.1 \\%', 'black!60')
    rot(e, 180, 3.0, '8/8 con pendiente: la ventana se sale de la meseta', 'azul!85!black')

    # (c) resolucion de pares
    e = Ejes(0.0, 0.0, 6.2, 3.3, (1, 300), (0, 1), xlog=True, ylog=False)
    titulo(e, "c) ¿Se detectan los dos pulsos del par?")
    L += e.marco([1, 3, 10, 30, 100, 300], [0, 0.5, 1], "$\\Delta t$, muestras",
                 "pares con dos eventos", fmt_y=lambda v: f"{v:g}")
    colores = {'placa': 'azul!85!black', 'rapido': 'verde!55!black', 'pz': 'rojo!75!black'}
    for det, col in colores.items():
        for par, extra in (('2000->1200', ''), ('8000->300', ', dash pattern=on 2pt off 1.2pt')):
            pts = res['resolucion'][det][par]
            L.append(e.curva([max(d, 1) for d, _ in pts], [q for _, q in pts],
                             f'{col}, line width=1.1pt{extra}'))
    rot(e, 21, 0.84, 'polo-cero', colores['pz'])
    rot(e, 21, 0.70, 'pendiente rápida', colores['rapido'])
    rot(e, 21, 0.56, 'pendiente de la placa', colores['placa'])
    rot(e, 21, 0.34, 'lleno: 2000 $\\to$ 1200', 'black!70')
    rot(e, 21, 0.20, 'cortado: 8000 $\\to$ 300', 'black!70')

    # (d) que pasa con cada pulso a 1 Mcps
    cats = [('bueno', 'verde!70', 'buenos'), ('malo', 'rojo', 'contaminados sin detectar'),
            ('marcado', 'amarillo', 'marcados'), ('perdido', 'grisr!80!black', 'perdidos')]
    confs = [('hoy', 'hoy: $k$ = 64, 2 ranuras, pendiente'),
             ('banco', 'banco, 4 ranuras, pendiente'),
             ('banco + inspector', 'banco + inspector, pendiente'),
             ('banco, disparo pz', 'banco, 4 ranuras, disparo con polo-cero')]
    x0, y0, ancho, alto = 7.6, 0.0, 6.2, 3.3
    L.append(f"\\node[anchor=south west, font=\\scriptsize\\bfseries, inner sep=0pt] at "
             f"({x0:.3f},{y0 + alto + 0.18:.3f}) {{d) Cada pulso de un tren de 1 Mcps}};")
    h = 0.48
    for q, (clave, nombre) in enumerate(confs):
        cnt = res['tren'][f'1000/{clave}']
        tot = sum(cnt.values())
        yb = y0 + alto - 0.62 - q * 0.80
        L.append(f"\\node[nodo, anchor=south west, inner sep=0pt] at ({x0:.3f},{yb + h + 0.03:.3f}) {{{nombre}}};")
        xa = x0
        for cat, col, _ in cats:
            fr = cnt[cat] / tot
            w = ancho * fr
            L.append(f"\\fill[{col}] ({xa:.3f},{yb:.3f}) rectangle ({xa + w:.3f},{yb + h:.3f});")
            if fr >= 0.04:
                L.append(f"\\node[nodo] at ({xa + w / 2:.3f},{yb + h / 2:.3f}) {{{100 * fr:.0f}}};")
            xa += w
        L.append(f"\\draw[black!50, line width=0.3pt] ({x0:.3f},{yb:.3f}) rectangle ({x0 + ancho:.3f},{yb + h:.3f});")
    xl = x0
    for cat, col, txt in cats:
        L.append(f"\\fill[{col}] ({xl:.3f},{y0 - 0.42:.3f}) rectangle ++(0.22,0.16);")
        L.append(f"\\node[nodo, anchor=west] at ({xl + 0.25:.3f},{y0 - 0.34:.3f}) {{{txt}}};")
        xl += 0.45 + 0.105 * len(txt)
    L.append(f"\\node[nodo, anchor=north east, text=black!60] at ({x0 + ancho:.3f},{y0 - 0.52:.3f}) "
             f"{{\\% de los pulsos que llegan; amplitud log-uniforme 100..8000}};")

    nombre = 'banco_pruebas'
    tex = os.path.join(AQUI, f'{nombre}.tex')
    with open(tex, 'w') as fh:
        fh.write(PLANTILLA % (nombre, "\n".join(L)))
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                        f"-output-directory={tmp}", f'{nombre}.tex'], cwd=AQUI, check=True,
                       capture_output=True)
        shutil.copy(os.path.join(tmp, f'{nombre}.pdf'), os.path.join(AQUI, f'{nombre}.pdf'))
    subprocess.run(["pdftocairo", "-svg", os.path.join(AQUI, f'{nombre}.pdf'),
                    os.path.join(AQUI, f'{nombre}.svg')], check=True)
    print(f'escrito {nombre}.tex, .pdf y .svg')


CANDIDATAS = [Forma(64, 48, 4, 80), Forma(32, 24, 3, 39), Forma(32, 28, 3, 39),
              Forma(16, 12, 2, 19), Forma(16, 16, 2, 19), Forma(16, 20, 2, 19),
              Forma(8, 8, 1, 10), Forma(8, 12, 1, 10), Forma(8, 16, 1, 10),
              Forma(8, 16, 2, 10)]
# el banco que se usa con cada disparo (lo decide la tabla de formas)
ELEGIDO = {'placa': 'ajustado', 'pz': 'analisis'}


def tabla_formas(rng, nombre_disp):
    """Secciones 1 y 2 con las latencias de un disparo: el inicio de ventana, la
    amplitud minima y los umbrales de cada forma candidata."""
    out = {}
    print(f'\nformas con el disparo {nombre_disp}: sesgo contra amplitud (peor caso <= {CRIT_SESGO} %), '
          f'umbrales en dt de disparo:')
    print(f'  {"forma":>12s} {"subida":>6s} {"c":>4s} {"A_min":>6s} {"peor A>=1200":>13s}'
          f' {"ideal":>9s} {"real":>9s} {"dM 0.1%":>10s} {"dM 0.5%":>10s}')
    for f in CANDIDATAS:
        ui = umbrales_ideales(f)
        for tr10 in (1.2, 4.0, 8.0):
            c, fila = mejor_c(f, tr10, rng)
            am = a_minima(fila)
            p1200 = max(p for _, p in fila[AMPS.index(1200.0):])
            ur = um = None
            if tr10 == 1.2:
                ur = umbrales_reales(f, c, tr10, rng)
                um = {}
                for dm in (0.001, 0.005):
                    up = umbrales_reales(f, c, tr10, rng, dmq=+dm)
                    un = umbrales_reales(f, c, tr10, rng, dmq=-dm)
                    um[dm] = (max(up[0], un[0]), max(up[1], un[1]))
            clave = f'{f.k}/{f.m}/{f.w}'
            out.setdefault(clave, {})[str(tr10)] = {
                'c': c, 'a_min': am, 'peor_1200': p1200, 'sesgo': fila,
                'umbral_ideal': ui, 'umbral_real': ur,
                'umbral_dm': {str(k): v for k, v in um.items()} if um else None}
            print(f'  {clave:>12s} {tr10:6.1f} {c:4d} {str(am):>6s} {p1200:12.3f}%'
                  f' {str(ui) if tr10 == 1.2 else "":>9s} {str(ur) if ur else "":>9s}'
                  f' {str(um[0.001]) if um else "":>10s} {str(um[0.005]) if um else "":>10s}')
    return out


def bancos(rng, formas, s_real, nombre_disp):
    """Seccion 3 y 4: el ruido y los pares con cada banco, con las ventanas y los
    umbrales que salen de la tabla de formas de ese disparo."""
    out = {}
    for nombre, banco in BANCOS.items():
        claves = [f'{f.k}/{f.m}/{f.w}' for f in banco]
        cs = [formas[cl]['1.2']['c'] for cl in claves]
        umbr_r = [tuple(formas[cl]['1.2']['umbral_dm']['0.001']) for cl in claves]
        umbr_i = [tuple(formas[cl]['1.2']['umbral_ideal']) for cl in claves]
        cs_i = [f.off - 7 for f in banco]
        b = {'formas': claves, 'c': cs, 'umbral_real': umbr_r, 'umbral_ideal': umbr_i}
        b['ruido'] = ruido_formas(banco, cs, s_real, rng)
        b['par_ideal'] = pares_banco(banco, cs_i, umbr_i, 2000.0, 1200.0, rng, ideal=True)
        b['par_real'] = pares_banco(banco, cs, umbr_r, 2000.0, 1200.0, rng, s_real, dmq=0.001)
        b['par_extremo'] = pares_banco(banco, cs, umbr_r, 8000.0, 300.0, rng, s_real, dmq=0.001)
        b['par_extremo_inv'] = pares_banco(banco, cs, umbr_r, 300.0, 8000.0, rng, s_real, dmq=0.001)
        b['tasa'] = {}
        for n_acc in (2, 4):
            b['tasa'][n_acc] = {
                'ideal': tasa_buenos(banco, umbr_i, 1000, n_acc, 104, np.random.default_rng(5)),
                'real': tasa_buenos(banco, umbr_r, 1000, n_acc, 104, np.random.default_rng(5))}
        out[nombre] = b
        print(f'\nbanco {nombre} con el disparo {nombre_disp}: {claves}, c = {cs}')
        print(f'  umbrales ideal {umbr_i}')
        print(f'  umbrales real  {umbr_r}  (dt de disparo, dM 0.1 %)')
        print('  ruido de F (% de A = 1000): ' + ', '.join(
            f"{k} {v['blanco']:.3f}/{v['real']:.3f}" for k, v in b['ruido'].items()) + '  (blanco/real)')
        for cl in ('par_ideal', 'par_real', 'par_extremo', 'par_extremo_inv'):
            p = b[cl]

            def desde(e):
                for i in range(len(e)):
                    if all(v < CRIT_PAR for v in e[i:]):
                        return p['dt'][i]
            print(f'  {cl:16s} A < 1 % desde dt {desde(p["A"])}, B desde {desde(p["B"])}; '
                  f'error a dt 2/10/20/50/100: A ' +
                  '/'.join(f"{p['A'][p['dt'].index(d)]:.2f}" for d in (2, 10, 20, 50, 100)) + ' B ' +
                  '/'.join(f"{p['B'][p['dt'].index(d)]:.2f}" for d in (2, 10, 20, 50, 100)))
        print('  buenos a 1 Mcps, G = 104, un disparo por pulso: ' + ', '.join(
            f"N={n}: {v['ideal']:.0f} ideal / {v['real']:.0f} real kcps" for n, v in b['tasa'].items()))
    return out


# las configuraciones del tren: (etiqueta, disparo, solo k = 64, ranuras, inspector)
CONFIGS = [('hoy', 'placa', True, 2, False),
           ('hoy, disparo pz', 'pz', True, 2, False),
           ('banco', 'placa', False, 4, False),
           ('banco + inspector', 'placa', False, 4, True),
           ('banco, disparo pz, N=2', 'pz', False, 2, False),
           ('banco, disparo pz', 'pz', False, 4, False)]


def main():
    global LAT
    rng = np.random.default_rng(11)
    res = {}

    w = capturas_e2e()
    s_real, res['ruido'] = medir_ruido(w)
    res['subida'] = medir_subida(w)
    print(f"ruido: sigma {res['ruido']['sigma']:.2f} cuentas, autocorrelacion 1..5 "
          f"{np.round(res['ruido']['autocorr_1_5'], 3)} ({res['ruido']['segmentos']} segmentos)")
    print(f"subida: escalon medio {res['subida']['escalon_medio']} ({res['subida']['escalones']} escalones)")

    print('\nlatencia del disparo (RTL), media por amplitud:')
    for nombre, (_, sufijo) in DISPAROS.items():
        lat = leer_latencias(sufijo)
        for tr in np.unique(lat[:, 0]):
            fila = [lat[(lat[:, 0] == tr) & (lat[:, 1] == a), 3].mean() for a in AMPS
                    if ((lat[:, 0] == tr) & (lat[:, 1] == a)).any()]
            print(f'  {nombre:6s} subida {tr:4.1f}: ' + ' '.join(f'{v:5.1f}' for v in fila))

    res['formas'], res['bancos'] = {}, {}
    for nombre in ('placa', 'pz'):
        LAT = leer_latencias(DISPAROS[nombre][1])
        res['formas'][nombre] = tabla_formas(rng, nombre)
        res['bancos'][nombre] = bancos(rng, res['formas'][nombre], s_real, nombre)

    print('\nganancia de la meseta (A = 1) por forma y subida:')
    for f in BANCOS['ajustado'] + [BANCOS['analisis'][-1]]:
        print(f'  {f.k:2d}/{f.m:2d} sh={f.sh}: ' + ' '.join(f'{ganancia(f, tr):.5f}' for tr in (1e-3, 1.2, 4.0, 8.0)))

    print('\ndisparo: el modelo de Python contra el RTL (latencia media por A; dt de dos disparos):')
    res['disparo'] = {}
    for nombre, (dsp, sufijo) in DISPAROS.items():
        fil, par = validar_disparo(dsp, os.path.join(AQUI, f'banco_latencias{sufijo}.txt'),
                                   os.path.join(AQUI, f'banco_pares{sufijo}.txt'), rng)
        res['disparo'][nombre] = {'latencia': {str(k): v for k, v in fil.items()}, 'pares': par}
        print(f'  {nombre}: latencia RTL/modelo ' +
              ' '.join(f'{k:.0f}:{v[0] if v[0] is None else round(v[0], 1)}/{v[1] if v[1] is None else round(v[1], 1)}'
                       for k, v in fil.items()))
        print('     dos disparos siempre desde dt (RTL/modelo): ' +
              ', '.join(f'{k} {v[0]}/{v[1]}' for k, v in par.items()))

    print('\ntren de Poisson (amplitud log-uniforme 100..8000), compuerta 104: '
          '% de los pulsos de verdad')
    res['tren'] = {}
    for tasa in (100, 300, 1000):
        r2 = np.random.default_rng(23)
        n = int(4e6 if tasa < 1000 else 2e6)
        pies, a, xl = tren(tasa, n, r2)
        x = np.round(xl + r2.normal(0, 4.57, n))
        seg = n / 125e6
        for etq, nd, solo, n_acc, con_insp in CONFIGS:
            dsp = DISPAROS[nd][0]
            b = res['bancos'][nd][ELEGIDO[nd]]
            banco = BANCOS[ELEGIDO[nd]]
            cl = clasificar(pies, a, xl, x, dsp, banco, b['c'], b['umbral_real'], n_acc, 104,
                            0 if solo else None, INSPECTOR if con_insp else None)
            cnt = {k: int((cl == k).sum()) for k in ('bueno', 'malo', 'marcado', 'perdido')}
            res['tren'][f'{tasa}/{etq}'] = cnt
            tot = len(cl)
            print(f'  {tasa:5d} kcps, {etq:24s}: buenos {100 * cnt["bueno"] / tot:5.1f} % '
                  f'({cnt["bueno"] / seg / 1e3:5.0f} kcps), apilados sin detectar {100 * cnt["malo"] / tot:5.2f} %, '
                  f'marcados {100 * cnt["marcado"] / tot:5.1f} %, perdidos {100 * cnt["perdido"] / tot:5.1f} %')

    res['resolucion'] = resolucion(rng)
    with open(os.path.join(AQUI, 'banco_pruebas.json'), 'w') as fh:
        json.dump(res, fh, indent=1)
    figura(res)


if __name__ == '__main__':
    main()

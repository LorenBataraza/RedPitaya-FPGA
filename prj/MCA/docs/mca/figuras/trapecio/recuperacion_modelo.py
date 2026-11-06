#!/usr/bin/env python3
"""El modelo de ranuras_y_recuperacion.md: ranuras, conformado adaptativo y descomposicion.

Lo usa figuras_recuperacion.py, que dibuja. Aca solo se calcula:

  umbrales(forma)          cuantas muestras libres antes y despues necesita un
                           trapecio para medir con error < 1 %
  error_pares(...)         el error RMS de A y de B contra dt, con ruido, para
                           cada metodo de recuperacion
  arribos, ranuras         un tren Poisson pasado por las ranuras y el
                           publicador del RTL: que pulsos se miden
  buenos*                  cuales quedan buenos con cada metodo

Los parametros son los de la placa: cola de 2 us (250 muestras a 125 MS/s),
compuerta de 384, ruido blanco de 4 cuentas por muestra.
"""
import math
from dataclasses import dataclass

import numpy as np

FS = 125.0                      # MS/s
TAU = 250.0
MQ = round(16.0 / (math.exp(1.0 / TAU) - 1.0))
SIGMA = 4.0
PUB = 18                        # ciclos de publicacion; entre dos encolados, 19
CRITERIO = 1.0                  # % de error RMS que cuenta como "mide bien"


@dataclass(frozen=True)
class Forma:
    """Un trapecio: subida k, meseta m, y la ventana de 2^lw muestras desde off."""
    k: int
    m: int
    lw: int
    off: int

    @property
    def l(self):
        return self.k + self.m

    @property
    def sh(self):
        return round(math.log2(16 * self.k * (1 + MQ / 16.0) / 8))

    @property
    def w(self):
        return 1 << self.lw


# La de la placa y tres mas cortas, cada una con la ventana centrada en la meseta
# [k-1, k+m-1]. Las mesetas cortas suponen una subida rapida: con un tiempo de
# subida t_c la meseta tiene que ser mayor que t_c.
FORMAS = [Forma(64, 48, 4, 80), Forma(32, 24, 3, 39), Forma(16, 12, 2, 19), Forma(8, 8, 1, 10)]
F64 = FORMAS[0]


# --------------------------------------------------------------------- senal
def pulso(a, t0, n, entero=True, tau=TAU):
    t = np.arange(n) - t0
    v = np.where(t >= 0, a * np.exp(-np.maximum(t, 0) / tau), 0.0)
    return np.round(v).astype(np.int64) if entero else v


def retrasar(v, j):
    o = np.zeros_like(v)
    o[..., j:] = v[..., :v.shape[-1] - j]
    return o


def salida(x, f):
    """La salida de mca_trap: en enteros y corrida sh si x es entero; en flotante si no."""
    d = x - retrasar(x, f.k) - retrasar(x, f.l) + retrasar(x, f.k + f.l)
    p = np.cumsum(d, -1)
    s = np.cumsum(16 * p + MQ * d, -1)
    return s >> f.sh if s.dtype.kind == "i" else s / 2.0 ** f.sh


def f_trap(x, pie, f):
    """F_TRAP de la ranura que abrio en `pie` (promedio de la salida en su ventana)."""
    t = salida(x, f)
    v = t[..., pie + f.off:pie + f.off + f.w].sum(-1) / f.w
    return np.floor(v) if t.dtype.kind == "i" else v


def integral(x, pie, g):
    return x[..., pie:pie + g].sum(-1).astype(float)


# ------------------------------------------------------------------ umbrales
def umbrales(f, a=1000, n=1200, t0=200, maximo=400):
    """(antes, despues): muestras libres para error < CRITERIO, sin ruido y con vecinos iguales."""
    xa = pulso(a, t0, n)
    ref = f_trap(xa, t0, f)
    ea, eb = [], []
    for dt in range(1, maximo + 1):
        xb = pulso(a, t0 + dt, n)
        x = xa + xb
        ea.append(abs(f_trap(x, t0, f) / ref - 1) * 100)
        eb.append(abs(f_trap(x, t0 + dt, f) / f_trap(xb, t0 + dt, f) - 1) * 100)

    def desde(e):
        for i in range(len(e)):
            if all(v < CRITERIO for v in e[i:]):
                return i + 1
        return None
    return desde(eb), desde(ea)


# ------------------------------------------------- recuperacion de un par
def coeficientes(dt, estimador, n=1400, t0=200, tau=TAU):
    """La matriz 2x2 que lleva (A, B) unitarios a lo que miden las dos ranuras."""
    ua = pulso(1.0, t0, n, entero=False, tau=tau)
    ub = pulso(1.0, t0 + dt, n, entero=False, tau=tau)
    return np.array([[estimador(ua, t0), estimador(ub, t0)],
                     [estimador(ua, t0 + dt), estimador(ub, t0 + dt)]])


def error_pares(dts, umbr, a1=1000, a2=600, g=384, r=300, n=1400, t0=200, rng=None,
                dt_err=0, tau_senal=TAU):
    """Error RMS (%) de A y de B contra dt, con ruido, para cada metodo.

    umbr: {forma: (antes, despues)}. Los errores de lo que pasa en la placa:
    tau_senal es la cola que llega de verdad, mientras que M y el modelo de la
    descomposicion suponen TAU; dt_err es lo que se equivoca el dt de los
    disparos, que la descomposicion usa (el trapecio y el banco no).

    Cada metodo se compara contra lo que mide de un pulso SOLO con el mismo
    error de modelo: una ganancia la absorbe la calibracion, lo que se mide aca
    es lo que el otro pulso agrega. Devuelve {metodo: (errores de A, errores de B)}.
    """
    rng = rng or np.random.default_rng(7)
    est_t = lambda x, p: f_trap(x, p, F64)                     # noqa: E731
    est_q = lambda x, p: integral(x, p, g)                     # noqa: E731
    metodos = ["trap64", "adaptivo", "desc_trap", "desc_int"]
    out = {m: ([], []) for m in metodos}
    for dt in dts:
        xa, xb = pulso(a1, t0, n, tau=tau_senal), pulso(a2, t0 + dt, n, tau=tau_senal)
        x = (xa + xb)[None] + np.round(rng.normal(0, SIGMA, (r, n))).astype(np.int64)

        def rms(v, ref):
            return 100 * np.sqrt(np.mean((v - ref) ** 2)) / ref

        # el trapecio de la placa, tal cual
        ra, rb = f_trap(xa, t0, F64), f_trap(xb, t0 + dt, F64)
        out["trap64"][0].append(rms(f_trap(x, t0, F64), ra))
        out["trap64"][1].append(rms(f_trap(x, t0 + dt, F64), rb))

        # adaptivo: cada ranura usa la forma mas larga que su vecino permite
        # (A mira hacia adelante, B hacia atras); si ninguna, la mas corta
        fa = next((f for f in FORMAS if umbr[f][1] <= dt), FORMAS[-1])
        fb = next((f for f in FORMAS if umbr[f][0] <= dt), FORMAS[-1])
        out["adaptivo"][0].append(rms(f_trap(x, t0, fa), f_trap(xa, t0, fa)))
        out["adaptivo"][1].append(rms(f_trap(x, t0 + dt, fb), f_trap(xb, t0 + dt, fb)))

        # descomposicion: las dos ranuras miden, se resuelve el sistema 2x2 con
        # el modelo (TAU y el dt que dicen los disparos)
        for nombre, est in (("desc_trap", est_t), ("desc_int", est_q)):
            c = coeficientes(dt + dt_err, est, n=n, t0=t0)
            sol = np.linalg.solve(c, np.vstack([est(x, t0), est(x, t0 + dt)]))
            sa, sb = est(xa, t0) / c[0, 0], est(xb, t0 + dt) / c[1, 1]
            out[nombre][0].append(rms(sol[0], sa))
            out[nombre][1].append(rms(sol[1], sb))
    return out


def dt_minimo(dts, err):
    """El primer dt desde el que el error RMS queda por debajo del criterio."""
    for i, d in enumerate(dts):
        if all(e < CRITERIO for e in err[i:]):
            return d
    return None


# ----------------------------------------------------------- tren de pulsos
def arribos(tasa_kcps, n_arribos, rng):
    """Instantes de disparo (en muestras) de un tren Poisson; dos en la misma muestra son uno."""
    rho = tasa_kcps * 1e3 / (FS * 1e6)
    t = np.floor(np.cumsum(rng.exponential(1.0 / rho, n_arribos))).astype(np.int64)
    return np.unique(t)


def ranuras(t, n_acc, g):
    """Que disparos encuentran ranura, con la logica del RTL.

    Una ranura abre con el disparo, mide g muestras, cierra, y queda cerrada hasta
    que el publicador la libera: 18 ciclos despues del cierre si estaba libre, 19
    despues de la anterior si no. Libre desde el ciclo siguiente a liberarse.
    """
    libre = [0] * n_acc
    ultima = -10 ** 9
    medido = np.zeros(len(t), bool)
    for i, ti in enumerate(t):
        for s in range(n_acc):
            if libre[s] <= ti:
                lib = max(ti + g + PUB, ultima + PUB + 1)
                ultima = lib
                libre[s] = lib + 1
                medido[i] = True
                break
    return medido


def vecinos(t):
    """Muestras al disparo anterior y al siguiente, se hayan medido o no."""
    return np.diff(t, prepend=-10 ** 9), np.diff(t, append=10 ** 12)


def buenos(t, medido, up, un):
    """Medidos y sin vecinos que los contaminen: un trapecio de umbrales (up, un)."""
    ant, sig = vecinos(t)
    return medido & (ant >= up) & (sig >= un)


def buenos_adaptivo(t, medido, umbr):
    """Con el banco: alcanza con que alguna forma tenga sus dos lados libres."""
    ant, sig = vecinos(t)
    ok = np.zeros(len(t), bool)
    for f in FORMAS:
        a, b = umbr[f]
        ok |= (ant >= a) & (sig >= b)
    return medido & ok


def buenos_descomp(t, medido, up, un, dmin):
    """Con la descomposicion de pares: arregla UN vecino cercano si ese vecino
    tambien se midio, esta a dmin o mas, y el par no tiene otro pulso cerca (los
    trios no se resuelven)."""
    ant, sig = vecinos(t)
    ant2 = np.concatenate([[10 ** 9], ant[:-1]])        # el "anterior" del anterior
    sig2 = np.concatenate([sig[1:], [10 ** 12]])        # el "siguiente" del siguiente
    med_ant = np.concatenate([[False], medido[:-1]])
    med_sig = np.concatenate([medido[1:], [False]])
    solo = (ant >= up) & (sig >= un)
    par_ant = (ant < up) & (ant >= dmin) & med_ant & (ant2 >= up) & (sig >= un)
    par_sig = (sig < un) & (sig >= dmin) & med_sig & (sig2 >= un) & (ant >= up)
    return medido & (solo | par_ant | par_sig)

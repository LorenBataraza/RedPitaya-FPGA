"""Modelo de referencia en Python de mt_slope_trig (y del Schmitt de nivel).

Bit-exacto en lo que importa para las figuras y para comparar contra el RTL:

  - s[n] por la MISMA recursión que el hardware,
        s[n] = s[n-1] + (x[n]-x[n-L]) - (x[n-L-G]-x[n-2L-G]),
    con historia en cero desde el re-arranque, en enteros;
  - el arranque silencioso: sin pulsos hasta tener 2L+G muestras;
  - el Schmitt simétrico, que arranca "disparado" (pide re-armar).

No modela los 5 ciclos de pipeline: los índices de disparo son el número de
muestra válida que produjo el cruce. Tampoco modela huecos de adc_dv: la
entrada son las muestras válidas, en orden.

`schmitt_nivel` es el disparo de nivel de rp_adc_trig.v, para comparar.
"""
from __future__ import annotations

import numpy as np


def respuesta_impulsiva(L: int, G: int) -> np.ndarray:
    """Los coeficientes del filtro: +1 (L veces), 0 (G veces), -1 (L veces)."""
    return np.concatenate([np.ones(L, np.int64), np.zeros(G, np.int64),
                           -np.ones(L, np.int64)])


def incremento(x, L: int, G: int) -> np.ndarray:
    """d[n] = (x[n]-x[n-L]) - (x[n-L-G]-x[n-2L-G]): lo que suma el acumulador."""
    x = np.asarray(x, dtype=np.int64)
    pad = 2 * L + G
    xp = np.concatenate([np.zeros(pad, np.int64), x])
    n = np.arange(pad, pad + len(x))
    return (xp[n] - xp[n - L]) - (xp[n - L - G] - xp[n - 2 * L - G])


def trapezoidal_rapido(x, L: int, G: int) -> np.ndarray:
    """s[n] por la recursión del RTL (acumulador del incremento)."""
    return np.cumsum(incremento(x, L, G))


def trapezoidal_directo(x, L: int, G: int) -> np.ndarray:
    """s[n] por la definición: convolución con la respuesta impulsiva."""
    x = np.asarray(x, dtype=np.int64)
    return np.convolve(x, respuesta_impulsiva(L, G))[:len(x)]


def schmitt_pendiente(s, L: int, G: int, thr: int, hyst: int):
    """Índices de los pulsos p (s >= thr) y n (s <= -thr), como el RTL.

    Mientras la ventana no está llena (n < 2L+G) el Schmitt queda en
    "disparado", y el primer pulso exige re-armar antes.
    """
    lleno = 2 * L + G
    sp = sn = True
    ip, in_ = [], []
    for k, v in enumerate(np.asarray(s)):
        if k < lleno:
            sp = sn = True
            continue
        if v >= thr:
            if not sp:
                ip.append(k)
            sp = True
        elif v < thr - hyst:
            sp = False
        if v <= -thr:
            if not sn:
                in_.append(k)
            sn = True
        elif v > -thr + hyst:
            sn = False
    return np.array(ip, int), np.array(in_, int)


def schmitt_nivel(x, thr: int, hyst: int) -> np.ndarray:
    """Índices de los pulsos p de rp_adc_trig: x >= thr, re-arma bajo thr-hyst."""
    arriba = False
    idx = []
    for k, v in enumerate(np.asarray(x)):
        if v >= thr:
            if not arriba:
                idx.append(k)
            arriba = True
        elif v < thr - hyst:
            arriba = False
    return np.array(idx, int)

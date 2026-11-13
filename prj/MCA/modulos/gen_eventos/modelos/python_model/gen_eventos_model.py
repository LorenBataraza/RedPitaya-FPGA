"""Modelo de referencia de gen_eventos: en qué ts del ring sale cada disparo,
y qué dato lleva cada muestra.

Es bit-exacto contra el RTL (lo verifica tb_gen_eventos con los vectores que
escribe `python3 gen_eventos_model.py --vectores`), y es lo que usa el software
para saber qué tiene que haber en cada slot.

Convención de tiempo: `ts` es el reloj del ring (ts_cnt de event_ring_top),
que vale 0 en el primer ciclo en RUNNING y cuenta una muestra por ciclo con el
dato continuo (dv = 1). El generador decide en el ciclo g (g = 0 un ciclo
después del arranque) y el pulso sale en el siguiente, así que la captura lo
toma con ts = g + 2. El tb_event_ring_gen lo confirma sobre el ring entero.
"""
from __future__ import annotations

import argparse
import os

M32 = 0xFFFF_FFFF
SEMILLA_0 = 0x2545_F491
TS_DEL_DISPARO = 2          # ts del disparo = ciclo de decisión + 2


def xorshift32(x: int) -> int:
    x ^= (x << 13) & M32
    x ^= x >> 17
    x ^= (x << 5) & M32
    return x


def disparos(n_ciclos: int, aleatorio: bool, periodo: int = 1000, umbral: int = 0,
             dt_min: int = 2, n: int = 0, semilla: int = 0) -> list[int]:
    """Los ts (del ring) de los disparos que salen en los primeros `n_ciclos` ciclos
    de decisión, con el ring en RUNNING todo el tiempo."""
    periodo = max(periodo, 2)
    dt_min = max(dt_min, 2)
    x = semilla or SEMILLA_0
    per = periodo - 1
    hold = 0
    out = []
    for g in range(n_ciclos):
        if n and len(out) >= n:
            break
        if aleatorio:
            disp = hold == 0 and x < umbral
            if disp:
                hold = dt_min - 1
            elif hold:
                hold -= 1
        else:
            disp = per == 0
            per = periodo - 1 if per == 0 else per - 1
        if disp:
            out.append(g + TS_DEL_DISPARO)
        x = xorshift32(x)
    return out


def intervalo_medio(umbral: int, dt_min: int = 2) -> float:
    """Ciclos entre disparos, en promedio, del modo aleatorio."""
    return (max(dt_min, 2) - 1) + 2**32 / umbral


def umbral_para(tasa_hz: float, dt_min: int = 2, fs: float = 125e6) -> int:
    """El UMBRAL que da `tasa_hz` disparos por segundo en el modo aleatorio."""
    resto = fs / tasa_hz - (max(dt_min, 2) - 1)
    if resto < 1:
        raise ValueError(f'{tasa_hz:g} Hz con dt_min = {dt_min}: el máximo es {fs / max(dt_min, 2):g}')
    return min(M32, round(2**32 / resto))


def patron(ts: int, n_ch: int = 2, dw: int = 14) -> list[int]:
    """Lo que el generador pone en cada canal cuando el reloj del ring vale `ts`
    (sin signo, dw bits): el canal par es ts, el impar su complemento."""
    m = (1 << dw) - 1
    return [(~ts & m) if c % 2 else (ts & m) for c in range(n_ch)]


# Los vectores de tb_gen_eventos: (nombre, configuración). Cortos a propósito.
VECTORES = (
    ('aleat_p02_dt5', dict(aleatorio=True, umbral=round(2**32 * 0.02), dt_min=5, semilla=0x1234_5678)),
    ('aleat_p50_dt2', dict(aleatorio=True, umbral=0x8000_0000, dt_min=2, semilla=0)),
)
N_CICLOS_VECTORES = 20000


def escribir_vectores(carpeta: str) -> None:
    os.makedirs(carpeta, exist_ok=True)
    for nombre, cfg in VECTORES:
        ts = disparos(N_CICLOS_VECTORES, **cfg)
        with open(os.path.join(carpeta, f'gen_{nombre}.hex'), 'w') as f:
            f.write(''.join(f'{t:08x}\n' for t in ts))
        print(f'gen_{nombre}.hex: {len(ts)} disparos en {N_CICLOS_VECTORES} ciclos')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--vectores', action='store_true', help='escribe sim/vectores/gen_*.hex')
    a = p.parse_args()
    if a.vectores:
        escribir_vectores(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'sim', 'vectores'))

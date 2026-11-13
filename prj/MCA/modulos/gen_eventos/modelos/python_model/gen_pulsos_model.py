"""Modelo de referencia de gen_pulsos: la muestra que sale en cada ciclo.

Es bit-exacto contra el RTL (lo verifica tb_gen_pulsos con los vectores que
escribe `python3 gen_pulsos_model.py --vectores`), y es lo que usa el software
para saber qué tiene que medir el MCA cuando el estímulo es el generador.

Simula los registros de gen_pulsos.sv uno por uno, ciclo por ciclo. No es
rápido (unos 10 µs por muestra), pero no hay lugar para que difiera.

Convención de tiempo: el ciclo g = 0 es el primero después del arranque (el
ciclo en que se escribió CTRL.en = 1), con todo el estado en su valor de
reset. `dat[g]` es lo que sale por dat_a_o en el ciclo g, y `trig` son los g
en que trig_o está alto. El pulso aparece en `dat` LAT_DAT = 5 ciclos después
(con SUBIDA = 0): el impulso registrado, y1, y2, el redondeo y la suma con la
base.
"""
from __future__ import annotations

import argparse
import math
import os

import numpy as np

from gen_eventos_model import SEMILLA_0, xorshift32

M32 = 0xFFFF_FFFF
K_AMP = 0x9E37_79B9
K_RUIDO = 0x7F4A_7C15
TAB_AW = 10
N_TABLA = 1 << TAB_AW
DW = 14
F = 8                     # bits de fracción de los polos
YW = 25                   # ancho de y1 e y2
DMAX, DMIN = (1 << (DW - 1)) - 1, -(1 << (DW - 1))
SIGMA_RUIDO_0 = math.sqrt(4 * (256**2 - 1) / 12)     # 147.8 cuentas con sh = 0
LAT_DAT = 5               # ciclos del pulso (trig_o) a su primera muestra en dat (SUBIDA = 0)

# Los registros de gen_pulsos con sus valores de reset
CFG = dict(aleatorio=False, periodo=1000, umbral=0, dt_min=2, n=0, semilla=0,
           amp_aleat=False, amp_n=0, decae=65280, subida=0, base=0,
           ruido=False, ruido_sh=0)


def _wrap(v: int, bits: int) -> int:
    m = 1 << bits
    return ((v + (m >> 1)) % m) - (m >> 1)


def semillas(semilla: int) -> tuple[int, int, int]:
    """Las tres semillas (disparos, amplitud, ruido) que salen de SEMILLA."""
    s0 = semilla or SEMILLA_0
    return s0, (s0 ^ K_AMP) | 1, (s0 ^ K_RUIDO) | 1


def traza(n_ciclos: int, tabla=None, **kw) -> dict:
    """Lo que sale de gen_pulsos en los primeros `n_ciclos` ciclos desde el arranque.

    `tabla` son las amplitudes (hasta 1024, con signo; las que faltan valen 0).
    Las claves de `kw` son las de `CFG`. Devuelve un dict con:
      dat       las muestras (int64), las de dat_a_o
      trig      los ciclos en que trig_o está alto
      amp       la amplitud de cada pulso, en el orden de `trig`
      desborde  si y1 se desbordó (ESTADO[2])
    """
    malas = set(kw) - set(CFG)
    if malas:
        raise KeyError(f'claves que gen_pulsos no tiene: {sorted(malas)}')
    c = {**CFG, **kw}
    tab = [0] * N_TABLA
    for i, v in enumerate(tabla if tabla is not None else []):
        tab[i] = _wrap(int(v), DW)

    aleat = bool(c['aleatorio'])
    per_m1 = max(int(c['periodo']) & M32, 2) - 1
    dtm_m1 = max(int(c['dt_min']) & 0xFFFF, 2) - 1
    umbral = int(c['umbral']) & M32
    n = int(c['n']) & M32
    amp_aleat = bool(c['amp_aleat'])
    amp_m1 = (int(c['amp_n']) - 1) % N_TABLA
    decae = int(c['decae']) & 0xFFFF
    subida = int(c['subida']) & 7
    base = _wrap(int(c['base']), DW)
    ruido = bool(c['ruido'])
    sh = int(c['ruido_sh']) & 15

    x, ra, rr = semillas(int(c['semilla']) & M32)
    per_cnt, hold, trig_gen, cnt, idx, tab_q, imp = per_m1, 0, False, 0, 0, 0, 0
    y1 = y2 = s = nz = d = 0
    nsum = 510                # ruido 0 en la primera muestra
    desborde = False

    dat = np.empty(n_ciclos, np.int64)
    trig, amp = [], []
    for g in range(n_ciclos):
        dat[g] = d
        # --- lo combinacional del ciclo g ---
        hecho = n != 0 and cnt >= n
        activo = not hecho
        if aleat:
            disp = activo and hold == 0 and x < umbral
        else:
            disp = activo and per_cnt == 0
        pulso = trig_gen
        idx_c = (ra >> (32 - TAB_AW)) if amp_aleat else idx
        if pulso:
            trig.append(g)
            amp.append(tab_q)
        p = y1 * decae + (imp << (16 + F)) + (0xFFFF if y1 < 0 else 0)
        if not -(1 << (16 + YW - 1)) <= p < (1 << (16 + YW - 1)):
            desborde = True
        y1n = _wrap(p >> 16, YW)
        y2n = _wrap(y2 + ((y1 - y2) >> subida), YW)
        s_c = (y2 + ((1 << F) - 1 if y2 < 0 else 0)) >> F
        nsum_c = (rr & 0xFF) + ((rr >> 8) & 0xFF) + ((rr >> 16) & 0xFF) + (rr >> 24)
        nz_c = (nsum - 510) >> sh if ruido else 0
        suma = s + base + nz
        # --- el flanco: todo el estado a la vez ---
        if pulso:
            cnt += 1
        trig_gen = disp
        if activo:
            x = xorshift32(x)
            if aleat:
                hold = dtm_m1 if disp else (hold - 1 if hold else 0)
            else:
                per_cnt = per_m1 if per_cnt == 0 else per_cnt - 1
        if disp:
            ra = xorshift32(ra)
            idx = 0 if idx == amp_m1 else (idx + 1) % N_TABLA
        rr = xorshift32(rr)
        imp = tab_q if pulso else 0
        tab_q = tab[idx_c]
        y1, y2, s, nsum, nz = y1n, y2n, s_c, nsum_c, nz_c
        d = min(max(suma, DMIN), DMAX)
    return dict(dat=dat, trig=np.array(trig, np.int64), amp=np.array(amp, np.int64),
                desborde=desborde)


# --- para configurarlo ---------------------------------------------------------

def decae_para(tau_muestras: float) -> int:
    """DECAE para una caída de `tau_muestras` (125 MSPS: 8 ns cada una)."""
    return max(0, min(0xFFFF, round(65536.0 * math.exp(-1.0 / float(tau_muestras)))))


def tau_de(decae: int) -> float:
    """La constante de tiempo, en muestras, de un DECAE."""
    return -1.0 / math.log(decae / 65536.0) if 0 < decae < 65536 else math.inf


def m_polo_cero(decae: int) -> float:
    """La M del polo-cero que cancela la caída: M = DECAE / (2^16 - DECAE).
    El trapecio y el disparo con polo-cero toman Mq = round(16 M)."""
    return decae / (65536.0 - decae)


def sigma_ruido(sh: int) -> float:
    """El sigma del ruido, en cuentas, para un RUIDO.sh."""
    return SIGMA_RUIDO_0 / (1 << int(sh))


def tabla_cdf(valores, pesos) -> list[int]:
    """Las 1024 amplitudes que sortean `valores` con probabilidades `pesos`
    (CDF inversa): la tabla del modo amp_aleat."""
    v = np.asarray(valores, float)
    w = np.asarray(pesos, float)
    cdf = np.cumsum(w) / w.sum()
    u = (np.arange(N_TABLA) + 0.5) / N_TABLA
    return [int(round(v[min(np.searchsorted(cdf, ui), v.size - 1)])) for ui in u]


# --- los vectores de tb_gen_pulsos --------------------------------------------

def _rampa(a0, paso):
    return [a0 + paso * i for i in range(N_TABLA)]


# (nombre, tabla, configuración, ciclos). Cortos a propósito.
VECTORES = (
    # periódico, en orden, sin subida: el pico es la amplitud; con signo y con
    # 8191 (el fondo de escala); AMP_N = 4 vuelve a empezar
    ('periodico_escalon', [1000, 3000, -2000, 8191],
     dict(periodo=700, amp_n=4, decae=65280), 6000),
    # Poisson a ~1.9 Mcps con tiempo muerto, amplitud al azar, subida, base,
    # ruido: apila y satura arriba
    ('poisson_apilado', _rampa(200, 7),
     dict(aleatorio=True, umbral=round(2**32 * 0.016), dt_min=5, semilla=0x1234_5678,
          amp_aleat=True, decae=65274, subida=2, base=-100, ruido=True, ruido_sh=5),
     20000),
    # pulsos negativos, la subida más lenta, ruido grande que satura abajo, N
    ('negativos_n', [-1500, -6000, -300],
     dict(periodo=1500, n=7, amp_n=3, decae=64000, subida=7, base=-7000,
          ruido=True, ruido_sh=0, semilla=99), 12000),
    # sin caída (DECAE = 65535): y1 se desborda
    ('desborde', [8191],
     dict(periodo=20, amp_n=1, decae=65535), 400),
    # el período mínimo (un pulso cada 2 ciclos) recorriendo la tabla entera en
    # orden (AMP_N = 0 son 1024), y vuelta a empezar
    ('rafaga_tabla', [(37 * i) % 1500 - 700 for i in range(N_TABLA)],
     dict(periodo=0, amp_n=0, decae=60000, subida=1), 2300),
)


def escribir_vectores(carpeta: str) -> None:
    os.makedirs(carpeta, exist_ok=True)
    claves = ('aleatorio', 'periodo', 'umbral', 'dt_min', 'n', 'semilla', 'amp_aleat',
              'amp_n', 'decae', 'subida', 'base', 'ruido', 'ruido_sh')
    for nombre, tabla, kw, n_ciclos in VECTORES:
        c = {**CFG, **kw}
        t = traza(n_ciclos, tabla, **kw)
        with open(os.path.join(carpeta, f'pul_{nombre}.txt'), 'w') as f:
            f.write(' '.join(str(int(c[k])) for k in claves)
                    + f' {len(tabla)} {n_ciclos} {int(t["desborde"])} {t["trig"].size}\n')
            for v in tabla:
                f.write(f'{int(v) & 0x3FFF:04x}\n')
            tr = set(t['trig'].tolist())
            for g, v in enumerate(t['dat']):
                f.write(f'{int(v) & 0x3FFF:04x} {int(g in tr)}\n')
        print(f'pul_{nombre}.txt: {t["trig"].size} pulsos en {n_ciclos} ciclos, '
              f'min {t["dat"].min()} max {t["dat"].max()}, desborde {t["desborde"]}')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--vectores', action='store_true', help='escribe sim/vectores/pul_*.txt')
    a = p.parse_args()
    if a.vectores:
        escribir_vectores(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'sim', 'vectores'))

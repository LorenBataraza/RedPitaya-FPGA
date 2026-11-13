#!/usr/bin/env python3
"""El estímulo del volcado del MCA2, y cómo leer lo que el RTL devuelve.

`replica_mca2.py` se compara contra el RTL entero (`mt_top` + `mca_top`, como
en el top) con este circuito, el mismo que usa `test_ring_format.py` para el
event_ring:

    python3 monte-carlo/volcado_mca2.py               # escribe el estímulo
    make -C ../sim tb_mca2_volcado                    # QuestaSim: el volcado
    python3 -m pytest monte-carlo/test_replica_mca2.py

Las dos cosas quedan en `monte-carlo/datos_ref/`. El estímulo son varios bloques
de configuración distinta, cada uno con su traza: pulsos de la campaña con
arribos de Poisson a tasas que apilan, para que haya de todo (ventanas
solapadas, disparos perdidos con todas midiendo y con alguna esperando al
publicador, amplitudes fuera de la ventana, el trapecio). El TB resetea el
DUT entre bloques, así cada uno arranca de cero como la réplica.

FORMATO DEL ESTÍMULO (texto, una línea por cosa)
    B n_acc gs gl pre asrc qsh amin amax L G thr hyst tk tm tmq toff tlw tsh
      nf an de {k m off lw sh an de, de las formas 1..3} pz pzk pzm pzmq pzsh pzthr pzhyst N
    <N líneas: la muestra en hex, 14 bits en complemento a dos>
    ...
    FIN

FORMATO DEL VOLCADO
    B <bloque>
    T <i>                     un flanco de trig_i, en la muestra i
    E <i> amp psd psd_ok f0 .. f10   un evento publicado
    C total accepted rej_amp rej_psd pileup lost_busy cross open lost_active win trig
    O t_ocup0 .. t_ocup4
    FIN
`i` es el índice de la muestra del estímulo que está en la entrada en ese
flanco de reloj.
"""

import argparse
import os
import sys

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

import pileup as pu                                          # noqa: E402
import replica_mca2 as r2                                    # noqa: E402

DATOS_REF = os.path.join(_AQUI, 'datos_ref')
ESTIMULO = os.path.join(DATOS_REF, 'mca2_estimulo.txt')
VOLCADO = os.path.join(DATOS_REF, 'mca2_volcado.txt')

# Las claves de la línea B, en orden (las del RTL; trap_m va en tm)
_CLAVES_B = ('n_acc', 'gate_short', 'gate_long', 'pre_dly', 'amp_src',
             'q_shift', 'amp_min', 'amp_max', 'L', 'G', 'thr', 'hyst',
             'trap_k', 'trap_m', 'trap_mq', 'trap_off', 'trap_lw', 'trap_sh',
             'n_formas', 'trap_antes', 'trap_despues',
             *(f'forma{f}_{n}' for f in (1, 2, 3)
               for n in ('k', 'm', 'off', 'lw', 'sh', 'antes', 'despues')),
             'fuente', 'pz_k', 'pz_m', 'pz_mq', 'pz_sh', 'pz_thr', 'pz_hyst')
FLUSH = 4000          # ceros al final: que todo cierre y se publique

# Mq del trapecio para una cola exponencial de tau muestras: M = 1/(e^{1/tau}-1)
_MQ_186 = int(round(16.0 / np.expm1(1.0 / pu.TAU_COLA)))

# El banco de la campaña, con el pulso del preamplificador (tau = 250) y su Mq
# nominal: lo que da `mca_banco_config(3992, formas=BANCO_PZ_4)`, sin importar la API.
# Es el banco de 4 formas, anterior al recorte del 2026-11-09 (BANCO_PZ tiene 3).
_MQ_PRE = 3992
_BANCO = dict(n_formas=4, gate_long=112, pre_dly=16, trap_mq=_MQ_PRE,
              trap_k=64, trap_m=48, trap_off=87, trap_lw=4, trap_sh=15,
              trap_antes=97, trap_despues=96,
              forma1_k=32, forma1_m=24, forma1_off=47, forma1_lw=3, forma1_sh=14,
              forma1_antes=49, forma1_despues=48,
              forma2_k=16, forma2_m=12, forma2_off=27, forma2_lw=2, forma2_sh=13,
              forma2_antes=26, forma2_despues=24,
              forma3_k=8, forma3_m=8, forma3_off=18, forma3_lw=1, forma3_sh=12,
              forma3_antes=15, forma3_despues=13)
_PZ = dict(fuente='pz', pz_k=2, pz_m=1, pz_mq=_MQ_PRE, pz_sh=10, pz_thr=353, pz_hyst=177)

# (configuración, tasa, espectro, muestras, semilla[, forma]). Cubren el asignador
# con 1, 2 y 4 ranuras (y n_acc = 7, que el RTL satura a 4), la compuerta corta en
# 0, los dos estimadores, una ventana de amplitud que rechaza, tres disparos
# por pendiente distintos y dos trapecios. Los del final son el banco y el
# polo-cero: el de la campaña a 1 Mcps, menos formas, `n_formas` = 7 (que el RTL
# recorta a 4), el banco con la pendiente, y una forma sola con umbrales, que
# marca sin tener alternativa.
BLOQUES = (
    (dict(n_acc=1), 100e3, 'linea', 120_000, 1),
    (dict(n_acc=4, amp_src=1, q_shift=8, amp_min=500, amp_max=3500,
          trap_k=64, trap_m=32, trap_mq=_MQ_186, trap_off=72, trap_lw=4,
          trap_sh=12), 200e3, 'realista', 150_000, 2),
    (dict(n_acc=2, gate_short=0, gate_long=200, pre_dly=10, L=4, G=2,
          thr=400, hyst=100, amp_max=2500), 300e3, 'realista', 100_000, 3),
    (dict(n_acc=7, gate_short=64, gate_long=600, pre_dly=40, L=16, G=8,
          thr=1500, hyst=700, trap_k=32, trap_m=16, trap_mq=_MQ_186,
          trap_off=40, trap_lw=3, trap_sh=11), 150e3, 'linea', 130_000, 4),
    (dict(n_acc=4, **_BANCO, **_PZ), 1000e3, 'realista', 80_000, 5, 'preamp'),
    (dict(n_acc=2, **{**_BANCO, 'n_formas': 2}, **_PZ, amp_src=1, q_shift=6,
          amp_max=30000), 500e3, 'realista', 60_000, 6, 'preamp'),
    (dict(n_acc=4, **{**_BANCO, 'n_formas': 7}, **_PZ), 800e3, 'linea', 60_000, 7, 'preamp'),
    (dict(n_acc=4, **{**_BANCO, 'gate_long': 200, 'pre_dly': 20, 'trap_off': 91,
                      'forma1_off': 51, 'forma2_off': 31, 'forma3_off': 22},
          L=4, G=2, thr=420, hyst=210), 600e3, 'realista', 60_000, 8, 'preamp'),
    (dict(n_acc=3, **{**_BANCO, 'n_formas': 1, 'gate_long': 300}, **_PZ),
     400e3, 'realista', 60_000, 9, 'preamp'),
    # Una forma que no entra en la compuerta (gana y da cero) y un disparo con
    # k + m de más, que mt_pz_trig satura a sus 31 muestras.
    (dict(n_acc=4, **{**_BANCO, 'n_formas': 3, 'forma1_off': 200},
          **{**_PZ, 'pz_k': 20, 'pz_m': 25, 'pz_sh': 14, 'pz_thr': 500, 'pz_hyst': 250}),
     300e3, 'realista', 60_000, 10, 'preamp'),
)


def traza(tasa_hz, espectro, n_muestras, semilla, forma='campana'):
    """Pulsos con arribos de Poisson, y FLUSH ceros al final. `forma` es la
    semi-gaussiana de la campaña o el pulso del preamplificador."""
    rng = np.random.default_rng(semilla)
    forma = r2.forma_preamp() if forma == 'preamp' else pu.forma_referencia()[0]
    n_ev = int(1.2 * tasa_hz * n_muestras / pu.FS_HZ) + 10
    t = pu.arribos_poisson(n_ev, tasa_hz, rng=rng) + 200
    t = t[t < n_muestras - forma.size]
    a = pu.sortear_amplitudes(t.size, espectro, rng=rng)
    y, o = pu.render(t, a, forma, rng=rng, lead=200, trail=0)
    x = np.zeros(n_muestras + FLUSH, np.int64)
    m = min(y.size, n_muestras)
    x[o:o + m] = y[:m] if o >= 0 else y[-o:-o + m]
    return x


def bloques():
    """[(cfg, x)] de cada bloque, con la configuración completa de la réplica."""
    out = []
    for kw, tasa, esp, n, sem, *forma in BLOQUES:
        out.append((r2.cfg(**kw), traza(tasa, esp, n, sem, *forma)))
    return out


def escribir_estimulo(path=ESTIMULO):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        for c, x in bloques():
            vals = [int(c['fuente'] == 'pz') if k == 'fuente' else int(c[k])
                    for k in _CLAVES_B]
            f.write('B ' + ' '.join(str(v) for v in vals) + f' {x.size}\n')
            for v in x:
                f.write(f'{int(v) & 0x3FFF:04x}\n')
        f.write('FIN\n')
    return path


def leer_estimulo(path=ESTIMULO):
    """[(cfg, x)] tal como los leyó el TB: el test usa el archivo, no lo regenera
    (otra versión de numpy podría sortear otra traza)."""
    out = []
    with open(path) as f:
        while True:
            ln = f.readline()
            if not ln or ln.startswith('FIN'):
                break
            p = ln.split()
            vals = [int(v) for v in p[1:-1]]
            n = int(p[-1])
            x = np.array([int(f.readline(), 16) for _ in range(n)], np.int64)
            x = np.where(x >= 0x2000, x - 0x4000, x)
            kw = dict(zip(_CLAVES_B, vals))
            kw['fuente'] = 'pz' if kw['fuente'] else 'pendiente'
            out.append((r2.cfg(**kw), x))
    return out


def leer_volcado(path=VOLCADO):
    """[{trig, eventos, cnt, t_ocup}] por bloque, como los arma `r2.medir`."""
    out = []
    cur = None
    with open(path) as f:
        for ln in f:
            p = ln.split()
            if not p:
                continue
            if p[0] == 'B':
                cur = dict(trig=[], ev=[], cnt=None, t_ocup=None)
                out.append(cur)
            elif p[0] == 'T':
                cur['trig'].append(int(p[1]))
            elif p[0] == 'E':
                cur['ev'].append([int(v) for v in p[1:]])
            elif p[0] == 'C':
                k = ('total', 'accepted', 'rej_amp', 'rej_psd', 'pileup',
                     'lost_busy', 'cross', 'open', 'lost_active', 'windows',
                     'trig')
                cur['cnt'] = dict(zip(k, (int(v) for v in p[1:])))
            elif p[0] == 'O':
                cur['t_ocup'] = np.array([int(v) for v in p[1:]], np.int64)
            elif p[0] == 'FIN':
                break
    for b in out:
        e = np.array(b.pop('ev'), np.int64).reshape(-1, 4 + r2.N_FEAT)
        b['trig'] = np.array(b['trig'], np.int64)
        b['eventos'] = dict(emite=e[:, 0], amp=e[:, 1], psd=e[:, 2],
                            psd_ok=e[:, 3].astype(bool), feat=e[:, 4:])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--salida', default=ESTIMULO)
    a = ap.parse_args(argv)
    p = escribir_estimulo(a.salida)
    print(f'estímulo: {p} ({os.path.getsize(p) / 1e6:.1f} MB, '
          f'{len(BLOQUES)} bloques)')
    for (c, x), (_, tasa, esp, *_) in zip(bloques(), BLOQUES):
        m = r2.medir(x, c, hasta=x.size)
        print(f'  n_acc={c["n_acc"]} gl={c["gate_long"]} {c["fuente"]} nf={c["n_formas"]} '
              f'{esp} {tasa / 1e3:.0f} kcps: '
              f'{m["cnt"]["cross"]} disparos, {m["cnt"]["open"]} abren, '
              f'{m["cnt"]["lost_active"]} lost_active, {m["cnt"]["lost_busy"]} lost_busy, '
              f'{m["cnt"]["accepted"]} publicados, {m["cnt"]["pileup"]} solapados')
    return 0


if __name__ == '__main__':
    sys.exit(main())

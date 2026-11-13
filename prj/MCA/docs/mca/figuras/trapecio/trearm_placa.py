#!/usr/bin/env python3
"""t_rearm de la placa contra el golden model, sobre la MISMA señal capturada.

Lee lo que dejó software/API/tests/placa/test_banco_poisson.py (modo `banco`: disparo
con polo-cero). Cada período capturado va repetido a monte-carlo/replica_mca2.py, que da
el Schmitt del polo-cero y la ocupación de las ranuras ciclo a ciclo. El t_rearm del
modelo son los ciclos con el Schmitt sin re-armar y alguna ranura libre: la prioridad del
teselado es veto > t_win > t_div > t_rearm > livetime (acá no hay veto). `trig_arm` baja
1 ciclo antes de que el flanco llegue al MCA (mt_event_logic.v), por eso LAT_PZ - 1.

    python3 trearm_placa.py ../../../../software/datos/placa_trearm_20261113/banco_poisson
"""
import json
import os
import sys

import numpy as np

SW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', 'software')
sys.path.insert(0, SW)
sys.path.insert(0, os.path.join(SW, 'monte-carlo'))

import replica_mca2 as r                                     # noqa: E402
from API.mca import BANCO_PZ, BANCO_PZ_4, mca_banco_config   # noqa: E402
from API.multitrigger import pz_ganancia                     # noqa: E402

FS = 125e6
REP = 40                      # períodos repetidos; los dos primeros son de arranque


def desarmado(y, thr, hyst):
    """1 en los ciclos con el Schmitt arriba, como `st` de mt_pz_trig.sv."""
    st = np.zeros(y.size, bool)
    s = 0
    for i, v in enumerate(y):
        if v >= thr:
            s = 1
        elif v < thr - hyst:
            s = 0
        st[i] = s
    return st


def t_rearm_modelo(x, base, mq, thr, hyst, n_acc, banco):
    """(fracción de t_rearm sobre el tiempo vivo, disparos por período, desarmado por disparo)."""
    cf = r.cfg(n_acc=n_acc, baseline=base, fuente='pz', pz_mq=mq, pz_thr=thr, pz_hyst=hyst,
               **mca_banco_config(mq, formas=banco))
    xx = np.tile(x, REP)
    m = r.medir(xx, cf)
    y = r.trapecio(xx, cf['pz_k'], cf['pz_m'], cf['pz_mq'], cf['pz_sh'], lmax=r.PZ_LMAX)
    st = np.roll(desarmado(y, thr, hyst), r.LAT_PZ - 1)

    # la ocupación ciclo a ciclo, como en replica_mca2.medir()
    t = m['trig']
    fe = r._features(xx, t, cf)
    amp = r._amp_int(fe['q_tot'], cf['q_shift']) if cf['amp_src'] else fe['pico']
    ok = (amp >= int(cf['amp_min'])) & (amp <= int(cf['amp_max']))
    estado, _, _, _, libre, _ = r._ranuras(t, ok, max(int(cf['gate_long']), 1), n_acc)
    assert (estado == m['estado']).all()
    abre = np.flatnonzero(estado == r.ABRE)
    occ = np.zeros(xx.size + 2, np.int64)
    np.add.at(occ, np.minimum(t[abre] + 1, xx.size), 1)
    np.add.at(occ, np.minimum(libre[abre], xx.size), -1)
    n_ocup = np.cumsum(occ)[:xx.size]
    assert (np.bincount(n_ocup, minlength=r.N_ACC_RTL + 1)[:r.N_ACC_RTL + 1] == m['t_ocup']).all()

    n0 = 2 * len(x)
    disp = int((t >= n0).sum())
    return (float(np.mean(st[n0:] & (n_ocup[n0:] < n_acc))), disp / (REP - 2),
            st[n0:].sum() / max(disp, 1))


def main(base):
    d = json.load(open(base + '.json'))
    tr = np.load(base + '_trazas.npz')
    mq, n_acc = d['mq'], d['n_acc']
    banco = BANCO_PZ_4 if d['n_formas'] == 4 else BANCO_PZ
    g = pz_ganancia(mq=mq)
    thr, hyst = int(round(50 * g)), int(round(25 * g))
    print(f'{n_acc} ranuras, {len(banco)} formas, Schmitt {thr}/{thr - hyst} (en el trapecio k=2)')
    print(f"{'tasa':>6} {'sem':>3} {'arribos':>7} | {'t_rearm RTL':>11} {'modelo':>7} | "
          f"{'disparos/arribo RTL':>19} {'modelo':>7} | {'desarmado/disparo':>17}")
    peor = 0.0
    for f in d['filas']:
        x = tr[f't{int(f["tasa"])}_s{f["sem"]}']
        fm, disp_m, por_disp = t_rearm_modelo(x, f['base'], mq, thr, hyst, n_acc, banco)
        c = f['banco']['c']
        fr = c['t_rearm_s'] / (c['realtime_s'] - c['vetotime_s'])
        disp_r = c['cross'] / c['realtime_s'] * len(x) / FS
        n = len(f['pos'])
        peor = max(peor, abs(fr - fm))
        print(f"{f['tasa'] / 1e3:5.0f}k {f['sem']:3d} {n:7d} | {100 * fr:10.2f}% {100 * fm:6.2f}% | "
              f"{disp_r / n:19.3f} {disp_m / n:7.3f} | {por_disp:12.2f} ciclos")
    print(f'\nmayor diferencia de t_rearm: {100 * peor:.2f} pp')


if __name__ == '__main__':
    main(sys.argv[1])

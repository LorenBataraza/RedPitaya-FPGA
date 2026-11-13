#!/usr/bin/env python3
"""El tren de Poisson de la placa contra el golden model, sobre la señal capturada.

Lee lo que dejó software/API/tests/placa/test_banco_poisson.py. Cada período capturado va
a monte-carlo/replica_mca2.py, repetido, y se compara con lo que midió el RTL: disparos,
ranuras, la forma elegida y los buenos. "Bueno" es un F_TRAP a menos de ±2 % de alguna de
las tres líneas del tren, medidas a baja tasa. No es el criterio de pruebas_banco.py (error
< 1 % contra la señal SIN ruido), así que los números no se comparan directo.

    python3 banco_placa.py datos/banco_poisson
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
TOL = 0.02


def hist(d, n=8192):
    h = np.zeros(n, np.int64)
    h[np.array(d['i'], int)] = d['n']
    return h


def lineas(h, tol=0.03):
    """Las tres líneas de un histograma de baja tasa: los máximos, separados."""
    h = h.astype(float).copy()
    h[0] = 0
    out = []
    for _ in range(3):
        i = int(np.argmax(h))
        lo, hi = max(1, int(i * (1 - tol))), int(i * (1 + tol)) + 1
        c = np.arange(lo, hi)
        w = h[lo:hi]
        if w.sum():
            out.append(float((c * w).sum() / w.sum()))
        h[lo:hi] = 0
    return sorted(out, reverse=True)


def buenos(h, ls):
    return int(sum(h[int(q * (1 - TOL)):int(q * (1 + TOL)) + 2].sum() for q in ls))


def bitstream(d):
    """(n_acc, banco) del bitstream que midió. Las corridas de antes del recorte
    (2026-11-09) no lo guardaban: se deduce de cuántas formas informó la placa, porque
    sólo hubo dos bitstreams con el banco, 4 ranuras con 4 formas y 3 con 3."""
    n_formas = d.get('n_formas') or len(d['filas'][0]['ok']['formas'])
    n_acc = d.get('n_acc') or (4 if n_formas == 4 else 3)
    return n_acc, (BANCO_PZ_4 if n_formas == 4 else BANCO_PZ)


def modelo(x, base, mq, thr, hyst, n_acc, banco, rep=40):
    """El golden model sobre un período repetido; descarta dos de arranque."""
    cf = r.cfg(n_acc=n_acc, baseline=base, fuente='pz', pz_mq=mq, pz_thr=thr, pz_hyst=hyst,
               **mca_banco_config(mq, formas=banco))   # lo que corría la placa
    m = r.medir(np.tile(x, rep), cf)
    n0 = 2 * len(x)
    sel = m['eventos']['emite'] >= n0
    t = m['trig']
    return dict(feat=m['eventos']['feat'][sel], cross=int((t >= n0).sum()),
                open=int((m['estado'][t >= n0] == r.ABRE).sum()), t=(rep - 2) * len(x) / FS)


def main(base):
    d = json.load(open(base + '.json'))
    t = np.load(base + '_trazas.npz')
    mq = d['mq']
    n_acc, banco = bitstream(d)
    g = pz_ganancia(mq=mq)
    thr, hyst = int(round(50 * g)), int(round(25 * g))
    filas = d['filas']
    baja = [f for f in filas if f['tasa'] == min(q['tasa'] for q in filas)]
    ls = lineas(sum(hist(f['banco']['h']) for f in baja))
    print(f'M = {mq / 16:.2f}, subida sube_s = {d["sube"] * 1e9:g} ns, holdoff {d["dur"]}; '
          f'{n_acc} ranuras, {len(banco)} formas; líneas (canal) {[round(q, 1) for q in ls]}')
    print('\n   tasa  arribos   disp   abre | RTL: f0    f1    f2    f3  marc | modelo: f0    f1    f2    f3  marc'
          ' | buenos: banco modelo unico   hoy   (k/s)')
    for tasa in sorted({f['tasa'] for f in filas}):
        sum_ = dict(rt=0.0, cross=0.0, open=0.0, g=0.0, gm=0.0, gu=0.0, gh=0.0, ma=0.0)
        rtl, mod = np.zeros(5), np.zeros(5)
        fs = [q for q in filas if q['tasa'] == tasa]
        for f in fs:
            c = f['banco']['c']
            rt = c['realtime_s']
            sum_['rt'] += rt
            sum_['cross'] += c['cross']
            sum_['open'] += c['open']
            sum_['g'] += buenos(hist(f['banco']['h']), ls)
            sum_['gu'] += buenos(hist(f['unico']['h']), ls)
            sum_['gh'] += buenos(hist(f['hoy']['h']), ls)
            rtl += np.array(f['banco_forma']['cuentas'], float) / f['banco_forma']['c']['total'] * c['total']
            m = modelo(t[f't{int(tasa)}_s{f["sem"]}'], f['base'], mq, thr, hyst, n_acc, banco)
            esc = rt / m['t']
            for i, q in enumerate((0, 1, 2, 3, r.MARCADO)):
                mod[i] += (m['feat'][:, r.F_FORMA] == q).sum() * esc
            hm = np.bincount(np.minimum(m['feat'][:, r.F_TRAP] >> 3, 8191), minlength=8192)
            sum_['gm'] += buenos(hm, ls) * esc
        rt = sum_['rt']
        arr = np.mean([q['n'] for q in fs]) / d['T']
        print(f'{tasa / 1e3:6.0f}k {arr / 1e3:7.1f} {sum_["cross"] / rt / 1e3:6.1f} {sum_["open"] / rt / 1e3:6.1f} | ' +
              ' '.join(f'{q / rt / 1e3:5.1f}' for q in rtl) + ' | ' + ' '.join(f'{q / rt / 1e3:5.1f}' for q in mod) +
              f' | {sum_["g"] / rt / 1e3:6.1f} {sum_["gm"] / rt / 1e3:6.1f} {sum_["gu"] / rt / 1e3:5.1f} {sum_["gh"] / rt / 1e3:5.1f}')


if __name__ == '__main__':
    main(sys.argv[1])

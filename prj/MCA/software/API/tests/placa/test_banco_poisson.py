#!/usr/bin/env python3
"""(P,R) Un tren de Poisson por el banco de trapecios, con la API de alto nivel en C.

Corre en la Pitaya, con el Rigol en IN1. Es lo que test_mca2_placa.py no mira: la
regla del banco con arribos al azar, a tasas de hasta 1 Mcps. Sobre la misma señal mide:

  banco    disparo con polo-cero + las 4 formas (`multitrigger_armar_banco`)
  unico    disparo con polo-cero + un solo trapecio 64/48, sin regla
  hoy      disparo por pendiente + un solo trapecio 64/48, sin regla

El ciclo del generador dura un buffer del osciloscopio (8192 muestras, RSZ = 13), así
que la captura cruda es un período entero de la señal: en la PC se le pasa al golden
model y se compara con lo que midió el RTL
(docs/mca/figuras/trapecio/banco_placa.py, que además cuenta los buenos).

    python3 API/tests/placa/test_banco_poisson.py --mq 3800 --out datos/banco_poisson

`mq` es M*16. Ojo: el M que da la etapa trapecio de test_mca2_placa.py (el de un par a
1 us: 242.8) no es el mejor para colas acumuladas, porque la cola real no es una sola
exponencial. Con este generador conviene ~237.5 (3800); ver
docs/mca/pruebas_banco_trapecios.md §6.
"""
import argparse
import json
import os
import sys
import time

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_mca2_placa import (FS, M_OR_MASK, M_SHIELD, Mem, OSC_PHYS, Pendiente,     # noqa: E402
                             abrir_generador, pulso_preamp)
from API.mca import (mca_banco_config, mca_clear, mca_close, mca_configure,         # noqa: E402
                     mca_get_formas_ok, mca_get_n_formas_max, mca_get_umbr_ok, mca_open,
                     mca_read_counters, mca_read_histogram, mca_set_sel_1d,
                     mca_set_zoom_1d_z, mca_start, mca_stop)
from API.multitrigger import (MtRegion, multitrigger_armar_banco,                   # noqa: E402
                              multitrigger_armar_mca, multitrigger_desarmar_mca,
                              multitrigger_disparo_mca)
from API.osciloscope import osciloscope_close, osciloscope_open                     # noqa: E402
from campanas.estimulo import _aplicar                                              # noqa: E402

NPTS = 16384                      # puntos de la forma del generador: 4 ns cada uno
N_BUF = 8192                      # el anillo del osciloscopio en este bitstream
T = N_BUF / FS                    # un buffer: 65.536 us
VPP_POR_CUENTA = 1.0 / 7550.0     # medido: 1 Vpp de una forma en [-1, 1] da ~7550 cuentas
LINEAS = (1.0, 0.5, 0.15)         # tres amplitudes, para ver cada una en el espectro
UNICA = ((64, 48, 4, 69, 0, 0),)  # la forma 0, sin umbrales: el trapecio de antes
BIT_SW = 1


def tren(tasa, semilla, sube, tau=2e-6):
    """Arribos uniformes en el ciclo (Poisson condicionado a n), con la cola circular."""
    rng = np.random.default_rng(semilla)
    n = max(1, rng.poisson(tasa * T))
    pos = rng.uniform(0, T, n)
    amp = rng.choice(LINEAS, n)
    t = np.arange(NPTS) * T / NPTS
    u = np.zeros(NPTS)
    for p, a in zip(pos, amp):
        u += a * pulso_preamp(((t - p) % T) + 1e-15, tau_s=tau, sube_s=sube)
    return u, pos, amp


def capturar(mt, buf):
    """Un buffer entero con disparo por software, en cuentas y en orden de tiempo. La
    máscara va en la región propia: el slot 1 ya no tiene el espejo en 0x240."""
    o = mt.osc
    mt.mt.w32(M_OR_MASK, 0)
    mt.mt.w32(M_OR_MASK + 4, 0)
    mt.mt.w32(M_SHIELD, 0)
    o.w32(0x000, 0x0202)
    o.w32(0x094, 0x0101)
    o.w32(0x014, 1)
    o.w32(0x114, 1)
    o.w32(0x010, N_BUF // 2)
    o.w32(0x110, N_BUF // 2)
    mt.mt.w32(M_OR_MASK, BIT_SW)
    mt.mt.w32(M_OR_MASK + 4, BIT_SW)
    o.w32(0x000, 0x0101)
    time.sleep(0.01)
    o.w32(0x004, 0x0101)
    time.sleep(0.01)
    wp = o.r32(0x018)
    d = buf.words(0x10000, N_BUF).astype(np.int64) & 0x3FFF
    d = np.where(d >= 0x2000, d - 0x4000, d)
    d = np.roll(d, -((wp + 1) % N_BUF))
    mt.mt.w32(M_OR_MASK, 0)
    mt.mt.w32(M_OR_MASK + 4, 0)
    o.w32(0x000, 0x0202)
    o.w32(0x094, 0x0101)
    return d


def medir(h, seg):
    mca_stop(h)
    mca_clear(h)
    mca_start(h)
    time.sleep(seg)
    mca_stop(h)
    time.sleep(0.01)
    return mca_read_counters(h), np.asarray(mca_read_histogram(h)).copy()


def disperso(h):
    i = np.flatnonzero(h)
    return {'i': i.tolist(), 'n': h[i].astype(int).tolist()}


def limpio(c):
    return {k: (v if isinstance(v, (int, float, bool, list)) else str(v)) for k, v in c.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--tasas', type=float, nargs='+', default=[20e3, 300e3, 600e3, 1e6])
    ap.add_argument('--semillas', type=int, nargs='+', default=[0, 1, 2, 3, 4])
    ap.add_argument('--a-top', type=float, default=1500.0, help='cuentas de la línea más alta')
    ap.add_argument('--sube', type=float, default=5e-9, help='sube_s del pulso; 5 ns: 1.6 muestras')
    ap.add_argument('--mq', type=int, default=3800, help='M*16')
    ap.add_argument('--dur', type=int, default=0, help='holdoff del shield, en ciclos')
    ap.add_argument('--seg', type=float, default=1.0)
    ap.add_argument('--bl-auto', action='store_true', help='el seguidor de base, con holdoff de 1500')
    ap.add_argument('--gen-ch', type=int, default=1)
    ap.add_argument('--out', default='datos/banco_poisson')
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)

    gen = abrir_generador()
    h = mca_open()
    mtr = MtRegion.open()
    osc = osciloscope_open()
    pend = Pendiente(ch=0)
    buf = Mem(OSC_PHYS, 0x30000)
    print('impl', h._via, 'n_formas_max', mca_get_n_formas_max(h), flush=True)
    res, trazas = [], {}
    try:
        # la base, con el generador encendido y casi sin pulsos
        u, _, _ = tren(2e3, 0, args.sube)
        _aplicar(gen, args.gen_ch, 2 * u / u.max() - 1, 1.0 / T, 0.2, normalize=False)
        base = int(round(np.median(capturar(pend, buf))))
        print(f'base medida: {base}', flush=True)
        for tasa in args.tasas:
            for sem in args.semillas:
                u, pos, amp = tren(tasa, sem, args.sube)
                tope = u.max()
                vpp = min(tope * args.a_top * VPP_POR_CUENTA, 1.05)
                _aplicar(gen, args.gen_ch, 2 * u / tope - 1, 1.0 / T, vpp, normalize=False)
                time.sleep(0.2)
                fila = {'tasa': tasa, 'sem': sem, 'n': int(len(pos)), 'vpp': vpp, 'pos': pos.tolist(),
                        'amp': amp.tolist(), 'base': base}

                bl = dict(bl_auto=True, bl_holdoff=1500) if args.bl_auto else dict(baseline=base)
                multitrigger_armar_banco(h, osc, mtr, args.mq, ch=0, sel_1d='trapecio', **bl)
                if args.dur:
                    mtr.w32(M_SHIELD, (args.dur << 16) | (1 << 8) | 1)
                est = multitrigger_disparo_mca(mtr, 0)
                fila['ok'] = dict(formas=[bool(q) for q in mca_get_formas_ok(h)],
                                  umbr=bool(mca_get_umbr_ok(h)), fuente=est['fuente'])
                c, hi = medir(h, args.seg)
                fila['banco'] = dict(c=limpio(c), h=disperso(hi))
                mca_set_sel_1d(h, 'forma')
                mca_set_zoom_1d_z(h, 3)          # el bin es el valor; 0xFFFF satura arriba
                c, hf = medir(h, args.seg)
                fila['banco_forma'] = dict(c=limpio(c), cuentas=[int(hf[f]) for f in range(4)] + [int(hf[-1])])
                mca_set_zoom_1d_z(h, 0)

                kw = mca_banco_config(args.mq, formas=UNICA, gate_long=112)
                mca_configure(h, n_acc=4, sel_1d='trapecio', baseline=base, **kw)
                c, hi = medir(h, args.seg)
                fila['unico'] = dict(c=limpio(c), h=disperso(hi))

                multitrigger_desarmar_mca(osc, mtr, ch=0)
                multitrigger_armar_mca(osc, mtr, ch=0)
                c, hi = medir(h, args.seg)
                fila['hoy'] = dict(c=limpio(c), h=disperso(hi))
                multitrigger_desarmar_mca(osc, mtr, ch=0)

                trazas[f't{int(tasa)}_s{sem}'] = capturar(pend, buf)
                res.append(fila)
                b = fila['banco']['c']
                print(f'{tasa / 1e3:6.0f} k/{sem}: n={len(pos):3d} Vpp={vpp:.2f} cross={b["cross"]:8d} '
                      f'open={b["open"]:8d} total={b["total"]:8d} formas {fila["banco_forma"]["cuentas"]}',
                      flush=True)
                json.dump({'filas': res, 'T': T, 'mq': args.mq, 'lineas': LINEAS, 'a_top': args.a_top,
                           'sube': args.sube, 'dur': args.dur, 'bl_auto': args.bl_auto},
                          open(args.out + '.json', 'w'))
                np.savez(args.out + '_trazas.npz', **trazas)
    finally:
        try:
            mca_stop(h)
            multitrigger_desarmar_mca(osc, mtr, ch=0)
        finally:
            gen.output(args.gen_ch, False)
            gen.close()
            buf.close()
            pend.close()
            osciloscope_close(osc)
            mca_close(h)


if __name__ == '__main__':
    main()

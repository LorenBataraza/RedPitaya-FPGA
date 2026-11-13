#!/usr/bin/env python3
"""(P) La aplicación entera con el generador de pulsos por el lazo digital, sin el
Rigol. Corre EN LA PC, contra el `mca_server` de la placa.

    gen_pulsos --lazo digital--> IN1 --> MCA en la PL --> mca_server --TCP--> MCARemote

Hace lo que hace la GUI con la pestaña Generador (las mismas ops `gen.*`), y
compara lo que mide el MCA con lo que se le pidió al generador:

  - la tasa de entrada λ̂ del `status` contra la tasa del generador;
  - las dos líneas del espectro: dónde caen (la razón de sus amplitudes no depende
    de la ganancia de la calibración) y cuánto pesa cada una;
  - las identidades del teselado, con el MCA parado;
  - el modo con N pulsos, que para solo.

Con una ranura, a propósito: así hay pérdidas, y λ̂ tiene que corregirlas.

Siempre deja la placa como estaba: generador parado, lazo apagado y el disparo
desarmado, aunque algo falle.

    make app-servidor-remoto          # el servidor en el 1001 de la placa
    python3 app/tests/placa/e2e_lazo_app.py --host 10.73.28.30

Requiere el bitstream del MCA con el generador (cce7b66b o posterior).
"""

import argparse
import os
import sys
import time

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

from API.analisis import buscar_picos                               # noqa: E402
from API.mca import (AMP_W, mca_amplitud_de_canal, mca_get_config,   # noqa: E402
                     mca_read_counters, mca_read_histogram, mca_set_trap_mq,
                     mca_stop)
from API.mca_net import PORT_DEFAULT                                # noqa: E402
from API.mca_remote import MCARemote                                # noqa: E402

# El MCA como en la campaña validada (e2e_rigol_app.py), con UNA ranura.
CFG_MCA = dict(baseline=0, bl_auto=True, bl_k=12, bl_holdoff=64, gate_short=32,
               gate_long=384, n_acc=1, pre_dly=16, amp_src=0, q_shift=0, dec=1,
               channel=0)
DISPARO = dict(L=8, G=4, thr=600, hyst=300)
# Dos líneas, 60/40, con ruido de σ = 2.3 cuentas.
LINEAS = [[1500, 0.6], [4000, 0.4]]
GEN = dict(aleatorio=True, dt_min=3, n=0, tau_us=2.0, subida=0, base=0, ruido=1,
           ruido_sh=6, salidas=1)

_pass = _fail = 0


def check(nombre, cond, detalle=''):
    global _pass, _fail
    if cond:
        _pass += 1
    else:
        _fail += 1
    print(f"  [{'OK  ' if cond else 'FALLA'}] {nombre}"
          + (f'   {detalle}' if detalle else ''))
    return cond


def sesion(h, args):
    info = h.info
    print(f"  MCA {info.get('n_channels')} canales, {info.get('n_acc_max')} ranuras, "
          f"PL {info.get('fpga_state')}")
    if not check('el servidor encuentra el MCA y el generador',
                 bool(info.get('presente')) and bool(info.get('has_pulsos')),
                 f"has_pulsos={info.get('has_pulsos')}"):
        return

    print('\n=== 1. el generador ===')
    g = h.pedir('gen.configurar', cfg=dict(GEN, tasa=args.tasa, lineas=LINEAS))
    tasa_gen = g['tasa_hz']
    pesos = {a: p for a, p in g['lineas']}
    check('la configuración releída es la pedida',
          set(pesos) == {1500, 4000} and g['config']['aleatorio'] == 1
          and g['config']['ruido_sh'] == 6,
          f"líneas {g['lineas']}, tasa {tasa_gen:.1f}/s, τ_d {g['tau_us']:.3f} µs, "
          f"Mq {g['mq']}")
    g = h.pedir('gen.lazo', on=True)
    check('el lazo quedó prendido', g['lazo'] is True)

    print('\n=== 2. el MCA ===')
    h.configure(**CFG_MCA)
    disparo = h.pedir('mca.disparo', ch=0, armar=True, **DISPARO)
    check('el disparo del MCA quedó armado', bool(disparo.get('armado')),
          f"{disparo.get('fuente')}, thr={DISPARO['thr']}")
    mca_set_trap_mq(h, int(g['mq']))
    check('la Mq del generador llegó al trapecio',
          mca_get_config(h)['trap_mq'] == g['mq'], f"trap_mq = {g['mq']}")

    print(f'\n=== 3. {args.segundos:g} s de tiempo vivo, con el generador andando ===')
    g = h.pedir('gen.ctrl', que='arrancar')
    check('el generador arrancó', g['estado']['generando'] is True)
    h.clear()
    h._pedir('ctrl.start', seconds=float(args.segundos), clear_first=False)
    inst = []
    t0 = time.time()
    while time.time() - t0 < args.segundos * 2 + 15:
        est = h.status()
        if est.get('tasa_entrada_inst_hz'):
            inst.append(est['tasa_entrada_inst_hz'])
        if not est['running']:
            break
        time.sleep(0.5)
    est = h.status()
    check('la exposición paró sola', not est['running'])
    check('el status trae el generador y el lazo',
          (est.get('gen') or {}).get('lazo') is True
          and (est.get('gen') or {}).get('generando') is True,
          f"gen_cnt {(est.get('gen') or {}).get('gen_cnt')}")

    c = mca_read_counters(h)
    lam = est['tasa_entrada_hz']
    salida = c['accepted'] / c['realtime_s']
    print(f"  real {c['realtime_s']:.3f} s = veto {c['vetotime_s']:.3f} + sin ranura "
          f"{c['t_win_s']:.3f} + publicador {c['t_div_s']:.3f} + re-armado "
          f"{c['t_rearm_s']:.3f} + vivo {c['livetime_s']:.3f}")
    print(f"  disparos {c['cross']} = abrieron {c['open']} + sin ranura "
          f"{c['lost_active']} + vetados {c['lost_veto']} + publicador "
          f"{c['cross'] - c['open'] - c['lost_active'] - c['lost_veto']}")
    suma = (c['vetotime_s'] + c['t_win_s'] + c['t_div_s'] + c['t_rearm_s']
            + c['livetime_s'])
    check('el teselado cierra (MCA parado)', abs(suma - c['realtime_s']) < 1e-6,
          f"{suma:.9f} vs {c['realtime_s']:.9f} s")
    check('sin veto', c['vetotime_s'] == 0 and c['lost_veto'] == 0)
    check('con una ranura se pierden pulsos', c['lost_active'] > 0,
          f"{c['lost_active']} sin ranura, muerto "
          f"{100 * c['deadtime_real_s'] / c['realtime_s']:.1f} %")
    err = lam / tasa_gen - 1
    check('λ̂ es la tasa del generador (±3 %)', abs(err) < 0.03,
          f"λ̂ {lam:.0f}/s contra {tasa_gen:.0f}/s ({100 * err:+.2f} %); "
          f"aceptados por segundo real {salida:.0f}/s "
          f"({100 * (salida / tasa_gen - 1):+.1f} %)")
    if len(inst) > 4:
        m, s = np.mean(inst[1:]), np.std(inst[1:])
        check('la tasa instantánea ronda la del generador',
              abs(m / tasa_gen - 1) < 0.05, f"{m:.0f} ± {s:.0f}/s en {len(inst)} lecturas")

    print('\n=== 4. el espectro ===')
    hist = mca_read_histogram(h)
    check('el espectro coincide con los aceptados', int(hist.sum()) == c['accepted'],
          f"{int(hist.sum())} cuentas")
    picos = sorted(buscar_picos(hist), key=lambda p: -p['area'])[:2]
    picos.sort(key=lambda p: p['canal'])
    if check('hay dos líneas', len(picos) == 2,
             ', '.join(f"canal {p['canal']:.1f} (FWHM {p['fwhm']:.2f}, área "
                       f"{p['area']:.0f})" for p in picos)):
        a = [mca_amplitud_de_canal(p['canal'], h.h_aw) / (1 << (AMP_W - 14))
             for p in picos]
        razon = a[1] / a[0]
        check('la razón de las amplitudes es 4000/1500 (±2 %)',
              abs(razon / (4000 / 1500) - 1) < 0.02,
              f"{a[0]:.1f} y {a[1]:.1f} cuentas: {razon:.4f} contra {4000 / 1500:.4f}")
        check('cada línea cae cerca de su amplitud (±10 %, la calibración)',
              abs(a[0] / 1500 - 1) < 0.1 and abs(a[1] / 4000 - 1) < 0.1,
              f"ganancia {a[0] / 1500:.4f} y {a[1] / 4000:.4f}")
        r_area = picos[0]['area'] / picos[1]['area']
        r_tabla = pesos[1500] / pesos[4000]
        check('las áreas guardan los pesos de la tabla (±5 %)',
              abs(r_area / r_tabla - 1) < 0.05,
              f"{r_area:.4f} contra {r_tabla:.4f}")
    np.savez_compressed(os.path.join(args.outdir, 'lazo_espectro.npz'), hist=hist,
                        **{k: v for k, v in c.items() if np.isscalar(v)})

    print('\n=== 5. N pulsos ===')
    h.pedir('gen.configurar', cfg=dict(GEN, tasa=args.tasa, n=5000, lineas=LINEAS))
    h.pedir('gen.ctrl', que='arrancar')
    t0 = time.time()
    g = h.pedir('gen.get')
    while not g['estado']['terminado'] and time.time() - t0 < 5:
        time.sleep(0.1)
        g = h.pedir('gen.get')
    check('para solo al llegar a N',
          g['estado']['terminado'] and g['estado']['gen_cnt'] == 5000,
          f"gen_cnt {g['estado']['gen_cnt']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--host', default='10.73.28.30')
    ap.add_argument('--port', type=int, default=PORT_DEFAULT)
    ap.add_argument('--tasa', type=float, default=20e3)
    ap.add_argument('--segundos', type=float, default=10.0)
    ap.add_argument('--outdir', default=os.path.join(_RAIZ, 'datos', 'e2e_lazo'))
    args = ap.parse_args(argv)
    os.makedirs(args.outdir, exist_ok=True)

    h = MCARemote.connect(args.host, args.port, timeout=30.0)
    try:
        sesion(h, args)
    finally:
        # La placa como estaba, pase lo que pase.
        for op, kw in (('gen.ctrl', {'que': 'parar'}), ('gen.lazo', {'on': False}),
                       ('mca.disparo', {'ch': 0, 'armar': False})):
            try:
                h.pedir(op, **kw)
            except Exception as e:                              # noqa: BLE001
                print(f'  (al limpiar, {op}: {type(e).__name__}: {e})')
        try:
            mca_stop(h)
            est = h.status()
            check('al final, el lazo apagado y el generador parado',
                  est['gen']['lazo'] is False and not est['gen']['generando'])
        finally:
            h.close()
    print(f'\n{_pass} OK, {_fail} FALLA')
    return 1 if _fail else 0


if __name__ == '__main__':
    raise SystemExit(main())

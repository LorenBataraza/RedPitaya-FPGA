#!/usr/bin/env python3
"""(P) La API por red (op `call`) contra el mca_server de la placa, desde la PC.

Sin generador: el disparo del MCA2 se arma sobre el ruido del ADC, con un
umbral de pendiente bajo, y se mide con 1 ranura y con todas (`n_acc_max`). Todo por
`MCARemote`, que es lo que usa la GUI:

    identify      el servidor habla el protocolo 2 y dice qué implementación corre
    mca.disparo   arma el disparo (op del servidor) y lo informa
    call          configure, start/stop/clear y las lecturas, enteras en la placa
    acquire       armado en el cliente (no viaja por `call`)

y comprueba que lo que vuelve cierre: el teselado de los relojes, la ocupación
(`t_ocup`), la atribución de los disparos y espectro == aceptados. Al final
desarma el disparo.

    make app-servidor-remoto                       # el servidor, en la placa
    python3 app/tests/placa/call_red.py 10.73.28.30 [--puerto 1001]
"""

import argparse
import os
import sys

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

import API.mca as A                                                # noqa: E402
from API.mca_net import PORT_DEFAULT                               # noqa: E402
from API.mca_remote import MCARemote                               # noqa: E402

_fallas = []


def check(nombre, ok, detalle=''):
    print(f'  [{"PASS" if ok else "FAIL"}] {nombre}' + (f'  {detalle}' if detalle else ''))
    if not ok:
        _fallas.append(nombre)


def cierra(c):
    rt = c['realtime_s']
    tes = abs(rt - (c['vetotime_s'] + c['t_win_s'] + c['t_div_s']
                    + c['t_rearm_s'] + c['livetime_s'])) < 1e-9
    ocu = abs(sum(c['t_ocup_s']) - (rt - c['vetotime_s'])) < 1e-9
    busy = c['cross'] - c['open'] - c['lost_active'] - c['lost_veto']
    return tes, ocu, busy


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('host')
    ap.add_argument('--puerto', type=int, default=PORT_DEFAULT)
    ap.add_argument('--thr', type=int, default=60,
                    help='umbral de la pendiente: 60 dispara sobre el ruido')
    args = ap.parse_args(argv)

    h = MCARemote.connect(args.host, args.puerto)
    info = h.info
    print(f"servidor: protocolo {info.get('protocol')}, impl {info.get('impl')}, "
          f"libmca {info.get('libmca_version')}, {info.get('n_acc_max')} ranuras")
    check('protocolo 2 (op call)', info.get('protocol') == 2)
    check('el servidor tiene el disparo', bool(info.get('has_disparo')))
    try:
        est = h.pedir('mca.disparo', ch=0, armar=True, L=8, G=4,
                      thr=args.thr, hyst=args.thr // 2)
        check('disparo armado, con we_keep', est['armado'] and est['we_keep'],
              str(est['pendiente']))
        # 1 ranura y todas las del bitstream (eran 4; desde el recorte del
        # 2026-11-09 son 3, y pedir más es ValueError)
        n_max = A.mca_get_n_acc_max(h)
        perdidas_1 = None
        for n in (1, n_max):
            A.mca_configure(h, n_acc=n)
            check(f'n_acc = {n} por call', A.mca_get_n_acc(h) == n)
            spec, m2d, c = A.mca_read_acquire(h, 1.0)
            tes, ocu, busy = cierra(c)
            print(f'    n_acc={n}: cross={c["cross"]} open={c["open"]} '
                  f'lost_active={c["lost_active"]} lost_busy={busy} '
                  f'hist={int(spec.sum())} t_ocup={[round(t, 4) for t in c["t_ocup_s"]]}')
            check(f'n_acc={n}: hubo disparos', c['cross'] > 0, str(c['cross']))
            check(f'n_acc={n}: espectro == aceptados',
                  int(spec.sum()) == c['accepted'])
            check(f'n_acc={n}: teselado y ocupación cierran', tes and ocu)
            check(f'n_acc={n}: la atribución cierra', busy >= 0)
            if n == 1:
                perdidas_1 = c['lost_active']
            else:
                # Erlang B: a la tasa del ruido (a ~ 0.1) con 3 ranuras se pierde
                # ~1e-4 de lo que llega, contra ~0.1 con una
                check(f'con {n} ranuras se pierde mucho menos por estar midiendo',
                      c['lost_active'] <= perdidas_1 / 10,
                      f"{c['lost_active']} contra {perdidas_1} con 1")
        try:
            A.mca_set_n_acc(h, 9)
            check('n_acc=9 rechazado en la placa', False)
        except ValueError as e:
            check('n_acc=9 rechazado en la placa, como ValueError', 'n_acc' in str(e))
    finally:
        est = h.pedir('mca.disparo', ch=0, armar=False)
        check('desarmado', not est['armado'])
        h.close()

    print(f'\nRESULTADO: {"PASS" if not _fallas else f"FAIL ({len(_fallas)})"}')
    return 1 if _fallas else 0


if __name__ == '__main__':
    sys.exit(main())

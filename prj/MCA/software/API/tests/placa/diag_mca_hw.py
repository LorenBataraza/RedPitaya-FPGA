#!/usr/bin/env python3
"""Diagnóstico incremental del MCA en hardware, un paso por invocación.

Existe porque el smoke test completo reinició la placa y hubo que aislar qué
operación lo dispara. Cada paso se corre por separado y se chequea
/proc/uptime entre uno y otro, así un reinicio queda atribuido sin ambigüedad.

    python3 diag_mca_hw.py <paso>

Pasos, del menos al más sospechoso:
    regs      lectura y escritura de registros sueltos (ya sabemos que anda)
    sweep     barrido de ~650 direcciones, incluidas no mapeadas
    bulk      lectura masiva del espectro con copia numpy   <-- principal sospechoso
    word      el mismo espectro pero palabra por palabra, de a 32 bits
    clear     barrido de borrado
    counters  relojes y contadores
"""

import os
import struct
import sys
import time

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mca_utils as mu


def uptime():
    with open('/proc/uptime') as f:
        return float(f.read().split()[0])


def main():
    paso = sys.argv[1] if len(sys.argv) > 1 else 'regs'
    print(f'>>> paso={paso}   uptime al empezar = {uptime():.1f} s')

    m = mu.MCA.open()
    print(f'    magic OK, H_AW={m.h_aw}')

    t0 = time.time()

    if paso == 'regs':
        for i in range(200):
            m.w32(mu.R_THR, 100 + (i & 0xFF))
            assert m.r32(mu.R_THR) & 0x3FFF == 100 + (i & 0xFF)
        print(f'    200 ciclos de escritura+lectura OK')

    elif paso == 'sweep':
        n = 0
        for off in range(0, 0x200, 4):
            m.r32(off); n += 1
        for off in range(mu.APERTURE_H, mu.APERTURE_H + 0x400, 4):
            m.r32(off); n += 1
        for off in range(mu.APERTURE_2D, mu.APERTURE_2D + 0x400, 4):
            m.r32(off); n += 1
        for off in (0x0FFFC, 0x1FFFC, 0x2FFFC, 0x00300, 0x00800, 0x0F000):
            m.r32(off); n += 1
        print(f'    {n} lecturas OK, {1e6*(time.time()-t0)/n:.1f} us cada una')

    elif paso == 'bulk':
        # PRINCIPAL SOSPECHOSO: np.frombuffer(...).copy() sobre /dev/mem hace un
        # memcpy que puede emitir accesos de 64 bits o en rafaga, y
        # axi4_slave.sv:101-102 RECHAZA toda rafaga y todo tamano != 2 o 4 bytes.
        print('    llamando a spectrum() (copia numpy de 16384 palabras)...')
        s = m.spectrum()
        print(f'    OK, {s.size} bins, suma={int(s.sum())}')

    elif paso == 'word':
        # El mismo dato pero forzando accesos de 32 bits de a uno.
        acc = 0
        for i in range(1 << m.h_aw):
            acc += m.r32(mu.APERTURE_H + 4 * i)
        print(f'    16384 lecturas de 32 b OK, suma={acc}, '
              f'{1e6*(time.time()-t0)/16384:.1f} us cada una')

    elif paso == 'clear':
        m.stop()
        print('    disparando el barrido de borrado...')
        m.clear()
        print('    borrado completo')

    elif paso == 'counters':
        m.stop(); m.start(); time.sleep(0.3)
        c = m.counters()
        m.stop()
        print(f"    realtime={c['realtime_s']:.4f} livetime={c['livetime_s']:.4f} "
              f"deadtime={c['deadtime_s']:.4f}")

    else:
        print(f'    paso desconocido: {paso}')
        m.close()
        return 2

    m.close()
    print(f'<<< paso={paso} TERMINO OK en {time.time()-t0:.2f} s   '
          f'uptime al terminar = {uptime():.1f} s')
    return 0


if __name__ == '__main__':
    sys.exit(main())

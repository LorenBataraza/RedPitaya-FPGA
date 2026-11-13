#!/usr/bin/env python3
"""Genera `calib_rp.npy`: lo que da la calibración de librp para cada cuenta del ADC.

Es la referencia de `osciloscope_calibrar` (libmca/src/osciloscope_lote.c). Sale de
compilar UNA vez `cmn_CalibCntsSigned` tal como está en la versión de rp-api que corre
en la placa, y correrla sobre las 16384 cuentas de 14 bits con varias calibraciones.
El repo guarda la tabla, no rp-api: para regenerarla hace falta un checkout.

    python3 API/tests/datos_ref/generar_calib_rp.py \\
        --rp-api ~/Desktop/IB/Sexto_Semestre/Lab_Redes/TP_Final/RedPitaya --rev aff683518

`aff683518` es el ecosistema 2.00-35, el de la placa (`/opt/redpitaya/version.txt`).
Esa versión recorta a ±2^13; la de diciembre de 2025 (`convert.hpp`) ya no recorta.

La tabla es un arreglo estructurado: una fila por calibración, con `gain`, `base`,
`offset` y `m`, las 16384 salidas en el orden de la cuenta cruda (0 a 16383, o sea
con el bit 13 como signo). `calib_rp.json` dice de dónde salió.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
BITS = 14

# (gain, base, offset). Cubren la división por desplazamiento (base 2^15, la de la
# placa) y por división (base que no es potencia de 2), el redondeo de los negativos,
# el recorte en los dos extremos y la calibración nula de librp (1, 1, 0).
CALIBRACIONES = (
    (32768, 32768, 0),
    (33423, 32768, -64),       # +2 %, con el offset de -64 cuentas medido en la placa
    (32112, 32768, 37),
    (36000, 32768, 200),       # recorta arriba
    (29000, 32768, -300),
    (65536, 32768, 0),         # x2: recorta casi todo
    (32768, 32768, 8191),      # recorta abajo
    (1, 1, 0),
    (10234, 10000, 15),        # base que no es potencia de 2
    (7, 3, -5),
)

ARNES = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

%(funcion)s

int main(int argc, char **argv)
{
    uint32_t gain = (uint32_t)strtoul(argv[1], 0, 0);
    uint32_t base = (uint32_t)strtoul(argv[2], 0, 0);
    int32_t offset = (int32_t)strtol(argv[3], 0, 0);
    for (uint32_t c = 0; c < (1u << %(bits)d); c++) {
        int16_t m = (int16_t)cmn_CalibCntsSigned(c, %(bits)d, gain, base, offset);
        fwrite(&m, sizeof(m), 1, stdout);
    }
    return 0;
}
'''


def extraer_funcion(fuente):
    """El cuerpo de `cmn_CalibCntsSigned`, desde la firma hasta la llave que la cierra."""
    m = re.search(r'^int32_t cmn_CalibCntsSigned\(.*?^\}', fuente, re.S | re.M)
    if m is None:
        raise SystemExit('no encontré cmn_CalibCntsSigned en common.c')
    return m.group(0)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--rp-api', required=True, help='checkout del repo RedPitaya')
    p.add_argument('--rev', default='aff683518')
    p.add_argument('--archivo', default='rp-api/api/src/common.c')
    p.add_argument('--salida', default=os.path.join(AQUI, 'calib_rp.npy'))
    a = p.parse_args(argv)

    fuente = subprocess.run(['git', '-C', a.rp_api, 'show', f'{a.rev}:{a.archivo}'],
                            check=True, capture_output=True, text=True).stdout
    funcion = extraer_funcion(fuente)
    tipo = np.dtype([('gain', '<u4'), ('base', '<u4'), ('offset', '<i4'),
                     ('m', '<i2', (1 << BITS,))])
    tabla = np.zeros(len(CALIBRACIONES), dtype=tipo)
    with tempfile.TemporaryDirectory() as d:
        c, exe = os.path.join(d, 'arnes.c'), os.path.join(d, 'arnes')
        with open(c, 'w') as fh:
            fh.write(ARNES % dict(funcion=funcion, bits=BITS))
        subprocess.run(['gcc', '-O0', '-std=c11', '-o', exe, c], check=True)
        for i, (g, b, o) in enumerate(CALIBRACIONES):
            crudo = subprocess.run([exe, str(g), str(b), str(o)], check=True,
                                   capture_output=True).stdout
            tabla[i] = (g, b, o, np.frombuffer(crudo, dtype='<i2'))
    np.save(a.salida, tabla)
    with open(os.path.splitext(a.salida)[0] + '.json', 'w') as fh:
        json.dump(dict(rev=a.rev, archivo=a.archivo, bits=BITS,
                       funcion_sha256=hashlib.sha256(funcion.encode()).hexdigest(),
                       funcion=funcion.splitlines()), fh, indent=1, ensure_ascii=False)
    print(f'{a.salida}: {len(tabla)} calibraciones x {1 << BITS} cuentas')
    return 0


if __name__ == '__main__':
    sys.exit(main())

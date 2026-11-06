#!/usr/bin/env python3
"""Corre las reglas de N42.42 (`n42.sch`) sobre archivos `.n42`, con Saxon.

`lxml` no las corre: están en XSLT 2. No es parte de `make verificar`: se corre a mano
cuando cambia lo que escribe `API/n42.py`. Hace falta `saxonche`, y el esqueleto ISO:

    pip install saxonche
    for f in iso_dsdl_include iso_svrl_for_xslt2 iso_schematron_skeleton_for_saxon; do
      curl -LO https://raw.githubusercontent.com/Schematron/schematron/master/trunk/schematron/code/$f.xsl
    done
    python3 correr_schematron.py CARPETA_DE_LOS_XSL n42.sch ARCHIVO.n42 ...

Los patrones abstractos se expanden acá, y no con el `iso_abstract_expand.xsl` del
esqueleto, porque ése no sustituye los parámetros en `let/@value`, y `n42.sch` los usa
ahí: el validador que sale no compila.

Sale con 1 si alguna regla falla. Las reglas prohíben un `StartDateTime` en el futuro:
un archivo escrito con un reloj adelantado falla acá.
"""

import copy
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET

from saxonche import PySaxonProcessor

SCH = '{http://purl.oclc.org/dsdl/schematron}'
SVRL = '{http://purl.oclc.org/dsdl/svrl}'


def _sustituir(texto, params):
    if not texto:
        return texto
    for nombre, valor in params:
        texto = re.sub(r'\$' + re.escape(nombre) + r'(?![\w-])', lambda _: valor, texto)
    return texto


def expandir_abstractos(entrada, salida):
    ET.register_namespace('sch', SCH[1:-1])
    raiz = ET.parse(entrada).getroot()
    abstractos = {p.get('id'): p for p in raiz.findall(SCH + 'pattern')
                  if p.get('abstract') == 'true'}
    for i, patron in enumerate(list(raiz)):
        if patron.tag != SCH + 'pattern' or not patron.get('is-a'):
            continue
        params = sorted(((q.get('name'), q.get('value'))
                         for q in patron.findall(SCH + 'param')),
                        key=lambda p: -len(p[0]))
        nuevo = ET.Element(SCH + 'pattern', {'id': patron.get('id')})
        for hijo in abstractos[patron.get('is-a')]:
            if hijo.tag == SCH + 'title':
                continue
            copia = copy.deepcopy(hijo)
            for e in copia.iter():
                e.text = _sustituir(e.text, params)
                e.tail = _sustituir(e.tail, params)
                for clave in list(e.attrib):
                    e.set(clave, _sustituir(e.get(clave), params))
            nuevo.append(copia)
        raiz.remove(patron)
        raiz.insert(i, nuevo)
    for patron in abstractos.values():
        raiz.remove(patron)
    with open(salida, 'w', encoding='utf-8') as f:
        f.write(ET.tostring(raiz, encoding='unicode'))


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    xsl, sch, archivos = sys.argv[1], sys.argv[2], sys.argv[3:]
    fallas_totales = 0
    with PySaxonProcessor(license=False) as proc, \
            tempfile.TemporaryDirectory() as tmp:
        xp = proc.new_xslt30_processor()

        def paso(hoja, entrada, salida):
            ex = xp.compile_stylesheet(stylesheet_file=os.path.join(xsl, hoja))
            ex.transform_to_file(source_file=entrada, output_file=salida)

        incluido = os.path.join(tmp, 'incluido.sch')
        expandido = os.path.join(tmp, 'expandido.sch')
        validador = os.path.join(tmp, 'validador.xsl')
        paso('iso_dsdl_include.xsl', sch, incluido)
        expandir_abstractos(incluido, expandido)
        paso('iso_svrl_for_xslt2.xsl', expandido, validador)

        ex = xp.compile_stylesheet(stylesheet_file=validador)
        for archivo in archivos:
            reporte = ET.fromstring(ex.transform_to_string(source_file=archivo))
            fallas = [' '.join(''.join(f.itertext()).split())
                      for f in reporte.iter(SVRL + 'failed-assert')]
            fallas_totales += len(fallas)
            print(f'{os.path.basename(archivo)}: {len(fallas)} fallas')
            for texto in fallas:
                print('    -', texto)
    return 1 if fallas_totales else 0


if __name__ == '__main__':
    sys.exit(main())

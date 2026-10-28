#!/usr/bin/env python3
"""Paleta, rcParams y helpers de eje compartidos por las figuras de matplotlib.

Es la mitad reusable de `docs/mca/figuras/figuras_resolucion.py`, que era donde
vivia la paleta y de donde la importaban por nombre las demas figuras del MCA.
Importar aquel modulo para conseguir un color arrastraba `mca_utils` y la ruta
de los `.npz` de la campana, asi que una figura de otro modulo no podia usar la
paleta sin arrastrar los datos del MCA. Aca no hay nada de eso: sin argparse,
sin datos, sin efectos mas alla de fijar los rcParams al importar.

La regla que esta paleta sirve, y que es la razon de que este archivo exista:

    LOS GRAFICOS VAN SIN TEXTO ADENTRO.

Solo ejes, leyenda y las marcas imprescindibles. Todo lo que hay que decir va
en el epigrafe, que escribe el mismo script que dibuja, para que no puedan
desincronizarse. Cuando una figura necesita rotular muchas cosas, lo que lleva
adentro es un NUMERO y la explicacion va en una fila de tabla del documento
--el patron de `figuras_movimiento_de_datos.py`--, no un parrafo dibujado.

    import sys, os
    sys.path.insert(0, os.path.join(AQUI, '..', '..', 'figuras'))
    from estilo import SUP, TINTA, TINTA2, MUDO, AZUL, NARAN, ROJO, panel
"""

import textwrap

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# --- paleta (validada con scripts/validate_palette.js, modo claro) -----------
SUP    = '#fcfcfb'   # superficie
TINTA  = '#0b0b0b'   # tinta primaria
TINTA2 = '#52514e'   # tinta secundaria
MUDO   = '#898781'   # ejes y etiquetas
GRILLA = '#e1e0d9'
AZUL   = '#2a78d6'   # serie 1: lo medido
NARAN  = '#eb6834'   # serie 2: lo real/deformado en los esquemas
ROJO   = '#d03b3b'   # crítico: el desvío que se está señalando
RAMPA  = ['#86b6ef', '#5598e7', '#2a78d6', '#1c5cab', '#104281']  # ordinal

VERDE  = '#1f7a4d'   # aceptado / commit
MORADO = '#6b4fbb'   # el PS / el otro dominio

plt.rcParams.update({
    'figure.facecolor': SUP, 'axes.facecolor': SUP, 'savefig.facecolor': SUP,
    'font.size': 10, 'axes.titlesize': 10, 'axes.labelsize': 10,
    'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': TINTA2,
    'text.color': TINTA, 'xtick.color': MUDO, 'ytick.color': MUDO,
    'axes.grid': True, 'grid.color': GRILLA, 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'legend.frameon': False, 'figure.dpi': 140,
})

FWHM_K = 2.0 * np.sqrt(2.0 * np.log(2.0))          # sigma -> FWHM


def limpiar(ax):
    """Saca las dos lineas de recuadro que no dicen nada."""
    for lado in ('top', 'right'):
        ax.spines[lado].set_visible(False)


def panel(ax, letra):
    """La letra (a)/(b)/(c) arriba a la izquierda, como en la figura 7."""
    ax.set_title(letra, loc='left', fontweight='bold', color=TINTA2, pad=6)


# Los nombres con guion bajo son los que ya usaban las figuras del MCA; se
# mantienen para no tener que tocar cada llamada.
_limpiar = limpiar
_panel = panel


# =============================================================================
# Epigrafes
#
# Mismo formato que `docs/figuras/ondas.py:write_epigrafes` y que los seis
# `epigrafes.txt` que ya hay en el repo: cabecera, y por figura una regla de 79
# guiones, el nombre del archivo, otra regla y el texto a 78 columnas.
# =============================================================================

ANCHO = 78
REGLA = "-" * 79


def reflow(texto, ancho=ANCHO):
    """Rearma un parrafo a `ancho` columnas respetando los saltos dobles."""
    bloques = [b.strip() for b in texto.strip().split("\n\n")]
    salida = []
    for b in bloques:
        if b.startswith(("  ", "\t", "|")):       # tabla o bloque preformateado
            salida.append(b)
            continue
        salida.append(textwrap.fill(" ".join(b.split()), ancho))
    return "\n\n".join(salida)


def escribir_epigrafes(path, cabecera, items, pie=""):
    """Un epigrafe por figura, con la cabecera y el pie que da el script.

    `items` son dicts con `archivo` y `nota`. Se escribe con el mismo formato
    que el resto del repo para que los siete `epigrafes.txt` se lean igual.
    """
    partes = [reflow(cabecera), ""]
    for it in items:
        partes += [REGLA, it["archivo"], REGLA, reflow(it["nota"]), ""]
    if pie:
        partes += [REGLA, reflow(pie), ""]
    txt = "\n".join(partes).rstrip() + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(txt)
    return txt

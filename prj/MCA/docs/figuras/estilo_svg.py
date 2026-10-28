#!/usr/bin/env python3
"""Paleta y tipografia de las figuras SVG escritas a mano.

Es la contraparte sin dependencias de `estilo.py` (que es de matplotlib): la
importan los scripts que emiten el SVG como texto, para que se vean igual que
las figuras TikZ de la tesis (`docs/osc/figuras/*.tex`):

  * fondo blanco siempre, sin variante oscura;
  * trazos negros y rellenos pastel de PALETA, los mismos `\\definecolor`;
  * codigo en Latin Modern Mono y texto en Latin Modern Roman.

`modulos/mk/datasheet.py` tiene su propia copia de PALETA porque vive en otro
arbol y no puede importar de aca; si se cambia un color, se cambia en los dos.

    from estilo_svg import PALETA, tinte, FONT_MONO, FONT_SERIF
"""

# Los \definecolor de docs/osc/figuras/panorama_rp_scope_com.tex.
PALETA = {
    "azul":     (108, 172, 228),     # acondicionamiento
    "verde":    (110, 214, 142),     # captura / histogramas en BRAM
    "amarillo": (252, 232, 160),     # trigger
    "naranja":  (252, 206, 160),     # camino a DDR
    "grisr":    (226, 226, 226),     # compartido
    "rojo":     (240, 128, 128),     # bus del sistema
}

TINTA = "#000000"     # trazos y texto principal
TINTA2 = "#595959"    # texto secundario (black!65)
NOTA = "#4d4d4d"      # anotaciones (black!70)
MUDO = "#8c8c8c"      # separadores y guias
APAGADO = "#a6a6a6"   # lo que esta pero no se usa

# Comillas como entidad: las cadenas van dentro de atributos y de <style>.
FONT_MONO = ('&quot;Latin Modern Mono&quot;,&quot;CMU Typewriter Text&quot;,'
             'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace')
FONT_SERIF = ('&quot;Latin Modern Roman&quot;,&quot;CMU Serif&quot;,'
              '&quot;Computer Modern Serif&quot;,Georgia,serif')


def tinte(color, p=1.0):
    """`color!p` de xcolor: mezcla con blanco, p=1 es el color pleno."""
    return "#" + "".join(f"{round(p * c + (1 - p) * 255):02x}"
                         for c in PALETA[color])


def ancho_serif(s, size):
    """Ancho aproximado de `s` en Latin Modern Roman, en las unidades del SVG.

    El SVG no puede medir texto, asi que se estima por clase de caracter: con
    un factor unico por caracter, "el reloj" y "el PS" salen con la misma
    cuenta y anchos muy distintos.
    """
    em = 0.0
    for c in s:
        if c == " ":
            em += 0.33
        elif c.isupper():
            em += 0.68
        elif c.isdigit():
            em += 0.50
        elif c in "ilj.,:;'|!":
            em += 0.28
        elif c in "mw":
            em += 0.78
        else:
            em += 0.47
    return em * size

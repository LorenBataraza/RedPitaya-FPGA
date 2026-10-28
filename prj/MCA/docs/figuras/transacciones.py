#!/usr/bin/env python3
"""Figuras de TRANSACCIONES: que dato entra a un bloque y que dato sale.

Es la mitad reusable de `docs/mca/figuras/figuras_cadena_estatica.py`, la que
produce `07_cadena.png`: la unica figura del proyecto que muestra el
funcionamiento de un bloque a nivel de dato y no a nivel de ciclo ni de
estructura. Las tres preguntas que contesta, en tres paneles:

    (a)  que entra          la senal, la rafaga, el flujo de muestras
    (b)  que viaja          el bloque y el REGISTRO que sale por el cable
    (c)  que sale           el espectro, el lote, la ventana congelada

El panel (b) es el que hace a la figura una figura de transacciones: entre los
bloques no va una flecha pelada sino el tren de valores concretos que viajan.
Esos valores son los MISMOS del panel (a) --no son de adorno-- y por eso la
figura se puede leer como una cuenta: entro esto, salio aquello.

Que esto no es:

  - no es un cronograma. Lo de ciclo a ciclo esta en `ondas.py` (WaveDrom sobre
    un VCD). Aca un paso es una transaccion, no un ciclo de reloj.
  - no es un diagrama de bloques. La estructura esta en los `*_interfaz.svg`
    que genera `datasheet.py` y en las figuras de `TOP/figuras/`.

La regla de `estilo.py` vale igual: el grafico va sin texto adentro. Lo que
lleva son los numeros que viajan y los rotulos imprescindibles; la explicacion
va al epigrafe.
"""

import json
import os

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

from estilo import SUP, TINTA, TINTA2, MUDO, AZUL, NARAN, ROJO, limpiar, panel


# =============================================================================
# Panel (b) — bloques y el tren de registros en el cable
# =============================================================================

def caja(ax, x, w, nombre, sub, color, y=1.15, h=1.15):
    """La caja de un bloque: nombre en grande, subtitulo de dos lineas."""
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle='round,pad=0.06,rounding_size=0.12',
        fc=SUP, ec=color, lw=2.0))
    ax.text(x + w / 2, y + h * 0.635, nombre, ha='center', va='center',
            fontsize=12.5, fontweight='bold', color=color)
    if sub:
        ax.text(x + w / 2, y + h * 0.26, sub, ha='center', va='center',
                fontsize=9, color=TINTA2)


def ficha(ax, x, y, texto, color=NARAN, size=10.5):
    """Un valor que viaja por el cable, con su recuadro."""
    ax.text(x, y, texto, ha='center', va='center', fontsize=size,
            fontweight='bold', color=color,
            bbox=dict(fc=SUP, ec=color, lw=1.2, boxstyle='round,pad=0.26'))


def cable(ax, x0, x1, y, etiqueta=None, tren=(), color=MUDO,
          fichas=NARAN, maxtren=3, dy=0.23, pie=None, ypie=0.90,
          xs=None, xpuntos=None, xetq=None):
    """Un tramo de cable con su flecha y, si viaja algo, el tren de valores.

    Coordenadas ABSOLUTAS: es la primitiva. `panel_cadena` es la version que
    reparte el ancho sola; esta existe para las figuras que ya tienen su
    composicion a mano y no se quieren mover ni un pixel.
    """
    ax.add_patch(FancyArrowPatch((x0, y), (x1, y), arrowstyle='-|>',
                                 mutation_scale=13, lw=1.6, color=color,
                                 shrinkA=0, shrinkB=0))
    if etiqueta:
        ax.text((x0 + x1) / 2 if xetq is None else xetq, y + dy, etiqueta,
                ha='center', va='bottom', fontsize=9, color=TINTA2)
    if pie:
        ax.text((x0 + x1) / 2, ypie, pie, ha='center', fontsize=9,
                color=MUDO, style='italic')
    tren = list(tren)
    if not tren:
        return
    n = min(len(tren), maxtren)
    if xs is None:
        xs = np.linspace(x0, x1, n + 2)[1:-1] if n > 1 else [(x0 + x1) / 2]
    for v, xv in zip(tren[:n], xs):
        ficha(ax, xv, y, str(v), color=fichas)
    if len(tren) > n:
        ax.text(x1 + 0.43 if xpuntos is None else xpuntos, y, '…',
                ha='center', va='center', fontsize=13, color=MUDO)


def panel_cadena(ax, piezas, ancho=10.0, y=1.15, h=1.15, maxtren=3):
    """Bloques y cables alternados, de izquierda a derecha.

    `piezas` es la lista de lo que hay en la fila, en orden. Cada una es un
    dict con `tipo`:

        {'tipo': 'caja',  'nombre':.., 'sub':.., 'color':.., 'w':..}
        {'tipo': 'cable', 'etiqueta':.., 'tren':[..], 'color':.., 'w':..,
         'pie':.., 'alto':..}

    `w` es el ancho RELATIVO: se normaliza para que la fila ocupe `ancho`. El
    `tren` son los valores concretos que viajan; si hay mas de `maxtren` se
    dibujan los primeros y un puntos suspensivos, igual que en la figura 7.
    """
    ax.set_xlim(0, ancho)
    ax.set_ylim(y - 0.62, y + h + 0.62)
    ax.axis('off')

    total = sum(p.get('w', 1.0) for p in piezas)
    k = ancho / total
    ymed = y + h / 2
    x = 0.0
    for p in piezas:
        w = p.get('w', 1.0) * k
        if p['tipo'] == 'caja':
            caja(ax, x, w, p['nombre'], p.get('sub', ''),
                 p.get('color', AZUL), y=y, h=h)
        else:
            col = p.get('color', MUDO)
            ax.add_patch(FancyArrowPatch(
                (x + 0.06 * w, ymed), (x + 0.94 * w, ymed),
                arrowstyle='-|>', mutation_scale=13, lw=1.6, color=col,
                shrinkA=0, shrinkB=0))
            # El rotulo va ARRIBA de la banda de las cajas, no a la altura
            # del cable: con tramos cortos, a la altura del cable se monta
            # sobre la caja de al lado.
            if p.get('etiqueta'):
                ax.text(x + w / 2, y + h + p.get('alto', 0.10), p['etiqueta'],
                        ha='center', va='bottom', fontsize=9, color=TINTA2)
            if p.get('pie'):
                ax.text(x + w / 2, y - 0.30, p['pie'], ha='center',
                        fontsize=9, color=MUDO, style='italic')
            tren = p.get('tren') or []
            if tren:
                n = min(len(tren), maxtren)
                xs = (np.linspace(x + 0.17 * w, x + 0.83 * w, n) if n > 1
                      else [x + w / 2])
                for v, xv in zip(tren[:n], xs):
                    ficha(ax, xv, ymed, str(v), color=p.get('fichas', NARAN))
                if len(tren) > n:
                    ax.text(x + 0.95 * w, ymed, '…', ha='center', va='center',
                            fontsize=13, color=MUDO)
        x += w


# =============================================================================
# Panel de tabla — los mismos datos, como los ve el bloque de abajo
# =============================================================================

def panel_tabla(ax, cols, filas, ancho=10.0, regla=True):
    """Tabla sin recuadros: solo la linea bajo el encabezado.

    `cols` son tuplas (x, titulo, ha). `filas` son listas de celdas, cada una
    un str o un dict {'t':.., 'color':.., 'bold':.., 'italic':..}.
    """
    ax.set_xlim(0, ancho)
    ax.set_ylim(0, 1)
    ax.axis('off')

    dy = 0.86 / (len(filas) + 1)
    y = 0.93
    for x, txt, ha in cols:
        ax.text(x, y, txt, ha=ha, va='center', fontsize=9, color=TINTA2,
                fontweight='bold')
    if regla:
        x0 = min(c[0] for c in cols) - 0.2
        x1 = max(c[0] for c in cols) + 0.1
        ax.plot([x0, x1], [y - dy * 0.5] * 2, lw=0.8, color=MUDO,
                clip_on=False)

    for i, fila in enumerate(filas, start=1):
        y = 0.93 - i * dy
        for (x, _, ha), celda in zip(cols, fila):
            c = celda if isinstance(celda, dict) else {'t': celda}
            ax.text(x, y, c['t'], ha=ha, va='center', fontsize=9.5,
                    color=c.get('color', TINTA),
                    fontweight='bold' if c.get('bold') else 'normal',
                    style='italic' if c.get('italic') else 'normal')


# =============================================================================
# Guardado y manifiesto
# =============================================================================

def guardar(fig, path, verbose=True):
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)
    if verbose:
        print("  " + os.path.basename(path))


def escribir_manifiesto(path, items):
    """`transacciones.json`: lo que lee `datasheet.py` para armar la seccion.

    Mismo contrato que `ondas.json`: una lista de dicts con `archivo`,
    `titulo`, `origen` y `nota`. Asi agregar o sacar una figura se refleja solo
    en el datasheet, sin nombrarla a mano en ningun `.md`.
    """
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def escribir_readme(path, titulo, intro, items, comando, extra=""):
    """El README del directorio de figuras, con la tabla del repo.

    Columnas figura/que muestra/datos, que es la convencion que ya usan
    `docs/mca/figuras/README.md` y `docs/TOP/figuras/README.md`.
    """
    L = [f"# {titulo}", "", intro.strip(), "", "```bash", comando.strip(),
         "```", "", "| Figura | Qué muestra | Datos |", "|---|---|---|"]
    for it in items:
        L.append(f"| [`{it['archivo']}`]({it['archivo']}) | "
                 f"{it['resumen']} | {it['datos']} |")
    L += ["", "Los epígrafes están en [`epigrafes.txt`](epigrafes.txt), que "
          "escribe el mismo script para que no puedan desincronizarse."]
    if extra:
        L += ["", extra.strip()]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L).rstrip() + "\n")

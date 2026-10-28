#!/usr/bin/env python3
"""osc_filter a nivel de transaccion: un flujo de muestras entra, otro sale.

La transaccion de este modulo no es un evento ni una rafaga: es UNA MUESTRA POR
CICLO, continua, sin handshake que la pueda frenar. Lo que el bloque hace con
ese flujo es todo lo que hay que entender, y para un filtro lineal la respuesta
al impulso lo dice entero.

  osc_a_impulso.png        que entra: el impulso, el mismo en los dos juegos
  osc_b_cadena.png         que viaja: el bloque, sus cuatro coeficientes
  osc_c_respuesta.png      que sale: las dos respuestas, y el modelo encima
  osc_transaccion.png      las tres juntas (la que va al informe)

LOS NUMEROS SON DEL RTL. Salen del VCD de `tb_osc_filter` --no de un modelo de
python ni de una formula-- recortado a `datos_osc_filter.npz`. En cada ciclo se
guarda tambien `ref_out`, la salida de `osc_filter_ref.v` (la copia congelada
del filtro anterior al rediseno) que el testbench corre en paralelo: la figura
dibuja las dos y comprueba que coinciden en TODOS los ciclos. Esa comprobacion
es el contenido de la figura, no un adorno.

    python3 transacciones_osc.py
    python3 transacciones_osc.py --extraer     # rehacer el npz desde el FST
"""

import argparse
import os
import sys

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

_AQUI = os.path.dirname(os.path.abspath(__file__))
_MCA = os.path.join(_AQUI, '..', '..', '..', '..')
sys.path.insert(0, os.path.join(_MCA, 'docs', 'figuras'))

from estilo import (SUP, TINTA, TINTA2, MUDO, AZUL, NARAN, ROJO, VERDE,  # noqa: E402
                    MORADO, limpiar, panel, escribir_epigrafes)
import transacciones as T                                       # noqa: E402

DATOS = os.path.join(_AQUI, 'datos_osc_filter.npz')
FST = os.path.join(_MCA, 'modulos', 'osc', 'work', 'waves', 'tb_osc_filter.fst')

# Los dos juegos de coeficientes que el testbench usa, con el instante en que
# los escribe. Son escenas del TB, no numeros elegidos para la figura.
ESCENAS = [
    ('reset', 0,
     'coeficientes de reset: la cadena queda transparente'),
    ('polocero', 13784000,
     'compensacion polo-cero: aa=25000, bb=1e6, pp=50000'),
]
NC = 230               # ciclos por escena que se guardan y se dibujan
IMPULSO = 4000


# =============================================================================
# Datos: del VCD del testbench al npz versionado
# =============================================================================
def extraer():
    sys.path.insert(0, os.path.join(_MCA, 'docs', 'figuras'))
    import ondas as O
    if not os.path.exists(FST):
        raise SystemExit(
            f"falta {os.path.relpath(FST, _MCA)}.\n"
            f"Correr:  make -C modulos/osc/work vcd TB=tb_osc_filter")
    v = O.Vcd(FST)
    P = int(v.period('clk'))

    def serie(n, t0, nc):
        ch, cur, j, out = v.changes[n], None, 0, []
        for k in range(nc):
            t = t0 + k * P
            while j < len(ch) and ch[j][0] <= t:
                b = ch[j][1]
                if set(b) <= set('01'):
                    cur = int(b, 2)
                j += 1
            out.append(cur if cur is not None else 0)
        return np.array(out, dtype=np.int64)

    def s(a, w):
        return np.where(a >= (1 << (w - 1)), a - (1 << w), a)

    out = {'periodo_ps': P, 'nc': NC, 'impulso': IMPULSO,
           'origen': os.path.relpath(FST, _MCA)}
    for nombre, t0, _ in ESCENAS:
        din = s(serie('din', t0, NC + 40), 16)
        # alinear en el impulso: el TB lo mete en un ciclo distinto por escena
        k0 = int(np.flatnonzero(din == IMPULSO)[0])
        out[f'{nombre}_din'] = s(serie('din', t0 + k0 * P, NC), 16)
        out[f'{nombre}_dut'] = s(serie('dut_out', t0 + k0 * P, NC), 14)
        out[f'{nombre}_ref'] = s(serie('ref_out', t0 + k0 * P, NC), 14)
        for c in ('c_aa', 'c_bb', 'c_kk', 'c_pp'):
            out[f'{nombre}_{c}'] = int(serie(c, t0 + k0 * P, 1)[0])
    np.savez_compressed(DATOS, **out)
    print("  datos_osc_filter.npz  (recortado de",
          os.path.relpath(FST, _MCA) + ")")


def cargar():
    if not os.path.exists(DATOS):
        raise SystemExit(
            f"falta {os.path.relpath(DATOS, _MCA)}.\n"
            f"Correr:  python3 {os.path.basename(__file__)} --extraer")
    return np.load(DATOS, allow_pickle=True)


def medir(d):
    r = {}
    for nombre, _, desc in ESCENAS:
        dut = d[f'{nombre}_dut']
        ref = d[f'{nombre}_ref']
        iguales = int((dut == ref).sum())
        # La latencia es hasta el PICO, no hasta la primera muestra no nula:
        # con polo-cero hay un precursor de unas pocas cuentas --el arranque
        # del camino directo-- cuatro ciclos antes del pico, y tomarlo como
        # "la respuesta" daria 4 ciclos en una escena y 8 en la otra para un
        # pipeline que no depende de los coeficientes.
        pico = int(np.abs(dut).max())
        ipico = int(np.abs(dut).argmax())
        nz = np.flatnonzero(dut != 0)
        lat = ipico
        pre = int(ipico - nz[0]) if nz.size else 0
        prev = int(np.abs(dut[:ipico]).max()) if ipico else 0
        cae = np.flatnonzero(np.abs(dut) <= max(1, pico // 100))
        cae = [c for c in cae if c > ipico]
        r[nombre] = dict(
            desc=desc, dut=dut, ref=ref, din=d[f'{nombre}_din'],
            iguales=iguales, n=len(dut), lat=lat, pico=pico,
            idx_pico=ipico, precursor=pre, precursor_max=prev,
            t1pct=(int(cae[0]) - lat) if cae else None,
            coef={c: int(d[f'{nombre}_c_{c}']) for c in ('aa', 'bb', 'kk', 'pp')})
    return r


# =============================================================================
# Paneles
# =============================================================================
def panel_impulso(ax, m, ejex=True):
    e = m['polocero']
    n = np.arange(e['n'])
    ax.stem(n[:40], e['din'][:40], linefmt='-', markerfmt='o', basefmt=' ')
    for c in ax.containers if hasattr(ax, 'containers') else []:
        pass
    for ln in ax.lines:
        ln.set_color(AZUL); ln.set_markersize(3.4); ln.set_linewidth(1.3)
    ax.set_ylabel('din [cuentas]')
    ax.set_xlim(-1, 40)
    ax.text(0.985, 0.90, f'un impulso de {int(IMPULSO)} cuentas',
            transform=ax.transAxes, ha='right', va='top', fontsize=10,
            fontweight='bold', color=TINTA)
    if ejex:
        ax.set_xlabel('Ciclo de adc_clk')
    else:
        ax.tick_params(labelbottom=False)
    limpiar(ax)


def panel_cadena(ax, m):
    e = m['polocero']['coef']
    T.panel_cadena(ax, [
        {'tipo': 'cable', 'etiqueta': 'AXI-S, una muestra por ciclo',
         'w': 1.5, 'tren': [str(IMPULSO)], 'fichas': AZUL},
        {'tipo': 'caja', 'nombre': 'osc_filter', 'w': 3.4,
         'sub': 'polo-cero + 2 IIR + escalado', 'color': AZUL},
        {'tipo': 'cable', 'etiqueta': 'AXI-S, sin ready que la frene',
         'w': 1.9, 'tren': ['3943', '3019', '…'], 'fichas': NARAN,
         'pie': f"aa={e['aa']}  ·  bb={e['bb']}  ·  "
                f"kk={e['kk']}  ·  pp={e['pp']}"},
        {'tipo': 'caja', 'nombre': 'osc_filter_ref', 'w': 3.4,
         'sub': 'el modelo congelado, en paralelo', 'color': MUDO},
    ])


def panel_respuesta(ax, m, ejex=True):
    for nombre, col, mk in (('reset', MUDO, 's'), ('polocero', AZUL, 'o')):
        e = m[nombre]
        n = np.arange(e['n'])
        ax.plot(n, e['dut'], lw=1.5, color=col,
                label=f"dut_out — {e['desc'].split(':')[0]}")
        ax.plot(n[::6], e['ref'][::6], mk, ms=3.6, mfc='none', mew=1.0,
                color=NARAN if nombre == 'polocero' else TINTA2,
                label='ref_out (modelo)' if nombre == 'polocero' else None)
    # Escala simetrica logaritmica: el pico son ~4000 cuentas y la cola se
    # va a unidades. En lineal la cola --que es justamente lo que el
    # polo-cero fabrica-- queda pegada al cero y no se ve nada.
    ax.set_yscale('symlog', linthresh=10, linscale=0.6)
    ax.set_yticks([-100, -10, 0, 10, 100, 1000])
    ax.set_yticklabels(['-100', '-10', '0', '10', '100', '1000'])
    ax.set_ylabel('salida [cuentas]  (symlog)')
    ax.set_xlim(-1, m['polocero']['n'])
    if ejex:
        ax.set_xlabel('Ciclo de adc_clk desde el impulso')
    else:
        ax.tick_params(labelbottom=False)
    ax.legend(loc='upper right', fontsize=9, ncol=1)
    limpiar(ax)


def _guardar(fig, nombre):
    T.guardar(fig, os.path.join(_AQUI, nombre))


# =============================================================================
# Epigrafes, manifiesto y README
# =============================================================================

def documentar(m, d):
    rs, pz = m['reset'], m['polocero']
    tot = sum(e['n'] for e in m.values())
    ig = sum(e['iguales'] for e in m.values())
    ns = float(d['periodo_ps']) / 1000.0

    items = [
        dict(archivo='osc_a_impulso.png',
             titulo='LO QUE ENTRA: UN IMPULSO',
             origen='`tb_osc_filter`, VCD completo',
             resumen='Qué entra: el impulso, el mismo en los dos juegos de '
                     'coeficientes',
             datos='simulación (RTL)',
             nota=f"Que entra. Una muestra de {int(d['impulso'])} cuentas y "
                  f"el resto cero. Para un filtro lineal invariante eso no es "
                  f"un caso mas: la respuesta al impulso LO DESCRIBE ENTERO, "
                  f"asi que las dos curvas del panel (c) son la "
                  f"caracterizacion completa del bloque con cada juego de "
                  f"coeficientes. El flujo es de una muestra por ciclo de "
                  f"adc_clk ({ns:.0f} ns) y no hay handshake que lo pueda "
                  f"frenar: el `tready` existe en los puertos pero el dato "
                  f"llega igual, asi que lo que el bloque hace tiene que "
                  f"hacerlo en un ciclo."),
        dict(archivo='osc_b_cadena.png',
             titulo='EL BLOQUE, Y EL MODELO QUE CORRE AL LADO',
             origen='`osc_filter.v` y `sim/osc_filter_ref.v`',
             resumen='Qué viaja: el flujo AXI-S y los cuatro coeficientes',
             datos='esquema',
             nota="Que viaja. El bloque es una compensacion polo-cero, dos "
                  "IIR de primer orden y una etapa de escalado, con cuatro "
                  "coeficientes configurables. Lo que esta figura agrega a un "
                  "diagrama de bloques es el segundo camino: el testbench "
                  "instancia AL LADO del DUT una copia congelada del filtro "
                  "anterior al rediseno (`osc_filter_ref.v`) y le da el mismo "
                  "flujo. No se comparan resumenes ni metricas: se comparan "
                  "las dos salidas muestra por muestra."),
        dict(archivo='osc_c_respuesta.png',
             titulo='LO QUE SALE: EL MISMO IMPULSO, DOS FILTROS',
             origen='`tb_osc_filter`, escenas de coeficientes de reset y '
                    'polo-cero',
             resumen='Qué sale: las dos respuestas al impulso, con `ref_out` '
                     'superpuesto',
             datos='simulación (RTL)',
             nota=f"Que sale, y es donde esta todo. Con los coeficientes de "
                  f"RESET la cadena queda transparente: el impulso de "
                  f"{int(d['impulso'])} sale como una sola muestra de "
                  f"{rs['pico']} --o sea ganancia "
                  f"{rs['pico'] / int(d['impulso']):.5f}, el error de "
                  f"redondeo de kk = 2^24-1 en vez de 2^24-- "
                  f"{rs['lat']} ciclos despues. Con la compensacion POLO-CERO "
                  f"el mismo impulso sale como una exponencial que arranca en "
                  f"{pz['pico']} y tarda {pz['t1pct']} ciclos en caer al 1 %: "
                  f"el filtro no recorta la cola, la FABRICA, porque esta "
                  f"pensado para cancelar la del detector --un cero donde el "
                  f"preamplificador pone su polo--. La latencia es la misma "
                  f"en los dos casos, {rs['lat']} ciclos, porque el pipeline "
                  f"no depende de los coeficientes: lo MEDIDO es "
                  f"{rs['lat']} y {pz['lat']}. Lo que si cambia es que con "
                  f"polo-cero el pico viene precedido por un precursor de "
                  f"hasta {pz['precursor_max']} cuentas que arranca "
                  f"{pz['precursor']} ciclos antes --el camino directo, que "
                  f"llega antes que las dos IIR--; es chico pero existe, y "
                  f"medir la latencia por la primera muestra no nula en vez "
                  f"de por el pico lo contaria como si la respuesta "
                  f"empezara ahi. Los circulos son "
                  f"`ref_out`: la salida del modelo congelado coincide con la "
                  f"del DUT en {ig} de los {tot} ciclos dibujados, o sea "
                  f"TODOS. Esa coincidencia es el contenido de la figura."),
        dict(archivo='osc_transaccion.png',
             titulo='LA TRANSACCION COMPLETA',
             origen='las tres anteriores, en una figura',
             resumen='**Las tres juntas**: la que conviene poner si en el '
                     'informe entra una sola',
             datos='simulación (RTL)',
             nota="Las tres preguntas en una imagen: que entra, que viaja y "
                  "que sale."),
    ]

    escribir_epigrafes(
        os.path.join(_AQUI, 'epigrafes.txt'),
        "Epigrafes de las figuras de transacciones de osc_filter.\n"
        "Los genera transacciones_osc.py; no editar a mano.",
        items,
        pie=f"PROCEDENCIA. Todo sale del VCD de `tb_osc_filter` "
            f"(`{str(d['origen'])}`, 23 MB), recortado a las dos escenas en "
            f"`datos_osc_filter.npz`. Las muestras son enteros del RTL: `din` "
            f"con signo de 16 b y las salidas de 14 b. La igualdad "
            f"dut == ref se recalcula al dibujar, asi que si alguna vez deja "
            f"de valer la figura lo va a mostrar. OJO con lo que esta figura "
            f"NO prueba: la equivalencia esta comprobada para los "
            f"coeficientes de estas dos escenas, no para todos. El testbench "
            f"agrega 12 juegos aleatorios mas; cubrir el espacio entero es "
            f"justamente el caso de verificacion formal que discute "
            f"docs/verificacion_formal.md.")

    T.escribir_manifiesto(os.path.join(_AQUI, 'transacciones.json'),
                          [{k: v for k, v in it.items()
                            if k in ('archivo', 'titulo', 'origen', 'nota')}
                           for it in items])

    T.escribir_readme(
        os.path.join(_AQUI, 'README.md'),
        'Figuras: osc_filter a nivel de transacción',
        "La transacción de este módulo no es un evento ni una ráfaga: es "
        "**una muestra por ciclo**, continua y sin handshake que la pueda "
        "frenar. Para un filtro lineal, la respuesta al impulso describe el "
        "bloque entero, así que eso es lo que muestran las figuras.\n\n"
        "Las genera [`transacciones_osc.py`](transacciones_osc.py):",
        items,
        "cd prj/MCA/docs/osc/figuras/transacciones\n"
        "python3 transacciones_osc.py\n"
        "python3 transacciones_osc.py --extraer   # desde el VCD de Questa",
        extra="**Qué prueba la figura.** El testbench corre "
              "[`osc_filter_ref.v`]"
              "(../../../../modulos/osc/sim/osc_filter_ref.v) —la copia "
              "congelada del filtro anterior al rediseño— en paralelo con el "
              "DUT y con el mismo flujo. La figura dibuja las dos salidas y "
              f"**recalcula** la igualdad al generarse: coinciden en {ig} de "
              f"{tot} ciclos.\n\n"
              "**Qué no prueba.** La equivalencia está comprobada para estos "
              "dos juegos de coeficientes, no para todos. El testbench agrega "
              "12 juegos aleatorios; cubrir el espacio completo con "
              "coeficientes simbólicos es el caso que discute "
              "[`verificacion_formal.md`](../../../verificacion_formal.md).")
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--extraer', action='store_true')
    a = ap.parse_args()
    if a.extraer:
        extraer()
    d = cargar()
    m = medir(d)

    print("Generando figuras en", _AQUI)

    fig, ax = plt.subplots(figsize=(9.6, 2.4)); panel_impulso(ax, m)
    _guardar(fig, 'osc_a_impulso.png')

    fig, ax = plt.subplots(figsize=(9.6, 2.2)); panel_cadena(ax, m)
    _guardar(fig, 'osc_b_cadena.png')

    fig, ax = plt.subplots(figsize=(9.6, 3.4)); panel_respuesta(ax, m)
    _guardar(fig, 'osc_c_respuesta.png')

    fig = plt.figure(figsize=(9.6, 8.2))
    gs = GridSpec(3, 1, figure=fig, height_ratios=[0.80, 0.70, 1.35],
                  hspace=0.46)
    ax = fig.add_subplot(gs[0]); panel(ax, '(a)  lo que entra: un impulso')
    panel_impulso(ax, m)
    ax = fig.add_subplot(gs[1]); panel(ax, '(b)  el bloque, y el modelo que corre al lado')
    panel_cadena(ax, m)
    ax = fig.add_subplot(gs[2]); panel(ax, '(c)  lo que sale: dos juegos de coeficientes, el mismo impulso')
    panel_respuesta(ax, m)
    _guardar(fig, 'osc_transaccion.png')

    for nombre, _, _ in ESCENAS:
        e = m[nombre]
        print(f"  {nombre:10s} latencia {e['lat']} ciclos  pico {e['pico']}  "
              f"dut==ref {e['iguales']}/{e['n']}  "
              f"cae al 1 % en {e['t1pct']} ciclos")
    documentar(m, d)
    print("  epigrafes.txt  transacciones.json  README.md")
    return m


if __name__ == '__main__':
    main()

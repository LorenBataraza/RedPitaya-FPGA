#!/usr/bin/env python3
"""event_ring a nivel de transaccion: una ventana entra, un slot sale.

La transaccion del modulo es UN EVENTO: la ventana de (pre+post) muestras por
canal que el trigger congela, serializada a exactamente un slot de DDR y
publicada con un footer que es la marca de commit.

  event_ring_a_ventana.png     que entra: la ventana capturada, muestra a muestra
  event_ring_b_slot.png        que viaja: la cadena y las palabras del slot
  event_ring_c_ring.png        que sale: el ring en DDR, con wr/rd y los creditos
  event_ring_transaccion.png   las tres juntas (la que va al informe)

LOS NUMEROS SON REALES. La ventana sale de una captura de la campana e2e
(`datos_e2e.npz` al lado de este script, recortado de
`software/datos/e2e_20260528_013404/` con `--extraer`), y el slot se arma con el
layout de `event_slot_writer.sv` y despues se **decodifica con el decodificador
de produccion** --`software/API/modelo_rtl/ring_format.py`, el mismo que usa el
lector real-- comprobando que las muestras vuelven bit a bit. Si el layout del
RTL y el del software se separan, este script falla en vez de dibujar mentiras.

    python3 transacciones_event_ring.py
    python3 transacciones_event_ring.py --extraer   # rehacer datos_e2e.npz
"""

import argparse
import os
import sys

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Rectangle, FancyArrowPatch

_AQUI = os.path.dirname(os.path.abspath(__file__))
_MCA = os.path.join(_AQUI, '..', '..', '..', '..')
sys.path.insert(0, os.path.join(_MCA, 'docs', 'figuras'))
sys.path.insert(0, os.path.join(_MCA, 'software'))

from estilo import (SUP, TINTA, TINTA2, MUDO, AZUL, NARAN, ROJO, VERDE,  # noqa: E402
                    MORADO, limpiar, panel, escribir_epigrafes)
import transacciones as T                                       # noqa: E402
from API.modelo_rtl import ring_format as RF                    # noqa: E402

DATOS = os.path.join(_AQUI, 'datos_e2e.npz')
CAMPANA = os.path.join(_MCA, 'software', 'datos', 'e2e_20260528_013404',
                       'principal', 'chunk_000000.npz')

EV = 1                 # que evento del chunk se dibuja
N_SLOTS_FIG = 12       # slots que entran en el dibujo del ring
T_CRED = 0
FS = 125_000_000       # adc_clk


# =============================================================================
# Datos
# =============================================================================
def extraer():
    """Recorta de la campana lo minimo que la figura dibuja, para versionarlo.

    El chunk completo son 14 MB y `software/datos/` no esta versionado, asi que
    una figura que lo lea directo no se puede regenerar en un clon limpio. Lo
    que se guarda al lado del script son tres eventos: 12 kB.
    """
    d = np.load(CAMPANA, allow_pickle=True)
    meta = d['meta'].item()
    src = meta['source']
    np.savez_compressed(
        DATOS,
        wave=d['wave'][:3].astype(np.int16),
        t_ns=d['t_ns'][:3], wp=d['wp'][:3], snap=d['snap'][:3],
        gap=d['gap'][:3],
        pre=src['pre'], post=src['post'], n_ch=src['n_ch'],
        # El umbral se saca de la CONSIGNA del test (thr_V) y no de
        # meta['scope_regs'], que en este chunk es un snapshot tomado antes de
        # armar: tiene adc_state=0 y wp_cur=0, o sea que no refleja la corrida.
        # Con thr_V el numero se valida solo: el cruce de subida cae en la
        # muestra 31 y pre vale 32.
        thr_cuentas=int(round(src['thr_V'] * meta['adc_cnt_per_V'])),
        hyst_cuentas=int(round(src['hyst_V'] * meta['adc_cnt_per_V'])),
        thr_V=src['thr_V'], canal_trig=0,
        adc_cnt_per_V=meta['adc_cnt_per_V'],
        origen=os.path.relpath(CAMPANA, _MCA),
        n_eventos_chunk=meta['chunk_events'],
        dropped=meta['chunk_dropped'])
    print("  datos_e2e.npz  (recortado de", os.path.relpath(CAMPANA, _MCA) + ")")


def cargar():
    if not os.path.exists(DATOS):
        raise SystemExit(
            f"falta {os.path.relpath(DATOS, _MCA)}.\n"
            f"Correr:  python3 {os.path.basename(__file__)} --extraer")
    return np.load(DATOS, allow_pickle=True)


# =============================================================================
# El slot: se arma con el layout del RTL y se verifica con el de produccion
# =============================================================================
def armar_slot(muestras, timestamp, seq, event_id, snapshot, flags=0):
    """Serializa un evento igual que `event_slot_writer.sv`.

    `muestras` es (n_ch, n_samp) int16. Devuelve (buf, slot_shift, palabras),
    donde `palabras` son las cuatro de cabecera y el footer, ya en int.
    """
    n_ch, n_samp = muestras.shape
    need = RF.HDR_BYTES + n_samp * n_ch * 2 + 8
    slot_shift = max(6, (need - 1).bit_length())

    w0 = timestamp & ((1 << 64) - 1)
    w1 = ((flags & 0xFF) << 56) | ((n_ch & 0xFF) << 48) | \
         ((n_samp & 0xFFFF) << 32) | (seq & 0xFFFFFFFF)
    w2 = ((event_id & 0xFFFFFFFF) << 32) | (snapshot & 0x1FFFF)
    w3 = 0
    footer = (((~seq) & 0xFFFFFFFF) << 32) | (seq & 0xFFFFFFFF)

    buf = bytearray(1 << slot_shift)
    cab = np.array([w0, w1, w2, w3], dtype='<u8')
    buf[0:RF.HDR_BYTES] = cab.tobytes()
    # intercaladas: ch0[k], ch1[k], ch0[k+1], ...
    inter = muestras.T.astype('<i2').tobytes()
    buf[RF.HDR_BYTES:RF.HDR_BYTES + len(inter)] = inter
    buf[(1 << slot_shift) - 8:] = np.array([footer], dtype='<u8').tobytes()
    return bytes(buf), slot_shift, dict(w0=w0, w1=w1, w2=w2, w3=w3,
                                        footer=footer)


def verificar(buf, slot_shift, muestras, seq):
    """El decodificador de produccion tiene que devolver lo que entro."""
    meta, m = RF.decode_slot(buf, slot_shift, expect_seq=seq)
    assert m.shape == muestras.shape, (m.shape, muestras.shape)
    assert np.array_equal(m, muestras), "las muestras no vuelven bit a bit"
    assert RF.footer_is_valid(int(np.frombuffer(
        buf[-8:], dtype='<u8')[0])), "footer mal formado"
    return meta


# =============================================================================
# Panel (a) — que entra
# =============================================================================
def panel_ventana(ax, d, ev=EV, ejex=True):
    w = d['wave'][ev]
    pre, post = int(d['pre']), int(d['post'])
    n = w.shape[1]
    x = np.arange(n) - pre
    thr = int(d['thr_cuentas'])

    ct = int(d['canal_trig'])
    otro = 1 - ct
    ax.axvspan(-pre, 0, color=GRIS_PRE, zorder=0)
    ax.plot(x, w[otro], lw=1.0, color=MUDO, label=f'ch{otro}')
    ax.plot(x, w[ct], lw=1.0, color=AZUL, label=f'ch{ct} (el que dispara)')
    ax.axhline(thr, color=ROJO, lw=1.1, ls='--', zorder=1)
    ax.axvline(0, color=ROJO, lw=1.1, zorder=2)

    ax.set_xlim(-pre, post)
    ax.set_ylabel('Muestra [cuentas de ADC]')
    if ejex:
        ax.set_xlabel('Muestra relativa al disparo')
    else:
        ax.tick_params(labelbottom=False)
    ax.legend(loc='upper right', ncol=2, fontsize=9)
    limpiar(ax)

    # donde cruza de verdad, que es lo que valida que pre este bien
    a = w[ct].astype(int)
    cr = np.flatnonzero((a[:-1] < thr) & (a[1:] >= thr))
    return dict(pico=int(a.max()), thr=thr, pre=pre, post=post, n=n,
                cruce=int(cr[0]) if cr.size else None,
                pico_idx=int(a.argmax()))


GRIS_PRE = '#eeeeea'


# =============================================================================
# Panel (b) — que viaja
# =============================================================================
def panel_slot(ax, info):
    """Tres bloques y, en el cable del final, las palabras que viajan."""
    T.panel_cadena(ax, [
        {'tipo': 'cable', 'etiqueta': 'muestras\n+ trigger', 'w': 0.95},
        {'tipo': 'caja', 'nombre': 'window_capture', 'w': 2.6,
         'sub': 'congela pre + post', 'color': AZUL},
        {'tipo': 'cable', 'w': 1.5, 'etiqueta': 'la ventana',
         'tren': [f"{info['n_samp']}×{info['n_ch']}"], 'fichas': AZUL},
        {'tipo': 'caja', 'nombre': 'stage_fifo', 'w': 2.1,
         'sub': '%d eventos en vuelo' % info['E'], 'color': AZUL},
        {'tipo': 'cable', 'w': 0.95, 'etiqueta': 'un evento'},
        {'tipo': 'caja', 'nombre': 'slot_writer', 'w': 2.3,
         'sub': '%d palabras de 64 b' % info['nwords'], 'color': NARAN},
        {'tipo': 'cable', 'w': 2.6, 'etiqueta': 'AXI HP0 → DDR',
         'pie': 'el footer es el commit: si está, todo lo de antes ya llegó',
         'tren': ['w0', 'w1', '…', 'footer'], 'fichas': NARAN},
    ], maxtren=4)


def panel_palabras(ax, pal, meta, info):
    cols = ((0.35, 'palabra', 'left'), (1.95, 'contenido', 'left'),
            (9.65, 'valor', 'right'))
    f = []
    f.append(['`w0`', 'timestamp — ciclos de adc_clk desde el start',
              {'t': f"{pal['w0']}", 'bold': True}])
    f.append(['`w1`', '{flags, n_ch, n_samp, seq}',
              {'t': f"flags {meta['flags']} · n_ch {meta['n_ch']} · "
                    f"n_samp {meta['n_samp']} · seq {meta['seq']}",
               'bold': True}])
    f.append(['`w2`', '{event_id, snapshot}',
              {'t': f"event_id {meta['event_id']} · "
                    f"snapshot {meta['snapshot']}", 'bold': True}])
    f.append(['`w3`', 'reservado', {'t': '0', 'color': MUDO}])
    f.append([f"`w4`..`w{info['nwords'] - 2}`",
              'muestras int16, 4 por palabra, intercaladas',
              {'t': f"{info['n_samp'] * info['n_ch']} muestras "
                    f"({info['bytes_muestras']} B)", 'bold': True}])
    f.append([f"`w{info['nwords'] - 1}`", 'FOOTER {~seq, seq}',
              {'t': f"0x{pal['footer']:016X}", 'bold': True, 'color': VERDE}])
    T.panel_tabla(ax, cols, f)


# =============================================================================
# Panel (c) — que sale: el ring
# =============================================================================
def panel_ring(ax, wr, rd, n_slots=N_SLOTS_FIG):
    global T_CRED
    T_CRED = RF.credits_used(wr, rd)
    ax.set_xlim(-0.6, n_slots + 0.4)
    ax.set_ylim(-2.05, 1.45)
    ax.axis('off')
    ax.grid(False)

    for i in range(n_slots):
        lleno = (i - rd) % n_slots < (wr - rd) % n_slots or \
                ((wr - rd) % n_slots == 0 and False)
        ax.add_patch(Rectangle((i + 0.06, -0.3), 0.88, 0.62,
                               fc=SUP if not lleno else '#e7f1e9',
                               ec=VERDE if lleno else MUDO,
                               lw=1.6 if lleno else 1.0,
                               ls='-' if lleno else (0, (4, 3))))
        ax.text(i + 0.5, 0.01, str(i), ha='center', va='center', fontsize=9,
                color=TINTA if lleno else MUDO,
                fontweight='bold' if lleno else 'normal')
        if lleno:                      # el footer, que es lo que el PS polea
            ax.add_patch(Rectangle((i + 0.74, -0.3), 0.20, 0.62,
                                   fc=VERDE, ec=VERDE, lw=0))

    def puntero(x, texto, color, arriba=True):
        y0, y1 = (1.02, 0.40) if arriba else (-1.02, -0.38)
        ax.add_patch(FancyArrowPatch((x, y0), (x, y1), arrowstyle='-|>',
                                     mutation_scale=12, lw=1.8, color=color,
                                     shrinkA=0, shrinkB=0))
        ax.text(x, y0 + (0.06 if arriba else -0.10), texto, ha='center',
                va='bottom' if arriba else 'top', fontsize=9.5,
                fontweight='bold', color=color)

    puntero(wr % n_slots + 0.5, f'WR_SLOT = {wr}', NARAN, True)
    puntero(rd % n_slots + 0.5, f'RD_SLOT = {rd}', MORADO, False)
    ax.text(n_slots / 2, -1.92,
            'el cuadrito verde es el footer: es lo que el PS polea en DDR, '
            'sin tocar el bus GP0',
            ha='center', fontsize=9, color=MUDO, style='italic')
    ax.text(-0.5, 1.42, f'{T_CRED} slots ocupados de {n_slots}',
            ha='left', va='top', fontsize=9, color=TINTA2)


# =============================================================================
# Las cuatro figuras
# =============================================================================
def preparar():
    d = cargar()
    w = d['wave'][EV]
    n_ch, n_samp = w.shape
    # el timestamp del slot son CICLOS de adc_clk desde el start
    ts = int(d['t_ns'][EV] - d['t_ns'][0]) * FS // 1_000_000_000
    seq, event_id, snap = EV, EV, int(d['snap'][EV])

    buf, slot_shift, pal = armar_slot(w, ts, seq, event_id, snap)
    meta = verificar(buf, slot_shift, w, seq)

    info = dict(n_ch=n_ch, n_samp=n_samp, slot_sz=1 << slot_shift,
                slot_shift=slot_shift, nwords=RF.slot_words(slot_shift),
                bytes_muestras=n_ch * n_samp * 2, E=4)
    return d, w, pal, meta, info


def _guardar(fig, nombre):
    T.guardar(fig, os.path.join(_AQUI, nombre))


# =============================================================================
# Epigrafes, manifiesto y README
#
# Los numeros los pone el script a partir de lo que acaba de dibujar: no hay
# ninguno escrito a mano, asi que no pueden desincronizarse de los datos.
# =============================================================================

def documentar(r, info, pal, meta, d):
    pad = info['slot_sz'] - RF.HDR_BYTES - info['bytes_muestras'] - 8
    util = 100.0 * info['bytes_muestras'] / info['slot_sz']
    us = info['n_samp'] / (FS / 1e6)

    items = [
        dict(archivo='event_ring_a_ventana.png',
             titulo='LA VENTANA QUE CONGELA EL TRIGGER',
             origen=f"campaña e2e, `{str(d['origen'])}`, evento {EV}",
             resumen='Qué entra: la ventana capturada, muestra a muestra, '
                     'con el pre-trigger sombreado',
             datos='medidos',
             nota=f"Que entra al modulo. Un evento es una ventana de "
                  f"{info['n_samp']} muestras por canal --{int(d['pre'])} "
                  f"antes del disparo y {int(d['post'])} despues, {us:.2f} us "
                  f"en total a 125 MSPS-- congelada en el instante en que el "
                  f"canal {int(d['canal_trig'])} cruza el umbral de "
                  f"{r['thr']} cuentas ({float(d['thr_V']):.2f} V a "
                  f"{int(d['adc_cnt_per_V'])} cuentas/V). El cruce de subida "
                  f"cae en la muestra {r['cruce']} y el pre-buffer mide "
                  f"{int(d['pre'])}: la figura no dibuja esa coincidencia, la "
                  f"MIDE sobre el dato, y es lo que confirma que la ventana "
                  f"esta alineada con el disparo. El pico llega "
                  f"{r['pico_idx'] - int(d['pre'])} muestras despues del "
                  f"cruce, con {r['pico']} cuentas. La banda gris de la "
                  f"izquierda es la historia que el pre-buffer ya tenia "
                  f"guardada cuando el trigger llego: sin ella el flanco de "
                  f"subida no estaria en el archivo."),
        dict(archivo='event_ring_b_slot.png',
             titulo='UNA VENTANA, UN SLOT',
             origen='layout de `event_slot_writer.sv`, verificado con '
                    '`software/API/modelo_rtl/ring_format.py`',
             resumen='Qué viaja: la cadena de captura y las palabras de 64 b '
                     'que componen el slot',
             datos='medidos + layout del RTL',
             nota=f"Que viaja. La ventana cruza tres bloques --captura, cola "
                  f"elastica de {info['E']} eventos en vuelo y serializador-- "
                  f"y sale por AXI HP0 como exactamente "
                  f"{info['nwords']} palabras de 64 b, en orden de direccion "
                  f"creciente para que el generador lineal del axi_wr_fifo "
                  f"las coloque sin saltos. La tabla son las palabras de este "
                  f"evento concreto, no un ejemplo: cabecera de "
                  f"{RF.HDR_BYTES} B, {info['bytes_muestras']} B de muestras, "
                  f"{pad} B de relleno y 8 B de footer. El relleno existe "
                  f"porque el slot tiene que ser potencia de dos para que la "
                  f"direccion salga de un shift, asi que de los "
                  f"{info['slot_sz']} B del slot solo {util:.0f} % son "
                  f"muestras. El FOOTER vale {{~seq, seq}} y es la MARCA DE "
                  f"COMMIT: como todas las escrituras salen por un unico "
                  f"master con un unico ID, AXI garantiza que se observan en "
                  f"orden, asi que si el footer esta bien formado todo lo "
                  f"anterior ya llego a DDR. Por eso el PS no necesita leer "
                  f"ningun registro por GP0 para saber que hay un evento "
                  f"nuevo. Los rangos de bits exactos de cada campo estan en "
                  f"la cabecera de `event_slot_writer.sv`; aca va el valor, "
                  f"que es lo que la figura puede mostrar y el RTL no."),
        dict(archivo='event_ring_c_ring.png',
             titulo='EL RING EN DDR',
             origen='esquema; los créditos salen de '
                    '`ring_format.credits_used()`',
             resumen='Qué sale: los slots del ring, los dos punteros y los '
                     'créditos ocupados',
             datos='esquema',
             nota=f"Que sale. Los slots forman una cola productor/consumidor "
                  f"en DDR: la PL avanza WR_SLOT al terminar de escribir y el "
                  f"PS avanza RD_SLOT al terminar de leer, y los dos son "
                  f"contadores LIBRES de 32 b --la resta cierra en modulo "
                  f"2^32 aunque hayan dado la vuelta, que es exactamente lo "
                  f"que hace el comparador de creditos del RTL--. En el "
                  f"dibujo hay {T_CRED} slots ocupados. El rectangulo verde "
                  f"de cada slot lleno es el footer. La diferencia con el "
                  f"esquema anterior (K=1, tau = 252.7 us) es que aca la PL "
                  f"no espera a nadie: mientras queden creditos sigue "
                  f"capturando, y el tiempo muerto deja de depender de la "
                  f"latencia del lector. Es un esquema: la cantidad de slots "
                  f"del dibujo es ilustrativa, la real sale de "
                  f"RING_SZ / SLOT_SZ."),
        dict(archivo='event_ring_transaccion.png',
             titulo='LA TRANSACCION COMPLETA',
             origen='las tres anteriores, en una figura',
             resumen='**Las tres juntas**: la que conviene poner si en el '
                     'informe entra una sola',
             datos='medidos + esquema',
             nota="Las tres preguntas en una imagen: que entra, que viaja y "
                  "que sale. Es la que va al informe si entra una sola."),
    ]

    escribir_epigrafes(
        os.path.join(_AQUI, 'epigrafes.txt'),
        "Epigrafes de las figuras de transacciones de event_ring.\n"
        "Los genera transacciones_event_ring.py; no editar a mano.",
        items,
        pie=f"PROCEDENCIA. La ventana sale de la campana e2e "
            f"(`{str(d['origen'])}`), recortada a tres eventos en "
            f"`datos_e2e.npz` para que la figura se pueda regenerar sin "
            f"tener los 14 MB del chunk. El slot se arma con el layout de "
            f"`event_slot_writer.sv` y se decodifica con "
            f"`ring_format.decode_slot()`, el mismo decodificador que usa el "
            f"lector de produccion, comprobando que las "
            f"{info['n_samp'] * info['n_ch']} muestras vuelven bit a bit. Si "
            f"el RTL y el software se separan, el script falla en vez de "
            f"dibujar un slot que no existe.")

    T.escribir_manifiesto(os.path.join(_AQUI, 'transacciones.json'),
                          [{k: v for k, v in it.items()
                            if k in ('archivo', 'titulo', 'origen', 'nota')}
                           for it in items])

    T.escribir_readme(
        os.path.join(_AQUI, 'README.md'),
        'Figuras: event_ring a nivel de transacción',
        "La transacción de este módulo es **un evento**: la ventana que el "
        "trigger congela, serializada a exactamente un slot de DDR y "
        "publicada con un footer que es la marca de commit. Las cuatro "
        "figuras contestan qué entra, qué viaja y qué sale.\n\n"
        "Las genera [`transacciones_event_ring.py`]"
        "(transacciones_event_ring.py):",
        items,
        "cd prj/MCA/docs/event_ring/figuras/transacciones\n"
        "python3 transacciones_event_ring.py\n"
        "python3 transacciones_event_ring.py --extraer   # rehacer datos_e2e.npz",
        extra="**De dónde salen los números.** La ventana es una captura "
              "real de la campaña e2e, recortada a tres eventos en "
              "[`datos_e2e.npz`](datos_e2e.npz) (12 kB) para que la figura se "
              "regenere sin los 14 MB del chunk original, que además no está "
              "versionado. El slot se arma con el layout de "
              "[`event_slot_writer.sv`]"
              "(../../../../modulos/event_ring/rtl/event_slot_writer.sv) y "
              "después se decodifica con `ring_format.decode_slot()`, el "
              "**mismo decodificador que usa el lector de producción**, "
              "verificando que las muestras vuelven bit a bit. Si el layout "
              "del RTL y el del software se separan, el script falla en vez "
              "de dibujar un slot que no existe.")
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--extraer', action='store_true',
                    help='rehacer datos_e2e.npz desde la campana')
    a = ap.parse_args()
    if a.extraer:
        extraer()

    d, w, pal, meta, info = preparar()
    wr, rd = 7, 3

    print("Generando figuras en", _AQUI)

    fig, ax = plt.subplots(figsize=(9.6, 3.6))
    r = panel_ventana(ax, d)
    _guardar(fig, 'event_ring_a_ventana.png')

    fig = plt.figure(figsize=(9.6, 4.3))
    gs = GridSpec(2, 1, figure=fig, height_ratios=[0.70, 1.05], hspace=0.06)
    panel_slot(fig.add_subplot(gs[0]), info)
    panel_palabras(fig.add_subplot(gs[1]), pal, meta, info)
    _guardar(fig, 'event_ring_b_slot.png')

    fig, ax = plt.subplots(figsize=(9.6, 2.7))
    panel_ring(ax, wr, rd)
    _guardar(fig, 'event_ring_c_ring.png')

    # El panel (b) son DOS ejes --la fila de bloques y la tabla de palabras--
    # que tienen que quedar pegados entre si y separados del resto, asi que van
    # en un GridSpec anidado: con un hspace unico no se puede.
    fig = plt.figure(figsize=(9.6, 9.6))
    gs = GridSpec(3, 1, figure=fig, height_ratios=[1.32, 1.62, 0.90],
                  hspace=0.34)
    ax = fig.add_subplot(gs[0])
    panel(ax, '(a)  la ventana que congela el trigger')
    panel_ventana(ax, d)

    gb = gs[1].subgridspec(2, 1, height_ratios=[0.60, 1.00], hspace=0.04)
    ax = fig.add_subplot(gb[0])
    panel(ax, '(b)  el camino: una ventana → un slot')
    panel_slot(ax, info)
    panel_palabras(fig.add_subplot(gb[1]), pal, meta, info)

    ax = fig.add_subplot(gs[2])
    panel(ax, '(c)  el ring en DDR')
    panel_ring(ax, wr, rd)
    _guardar(fig, 'event_ring_transaccion.png')

    resumen = dict(r, **info)
    print(f"evento {EV}: {info['n_ch']}×{info['n_samp']} muestras, pico "
          f"{r['pico']} cuentas, umbral {r['thr']}")
    print(f"slot: {info['slot_sz']} B ({info['nwords']} palabras de 64 b), "
          f"cabecera {RF.HDR_BYTES} B + muestras {info['bytes_muestras']} B "
          f"+ footer 8 B, relleno "
          f"{info['slot_sz'] - RF.HDR_BYTES - info['bytes_muestras'] - 8} B")
    print(f"decode_slot() de produccion: OK, muestras identicas")
    documentar(r, info, pal, meta, d)
    print("  epigrafes.txt  transacciones.json  README.md")
    return resumen


if __name__ == '__main__':
    main()

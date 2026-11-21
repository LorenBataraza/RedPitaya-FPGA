#!/usr/bin/env python3
"""Diagramas de tiempo del modulo Multitrigger, con WaveDrom, desde simulacion.

Dos figuras salen del VCD de `tb_trigger_shield` y una del de
`tb_mt_trig_src`.

La secuencia de uso del multitrigger (el contrato PS <-> modulo) ya no es una
figura de ondas: es un diagrama de secuencia en docs/mt/figuras/secuencia/, y
va en la §1.3 del datasheet.

La ventana de cada figura se ubica por la CONFIGURACION que define la escena
--que combinacion de shield_src / shield_dst / shield_dur esta escrita-- y no
por un tiempo fijo, asi que las figuras siguen saliendo en su lugar si el
testbench agrega una escena antes.

La primera figura junta las TRES formas del veto en un solo dibujo, separadas
por el hueco de WaveDrom (`|`): son tres ventanas distintas del mismo
testbench y el hueco dice explicitamente que entre una y otra se salteo
tiempo. Pegarlas sin el hueco daria a entender que una sigue a la otra.

Salidas en <out_dir> (por defecto, el directorio de este script):

  mt_veto_tres_formas.json / .svg   nivel, nivel con cola y ventana por flanco
  mt_holdoff_rearm.json / .svg      el holdoff src->dst y el re-arm
  mt_trig_src_enganche.json / .svg  single-shot vs continuo
  ondas_mt.html           visor; no necesita nada instalado

Los FST que vienen al lado de este script son la salida de

  cd prj/MCA
  make -C modulos/mt/work vcd TB=tb_trigger_shield \\
      VCD_ADD="/tb_trigger_shield/*"
  vcd2fst modulos/mt/work/waves/tb_trigger_shield.vcd \\
      docs/mt/figuras/ondas/tb_trigger_shield.fst

y lo mismo con tb_mt_trig_src. Pesan 2-3 kB cada uno, asi que se
versionan y las figuras se regeneran en un clon limpio sin Questa.

Uso:
  python3 ondas_mt.py                # con los FST versionados
  python3 ondas_mt.py --render none   # solo WaveJSON + HTML
"""

import argparse
import sys
from html import escape
from pathlib import Path

AQUI = Path(__file__).parent                 # docs/mt/figuras/ondas/
sys.path.insert(0, str(AQUI.parents[2] / "figuras"))       # docs/figuras/

import ondas as O                                          # noqa: E402

MCA = AQUI.parents[3]                                      # prj/MCA/
SIM = MCA / "modulos" / "mt" / "sim"
TB_SHIELD = SIM / "tb_trigger_shield.sv"
TB_SRC = SIM / "tb_mt_trig_src.sv"

FST_SHIELD = "tb_trigger_shield.fst"
FST_SRC = "tb_mt_trig_src.fst"

# Los indices del testbench: N=4 canales de scope, y arriba las tres fuentes
# externas. DST_MCA es el bit de destino que convierte el escudo en veto.
N = 4
SRC_EXT_P, SRC_EXT_LVL, DST_MCA = N, N + 2, N

# Cada escena queda identificada por lo que se escribe en la configuracion.
# Se busca por VALOR, no por numero de escena.
ESC_NIVEL = {"shield_src": 1 << SRC_EXT_LVL, "shield_dst": 1 << DST_MCA,
             "shield_dur": 0}
ESC_COLA = {"shield_src": 1 << SRC_EXT_LVL, "shield_dst": 1 << DST_MCA,
            "shield_dur": 8}
ESC_VENTANA = {"shield_src": 1 << SRC_EXT_P, "shield_dst": 1 << DST_MCA,
               "shield_dur": 12}
ESC_HOLDOFF = {"shield_src": 0b0001, "shield_dst": 0b0010, "shield_dur": 5}


# ----------------------------------------------------------------------
# Ubicar la escena
# ----------------------------------------------------------------------

def escena_con(vcd, cfg, señal="trig_event"):
    """El instante en que arranca la escena cuya configuracion es `cfg`.

    Cada escena hace reset_dut y despues escribe su configuracion, asi que se
    busca el primer release de rstn tras el cual la configuracion coincide. Se
    mira unos ciclos despues del release porque el testbench escribe la
    configuracion en el negedge siguiente.
    """
    per = vcd.period("clk")
    for t in vcd.edges("rstn", lambda v: v == 1):
        for k in range(1, 5):                      # unos ciclos de margen
            tm = t + k * per
            if all(O._to_int(vcd.value_at(n, tm)) == v for n, v in cfg.items()):
                return t
    sys.exit(f"el VCD no tiene una escena con {cfg}: cambio tb_trigger_shield?")


def ventana_tras(vcd, t_escena, señal, antes, despues, pred=lambda v: v != 0):
    """Ventana alrededor del primer flanco de `señal` despues de la escena."""
    t = vcd.first_edge(señal, pred, t_escena)
    if t is None:
        sys.exit(f"no encontre el flanco de {señal} tras la escena")
    per = vcd.period("clk")
    return [int(t - antes * per), int(t + despues * per)], t


# ----------------------------------------------------------------------
# Figura 1: las tres formas del veto, en un dibujo con huecos
# ----------------------------------------------------------------------

VETOS = (
    ("nivel", ESC_NIVEL, 3, 28,
     "dur=0: el veto ES la linea"),
    ("cola", ESC_COLA, 3, 17,
     "dur=8: sigue 8 ciclos tras bajar"),
    ("ventana", ESC_VENTANA, 3, 17,
     "flanco + dur=12: ventana fija"),
)


def _clk_lbl(vcd):
    """La etiqueta del reloj, con la frecuencia MEDIDA del VCD.

    Escrita a mano decia 125 MHz y estos testbenches corren a 100 (`#5` con
    timescale 1ns). Un numero a mano en una figura generada es exactamente lo
    que este script esta para evitar.
    """
    return f"clk  {1e6 / vcd.period('clk'):.0f} MHz"


def fig_veto(vcd, step, hscale):
    """Las tres formas del veto al MCA, una al lado de la otra."""
    vcd.require("clk", "rstn", "trig_event", "mca_veto", "active", "cnt",
                "shield_dur", "trig_dis_clr")
    per = vcd.period("clk")
    grids, marcas, medidas = [], [], []
    for _nom, cfg, antes, despues in ((v[0], v[1], v[2], v[3]) for v in VETOS):
        t_esc = escena_con(vcd, cfg)
        (t0, t1), t_flanco = ventana_tras(vcd, t_esc, "trig_event",
                                          antes, despues)
        grids.append(O.build_grid(vcd, t0, t1, step, ref="clk"))
        marcas.append((t_flanco, t0, t1))
        # Lo que afirma la figura: cuantos ciclos dura el veto de verdad.
        sube = vcd.first_edge("mca_veto", lambda v: v == 1, t_flanco)
        baja = (vcd.first_edge("mca_veto", lambda v: v == 0, sube)
                if sube is not None else None)
        medidas.append(None if sube is None or baja is None
                       else int(round((baja - sube) / per)))

    n, offs = O.cols_multi(grids)
    col = lambda i, t: offs[i] + O.column_of(grids[i], t)

    nd_fl = O.nodes(n, {col(i, m[0]): c
                        for i, (m, c) in enumerate(zip(marcas, "ace"))})
    nd_vt = {}
    for i, (t_flanco, _t0, t1) in enumerate(marcas):
        sube = vcd.first_edge("mca_veto", lambda v: v == 1, t_flanco)
        baja = vcd.first_edge("mca_veto", lambda v: v == 0, sube) if sube else None
        if baja is not None and baja <= t1:
            nd_vt[col(i, baja)] = "bdf"[i]
    nd_vt = O.nodes(n, nd_vt)

    rm = lambda name, label, **k: O.row_multi(vcd, name, label, grids, **k)
    filas = [
        O.row_clk(_clk_lbl(vcd), n),
        rm("trig_event", "trig_event_i", fmt=O.hexf(2), ch=O.BUS_ADDR,
           node=nd_fl),
        rm("shield_dur", "shield_dur_i", fmt=O.decf()),
        {},
        rm("active", "active_o  (holdoff corriendo)"),
        rm("cnt", "cnt_o", fmt=O.decf()),
        rm("mca_veto", "mca_veto_o", node=nd_vt),
        rm("trig_dis_clr", "trig_dis_clr_o", fmt=O.hexf(1)),
    ]

    edge = []
    for i, m in enumerate(medidas):
        a, b = "ace"[i], "bdf"[i]
        if m is not None:
            edge.append(f"{a}<->{b} {m} ciclos")
    edge = O.filtrar_edges(edge, nd_fl, nd_vt)

    pie = (f"tb_trigger_shield - tres escenas, separadas por el hueco: "
           f"1 columna = 1 ciclo de clk ({per/1000.0:.0f} ns); entre tramos "
           f"se saltea tiempo")
    wj = {"signal": filas, "edge": edge,
          "head": {"text": "LAS TRES FORMAS DEL VETO AL MCA  -  "
                           "nivel / nivel con cola / ventana por flanco"},
          "foot": {"text": pie}, "config": {"hscale": hscale}}
    info = dict(columnas=n, senales=sum(1 for f in filas if f),
                medidas=medidas,
                tramos=[(m[1] / 1000.0, m[2] / 1000.0) for m in marcas])
    return wj, info


def detalle_veto(info):
    nom = [v[4] for v in VETOS]
    lin = []
    for (etq, m, (t0, t1)) in zip(nom, info["medidas"], info["tramos"]):
        dur = f"{m} ciclos de veto" if m is not None else "el veto no termina en la ventana"
        lin.append(f"  · {etq}: {dur}  (ventana {t0:.0f}-{t1:.0f} ns)")
    return ("\n".join(lin) + f"\n  · {info['senales']} señales, "
            f"{info['columnas']} columnas en tres tramos.")


# ----------------------------------------------------------------------
# Figura 2: el holdoff y el re-arm
# ----------------------------------------------------------------------

def fig_holdoff(vcd, step, hscale):
    """dur=5: active durante el holdoff y el clear en dst al expirar."""
    vcd.require("clk", "trig_event", "active", "cnt", "trig_dis_clr")
    per = vcd.period("clk")
    t_esc = escena_con(vcd, ESC_HOLDOFF)
    (t0, t1), t_fl = ventana_tras(vcd, t_esc, "trig_event", 3, 14)
    grid = O.build_grid(vcd, t0, t1, step, ref="clk")
    n = len(grid)
    col = lambda t: O.column_of(grid, t)

    t_act = vcd.first_edge("active", lambda v: v == 1, t_fl)
    t_fin = vcd.first_edge("active", lambda v: v == 0, t_act) if t_act else None
    t_clr = vcd.first_edge("trig_dis_clr", lambda v: v != 0, t_fl)

    nd_fl = O.nodes(n, {col(t_fl): "a"})
    nd_act = O.nodes(n, {col(t_fin): "b"}) if t_fin else None
    nd_clr = O.nodes(n, {col(t_clr): "c"}) if t_clr else None

    r = lambda name, label, **k: O.row(vcd, name, label, grid, **k)
    filas = [
        O.row_clk(_clk_lbl(vcd), n),
        r("trig_event", "trig_event_i  (src = ch0)", fmt=O.hexf(2),
          ch=O.BUS_ADDR, node=nd_fl),
        r("shield_dur", "shield_dur_i", fmt=O.decf()),
        {},
        r("active", "active_o", node=nd_act),
        r("cnt", "cnt_o  (cuenta el holdoff)", fmt=O.decf(), ch=O.BUS_DATA),
        r("trig_dis_clr", "trig_dis_clr_o  (dst = ch1)", fmt=O.hexf(1),
          ch=O.BUS_DATA, node=nd_clr),
    ]
    dur = O._to_int(vcd.value_at("shield_dur", t_fl))
    hold = int(round((t_fin - t_act) / per)) if t_act and t_fin else None
    edge = O.filtrar_edges(
        [f"a<->b {hold} ciclos" if hold else "a<->b", "b~>c re-arm"],
        nd_fl, nd_act, nd_clr)

    pie = (f"tb_trigger_shield - shield_dur={dur} - "
           f"1 columna = 1 ciclo de clk ({per/1000.0:.0f} ns)")
    wj = {"signal": filas, "edge": edge,
          "head": {"text": "HOLDOFF Y RE-ARM  -  el escudo cuenta y al "
                           "expirar limpia el canal de destino"},
          "foot": {"text": pie}, "config": {"hscale": hscale}}
    return wj, dict(columnas=n, senales=sum(1 for f in filas if f),
                    dur=dur, hold=hold, t0=t0 / 1000.0, t1=t1 / 1000.0)


# ----------------------------------------------------------------------
# Figura 3: el enganche de la fuente de trigger
# ----------------------------------------------------------------------

def fig_trig_src(vcd, step, hscale):
    """Single-shot: el flanco dispara, engancha el disable y limpia la mascara."""
    vcd.require("clk", "adc_trig", "trg_state", "adc_trg_dis")
    per = vcd.period("clk")
    # La escena 1 es la unica con we_keep=0 (single-shot) y mascara en ADC_P0.
    t_disp = vcd.first_edge("adc_trig", lambda v: v == 1, 0)
    if t_disp is None:
        sys.exit("el VCD no tiene ningun disparo de adc_trig")
    t0, t1 = t_disp - 5 * per, t_disp + 10 * per
    grid = O.build_grid(vcd, t0, t1, step, ref="clk")
    n = len(grid)
    col = lambda t: O.column_of(grid, t)

    t_dis = vcd.first_edge("adc_trg_dis", lambda v: v != 0, t_disp)
    t_limp = vcd.first_edge("trg_state", lambda v: v == 0, t_disp)

    nd_tr = O.nodes(n, {col(t_disp): "a"})
    nd_di = O.nodes(n, {col(t_dis): "b"}) if t_dis else None
    nd_ms = O.nodes(n, {col(t_limp): "c"}) if t_limp else None

    r = lambda name, label, **k: O.row(vcd, name, label, grid, **k)
    filas = [
        O.row_clk(_clk_lbl(vcd), n),
        r("trg_state", "trg_state  (mascara de fuentes)", fmt=O.hexf(4),
          ch=O.BUS_ADDR, node=nd_ms),
        {},
        r("adc_trig", "adc_trig  (disparo)", node=nd_tr),
        r("adc_trg_dis", "adc_trg_dis  (enganchado)", fmt=O.hexf(1),
          ch=O.BUS_DATA, node=nd_di),
    ]
    edge = O.filtrar_edges(["a~>b engancha el disable",
                            "a~>c single-shot: limpia la mascara"],
                           nd_tr, nd_di, nd_ms)
    pie = (f"tb_mt_trig_src, escena 1 (single-shot) - "
           f"1 columna = 1 ciclo de clk ({per/1000.0:.0f} ns)")
    wj = {"signal": filas, "edge": edge,
          "head": {"text": "DISPARO SINGLE-SHOT  -  el flanco dispara, "
                           "engancha el disable y la mascara se auto-limpia"},
          "foot": {"text": pie}, "config": {"hscale": hscale}}
    return wj, dict(columnas=n, senales=sum(1 for f in filas if f),
                    t0=t0 / 1000.0, t1=t1 / 1000.0,
                    lat_dis=int(round((t_dis - t_disp) / per)) if t_dis else None,
                    lat_msk=int(round((t_limp - t_disp) / per)) if t_limp else None)


# ----------------------------------------------------------------------

TITULOS = {
    "mt_veto_tres_formas":
        "LAS TRES FORMAS DEL VETO AL MCA  -  nivel / nivel con cola / "
        "ventana por flanco",
    "mt_holdoff_rearm":
        "HOLDOFF Y RE-ARM  -  el escudo cuenta y al expirar limpia el canal "
        "de destino",
    "mt_trig_src_enganche":
        "DISPARO SINGLE-SHOT  -  el flanco dispara, engancha el disable y la "
        "mascara se auto-limpia",
}

NOTAS = {
    "mt_veto_tres_formas":
        "El mismo bloque da tres vetos distintos segun como se lo configure, y "
        "la diferencia no esta en el RTL sino en que fuente se elige y que "
        "duracion se escribe. Con una fuente de NIVEL y dur=0 el veto es la "
        "linea con un ciclo de latencia: dura lo que dure la linea. Con la "
        "misma fuente y dur=8 el veto se extiende ocho ciclos despues de que "
        "la linea baje, que es lo que hace falta cuando el estimulo deja cola. "
        "Con una fuente de FLANCO y dur=12 el veto es una ventana fija de doce "
        "ciclos, sin importar cuanto dure el pulso. Los tres tramos vienen de "
        "escenas distintas del testbench y el hueco entre ellos dice que se "
        "salteo tiempo: no es una secuencia.",
    "mt_holdoff_rearm":
        "Lo que el escudo hace de verdad: cuando el canal fuente dispara, "
        "arranca un contador y mantiene `active` mientras cuenta; al expirar "
        "emite UN pulso de clear en el canal de destino, que es lo que lo "
        "vuelve a armar. Importa que el clear salga al EXPIRAR y no al "
        "disparar: si saliera al disparar, el canal de destino se re-armaria "
        "en medio del evento que el escudo esta tratando de protegerlo.",
    "mt_trig_src_enganche":
        "El flanco de la fuente habilitada dispara `adc_trig` y en el mismo "
        "movimiento engancha `adc_trg_dis`, que es lo que impide que el "
        "siguiente flanco vuelva a disparar. En modo single-shot la mascara se "
        "auto-limpia, asi que para volver a disparar hace falta reescribirla; "
        "en modo continuo la mascara persiste y basta con limpiar el disable. "
        "Esa es la unica diferencia entre los dos modos.",
}

CABECERA = """EPÍGRAFES DE LAS FIGURAS DE ONDAS DEL MODULO MULTITRIGGER
=========================================================

Las tres las escribe `ondas_mt.py` leyendo los VCD de
`tb_trigger_shield` y `tb_mt_trig_src`. Los números de abajo --cuántos
ciclos dura cada veto, cuánto cuenta el holdoff-- los mide el script sobre el
VCD, así que no pueden desincronizarse de los dibujos.

Reloj de la simulación: clk = {f_clk:.0f} MHz.

Escenas de tb_trigger_shield:

{esc_shield}

Escenas de tb_mt_trig_src:

{esc_src}"""

PIE = """Las ventanas se ubican por la CONFIGURACION que define cada escena --qué
combinación de shield_src / shield_dst / shield_dur está escrita-- y no por un
tiempo fijo: si el testbench agrega una escena antes, las figuras siguen
saliendo donde corresponde."""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    O.add_common_args(ap, AQUI)
    args = ap.parse_args()
    out_dir = Path(args.out)

    sh = O.Vcd(O.need_vcd(AQUI / FST_SHIELD,
                          "make -C modulos/mt/work vcd "
                          "TB=tb_trigger_shield VCD_ADD=\"/tb_trigger_shield/*\""
                          " && vcd2fst ..."))
    per = sh.period("clk")
    step = per if args.step == "auto" else O.parse_step(sh, args.step, ("clk",))
    fclk = 1e6 / per

    items, avisado = [], False

    wj, info = fig_veto(sh, step, args.hscale)
    avisado = O.emitir(out_dir, "mt_veto_tres_formas", wj, args.render, avisado,
                       info=f"{info['columnas']} columnas en 3 tramos, "
                            f"vetos de {info['medidas']} ciclos")
    items.append(dict(titulo=TITULOS["mt_veto_tres_formas"],
                      nota=NOTAS["mt_veto_tres_formas"], json=wj,
                      archivo="mt_veto_tres_formas.svg",
                      origen="`tb_trigger_shield`, escenas 4, 5 y 6",
                      detalle=detalle_veto(info)))

    wj, info = fig_holdoff(sh, step, args.hscale)
    avisado = O.emitir(out_dir, "mt_holdoff_rearm", wj, args.render, avisado,
                       info=f"{info['columnas']} columnas, holdoff "
                            f"{info['hold']} ciclos con dur={info['dur']}")
    items.append(dict(
        titulo=TITULOS["mt_holdoff_rearm"], nota=NOTAS["mt_holdoff_rearm"],
        json=wj, archivo="mt_holdoff_rearm.svg",
        origen="`tb_trigger_shield`, escena 2",
        detalle=f"  · shield_dur={info['dur']} -> `active` se mantiene "
                f"{info['hold']} ciclos.\n"
                f"  · {info['senales']} señales, {info['columnas']} columnas, "
                f"ventana {info['t0']:.0f} a {info['t1']:.0f} ns."))

    src = O.Vcd(O.need_vcd(AQUI / FST_SRC,
                           "make -C modulos/mt/work vcd "
                           "TB=tb_mt_trig_src && vcd2fst ..."))
    step_s = (src.period("clk") if args.step == "auto"
              else O.parse_step(src, args.step, ("clk",)))
    wj, info = fig_trig_src(src, step_s, args.hscale)
    avisado = O.emitir(out_dir, "mt_trig_src_enganche", wj, args.render,
                       avisado, info=f"{info['columnas']} columnas")
    items.append(dict(
        titulo=TITULOS["mt_trig_src_enganche"],
        nota=NOTAS["mt_trig_src_enganche"], json=wj,
        archivo="mt_trig_src_enganche.svg",
        origen="`tb_mt_trig_src`, escena 1",
        detalle=f"  · El disable se engancha {info['lat_dis']} ciclo(s) "
                f"después del disparo; la máscara se limpia a los "
                f"{info['lat_msk']}.\n"
                f"  · {info['senales']} señales, {info['columnas']} columnas, "
                f"ventana {info['t0']:.0f} a {info['t1']:.0f} ns."))

    html = out_dir / "ondas_mt.html"
    O.write_html(html, "Ondas del m&oacute;dulo Multitrigger",
                 escape("Generado por "
                        "docs/mt/figuras/ondas/ondas_mt.py "
                        "desde los VCD de tb_trigger_shield y "
                        "tb_mt_trig_src."),
                 items, titulo_tab="Ondas del modulo Multitrigger")
    print(f"escrito {html.name}  (abrilo en el browser: renderiza desde CDN)")

    fmt = lambda tb: "\n".join(f"  {e.num}) {e.titulo}"
                               for e in O.escenas(tb)) or "  (?)"
    O.write_epigrafes(out_dir / "epigrafes.txt",
                      CABECERA.format(f_clk=fclk, esc_shield=fmt(TB_SHIELD),
                                      esc_src=fmt(TB_SRC)),
                      items, PIE)
    print("escrito epigrafes.txt")
    O.write_manifiesto(out_dir / "ondas.json", items)
    return 0


if __name__ == "__main__":
    sys.exit(main())

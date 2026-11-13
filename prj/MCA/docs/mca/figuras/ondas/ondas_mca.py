#!/usr/bin/env python3
"""Diagramas de tiempo del modulo MCA, con WaveDrom, desde simulacion.

Las cuatro figuras salen de VCD de los testbenches del modulo:

  mca_pulso_vida       la vida de un pulso en mca_pulse_feature: cruce de
                       umbral, ventana abierta, carga acumulada, cierre y el
                       evento con su bus de features
  mca_apilamiento      el mismo bloque cuando la ventana llega a maxlen: el
                       pulso se cuenta pero NO se acepta
  mca_hist_rmw         mca_hist con incrementos al MISMO bin en ciclos
                       consecutivos: el puenteo de la escritura en vuelo
  mca_ack_borrado      mca_top: leer DURANTE el barrido de borrado y el ack
                       llega igual. Es lo que la cabecera del RTL marca como
                       lo mas importante del modulo

La secuencia de uso de mca_top (el contrato PS <-> modulo) ya no es una figura
de ondas: es un diagrama de secuencia en docs/mca/figuras/secuencia/, y va en
la §1.3 del datasheet.

La ventana de cada figura se ubica por CONDICIONES SOBRE LAS SENALES --el
cruce del umbral, el valor de cfg_maxlen que define la escena, la racha de
incrementos, la escritura de run|clear_all-- y nunca por un tiempo fijo.

Una columna es UN ciclo de reloj, no un semiciclo: hay un solo dominio y lo
que importa es la secuencia de muestras. (Las figuras del bus de sistema, en
docs/TOP/figuras/bus_sistema/, si usan semiciclos, porque ahi hay dos relojes
asincronicos y la fase importa.)

Los FST que vienen al lado de este script son la salida de

  cd prj/MCA
  for tb in tb_mca_pulse_feature tb_mca_hist tb_mca_top; do
    make -C modulos/mca/work vcd TB=$tb VCD_ADD="/$tb/*"
  done
  python3 docs/mca/figuras/ondas/ondas_mca.py --recortar

El `--recortar` acota cada VCD a la ventana que se dibuja. Sin eso el de
tb_mca_top son 2.3 MB (barre 2^13 bins) y el de tb_mca_pulse_feature 540 kB;
recortados quedan en pocos kB y se pueden versionar, asi que las figuras se
regeneran en un clon limpio sin Questa.

Uso:
  python3 ondas_mca.py                # con los FST versionados
  python3 ondas_mca.py --render none  # solo WaveJSON + HTML
"""

import argparse
import subprocess
import sys
from html import escape
from pathlib import Path

AQUI = Path(__file__).parent                      # docs/mca/figuras/ondas/
sys.path.insert(0, str(AQUI.parents[2] / "figuras"))          # docs/figuras/

import ondas as O                                             # noqa: E402

MCA = AQUI.parents[3]                                          # prj/MCA/
SIM = MCA / "modulos" / "mca" / "sim"
WAVES = MCA / "modulos" / "mca" / "work" / "waves"

TB_FEAT, TB_HIST, TB_TOP = "tb_mca_pulse_feature", "tb_mca_hist", "tb_mca_top"

# Config de la escena 1 de tb_mca_pulse_feature: pulso rectangular de 20
# muestras de 500 sobre base 0, con maxlen holgado. Se identifica por maxlen
# porque es lo que distingue la escena del pulso limpio de la del apilamiento.
MAXLEN_LIMPIO, MAXLEN_APILA = 1000, 10
ALTURA = 500


# ----------------------------------------------------------------------
# Localizadores de ventana
# ----------------------------------------------------------------------

def racha(vcd, name, pred, largo, after=0):
    """Inicio de la primera racha de `largo` ciclos consecutivos con pred.

    Para el forwarding de mca_hist: la escena que importa es la de cuatro
    incrementos seguidos al mismo bin, y se la encuentra por la racha y no por
    el numero de escena.
    """
    per = vcd.period("clk")
    ups = [t for t in vcd.edges("clk", lambda v: v == 1) if t >= after]
    corrida = 0
    for t in ups:
        iv = O._to_int(vcd.value_at(name, t))
        if iv is not None and pred(iv):
            corrida += 1
            if corrida == largo:
                return t - (largo - 1) * per
        else:
            corrida = 0
    return None


def escena_maxlen(vcd, maxlen):
    """El primer cruce de umbral con `cfg_maxlen` en ese valor.

    `cfg_maxlen` es lo que separa la escena del pulso limpio (1000) de la del
    apilamiento (10), y dentro de la escena el pulso arranca cuando `dat` sube
    por encima del umbral.
    """
    thr = O._to_int(vcd.value_at("cfg_thr", vcd.changes["clk"][-1][0])) or 100
    for t in vcd.edges("dat", lambda v: 0 < v <= 8191 and v > thr):
        if O._to_int(vcd.value_at("cfg_maxlen", t)) == maxlen:
            return t
    sys.exit(f"no encontre un pulso con cfg_maxlen={maxlen} en el VCD")


def escena_borrado(vcd):
    """La escritura de run|clear_all que arranca el barrido en tb_mca_top.

    La direccion del bus trae la base del slot (0x4070_0000), asi que se
    compara el OFFSET: el mapa del datasheet esta en offsets y el testbench
    escribe `bus_a_write(20'h0000C, ...)`.
    """
    for t in vcd.edges("a_wen", lambda v: v == 1):
        addr = O._to_int(vcd.value_at("a_addr", t))
        if (addr is not None and (addr & 0xFFFFF) == 0x0000C
                and O._to_int(vcd.value_at("a_wdata", t)) == 3):
            return t
    sys.exit("no encontre la escritura de run|clear_all (offset 0x0C <- 3) "
             "en el VCD")


# ----------------------------------------------------------------------
# Figura 1 y 2: la vida de un pulso, limpio y apilado
# ----------------------------------------------------------------------

SEN_FEAT = ("clk", "dat", "val", "cfg_thr", "cfg_maxlen", "busy", "ev_valid",
            "ev_amp", "last_qtot", "last_qtail", "c_total", "c_acc", "c_pileup")


def hitos_pulso(vcd, maxlen):
    """Los cuatro instantes de un pulso: cruce, apertura, cierre y evento.

    `t_ev` sale None cuando el pulso NO genera evento, que es justo el caso del
    apilamiento. Hay que acotar la busqueda a unos ciclos despues del cierre:
    sin eso, `first_edge(ev_valid)` se va a buscar el evento de la escena
    SIGUIENTE --175 ciclos mas adelante-- y la ventana de la figura se vuelve
    ilegible mostrando dos escenas pegadas.
    """
    per = vcd.period("clk")
    t_cruce = escena_maxlen(vcd, maxlen)
    t_abre = vcd.first_edge("busy", lambda v: v == 1, t_cruce)
    t_cierra = vcd.first_edge("busy", lambda v: v == 0, t_abre) if t_abre else None
    t_ev = vcd.first_edge("ev_valid", lambda v: v == 1, t_cruce)
    if t_ev is not None and t_cierra is not None and t_ev > t_cierra + 20 * per:
        t_ev = None                    # el evento es de otra escena
    return t_cruce, t_abre, t_cierra, t_ev


def fig_pulso(vcd, step, hscale, maxlen, titulo):
    """Un pulso de punta a punta: umbral, ventana, carga y resultado."""
    vcd.require(*SEN_FEAT)
    per = vcd.period("clk")
    t_cruce, t_abre, t_cierra, t_ev = hitos_pulso(vcd, maxlen)
    # El veredicto llega con el cierre: o sube c_acc o sube c_pileup.
    fin = t_ev or t_cierra or (t_cruce + 30 * per)
    t0, t1 = t_cruce - 4 * per, fin + 8 * per
    grid = O.build_grid(vcd, t0, t1, step, ref="clk")
    n = len(grid)
    col = lambda t: O.column_of(grid, t)

    nd_cr = O.nodes(n, {col(t_cruce): "a"})
    nd_bz = O.nodes(n, {**({col(t_abre): "b"} if t_abre else {}),
                        **({col(t_cierra): "c"} if t_cierra else {})})
    nd_ev = O.nodes(n, {col(t_ev): "d"}) if t_ev else None

    r = lambda name, label, **k: O.row(vcd, name, label, grid, **k)
    s14 = O.decf(signed_bits=14)
    filas = [
        O.row_clk(f"clk  {1e6/per:.0f} MHz", n),
        r("dat", "dat_i  (muestra)", fmt=s14, ch=O.BUS_DATA, node=nd_cr),
        r("val", "val_i"),
        r("cfg_thr", "cfg_thr_i  (umbral)", fmt=s14),
        r("cfg_maxlen", "cfg_maxlen_i", fmt=O.decf()),
        {},
        r("busy", "busy_o  (ventana abierta)", node=nd_bz),
        r("last_qtot", "q_tot  (carga total)", fmt=O.decf(), ch=O.BUS_ADDR),
        r("last_qtail", "q_tail  (carga de cola)", fmt=O.decf(), ch=O.BUS_ADDR),
        {},
        r("ev_valid", "ev_valid_o", node=nd_ev),
        r("ev_amp", "ev_amp_o", fmt=O.decf(), ch=O.BUS_DATA),
        r("c_total", "cnt_total_o", fmt=O.decf()),
        r("c_acc", "cnt_accepted_o", fmt=O.decf()),
        r("c_pileup", "cnt_pileup_o", fmt=O.decf()),
    ]

    largo = (int(round((t_cierra - t_abre) / per))
             if t_abre and t_cierra else None)
    edge = O.filtrar_edges(
        ["a~>b abre la ventana",
         f"b<->c {largo} ciclos" if largo else "b<->c",
         "c~>d"], nd_cr, nd_bz, nd_ev)

    thr = O._to_int(vcd.value_at("cfg_thr", t_cruce))
    pie = (f"{TB_FEAT} - thr={thr}, maxlen={maxlen} - "
           f"1 columna = 1 ciclo de clk ({per/1000.0:.0f} ns)")
    wj = {"signal": filas, "edge": edge, "head": {"text": titulo},
          "foot": {"text": pie}, "config": {"hscale": hscale}}

    leer = lambda name, t: O._to_int(vcd.value_at(name, t))
    info = dict(columnas=n, senales=sum(1 for f in filas if f),
                t0=t0 / 1000.0, t1=t1 / 1000.0, largo=largo, thr=thr,
                maxlen=maxlen,
                qtot=leer("last_qtot", t1), qtail=leer("last_qtail", t1),
                amp=leer("ev_amp", t1), total=leer("c_total", t1),
                acc=leer("c_acc", t1), pileup=leer("c_pileup", t1),
                hubo_ev=t_ev is not None)
    return wj, info


def ventana_pulso(vcd, maxlen):
    """La ventana que hay que recortar para la figura del pulso.

    Un poco mas ancha que la que dibuja fig_pulso(), para que el recorte no
    quede justo al borde de la grilla.
    """
    per = vcd.period("clk")
    t_cruce, _t_abre, t_cierra, t_ev = hitos_pulso(vcd, maxlen)
    fin = t_ev or t_cierra or (t_cruce + 30 * per)
    return t_cruce - 8 * per, fin + 14 * per


# ----------------------------------------------------------------------
# Figura 3: el read-modify-write de mca_hist
# ----------------------------------------------------------------------

def ventana_rmw(vcd):
    per = vcd.period("clk")
    t = racha(vcd, "inc", lambda v: v == 1, 4)
    if t is None:
        sys.exit("no encontre una racha de 4 incrementos seguidos en el VCD")
    return t - 4 * per, t + 16 * per


def fig_rmw(vcd, step, hscale):
    """Cuatro incrementos al mismo bin en ciclos consecutivos."""
    vcd.require("clk", "inc", "inc_addr", "rd", "rd_addr", "rd_data", "busy")
    per = vcd.period("clk")
    t0, t1 = ventana_rmw(vcd)
    t_ini = t0 + 4 * per
    grid = O.build_grid(vcd, t0, t1, step, ref="clk")
    n = len(grid)
    col = lambda t: O.column_of(grid, t)

    t_fin = vcd.first_edge("inc", lambda v: v == 0, t_ini)
    nd_in = O.nodes(n, {**{col(t_ini): "a"},
                        **({col(t_fin): "b"} if t_fin else {})})

    r = lambda name, label, **k: O.row(vcd, name, label, grid, **k)
    filas = [
        O.row_clk(f"clk  {1e6/per:.0f} MHz", n),
        r("inc", "inc_i", node=nd_in),
        r("inc_addr", "inc_addr_i  (el MISMO bin)", fmt=O.decf(),
          ch=O.BUS_ADDR),
        {},
        r("busy", "busy_o"),
        r("rd", "rd_i"),
        r("rd_addr", "rd_addr_i", fmt=O.decf(), ch=O.BUS_ADDR),
        r("rd_data", "rd_data_o  (la cuenta del bin)", fmt=O.decf(),
          ch=O.BUS_DATA),
    ]
    cuantos = int(round((t_fin - t_ini) / per)) if t_fin else None
    edge = O.filtrar_edges(
        [f"a<->b {cuantos} incrementos seguidos" if cuantos else "a<->b"],
        nd_in)
    addr = O._to_int(vcd.value_at("inc_addr", t_ini))
    pie = (f"{TB_HIST} - {cuantos} incrementos al bin {addr} en ciclos "
           f"consecutivos - 1 columna = 1 ciclo de clk "
           f"({per/1000.0:.0f} ns)")
    wj = {"signal": filas, "edge": edge,
          "head": {"text": "READ-MODIFY-WRITE AL MISMO BIN  -  la cuenta no "
                           "se pierde aunque los eventos lleguen pegados"},
          "foot": {"text": pie}, "config": {"hscale": hscale}}
    return wj, dict(columnas=n, senales=sum(1 for f in filas if f),
                    t0=t0 / 1000.0, t1=t1 / 1000.0, cuantos=cuantos, addr=addr)


# ----------------------------------------------------------------------
# Figura 4: el ack durante el barrido de borrado
# ----------------------------------------------------------------------

def ventana_borrado(vcd):
    per = vcd.period("clk")
    t_w = escena_borrado(vcd)
    # Hasta el final de la segunda lectura posterior, que es donde se ve que
    # el ack sigue llegando con el barrido en curso.
    t = t_w
    for _ in range(4):
        t = vcd.first_edge("a_ren", lambda v: v == 1, t + per) or t
    fin = vcd.first_edge("a_ack", lambda v: v == 0, t) or (t + 20 * per)
    return t_w - 4 * per, fin + 6 * per


def fig_borrado(vcd, step, hscale):
    """Leer mientras el barrido de borrado corre: el ack llega igual."""
    vcd.require("clk", "a_addr", "a_wdata", "a_wen", "a_ren", "a_rdata",
                "a_ack", "a_err")
    per = vcd.period("clk")
    t0, t1 = ventana_borrado(vcd)
    t_w = escena_borrado(vcd)
    grid = O.build_grid(vcd, t0, t1, step, ref="clk")
    n = len(grid)
    col = lambda t: O.column_of(grid, t)

    # Los acks que caen en la ventana, y la latencia de cada lectura.
    lats = []
    t = t_w
    marcas = {}
    letras = "acegi"
    for i in range(len(letras)):
        tr = vcd.first_edge("a_ren", lambda v: v == 1, t + per)
        if tr is None or tr > t1:
            break
        ta = vcd.first_edge("a_ack", lambda v: v == 1, tr)
        if ta is None or ta > t1:
            break
        marcas[col(tr)] = letras[i]
        marcas[col(ta)] = "bdfhj"[i]
        lats.append(int(round((ta - tr) / per)))
        t = ta
    nd_rd = O.nodes(n, marcas)

    r = lambda name, label, **k: O.row(vcd, name, label, grid, **k)
    h5 = O.hexf(5)
    filas = [
        O.row_clk(f"clk  {1e6/per:.0f} MHz", n),
        r("a_addr", "sys_addr", fmt=h5, ch=O.BUS_ADDR),
        r("a_wdata", "sys_wdata", fmt=O.hexf(8), ch=O.BUS_DATA),
        r("a_wen", "sys_wen"),
        {},
        r("a_ren", "sys_ren", node=nd_rd),
        r("a_rdata", "sys_rdata", fmt=O.hexf(8), ch=O.BUS_DATA),
        r("a_ack", "sys_ack"),
        r("a_err", "sys_err"),
    ]
    edge = O.filtrar_edges(
        [f"{letras[i]}<->{'bdfhj'[i]} {l} ciclos" for i, l in enumerate(lats)],
        nd_rd)
    pie = (f"{TB_TOP} - escritura de run|clear_all y lecturas con el barrido "
           f"en curso - 1 columna = 1 ciclo de clk ({per/1000.0:.0f} ns)")
    wj = {"signal": filas, "edge": edge,
          "head": {"text": "ACK DE LATENCIA FIJA  -  el barrido de borrado "
                           "dura miles de ciclos y el bus no se entera"},
          "foot": {"text": pie}, "config": {"hscale": hscale}}
    return wj, dict(columnas=n, senales=sum(1 for f in filas if f),
                    t0=t0 / 1000.0, t1=t1 / 1000.0, lats=lats)


# ----------------------------------------------------------------------

TITULOS = {
    "mca_pulso_vida":
        "LA VIDA DE UN PULSO  -  cruce de umbral, ventana, carga acumulada y "
        "evento",
    "mca_apilamiento":
        "APILAMIENTO  -  la ventana llega a maxlen: el pulso se cuenta pero "
        "NO se acepta",
    "mca_hist_rmw":
        "READ-MODIFY-WRITE AL MISMO BIN  -  la cuenta no se pierde aunque los "
        "eventos lleguen pegados",
    "mca_ack_borrado":
        "ACK DE LATENCIA FIJA  -  el barrido de borrado dura miles de ciclos "
        "y el bus no se entera",
}

NOTAS = {
    "mca_pulso_vida":
        "Es la figura central del modulo: todo lo que el MCA hace por evento "
        "pasa aca. La muestra cruza el umbral, `busy` sube y marca la ventana "
        "abierta, las dos cargas se acumulan mientras la ventana dura "
        "--q_tot sobre toda la ventana y q_tail desde la segunda muestra, que "
        "es lo que hace separable la forma del pulso-- y al cerrar sale "
        "`ev_valid` con la amplitud y el bus de features. El pulso es "
        "RECTANGULAR a proposito, igual que en el testbench: su ventana es "
        "inequivoca, asi que los numeros del epigrafe salen de una "
        "multiplicacion y no de reimplementar el DUT.",
    "mca_apilamiento":
        "El mismo bloque con `maxlen` chico y un pulso mas largo que eso. La "
        "ventana se cierra por limite y el evento cae en `cnt_pileup` sin "
        "pasar por `cnt_accepted`: no sale `ev_valid`. Lo que importa es que "
        "SI se cuenta en `cnt_total`. Un evento descartado que no se cuenta en "
        "ningun lado es tiempo muerto invisible, y sin ese numero no se puede "
        "corregir el espectro por eventos perdidos.",
    "mca_hist_rmw":
        "El histograma es una BRAM: incrementar un bin es leerlo, sumarle uno "
        "y escribirlo, y eso tarda varios ciclos. Si dos eventos consecutivos "
        "caen en el MISMO bin, el segundo leeria el valor viejo --el que "
        "todavia no se escribio-- y una de las dos cuentas se perderia. La "
        "figura muestra cuatro incrementos seguidos al mismo bin y la lectura "
        "posterior dando el total correcto: el bloque puentea la escritura en "
        "vuelo. Es el peor caso realista, porque un pico del espectro es "
        "justamente muchos eventos al mismo bin.",
    "mca_ack_borrado":
        "Lo que la cabecera del RTL marca como lo mas importante del modulo. "
        "El barrido de borrado recorre 2^H_AW bins y dura miles de ciclos, "
        "muchisimo mas que los 32 ciclos de timeout del axi4_slave. Si el ack "
        "dependiera de que el motor este libre, una lectura durante el barrido "
        "no haria ack nunca, y eso no produce una lectura mala: deja el CDC "
        "del slot desincronizado para siempre --reg_do != reg_done-- y ese "
        "slot no acepta mas transacciones. El ack sale de un shift register "
        "incondicional, asi que llega con la misma latencia este barriendo o "
        "no, que es lo que la figura mide.",
}

CABECERA = """EPÍGRAFES DE LAS FIGURAS DE ONDAS DEL MODULO MCA
================================================

Las cuatro las escribe `ondas_mca.py` leyendo los VCD de
`tb_mca_pulse_feature`, `tb_mca_hist` y `tb_mca_top`. Los números de abajo
--cuántos ciclos dura la ventana del pulso, cuántos incrementos seguidos
absorbe el histograma, cuántos ciclos tarda el ack-- los mide el script sobre
el VCD, así que no pueden desincronizarse de los dibujos.

Reloj de la simulación: {relojes}

Escenas de tb_mca_pulse_feature:

{esc_feat}

Escenas de tb_mca_hist:

{esc_hist}

Escenas de tb_mca_top:

{esc_top}"""

PIE = """Las ventanas se ubican por condiciones sobre las señales --el cruce del
umbral, el valor de cfg_maxlen que define la escena, la racha de incrementos, la
escritura de run|clear_all-- y nunca por un tiempo fijo: si el testbench agrega
una escena antes, las figuras siguen saliendo donde corresponde."""


# ----------------------------------------------------------------------
# Recorte
# ----------------------------------------------------------------------

RECORTES = (
    (TB_FEAT, "pulso", lambda v: ventana_pulso(v, MAXLEN_LIMPIO)),
    (TB_FEAT, "apila", lambda v: ventana_pulso(v, MAXLEN_APILA)),
    (TB_HIST, "rmw", ventana_rmw),
    (TB_TOP, "borrado", ventana_borrado),
)


def recortar():
    """Acota cada VCD grande a la ventana que se dibuja y deja los FST aca."""
    for tb, slug, ventana in RECORTES:
        src = O.need_vcd(WAVES / f"{tb}.vcd",
                         f"make -C modulos/mca/work vcd TB={tb} "
                         f"VCD_ADD=\"/{tb}/*\"")
        vcd = O.Vcd(src)
        per = vcd.period("clk")
        t0, t1 = ventana(vcd)
        tmp = AQUI / f"_{slug}.vcd"
        # El margen de dos ciclos es para que build_grid() encuentre el flanco
        # anterior a t0, donde se ancla la grilla.
        O.recortar(src, tmp, t0 - 2 * per, t1 + 2 * per)
        fst = AQUI / f"{tb}_{slug}.fst"
        subprocess.run(["vcd2fst", str(tmp), str(fst)], check=True)
        tmp.unlink()
        print(f"escrito {fst.name}  ({fst.stat().st_size // 1024} kB, "
              f"ventana {t0/1000.0:.0f}-{t1/1000.0:.0f} ns)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    O.add_common_args(ap, AQUI)
    ap.add_argument("--recortar", action="store_true",
                    help="recorta los VCD de work/waves/ a las ventanas que se "
                         "dibujan y escribe los FST al lado de este script")
    args = ap.parse_args()
    if args.recortar:
        return recortar()

    out_dir = Path(args.out)
    items, avisado = [], False
    relojes = {}

    def abrir(tb, slug):
        fst = O.need_vcd(AQUI / f"{tb}_{slug}.fst",
                         "python3 ondas_mca.py --recortar")
        v = O.Vcd(fst)
        relojes[tb] = 1e6 / v.period("clk")
        paso = (v.period("clk") if args.step == "auto"
                else O.parse_step(v, args.step, ("clk",)))
        return v, paso

    # --- 1 y 2: la vida de un pulso, limpio y apilado ---
    for slug, maxlen, clave in (("pulso", MAXLEN_LIMPIO, "mca_pulso_vida"),
                                ("apila", MAXLEN_APILA, "mca_apilamiento")):
        v, paso = abrir(TB_FEAT, slug)
        wj, info = fig_pulso(v, paso, args.hscale, maxlen, TITULOS[clave])
        avisado = O.emitir(out_dir, clave, wj, args.render, avisado,
                           info=f"{info['columnas']} columnas, ventana de "
                                f"{info['largo']} ciclos")
        items.append(dict(titulo=TITULOS[clave], nota=NOTAS[clave], json=wj,
                          archivo=f"{clave}.svg",
                          origen=f"`{TB_FEAT}`, escena "
                                 f"{'1 (pulso rectangular)' if maxlen == MAXLEN_LIMPIO else '5 (apilamiento)'}",
                          detalle=detalle_pulso(info)))

    # --- 3: el read-modify-write ---
    v, paso = abrir(TB_HIST, "rmw")
    wj, info = fig_rmw(v, paso, args.hscale)
    avisado = O.emitir(out_dir, "mca_hist_rmw", wj, args.render, avisado,
                       info=f"{info['columnas']} columnas, "
                            f"{info['cuantos']} incrementos")
    items.append(dict(
        titulo=TITULOS["mca_hist_rmw"], nota=NOTAS["mca_hist_rmw"], json=wj,
        archivo="mca_hist_rmw.svg",
        origen=f"`{TB_HIST}`, escena 3 (forwarding)",
        detalle=f"  · {info['cuantos']} incrementos seguidos al bin "
                f"{info['addr']}, y la lectura posterior da el total.\n"
                f"  · {info['senales']} señales, {info['columnas']} columnas, "
                f"ventana {info['t0']:.0f} a {info['t1']:.0f} ns."))

    # --- 4: el ack durante el barrido ---
    v, paso = abrir(TB_TOP, "borrado")
    wj, info = fig_borrado(v, paso, args.hscale)
    lats = info["lats"]
    avisado = O.emitir(out_dir, "mca_ack_borrado", wj, args.render, avisado,
                       info=f"{info['columnas']} columnas, acks de {lats} ciclos")
    cte = ("siempre el mismo" if len(set(lats)) == 1
           else f"entre {min(lats)} y {max(lats)}") if lats else "—"
    items.append(dict(
        titulo=TITULOS["mca_ack_borrado"], nota=NOTAS["mca_ack_borrado"],
        json=wj, archivo="mca_ack_borrado.svg",
        origen=f"`{TB_TOP}`, escena 5 (lectura durante el borrado)",
        detalle=f"  · Latencia del ack en las lecturas de la ventana: "
                f"{lats} ciclos ({cte}), con el barrido en curso.\n"
                f"  · El presupuesto es 32 ciclos (el timeout de "
                f"`axi4_slave.sv:193`).\n"
                f"  · {info['senales']} señales, {info['columnas']} columnas, "
                f"ventana {info['t0']:.0f} a {info['t1']:.0f} ns."))

    html = out_dir / "ondas_mca.html"
    O.write_html(html, "Ondas del m&oacute;dulo MCA",
                 escape("Generado por docs/mca/figuras/ondas/ondas_mca.py "
                        "desde los VCD de tb_mca_pulse_feature, tb_mca_hist y "
                        "tb_mca_top."),
                 items, titulo_tab="Ondas del modulo MCA")
    print(f"escrito {html.name}  (abrilo en el browser: renderiza desde CDN)")

    fmt = lambda tb: "\n".join(f"  {e.num}) {e.titulo}"
                               for e in O.escenas(SIM / f"{tb}.sv")) or "  (?)"
    rel = ", ".join(f"{tb} a {f:.0f} MHz" for tb, f in sorted(relojes.items()))
    O.write_epigrafes(out_dir / "epigrafes.txt",
                      CABECERA.format(relojes=rel, esc_feat=fmt(TB_FEAT),
                                      esc_hist=fmt(TB_HIST),
                                      esc_top=fmt(TB_TOP)),
                      items, PIE)
    print("escrito epigrafes.txt")
    O.write_manifiesto(out_dir / "ondas.json", items)
    return 0


def detalle_pulso(info):
    lin = [f"  · Umbral {info['thr']}, maxlen {info['maxlen']}: la ventana "
           f"queda abierta {info['largo']} ciclos."]
    if info["hubo_ev"]:
        lin.append(f"  · q_tot={info['qtot']}, q_tail={info['qtail']}, "
                   f"amplitud={info['amp']}: el pulso se ACEPTA.")
    else:
        lin.append("  · No sale ev_valid: el pulso se cierra por maxlen y "
                   "se cuenta como apilamiento.")
    lin.append(f"  · Contadores al final de la ventana: total={info['total']}, "
               f"aceptados={info['acc']}, apilados={info['pileup']}.")
    lin.append(f"  · {info['senales']} señales, {info['columnas']} columnas, "
               f"ventana {info['t0']:.0f} a {info['t1']:.0f} ns.")
    return "\n".join(lin)


if __name__ == "__main__":
    sys.exit(main())

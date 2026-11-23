#!/usr/bin/env python3
"""Diagramas de tiempo del protocolo del bus de sistema, hechos con WaveDrom a
partir de una simulacion de verdad.

Las ondas salen de `prj/MCA/sim/tb_sys_bus_proto.sv`, que es el unico testbench
del arbol que instancia el camino completo -- `sys_bus_interconnect`, con un
`sys_bus_cdc` por slot, y `mca_top` colgado del slot 7 -- en vez de un BFM que
imita al CDC. O sea que lo que se dibuja es el handshake por toggle que corre en
la placa, con las latencias que mide el simulador, no un esquema a mano.

Lo generico --leer el VCD, muestrearlo en una grilla de ciclos, armar las filas
de WaveJSON, renderizar y escribir los epigrafes-- vive en
`docs/figuras/ondas.py`, compartido con los scripts de ondas de cada modulo.
Aca queda solo lo propio de estas tres figuras: que senales van en cada fila,
como se detectan las fases del handshake y que dice cada nota.

Lo que se gana con WaveDrom es el lenguaje propio de los diagramas de tiempo:
buses hexagonales, grupos por dominio de reloj, nodos y flechas de causalidad
(edges), y salida vectorial que escala en el informe.

Lo que se paga es que WaveDrom es por ciclos, no por tiempo: hay que muestrear.
El VCD se muestrea en una grilla alineada a los flancos de clk_ps (por defecto
un paso de medio periodo), asi que:

  - clk_ps y todo el dominio del PS caen exactos en la grilla;
  - clk_adc, que es ASINCRONICO (mismo nominal de 125 MHz, otra fuente), queda
    cuantizado al medio ciclo mas cercano. Es aproximado a proposito: las
    columnas son semiciclos de clk_ps, no nanosegundos.

Los tiempos exactos (latencia de la vuelta completa) se miden sobre el VCD, no
sobre la grilla, y van escritos en las etiquetas y en el pie de cada figura.

Las tres transacciones se detectan solas leyendo `dbg_showcase` (1 = escritura,
2 = lectura, 3 = lectura de una direccion no mapeada) y las fases salen de los
flancos reales de wen/ren/ack: no hay tiempos hardcodeados que se desincronicen
si cambia el testbench.

Salidas en <out_dir> (por defecto, el directorio de este script):

  bus_escritura.json / .svg       escritura de un registro de config
  bus_lectura.json  / .svg        lectura del mismo registro
  bus_no_mapeada.json / .svg      lectura de una direccion sin mapear (§7.1)
  bus_escritura_cdc.json / .svg   la misma escritura con el toggle del CDC por
                                  dentro; las otras tres lo dibujan como caja
                                  negra (ver `filas`)
  bus_protocolo.html              visor con las tres y las notas; no necesita
                                  nada instalado (WaveDrom viene del CDN)

Renderers (--render):
  auto  `wavedrom-cli` del PATH (SVG + PNG), sino el modulo python `wavedrom`
  py    modulo python:  pip install --user wavedrom      (solo SVG)
  cli   CLI oficial:    npm i -g wavedrom-cli            (SVG + PNG; si no esta
        en el PATH lo baja con `npx -y wavedrom-cli`, o sea que pide red)
  none  solo WaveJSON + HTML

Uso:
  python3 figuras_bus_sistema.py                      # con el FST versionado
  python3 figuras_bus_sistema.py --vcd ../../../../sim/waves/tb_sys_bus_proto.vcd
  python3 figuras_bus_sistema.py --step 2 --hscale 2  # mas resolucion temporal

El FST que viene al lado de este script es la salida de

  cd prj/MCA/sim && make vcd TB=tb_sys_bus_proto
  vcd2fst waves/tb_sys_bus_proto.vcd \\
          ../docs/TOP/figuras/bus_sistema/tb_sys_bus_proto.fst

y se versiona (26 kB contra 271 kB del VCD) para que las figuras se puedan
regenerar en un clon limpio, sin Questa.
"""

import argparse
import sys
import textwrap
from html import escape
from pathlib import Path

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI.parents[2] / "figuras"))

import ondas as O                                          # noqa: E402

# dbg_showcase del testbench: que transaccion esta en vitrina.
SHOW = {"escritura": 1, "lectura": 2, "no_mapeada": 3}


# ----------------------------------------------------------------------
# Las fases del handshake, de los flancos reales
# ----------------------------------------------------------------------

def phases(vcd, t_start):
    """Los cuatro instantes del lado master: en arriba, ack, en abajo, ack abajo.

    `en` es wen|ren: el master sostiene el enable hasta ver el ack, asi que la
    transaccion entera son esos cuatro flancos.
    """
    t_en_up = vcd.first_edge("m_en", lambda v: v == 1, t_start)
    t_ack_up = vcd.first_edge("m_ack", lambda v: v == 1, t_en_up)
    t_en_dn = vcd.first_edge("m_en", lambda v: v == 0, t_ack_up)
    t_ack_dn = vcd.first_edge("m_ack", lambda v: v == 0, t_ack_up)
    if None in (t_en_up, t_ack_up, t_en_dn, t_ack_dn):
        sys.exit("no se encontraron las fases del handshake en el VCD")
    return t_en_up, t_ack_up, t_en_dn, t_ack_dn


# ----------------------------------------------------------------------
# Las tres figuras
# ----------------------------------------------------------------------

TITULOS = {
    "escritura":  "ESCRITURA  -  AMP_MAX (0x4070_0034) <- 0x00001234",
    "lectura":    "LECTURA  -  AMP_MAX (0x4070_0034) -> 0x00001234",
    "no_mapeada": "LECTURA DE UNA DIRECCION NO MAPEADA  -  0x4070_0F00 -> 0x00000000",
}


def filas(vcd, kind, vista="protocolo"):
    """Que senal va en cada fila, por dominio de reloj.

    Se devuelve como especificacion y no como filas ya dibujadas porque antes
    de muestrear hay que saber QUE se dibuja: `cortar()` decide donde saltear
    tiempo mirando si cambia alguna de estas senales, y los relojes no cuentan
    (cambian en cada columna). De paso, la lista es la documentacion de que
    senales componen el protocolo.

    `vista` elige cuanto se ve del CDC. En "protocolo" el CDC es una caja
    negra: se dibujan solo los dos puertos del bus, el del master y el del
    esclavo, y los cruces quedan como dos flechas con su latencia. En "cdc"
    se agregan las senales del handshake por toggle (ctrl_do, los
    sincronizadores, reg_done). Sacarlas no solo ahorra filas: mientras el
    toggle cruza no cambia ninguna de las que quedan, asi que `cortar()`
    encuentra tramos muertos mas largos y la figura se acorta sola.

    Cada fila es (nombre en el VCD, etiqueta, nodo o None, kwargs de row).
    """
    es_escritura = (kind == "escritura")
    cdc = (vista == "cdc")
    hex8 = O.hexf(8)

    # --- dominio fclk[0]: el master (en la placa, axi4_slave) ---
    ps = [("m_addr", "addr", None, dict(fmt=hex8, ch="addr")),
          ("m_wdata", "wdata", None, dict(fmt=hex8, ch="wdata"))]
    if not es_escritura:
        ps.pop()                       # en una lectura wdata no significa nada
    ps.append(("m_wen" if es_escritura else "m_ren",
               "wen" if es_escritura else "ren", "en", {}))
    if cdc:
        ps += [("ctrl_do", "ctrl_do (toggle)", None, {}),
               ("ctrl_done_s", "done_csff[2]", None, dict(bit=2))]
    ps.append(("m_ack", "ack", "ack", {}))
    if not es_escritura:
        ps.append(("m_rdata", "rdata", "sink", dict(fmt=hex8, ch="rdata")))

    # --- dominio adc_clk: el CDC del lado registros y el esclavo ---
    adc = []
    if cdc:
        adc += [("reg_do", "reg_do (3 FF)", None, {}),
                ("reg_pend", "reg_do != reg_done", "pend", {})]
    adc.append(("s_addr", "sys_addr", None, dict(fmt=hex8, ch="addr")))
    if es_escritura:
        adc += [
            ("s_wdata", "sys_wdata", None, dict(fmt=hex8, ch="wdata")),
            ("s_wen", "sys_wen", "sen", {}),
            ("wr_stb", "wr_stb (1 ciclo)", "stb", {}),
        ]
    else:
        adc += [
            ("s_ren", "sys_ren", "sen", {}),
            ("rd_stb", "rd_stb (1 ciclo)", "stb", {}),
        ]
    adc.append(("s_ack", "sys_ack (en_sr[3])", "sack", {}))
    if cdc:
        adc.append(("reg_done", "reg_done", "done", {}))
    if es_escritura:
        adc.append(("cfg_amp_max", "cfg_amp_max", "sink",
                    dict(fmt=O.hexf(4), ch="reg")))
    else:
        adc.append(("s_rdata", "sys_rdata", None, dict(fmt=hex8, ch="rdata")))
    return ps, adc


def sin_repetidas(row):
    """Borra la etiqueta de un segmento de bus de una sola columna que repite
    la del segmento anterior.

    Pasa del otro lado de un salto temporal: el bus se corta en la junta (ver
    `armar`) y si el valor cambia a la columna siguiente, queda un segmento de
    una columna con la misma etiqueta que ya se lee antes del salto, y no
    entra ("0x40700000" desborda a hscale 2). Se borra solo si repite: un
    valor nuevo se deja aunque desborde, porque es informacion.
    """
    data = row.get("data")
    if not data:
        return
    wave = row["wave"]
    inicios = [i for i, c in enumerate(wave) if c in "=2345"]
    for k, i in enumerate(inicios):
        fin = inicios[k + 1] if k + 1 < len(inicios) else len(wave)
        largo = sum(1 for c in wave[i:fin] if c != "|")
        if k > 0 and largo == 1 and data[k] == data[k - 1]:
            data[k] = ""


def diagram(vcd, kind, step, hscale, min_run, contexto, vista="protocolo"):
    """WaveJSON de una transaccion. kind: escritura | lectura | no_mapeada;
    vista: protocolo (el CDC como caja negra) | cdc (con el toggle adentro)."""
    per_ps = vcd.period("clk_ps")
    per_adc = vcd.period("clk_adc")
    es_escritura = (kind == "escritura")

    t_show, _ = vcd.interval("dbg_showcase", SHOW[kind])
    if t_show is None:
        sys.exit(f"el VCD no tiene la transaccion de vitrina dbg_showcase="
                 f"{SHOW[kind]} ({kind}): hay que correr el TB nuevo")

    p = phases(vcd, t_show)
    # Un ciclo de clk_ps de margen a cada lado: alcanza para ver el bus parado
    # antes del enable y liberado despues del ack. El tiempo muerto del medio
    # --el que de verdad alarga la figura-- lo saca `cortar`, que sabe donde
    # esta porque lo mide; no se recorta con el margen.
    t0, t1 = p[0] - per_ps, p[3] + per_ps

    ps_spec, adc_spec = filas(vcd, kind, vista)
    dibujadas = [n for n, _l, _nd, _k in ps_spec + adc_spec]
    grid = O.build_grid(vcd, t0, t1, step)
    enteras = len(grid)
    # Los relojes quedan afuera: cambian en cada columna, asi que con ellos
    # adentro no habria nunca un tramo muerto que cortar.
    tramos = O.cortar(vcd, grid, dibujadas, min_run=min_run, contexto=contexto)
    n, offs = O.cols_multi(tramos)
    col = lambda t: O.column_multi(tramos, offs, t)

    # Instantes de interes, todos de flancos reales del VCD.
    t_reg_do = vcd.first_edge("reg_pend", lambda v: v == 1, p[0])
    t_s_en = vcd.first_edge("s_en", lambda v: v == 1, p[0])
    t_stb = vcd.first_edge("wr_stb" if es_escritura else "rd_stb",
                           lambda v: v == 1, p[0])
    t_s_ack = vcd.first_edge("s_ack", lambda v: v == 1, p[0])
    # reg_done NO es un flanco de subida fijo: togglea, asi que una transaccion
    # lo sube y la siguiente lo baja. Lo que marca el nodo es el PRIMER cambio
    # despues del ack del esclavo, en cualquier sentido.
    t_done = vcd.change_after("reg_done", t_s_ack, t1) if t_s_ack else None
    sink = "cfg_amp_max" if es_escritura else "m_rdata"
    t_sink = vcd.change_after(sink, t_stb, t1) if t_stb is not None else None

    # Nodos: a/c en el enable del master, b/d en su ack (las cuatro fases),
    # e donde el toggle llega al dominio adc_clk, f en el enable del esclavo,
    # g en el estrobo de un ciclo, h en el ack del esclavo, i en reg_done y
    # j donde aterriza el dato.
    nd = {"en": O.nodes(n, {col(p[0]): "a", col(p[2]): "c"}),
          "ack": O.nodes(n, {col(p[1]): "b", col(p[3]): "d"})}
    # Solo los nodos de las filas que se dibujan: una flecha a un nodo que no
    # esta en ninguna fila WaveDrom la dibuja colgando desde el origen.
    claves = {clave for _n, _l, clave, _k in ps_spec + adc_spec if clave}
    for clave, letra, t in (("pend", "e", t_reg_do), ("sen", "f", t_s_en),
                            ("stb", "g", t_stb), ("sack", "h", t_s_ack),
                            ("done", "i", t_done), ("sink", "j", t_sink)):
        if t is not None and clave in claves:
            nd[clave] = O.nodes(n, {col(t): letra})

    # --- el color del bus dice si lo que hay es la carga util de ESTA
    # transaccion. Los valores se LEEN del VCD, no se escriben a mano: la
    # direccion y el wdata, con el enable arriba del lado del master; el rdata,
    # con el ack arriba, que es cuando el master lo muestrea. Asi el azul se
    # puede seguir con la vista bajando por la figura.
    valor = lambda s, t: int(vcd.value_at(s, t), 2)
    a_viva = valor("m_addr", p[0])
    d_escrito = valor("m_wdata", p[0]) if es_escritura else None
    d_leido = valor("m_rdata", p[1]) if not es_escritura else None
    color = {"addr": O.ch_vivo(a_viva),
             "wdata": O.ch_vivo(d_escrito),
             "rdata": O.ch_vivo(d_leido),
             # cfg_amp_max son los 16 bits bajos de lo que se escribio
             "reg": O.ch_vivo((d_escrito or 0) & 0xFFFF)}

    def armar(spec):
        out = []
        for nombre, label, clave, kw in spec:
            kw = dict(kw)
            if "ch" in kw:
                kw["ch"] = color[kw["ch"]]
            # seguido solo para las senales de un bit: los tramos son de la
            # MISMA transaccion, asi que una que no cambio al otro lado del
            # hueco se continua en vez de volver a dibujar el flanco.
            #
            # Los buses NO: WaveDrom centra la etiqueta sobre el segmento, asi
            # que un segmento que cruza el hueco se queda con la etiqueta
            # debajo del hueco y recortada ("0x4070003|"). Cortandolo en la
            # junta, cada tramo centra la suya y el valor queda escrito a los
            # dos lados, que ademas ahorra tener que buscarlo antes del salto.
            # (Los relojes tampoco pasan por aca: ahi hay que dibujar el flanco
            # de cada tramo.)
            out.append(O.row_multi(vcd, nombre, label, tramos,
                                   seguido=("fmt" not in kw),
                                   node=nd.get(clave), **kw))
        return out

    ps_rows = [O.row_multi(vcd, "clk_ps", "clk_fpga_0", tramos)] + armar(ps_spec)
    adc_rows = [O.row_multi(vcd, "clk_adc", "adc_clk", tramos)] + armar(adc_spec)
    for r in ps_rows + adc_rows:
        sin_repetidas(r)

    lat_ns = (p[1] - p[0]) / 1000.0
    lat_cyc = (p[1] - p[0]) / float(per_ps)
    # Las etiquetas van cortas a proposito: WaveDrom las centra sobre la curva y
    # las largas terminan escritas encima de otras señales. La explicacion larga
    # va en el visor HTML y en el .md, no en el dibujo.
    #
    # Con el CDC como caja negra, cada cruce es una sola flecha de puerto a
    # puerto: del enable del master al del esclavo (ida) y del ack del esclavo
    # al del master (vuelta), con lo que tardan medido sobre el VCD.
    ida_ns = (t_s_en - p[0]) / 1000.0 if t_s_en else None
    vuelta_ns = (p[1] - t_s_ack) / 1000.0 if t_s_ack else None
    if vista == "cdc":
        edge = [f"a<->b {lat_ns:.0f} ns",
                "a~>e toggle: 3 FF",
                "f~>g estrobo",
                "h~>i",
                "i~>b 3 FF",
                "g~>j"]
    else:
        edge = [f"a<->b {lat_ns:.0f} ns", "f~>g estrobo", "g~>j"]
        if ida_ns is not None:
            edge.append(f"a~>f ida {ida_ns:.0f} ns")
        if vuelta_ns is not None:
            edge.append(f"h~>b vuelta {vuelta_ns:.0f} ns")
    edge = O.filtrar_edges(edge, *nd.values())

    # El pie se centra sobre el ancho del dibujo y WaveDrom no lo parte: si es
    # mas largo que el canvas, se corta en los dos extremos. Por eso va corto y
    # el detalle (la grilla, la leyenda del color) queda en el visor y en el .md.
    pie = (f"tb_sys_bus_proto - vuelta completa {lat_ns:.0f} ns = "
           f"{lat_cyc:.0f} ciclos de clk_fpga_0, de un presupuesto de 32")

    wj = {
        "signal": [
            [f"PS - clk_fpga_0 {1e6/per_ps:.0f} MHz"] + ps_rows,
            {},
            [f"PL - adc_clk {1e6/per_adc:.0f} MHz"] + adc_rows,
        ],
        "edge": edge,
        "head": {"text": TITULOS[kind] + ("  -  CON EL CDC POR DENTRO"
                                          if vista == "cdc" else ""),
                 "tick": 0},
        "foot": {"text": pie},
        "config": {"hscale": hscale},
    }
    huecos = len(tramos) - 1
    saltos = ("sin saltos temporales" if huecos == 0 else
              "con 1 salto temporal" if huecos == 1 else
              f"con {huecos} saltos temporales")
    return wj, dict(columnas=n, enteras=enteras, huecos=huecos, saltos=saltos,
                    senales=len(ps_rows) + len(adc_rows),
                    t0=t0 / 1000.0, t1=t1 / 1000.0,
                    lat_ns=lat_ns, lat_cyc=lat_cyc,
                    ida_ns=ida_ns, vuelta_ns=vuelta_ns)


NOTAS = {
    "escritura":
        "El CDC como caja negra: arriba el puerto del master, en clk_fpga_0; "
        "abajo el del esclavo, en adc_clk. El master pone addr y wdata, "
        "levanta wen y sostiene los tres hasta ver el ack. La flecha de ida "
        "es lo que tarda ese pedido en aparecer del lado del esclavo, y la de "
        "vuelta lo que tarda el ack del esclavo en llegarle al master; por "
        "dentro, cada una es un toggle cruzando tres flops. Del lado del "
        "esclavo sys_wen queda alto hasta el ack, seis ciclos de adc_clk, "
        "asi que el esclavo escribe con un estrobo de un ciclo (wr_stb) para "
        "no ejecutar la escritura seis veces. El ack sale de en_sr[3]: "
        "latencia fija, sin mirar la direccion. Como cruza el toggle esta en "
        "bus_escritura_cdc.",
    "escritura_cdc":
        "IDA (origen clk_fpga_0, destino adc_clk). El master pone addr y wdata "
        "y levanta wen; en ese mismo flanco de clk_fpga_0 el CDC invierte "
        "ctrl_do y latchea ctrl_we. El toggle entra al dominio adc_clk por tres "
        "flops (reg_do_csff[1:0] y reg_do), asi que reg_do != reg_done recien "
        "se hace cierto tres ciclos de adc_clk despues: ese es el precio del "
        "cruce, y es lo que mide la flecha a~>e. Con reg_we_csff[1] ya "
        "sincronizado, reg_write_synced sube y el MISMO flanco de adc_clk "
        "carga bus_m.addr y bus_m.wdata desde bus_s: la direccion y el dato no "
        "pasan por ningun sincronizador, pero tampoco hace falta, porque el "
        "master los dejo quietos desde antes de wen y los sostiene hasta el "
        "ack -- el registro de destino los captura en un instante que el "
        "handshake ya hizo seguro. "
        "VUELTA (origen adc_clk, destino clk_fpga_0). sys_wen queda alto "
        "seis ciclos de adc_clk, hasta que el ack lo baja, asi que el "
        "esclavo necesita el estrobo de un ciclo (wr_stb) para no ejecutar el "
        "case seis veces: con registros de config es inocuo, con un bit "
        "autolimpiante como clr_pulse no. El ack del esclavo copia reg_do en "
        "reg_done, y reg_done vuelve por otros tres flops hasta "
        "ctrl_done_csff; el master ve un pulso de un ciclo "
        "(ctrl_done_csff[1] != [2]) y suelta wen.",
    "lectura":
        "La ida es identica a la escritura --mismo toggle, mismos tres flops, "
        "mismo estrobo-- y lo propio de la lectura esta en la vuelta. El dato "
        "aparece en sys_rdata en el dominio adc_clk, registrado y congelado, "
        "unos 53 ns ANTES de que el ack termine de cruzar a "
        "clk_fpga_0, y en el camino no hay ningun sincronizador: rdata es un "
        "assign que atraviesa el CDC crudo. No hace falta sincronizarlo, y de "
        "hecho no se podria sin romper el ancho de banda: el ack ES la "
        "garantia de que el dato ya se asento, asi que cuando el master lo "
        "muestrea --en el ciclo de clk_fpga_0 en que ve el ack-- esta leyendo "
        "un valor que no se movio en varios ciclos de adc_clk. Lo que si se "
        "timea de verdad es ese cruce de 32 bits, con ~0.94 ns de margen (§8, "
        "regla 4): por eso sys_rdata tiene que ser un registro plano.",
    "no_mapeada":
        "0x0F00 no esta en el mapa de mca_top: cae en el default del casez y "
        "devuelve 0. El handshake, en cambio, es el mismo hasta el ciclo: el "
        "ack sale de en_sr[3], un shift register de adc_clk alimentado por "
        "sys_wen|sys_ren que no mira la direccion, asi que la latencia de la "
        "vuelta es identica a la de las otras dos figuras. Eso es justo lo que "
        "hay que mirar. Si el ack dependiera de la direccion, esta transaccion "
        "no lo levantaria nunca: reg_done no alcanzaria a reg_do, el strobe de "
        "lectura quedaria pegado en alto del lado adc_clk y ctrl_do no podria "
        "volver a togglear del lado clk_fpga_0 -- el CDC del slot queda "
        "desincronizado para siempre (§7.1). No es una lectura mala, es un "
        "slot muerto.",
}

# El codigo de color y el hueco se explican una sola vez, aca, y se interpolan
# en el visor y en los epigrafes: son los dos convenios de lectura que no se
# deducen mirando el dibujo.
LEYENDA = ("Codigo de color del bus: AZUL = la carga util de esta transaccion "
           "(la direccion que se decodifica, el dato que se escribe o el que "
           "vuelve), para poder seguirla con la vista mientras baja por el "
           "sistema; BLANCO = el bus parado, o todavia con la sobra de la "
           "transaccion anterior, que es lo que se ve del lado del esclavo "
           "porque sys_bus_cdc solo recarga bus_m.addr cuando arranca una "
           "transaccion nueva. El par de eses encontradas es un salto temporal: "
           "ahi no cambia ninguna de las senales dibujadas --un sincronizador "
           "corriendo, o el shift register del esclavo contando-- y se saco "
           "para acortar la figura.")


# ----------------------------------------------------------------------
# Visor y epigrafes
# ----------------------------------------------------------------------

TITULO_H1 = ("El bus de sistema de la Red Pitaya &ndash; handshake por toggle "
             "entre\nclk_fpga_0 (PS) y adc_clk (PL)")
TITULO_TAB = "Bus de sistema de la Red Pitaya - protocolo"
SUB = ("Generado por docs/TOP/figuras/bus_sistema/figuras_bus_sistema.py\n"
       "desde {vcd}, que son las ondas de prj/MCA/sim/tb_sys_bus_proto.sv:\n"
       "sys_bus_interconnect + sys_bus_cdc + mca_top, el RTL de verdad.\n"
       "{grilla}\n{leyenda}")

CABECERA = """EPÍGRAFES DE LAS FIGURAS DEL PROTOCOLO DEL BUS
==============================================

Los tres diagramas los escribe `figuras_bus_sistema.py` leyendo las ondas de
`prj/MCA/sim/tb_sys_bus_proto.sv` (sys_bus_interconnect + sys_bus_cdc +
mca_top). Los números de abajo los recalcula el script del VCD, así que no
pueden desincronizarse de los dibujos.

Relojes de la simulación: clk_fpga_0 = {f_ps:.0f} MHz, adc_clk = {f_adc:.0f} MHz,
asíncronos entre sí (en la placa son dos fuentes distintas de 125 MHz)."""

PIE = """Las tres figuras comparten la escala: una columna es un semiciclo de
clk_fpga_0 ({paso:.1f} ns). adc_clk queda cuantizado a esa grilla porque
WaveDrom dibuja ciclos, no nanosegundos; los tiempos de las etiquetas se miden
sobre el VCD, no sobre la grilla.

{leyenda}"""

DETALLE = """  · Vuelta completa: {lat_ns:.0f} ns = {lat_cyc:.0f} ciclos de clk_fpga_0, sobre
    un presupuesto de 32 (el timeout de `axi4_slave.sv:193`).
  · {senales} señales, ventana {t0:.1f} a {t1:.1f} ns.
  · {columnas} columnas dibujadas de {enteras}, {saltos}."""


# ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    O.add_common_args(ap, AQUI, fst="tb_sys_bus_proto.fst")
    ap.add_argument("--min-run", type=int, default=5,
                    help="columnas quietas seguidas a partir de las cuales se "
                         "mete un salto temporal; 0 lo desactiva y la figura "
                         "sale entera (default: %(default)s)")
    ap.add_argument("--contexto", type=int, default=1,
                    help="columnas quietas que se dejan a cada lado del salto "
                         "(default: %(default)s)")
    # El ancho de columna que el salto temporal paga: con 27 columnas en vez de
    # 35, el dibujo a hscale 2 entra en el mismo canvas --que lo fija el largo
    # del pie, no las ondas-- y las etiquetas de 10 caracteres ("0x00001234")
    # dejan de desbordar los segmentos cortos.
    ap.set_defaults(hscale=2)
    args = ap.parse_args()

    vcd_path = O.need_vcd(args.vcd,
                          "cd prj/MCA/sim && make vcd TB=tb_sys_bus_proto")
    out_dir = Path(args.out)

    vcd = O.Vcd(vcd_path)
    if "dbg_showcase" not in vcd:
        sys.exit("VCD sin dbg_showcase en el scope del TB: hay que volcarlo con\n"
                 "  make vcd TB=tb_sys_bus_proto\n"
                 "que pasa -voptargs=+acc; sin eso vopt se come las señales "
                 "del testbench.")

    step = O.parse_step(vcd, args.step, refs=("clk_ps", "clk_adc"))
    items, avisado = [], False
    # Las tres transacciones con el CDC como caja negra, y la escritura otra
    # vez con el toggle por dentro: es la que acompaña al paso a paso del §6.1.
    for kind, vista, slug, nota in (
            ("escritura", "protocolo", "bus_escritura", "escritura"),
            ("lectura", "protocolo", "bus_lectura", "lectura"),
            ("no_mapeada", "protocolo", "bus_no_mapeada", "no_mapeada"),
            ("escritura", "cdc", "bus_escritura_cdc", "escritura_cdc")):
        wj, info = diagram(vcd, kind, step, args.hscale,
                           args.min_run, args.contexto, vista)
        # El título (head) y el pie (foot) van al visor HTML y a epigrafes.txt,
        # no al dibujo: la figura del informe no lleva texto arriba ni abajo.
        dibujo = {k: v for k, v in wj.items() if k != "foot"}
        dibujo["head"] = {"tick": 0}
        avisado = O.emitir(out_dir, slug, dibujo, args.render, avisado,
                           info=f"{info['senales']} senales, "
                                f"{info['columnas']}/{info['enteras']} columnas "
                                f"({info['huecos']} salto/s), ventana "
                                f"{info['t0']:.1f}-{info['t1']:.1f} ns, "
                                f"vuelta {info['lat_ns']:.0f} ns")
        items.append(dict(titulo=wj["head"]["text"], nota=NOTAS[nota], json=wj,
                          archivo=f"{slug}.svg", info=info,
                          detalle=DETALLE.format(**info)))

    per_ps, per_adc = vcd.period("clk_ps"), vcd.period("clk_adc")
    paso = per_ps / 2.0 if step == "events" else step
    grilla = (f"Una columna es un semiciclo de clk_fpga_0 ({paso/1000.0:.1f} ns); "
              f"adc_clk es asincronico y queda cuantizado a esa grilla.")

    html_path = out_dir / "bus_protocolo.html"
    # El titulo lleva `&ndash;` a proposito y va crudo; lo que se interpola
    # (nombre de archivo, grilla, leyenda) se escapa.
    O.write_html(html_path, TITULO_H1,
                 SUB.format(vcd=escape(vcd_path.name), grilla=escape(grilla),
                            leyenda=escape(LEYENDA)),
                 items, titulo_tab=TITULO_TAB)
    print(f"escrito {html_path.name}  (abrilo en el browser: renderiza desde CDN)")

    epi_path = out_dir / "epigrafes.txt"
    O.write_epigrafes(epi_path,
                      CABECERA.format(f_ps=1e6 / per_ps, f_adc=1e6 / per_adc),
                      items, PIE.format(paso=paso / 1000.0,
                                        leyenda=textwrap.fill(LEYENDA, 78)))
    print(f"escrito {epi_path.name}")


if __name__ == "__main__":
    main()

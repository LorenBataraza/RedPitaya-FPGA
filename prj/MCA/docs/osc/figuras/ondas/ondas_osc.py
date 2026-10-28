#!/usr/bin/env python3
"""Diagramas de tiempo del modulo OSC, con WaveDrom, desde una simulacion.

Las dos primeras figuras salen del VCD de `tb_osc_filter`, que es un testbench
de EQUIVALENCIA: instancia `osc_filter` y `osc_filter_ref` (el filtro original
del repo) lado a lado, con el mismo estimulo y los mismos coeficientes, y
cuenta las discrepancias ciclo a ciclo. Por eso las figuras dibujan las dos
salidas superpuestas: lo que se ve es la prueba de que el rediseno no cambio la
respuesta, no un dibujo de como deberia ser.

La tercera es un ESQUEMA: el flujo de utilizacion de `osc_cfg`, donde una
columna es una transaccion del bus y no un ciclo de reloj. No hay VCD detras
--`osc_cfg` no tiene testbench, ver §1.7 de su datasheet-- y el epigrafe lo
dice.

La ventana de cada figura se ubica por CONDICIONES SOBRE LAS SENALES, no por un
tiempo fijo: la escena se busca por el juego de coeficientes que la define y el
instante por el flanco del estimulo. Si manana el testbench agrega una escena
antes, las figuras siguen saliendo en el lugar correcto.

Salidas en <out_dir> (por defecto, el directorio de este script):

  osc_filter_impulso.json / .svg      respuesta al impulso con los
                                      coeficientes de reset (cadena transparente)
  osc_filter_polocero.json / .svg     el mismo impulso con compensacion
                                      polo-cero: la cola que decae
  osc_cfg_adquisicion.json / .svg     el flujo de una adquisicion (esquema)
  ondas_osc.html                      visor con las tres; no necesita nada
                                      instalado (WaveDrom viene del CDN)

El FST que viene al lado de este script es la salida de

  cd prj/MCA && make -C modulos/osc/work vcd TB=tb_osc_filter \\
      VCD_ADD="/tb_osc_filter/*"
  python3 docs/osc/figuras/ondas/ondas_osc.py --recortar \\
      modulos/osc/work/waves/tb_osc_filter.vcd

El `--recortar` es importante: el VCD completo son 23 MB (y 1.5 MB de FST)
porque el testbench empuja ~15000 muestras y Questa escribe los vectores bit
por bit. Recortado a las dos ventanas que se dibujan queda en decenas de kB y
se puede versionar, asi que las figuras se regeneran en un clon limpio sin
Questa.

Uso:
  python3 ondas_osc.py                    # con los FST versionados
  python3 ondas_osc.py --render none      # solo WaveJSON + HTML
"""

import argparse
import sys
from html import escape
from pathlib import Path

AQUI = Path(__file__).parent                 # docs/osc/figuras/ondas/
sys.path.insert(0, str(AQUI.parents[2] / "figuras"))       # docs/figuras/

import ondas as O                                          # noqa: E402

MCA = AQUI.parents[3]                                      # prj/MCA/
TB = MCA / "modulos" / "osc" / "sim" / "tb_osc_filter.sv"

# Los dos juegos de coeficientes que definen las escenas que se dibujan. Se
# buscan por VALOR y no por numero de escena: asi la figura no se corre de lugar
# si el testbench agrega un caso antes.
#
# Las dos figuras son la RESPUESTA AL IMPULSO, no al escalon, y no por gusto:
# con aa != 0 la constante de tiempo del lazo recursivo es de cientos de ciclos,
# asi que un escalon no se asienta dentro de una ventana dibujable --la salida
# no se mueve en 40 columnas-- mientras que el impulso muestra la cola de
# compensacion completa en 25.
COEF_DIRECTO = {"c_aa": 0, "c_bb": 0, "c_kk": (1 << 24) - 1, "c_pp": 0}
COEF_POLOCERO = {"c_aa": 25000, "c_bb": 1000000, "c_pp": 50000}

IMPULSO = 4000
FST = {"impulso": "tb_osc_filter_impulso.fst",
       "polocero": "tb_osc_filter_polocero.fst"}


# ----------------------------------------------------------------------
# Ubicar la escena
# ----------------------------------------------------------------------

def caso_con(vcd, coefs):
    """El instante en que arranca el run_case cuyos coeficientes son `coefs`.

    `set_coeffs` baja rst_n, escribe los coeficientes y lo vuelve a subir, asi
    que cada release de rst_n abre un caso. Se devuelve el primero en el que
    todos los coeficientes pedidos coinciden.
    """
    for t in vcd.edges("rst_n", lambda v: v == 1):
        t_mira = t + 3 * vcd.period("clk")       # ya escritos y estables
        if all(O._to_int(vcd.value_at(n, t_mira)) == v for n, v in coefs.items()):
            return t
    sys.exit(f"el VCD no tiene un caso con {coefs}: cambio tb_osc_filter?")


def _ventana_impulso(vcd, coefs, antes, despues):
    """El impulso de `stim_impulse` dentro del caso que define `coefs`.

    `stim_impulse` es lo primero que corre cada run_case: dos ceros, una muestra
    de 4000 y 200 ceros para ver la respuesta completa.
    """
    t_caso = caso_con(vcd, coefs)
    t_imp = vcd.first_edge("din", lambda v: v == IMPULSO, t_caso)
    if t_imp is None:
        sys.exit(f"no encontre el impulso (din={IMPULSO}) en el caso {coefs}")
    per = vcd.period("clk")
    return t_imp - antes * per, t_imp + despues * per, t_imp


def ventana_impulso(vcd):
    return _ventana_impulso(vcd, COEF_DIRECTO, 3, 16)


def ventana_polocero(vcd):
    return _ventana_impulso(vcd, COEF_POLOCERO, 3, 30)


# ----------------------------------------------------------------------
# Las figuras del filtro
# ----------------------------------------------------------------------

def _pico(vcd, name, t0, t1, bits=14):
    """Instante del maximo en valor absoluto de `name` en la ventana."""
    mejor, cuando = None, None
    for t, v in vcd.changes[name]:
        if t < t0 or t > t1:
            continue
        iv = O._to_int(v)
        if iv is None:
            continue
        if iv >> (bits - 1):
            iv -= 1 << bits
        if mejor is None or abs(iv) > abs(mejor):
            mejor, cuando = iv, t
    return cuando


def fig_filtro(vcd, t0, t1, t_marca, step, hscale, titulo, etiqueta):
    """Una ventana de tb_osc_filter: entrada, las dos salidas y el contador de
    discrepancias. Es siempre la misma estructura; lo que cambia es la ventana y
    los coeficientes, que van en el encabezado."""
    vcd.require("clk", "din", "dvalid", "dut_out", "ref_out", "mismatches")
    # Una columna = UN ciclo, no un semiciclo. Las figuras del bus necesitan el
    # semiciclo porque tienen dos relojes asincronicos y hay que ver en que
    # fase cae cada flanco; aca hay un solo reloj y lo que importa es la
    # secuencia de muestras, asi que el semiciclo solo duplicaria el ancho.
    grid = O.build_grid(vcd, t0, t1, step, ref="clk")
    n = len(grid)
    col = lambda t: O.column_of(grid, t)
    s14 = O.decf(signed_bits=14)

    nd_in = O.nodes(n, {col(t_marca): "a"})
    # Dos instantes distintos y conviene no confundirlos: el primer cambio de
    # la salida (que con el lazo recursivo activo es el pre-timbre, un -66
    # cuatro ciclos antes) y el PICO, que es la latencia que uno quiere citar.
    t_out = vcd.change_after("dut_out", t_marca, t1)
    t_pico = _pico(vcd, "dut_out", t_marca, t1)
    nd_out = O.nodes(n, {col(t_pico): "b"}) if t_pico else None

    filas = [
        O.row_clk(f"clk  {1e6 / vcd.period('clk'):.0f} MHz", n),
        O.row(vcd, "din", "s_axis_tdata", grid, fmt=s14, ch=O.BUS_DATA,
              node=nd_in),
        O.row(vcd, "dvalid", "s_axis_tvalid", grid),
        {},
        O.row(vcd, "dut_out", "m_axis_tdata  (osc_filter)", grid, fmt=s14,
              ch=O.BUS_DATA, node=nd_out),
        O.row(vcd, "ref_out", "m_axis_tdata  (osc_filter_ref)", grid, fmt=s14,
              ch=O.BUS_ADDR),
        O.row(vcd, "mismatches", "discrepancias", grid, fmt=O.decf()),
    ]

    coefs = {k: O._to_int(vcd.value_at(k, t_marca))
             for k in ("c_aa", "c_bb", "c_kk", "c_pp")}
    per = float(vcd.period("clk"))
    lat_cyc = (t_out - t_marca) / per if t_out else None
    lat_pico = (t_pico - t_marca) / per if t_pico else None
    edge = O.filtrar_edges(
        [f"a~>b pico: {lat_pico:.0f} ciclos" if lat_pico else "a~>b"],
        nd_in, nd_out)

    per_ns = vcd.period("clk") / 1000.0
    cuantos = ("1 ciclo" if abs(step - vcd.period("clk")) < 1
               else f"{step/1000.0:.1f} ns")
    pie = (f"tb_osc_filter - aa={coefs['c_aa']} bb={coefs['c_bb']} "
           f"kk=0x{coefs['c_kk']:X} pp={coefs['c_pp']} - "
           f"1 columna = {cuantos} de clk ({per_ns:.0f} ns)")
    wj = {"signal": filas, "edge": edge,
          "head": {"text": titulo, "tick": 0},
          "foot": {"text": pie},
          "config": {"hscale": hscale}}

    lo_d, hi_d = vcd.extremos("dut_out", t0, t1, signed_bits=14)
    lo_r, hi_r = vcd.extremos("ref_out", t0, t1, signed_bits=14)
    disc = O._to_int(vcd.value_at("mismatches", t1)) or 0
    info = dict(columnas=n, senales=sum(1 for f in filas if f),
                t0=t0 / 1000.0, t1=t1 / 1000.0, lat_cyc=lat_cyc,
                lat_pico=lat_pico,
                dut=(lo_d, hi_d), ref=(lo_r, hi_r), disc=disc,
                etiqueta=etiqueta, **coefs)
    return wj, info


DETALLE_FILTRO = """  · Coeficientes: aa={c_aa}, bb={c_bb}, kk=0x{c_kk:X}, pp={c_pp}.
  · {lat_txt}
  · Recorrido de la salida en la ventana: osc_filter [{dut[0]}, {dut[1]}],
    osc_filter_ref [{ref[0]}, {ref[1]}] -- {equiv}.
  · {senales} señales, {columnas} columnas, ventana {t0:.1f} a {t1:.1f} ns."""


def detalle_filtro(info):
    if info["lat_pico"] is None:
        lat = "La salida no cambia dentro de la ventana."
    elif info["lat_cyc"] is not None and info["lat_cyc"] < info["lat_pico"]:
        # Con el lazo recursivo activo la salida se mueve ANTES del pico: ese
        # primer movimiento es el pre-timbre del IIR2, no la respuesta.
        lat = (f"El pico de la salida llega {info['lat_pico']:.0f} ciclos "
               f"después del impulso; la salida empieza a moverse "
               f"{info['lat_cyc']:.0f} ciclos después, que es el pre-timbre "
               f"del IIR2 y no la respuesta.")
    else:
        lat = (f"La salida responde {info['lat_pico']:.0f} ciclos después del "
               f"impulso: es la latencia de la cadena.")
    equiv = ("idénticos, como tiene que ser en un test de equivalencia"
             if info["dut"] == info["ref"] else
             "DISTINTOS: el testbench tendría que estar fallando")
    return DETALLE_FILTRO.format(lat_txt=lat, equiv=equiv, **info)


# ----------------------------------------------------------------------
# El flujo de utilizacion de osc_cfg (esquema, sin VCD)
# ----------------------------------------------------------------------

def fig_adquisicion(hscale):
    """La secuencia de una adquisicion, paso por paso.

    Una columna es un PASO del software, no un ciclo: los tiempos reales entre
    pasos los pone el que programa y no tienen nada que ver con el ancho de las
    columnas. Lo que la figura fija es el ORDEN y que cada paso depende del
    anterior.
    """
    # La configuracion es una escalera: cada registro en su paso (mapa
    # canonico; los de canal, base 0x01100 + 0x40*ch). Primero los modos
    # globales y despues la cadena de cada canal en el orden del datapath.
    # Entran cuatro por columna y las cajas van sin texto: el nombre esta en
    # la fila. El grupo va pegado a la fila de escritura para que las flechas
    # de abajo no lo crucen, y los nodos van en mayuscula para que WaveDrom no
    # dibuje la letra.
    n_col = 19
    cfg, _ = O.escalera([(r, None) for r in (
        "CFG_INDEP", "CFG_WE_KEEP", "DEC", "FILT_BYP", "FILT_AA", "FILT_BB",
        "FILT_KK", "FILT_PP", "CALIB_OFFSET", "CALIB_GAIN", "AVG_EN",
        "THRESH", "HYST", "DEB_LEN", "DLY  (>= 1)")], 1, n_col, por_col=4)
    filas = [
        ["configuracion"] + cfg,
        {"name": "escritura del PS", "wave": "x3...x4.x..........",
         "data": ["configuracion", "CMD_ARM"],
         "node": "........C.........."},
        {},
        {"name": "trigger", "wave": "0.........10.......",
         "node": "..........E........"},
        {"name": "escribiendo en el buffer", "wave": "0.......1.....0....",
         "node": "........F.....G...."},
        {"name": "write_ptr", "wave": "x.......=.=.=.=....",
         "data": ["0", "N1", "N2", "fin"]},
        {"name": "trig_ptr", "wave": "x.........=........", "data": ["donde pego"]},
        {},
        {"name": "lectura del PS", "wave": "x..............6..x",
         "data": ["buffer + punteros"]},
        {},       # wavedrom-cli no cuenta el grupo en el alto: sin esto el pie
                  # queda recortado
    ]
    edge = ["C~>F armado", "E~>G post-trigger"]
    pie = ("ESQUEMA: una columna es un paso, no un ciclo; cada registro se "
           "escribe en su propio paso. El tiempo entre pasos lo pone el "
           "software; lo que fija la figura es el orden.")
    return O.esquema(filas,
                     head={"text": "FLUJO DE UNA ADQUISICION  -  osc_cfg"},
                     foot=pie, hscale=hscale) | {"edge": edge}


# ----------------------------------------------------------------------

TITULOS = {
    "impulso": "RESPUESTA AL IMPULSO  -  coeficientes de reset (la cadena es "
               "transparente), osc_filter vs osc_filter_ref",
    "polocero": "RESPUESTA AL IMPULSO  -  compensacion polo-cero (aa=25000): "
                "la cola que compensa el preamplificador",
    "adquisicion": "FLUJO DE UNA ADQUISICION  -  osc_cfg",
}

NOTAS = {
    "impulso":
        "Los coeficientes de reset son los que usa el driver hoy, asi que es "
        "la configuracion que mas importa que no haya cambiado. Un impulso "
        "entra y sale UN solo impulso, del mismo tamano: con aa=bb=pp=0 y kk "
        "en 2^24-1 la cadena es transparente y lo unico que agrega es "
        "latencia, que es el numero que da esta figura. Las dos salidas se "
        "dibujan superpuestas a proposito: tb_osc_filter es un test de "
        "EQUIVALENCIA contra el filtro original del repo, asi que las filas de "
        "osc_filter y osc_filter_ref tienen que ser la misma onda columna por "
        "columna. Si en alguna se separan, el testbench esta fallando y la "
        "figura lo muestra.",
    "polocero":
        "La misma entrada que la figura anterior --un impulso-- con el lazo "
        "recursivo activo. Ahora la salida no es un impulso sino un pico "
        "seguido de una COLA que decae: eso es la compensacion polo-cero, que "
        "cancela la cola del preamplificador para que el pulso vuelva a la "
        "linea de base antes del siguiente. Es la parte del filtro que se "
        "rediseno, y la figura muestra que la cola entera --mas de veinte "
        "muestras-- coincide con la del filtro original muestra por muestra. "
        "Se dibuja el impulso y no un escalon porque con aa=25000 la constante "
        "de tiempo es de cientos de ciclos: un escalon no se asienta dentro de "
        "una ventana que se pueda mirar.",
    "adquisicion":
        "Es un esquema de la SECUENCIA, no una medicion: no hay testbench de "
        "osc_cfg del que sacar las ondas (ver §1.7 de su datasheet, que lo "
        "marca como deuda de verificacion). La configuracion es una escalera: "
        "el bus del PS escribe un registro por vez, primero los modos globales "
        "y despues la cadena de cada canal en el orden del datapath; DLY tiene "
        "que quedar en 1 o mas, porque el 0 de reset es el caso degenerado de "
        "rp_bram_sm. Lo que la figura fija es el orden y "
        "las dependencias: la configuracion del filtro y del diezmado va ANTES "
        "del armado, porque cambiarla con el buffer llenandose mezcla muestras "
        "de dos configuraciones en la misma traza; y la lectura va despues de "
        "que el puntero deje de moverse, porque leer durante la captura "
        "devuelve una traza partida entre dos vueltas del buffer.",
}

CABECERA = """EPÍGRAFES DE LAS FIGURAS DE ONDAS DEL MODULO OSC
================================================

Las dos primeras las escribe `ondas_osc.py` leyendo el VCD de
`modulos/osc/sim/tb_osc_filter.sv`, que corre `osc_filter` y `osc_filter_ref`
en paralelo y compara ciclo a ciclo. Los números de abajo los mide el script
sobre el VCD, así que no pueden desincronizarse de los dibujos.

La tercera es un esquema de secuencia y no tiene VCD detrás; se marca como tal
en su epígrafe.

Reloj de la simulación: clk = {f_clk:.0f} MHz (como adc_clk en la placa).
Escenas del testbench de las que salen las ventanas:

{escenas}"""

PIE = """Las ventanas se ubican por condiciones sobre las señales --el juego de
coeficientes que define la escena y el flanco del estímulo--, nunca por un
tiempo fijo: si el testbench agrega un caso antes, las figuras siguen saliendo
donde corresponde."""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    O.add_common_args(ap, AQUI)
    ap.add_argument("--recortar", metavar="VCD",
                    help="recorta ese VCD completo a las ventanas que se "
                         "dibujan y escribe los FST versionables al lado de "
                         "este script")
    args = ap.parse_args()

    if args.recortar:
        return recortar(args.recortar)

    out_dir = Path(args.out)
    items, avisado = [], False
    fclk = None

    for kind, ventana in (("impulso", ventana_impulso),
                          ("polocero", ventana_polocero)):
        fst = O.need_vcd(
            AQUI / FST[kind],
            "python3 ondas_osc.py --recortar "
            "modulos/osc/work/waves/tb_osc_filter.vcd")
        vcd = O.Vcd(fst)
        # Un ciclo por columna: ver el comentario de fig_filtro().
        step = (vcd.period("clk") if args.step == "auto"
                else O.parse_step(vcd, args.step, refs=("clk",)))
        fclk = 1e6 / vcd.period("clk")
        t0, t1, marca = ventana(vcd)
        wj, info = fig_filtro(vcd, t0, t1, marca, step, args.hscale,
                              TITULOS[kind], kind)
        avisado = O.emitir(out_dir, f"osc_filter_{kind}", wj, args.render,
                           avisado,
                           info=f"{info['senales']} senales, "
                                f"{info['columnas']} columnas, ventana "
                                f"{info['t0']:.1f}-{info['t1']:.1f} ns")
        items.append(dict(titulo=TITULOS[kind], nota=NOTAS[kind], json=wj,
                          archivo=f"osc_filter_{kind}.svg",
                          origen=f"`tb_osc_filter`, caso de "
                                 f"{'coeficientes de reset' if kind == 'impulso' else 'compensacion polo-cero'}",
                          detalle=detalle_filtro(info)))

    wj = fig_adquisicion(max(args.hscale, 2))
    avisado = O.emitir(out_dir, "osc_cfg_adquisicion", wj, args.render, avisado,
                       info="esquema, sin VCD")
    items.append(dict(
        titulo=TITULOS["adquisicion"], nota=NOTAS["adquisicion"], json=wj,
        archivo="osc_cfg_adquisicion.svg",
        origen="esquema (sin VCD: `osc_cfg` no tiene testbench)",
        detalle="  · ESQUEMA: una columna es un paso del software, no un "
                "ciclo de reloj.\n  · Sin VCD: `osc_cfg` no tiene testbench."))

    html = out_dir / "ondas_osc.html"
    O.write_html(html, "Ondas del m&oacute;dulo OSC",
                 escape("Generado por docs/osc/figuras/ondas/ondas_osc.py. Las "
                        "dos primeras salen del VCD de tb_osc_filter "
                        "(osc_filter contra osc_filter_ref); la tercera es un "
                        "esquema de secuencia."),
                 items, titulo_tab="Ondas del modulo OSC")
    print(f"escrito {html.name}  (abrilo en el browser: renderiza desde CDN)")

    esc = "\n".join(f"  {e.num}) {e.titulo}" for e in O.escenas(TB)) or "  (?)"
    O.write_epigrafes(out_dir / "epigrafes.txt",
                      CABECERA.format(f_clk=fclk or 125, escenas=esc),
                      items, PIE)
    print("escrito epigrafes.txt")
    O.write_manifiesto(out_dir / "ondas.json", items)
    return 0


def recortar(vcd_grande):
    """Recorta el VCD completo a las dos ventanas y deja los FST al lado.

    Hay que leer el VCD grande dos veces (una por ventana), que es barato al
    lado de versionar 1.5 MB de FST por figura.
    """
    import subprocess                                      # noqa: PLC0415
    src = O.need_vcd(vcd_grande, "make -C modulos/osc/work vcd TB=tb_osc_filter")
    vcd = O.Vcd(src)
    per = vcd.period("clk")
    for kind, ventana in (("impulso", ventana_impulso),
                          ("polocero", ventana_polocero)):
        t0, t1, _ = ventana(vcd)
        # Margen: el recorte tiene que incluir el flanco de reloj anterior a t0,
        # porque build_grid() se ancla en el ultimo flanco <= t0.
        tmp = AQUI / f"_{kind}.vcd"
        O.recortar(src, tmp, t0 - 2 * per, t1 + 2 * per)
        fst = AQUI / FST[kind]
        subprocess.run(["vcd2fst", str(tmp), str(fst)], check=True)
        tmp.unlink()
        print(f"escrito {fst.name}  ({fst.stat().st_size // 1024} kB, "
              f"ventana {(t0 - 2 * per) / 1000.0:.1f}-{(t1 + 2 * per) / 1000.0:.1f} ns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

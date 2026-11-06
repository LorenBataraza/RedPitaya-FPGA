#!/usr/bin/env python3
"""
Generador de datasheets por modulo de RTL.

Lee la cabecera de un modulo SystemVerilog y emite dos cosas:

  1. docs/datasheet/figuras/<top>_interfaz.svg
     El diagrama de bloques de la INTERFAZ: un simbolo con los puertos de
     entrada a la izquierda, los de salida a la derecha, agrupados por los
     banners `// --- grupo ---` que ya tiene el RTL del proyecto, con el ancho
     de cada bus resuelto con los parametros reales de sintesis.

  2. docs/datasheet/datasheet_<top>.md
     El datasheet. Las secciones derivables del RTL y de la sintesis se
     escriben entre marcas `<!-- AUTO:x -->` ... `<!-- /AUTO:x -->` y se
     REESCRIBEN en cada corrida; todo lo que esta fuera de esas marcas es
     prosa a mano y NO se toca nunca. O sea: se puede regenerar despues de
     cambiar un puerto sin perder lo escrito.

  3. docs/datasheet/prosa/<top>.md
     La §1.1 «Que hace»: lo UNICO del datasheet que no se deriva del RTL, y
     por eso lo unico que se guarda aparte. El generador lo crea vacio la
     primera vez y despues no lo reescribe nunca; en cada corrida lo copia
     dentro del bloque AUTO:prosa de la pagina, descartando los comentarios
     HTML de cabecera del archivo. La consecuencia buscada es que la pagina
     sea derivable ENTERA: borrarla y regenerarla no pierde una linea.

Lo que se autogenera:

    resumen       nombre, archivo, MAGIC decodificado, conteo de puertos,
                  el banner de cabecera del RTL y el diagrama
    interfaces    tabla de parametros + una tabla de puertos por grupo
    regmap        enlace al mapa de registros del modulo, si existe
    clocks        relojes y resets detectados + dominio inferido por puerto
    timing        Fmax, camino critico (startpoint/endpoint, niveles de
                  logica) y recursos, de syn/outputs/metrics.txt y del
                  barrido work/rpt/sweep_results.csv
    prosa         la §1.1 a mano, traida de docs/datasheet/prosa/<top>.md
    transacciones figuras de transacciones del modulo, via transacciones.json
    ondas         figuras de ondas del modulo, via ondas.json
    verificacion  testbenches que declara el work/Makefile, assertions por
                  bind y enlace al plan de verificacion

Lo que queda a mano (el scaffold deja el titulo y una pista):

    la §1.1 —en prosa/<top>.md, no en la pagina—, las notas de waveforms,
    la estrategia de CDC y el esquema de laboratorio.

Uso:
    python3 datasheet.py --module mca                 # el TOP del work/Makefile
    python3 datasheet.py --module mt --top trigger_shield
    python3 datasheet.py --module mt --all-tops
    python3 datasheet.py --all                        # todos los modulos
    python3 datasheet.py --module mca --check         # no escribe; falla si
                                                      # el datasheet quedo viejo
    python3 datasheet.py --rtl ../../rtl/osc.sv --out /tmp/osc  # archivo suelto

Sin dependencias: ni graphviz ni matplotlib. El SVG se emite a mano para que
corra igual en la maquina del laboratorio.
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import re
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
MODULOS = os.path.abspath(os.path.join(HERE, ".."))
MCA_ROOT = os.path.abspath(os.path.join(MODULOS, ".."))
REPO_ROOT = os.path.abspath(os.path.join(MCA_ROOT, "..", ".."))
DOCS = os.path.join(MCA_ROOT, "docs")
DS_DIR = os.path.join(DOCS, "datasheet")


# --------------------------------------------------------------------------- #
# Modelo
# --------------------------------------------------------------------------- #
@dataclass
class Param:
    name: str
    default: str            # tal cual aparece en el RTL
    value: object = None    # resuelto a entero, o None si no se pudo
    kind: str = ""          # integer, [31:0], ...
    desc: str = ""
    overridden: bool = False  # lo pisa GENERICS del work/Makefile


@dataclass
class Port:
    dir: str                # input / output / inout
    name: str
    width_expr: str = ""    # "2*DW-1:0" o "" si es de 1 bit
    bits: int = 1           # ancho resuelto; 1 si no se pudo resolver
    msb: object = None
    lsb: object = None
    kind: str = ""          # reg / wire / logic
    signed: bool = False
    desc: str = ""          # comentario al final de la linea
    notes: list = field(default_factory=list)   # comentarios arriba del puerto
    domain: str = ""

    @property
    def width_label(self) -> str:
        """Lo que se dibuja al lado del pin: ancho resuelto, o la expresion."""
        if not self.width_expr:
            return ""
        if self.msb is not None and self.lsb is not None:
            return f"[{self.msb}:{self.lsb}]"
        return f"[{self.width_expr}]"

    @property
    def width_doc(self) -> str:
        """Lo que va en la tabla: el ancho resuelto, y la expresion al lado solo
        si esta parametrizada (ahi importa de que depende)."""
        if not self.width_expr:
            return "1"
        if self.msb is None:
            return f"`[{self.width_expr}]`"
        if not re.search(r"[A-Za-z_]", self.width_expr):
            return f"{self.bits}"
        return f"{self.bits} `[{self.width_expr}]`"


@dataclass
class Group:
    name: str = ""
    doc: list = field(default_factory=list)
    ports: list = field(default_factory=list)

    @property
    def ins(self):
        return [p for p in self.ports if p.dir == "input"]

    @property
    def outs(self):
        return [p for p in self.ports if p.dir != "input"]


@dataclass
class Iface:
    name: str
    path: str                                  # absoluto
    banner: list = field(default_factory=list)  # el //==== de arriba del modulo
    params: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    localparams: dict = field(default_factory=dict)
    body: str = ""                             # del `);` de los puertos a endmodule
    env: dict = field(default_factory=dict)    # parametros resueltos a entero

    @property
    def ports(self):
        return [p for g in self.groups for p in g.ports]

    def port(self, name: str):
        for p in self.ports:
            if p.name == name:
                return p
        return None

    @property
    def rel(self) -> str:
        r = os.path.relpath(self.path, REPO_ROOT)
        return self.path if r.startswith("..") else r


# --------------------------------------------------------------------------- #
# Evaluacion de expresiones de Verilog
# --------------------------------------------------------------------------- #
_BASES = {"h": 16, "d": 10, "b": 2, "o": 8}
_LITERAL = re.compile(r"(\d+)?'([hdbosHDBOS])([0-9a-fA-F_xzXZ]+)")


def clog2(x: int) -> int:
    n, r = 1, 0
    while n < x:
        n <<= 1
        r += 1
    return r


_BINOP = {
    ast.Add: lambda a, b: a + b,       ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,      ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,      ast.LShift: lambda a, b: a << b,
    ast.RShift: lambda a, b: a >> b,   ast.BitOr: lambda a, b: a | b,
    ast.BitAnd: lambda a, b: a & b,    ast.BitXor: lambda a, b: a ^ b,
}
_UNOP = {ast.UAdd: lambda v: +v, ast.USub: lambda v: -v, ast.Invert: lambda v: ~v}


def _node_eval(node, env):
    """Evaluador propio: nada de eval(), solo aritmetica entera y clog2."""
    if isinstance(node, ast.Expression):
        return _node_eval(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise KeyError(node.id)
        return env[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNOP:
        return _UNOP[type(node.op)](_node_eval(node.operand, env))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOP:
        return _BINOP[type(node.op)](_node_eval(node.left, env),
                                     _node_eval(node.right, env))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "clog2":
        return clog2(int(_node_eval(node.args[0], env)))
    raise ValueError(ast.dump(node))


def eval_expr(expr: str, env: dict):
    """Resuelve una expresion de Verilog a entero. None si no se puede."""
    if expr is None:
        return None
    e = expr.strip()
    if not e:
        return None

    def lit(m):
        base = _BASES.get(m.group(2).lower(), 10)
        digits = m.group(3).replace("_", "")
        if re.search(r"[xzXZ]", digits):
            raise ValueError("literal con x/z")
        return str(int(digits, base))

    try:
        e = _LITERAL.sub(lit, e)
    except ValueError:
        return None
    e = e.replace("$clog2", "clog2").replace("$bits", "clog2")
    try:
        return _node_eval(ast.parse(e, mode="eval"), env)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Parser de la cabecera
# --------------------------------------------------------------------------- #
def strip_block_comments(text: str) -> str:
    """Saca los /* */ conservando los saltos de linea (asi no se mueven)."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("\n" * text.count("\n", i, j))
            i = j
        elif text.startswith("//", i):          # un // se come el resto, incluso un /*
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(text[i:j])
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def split_comment(line: str):
    """Parte una linea en (codigo, comentario). El comentario sin el //."""
    i = line.find("//")
    if i < 0:
        return line, None
    return line[:i], line[i + 2:].strip()


BANNER_RE = re.compile(r"^\s*-{2,}\s*(.*?)\s*-{2,}\s*$")

DECL_RE = re.compile(
    r"""^\s*
        (?:(?P<dir>input|output|inout)\b\s*)?
        (?:(?P<kind>wire|reg|logic|var|bit)\b\s*)?
        (?:(?P<sign>signed|unsigned)\b\s*)?
        (?:(?P<kind2>wire|reg|logic|var|bit)\b\s*)?
        (?:\[(?P<w>[^\]]*)\]\s*)?
        (?P<names>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)
        \s*,?\s*$""",
    re.VERBOSE)

PARAM_RE = re.compile(
    r"""^\s*
        (?:(?P<pk>parameter|localparam)\b\s*)?
        (?:(?P<type>integer|int|real|realtime|time|bit|logic|byte|shortint|longint|string|signed|unsigned|type)\b\s*)?
        (?:\[(?P<w>[^\]]*)\]\s*)?
        (?P<name>[A-Za-z_]\w*)
        \s*=\s*(?P<val>.+?)\s*,?\s*$""",
    re.VERBOSE)


def is_label(pending: list) -> bool:
    """¿El bloque de comentarios es un rótulo de grupo y no una explicación?
    Una sola línea, corta y sin punto final: `// Fuentes de trigger` sí,
    `// Mientras vale 1 no se abren pulsos, ...` no."""
    if len(pending) != 1:
        return False
    t = pending[0].strip()
    return bool(t) and len(t) <= 72 and not t.endswith((".", ":", ";")) \
        and not t.startswith(("TODO", "FIXME", "XXX", "OJO", "NOTA"))


def balanced(text: str, start: int):
    """Devuelve (contenido_sin_parentesis, indice_despues_del_cierre)."""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c == "(":
            depth += 1
            if depth == 1:
                begin = i + 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[begin:i], i + 1
        i += 1
    raise ValueError("parentesis sin cerrar")


def leading_banner(lines, mod_line: int) -> list:
    """El bloque //==== ... //==== inmediatamente arriba del `module`."""
    i = mod_line - 1
    while i >= 0 and lines[i].strip() in ("", "`timescale 1ns/1ps"):
        i -= 1
    end = i
    while i >= 0 and lines[i].lstrip().startswith("//"):
        i -= 1
    out = []
    for ln in lines[i + 1:end + 1]:
        t = ln.lstrip()[2:]
        if re.fullmatch(r"\s*[=\-]{4,}\s*", t):
            continue
        out.append(t.rstrip())
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    # Dedent: el `// ` de cada linea deja un espacio parejo que en Markdown se
    # arrastra a la cita.
    pad = min((len(x) - len(x.lstrip()) for x in out if x.strip()), default=0)
    return [x[pad:] for x in out]


def parse_iface(path: str, name: str = None, generics: dict = None) -> Iface:
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    text = strip_block_comments(raw)
    lines = text.split("\n")

    pat = re.compile(r"^[ \t]*module\s+(%s)\b" % (re.escape(name) if name else r"\w+"),
                     re.MULTILINE)
    m = pat.search(text)
    if not m:
        raise SystemExit(f"[datasheet] no encontre `module {name or ''}` en {path}")
    mod_name = m.group(1)
    mod_line = text.count("\n", 0, m.start())

    # #( params ) ( ports );   -- el #( es opcional
    rest = text[m.end():]
    off = m.end()
    hash_i = rest.find("#")
    paren_i = rest.find("(")
    param_txt = ""
    if 0 <= hash_i < paren_i:
        param_txt, consumed = balanced(rest, hash_i)
        off += consumed
    port_txt, after_ports = balanced(text, off)

    iface = Iface(name=mod_name, path=os.path.abspath(path),
                  banner=leading_banner(lines, mod_line))
    # El cuerpo, del `);` de la lista de puertos hasta el endmodule de ESTE
    # modulo: es lo que lee parse_hier(). Se corta ahi porque un archivo puede
    # tener mas de un modulo.
    end_m = re.search(r"^\s*endmodule\b", text[after_ports:], re.MULTILINE)
    iface.body = text[after_ports:after_ports + end_m.start()] if end_m \
        else text[after_ports:]

    # --- parametros ----------------------------------------------------------
    env = {}
    for line in param_txt.split("\n"):
        code, comment = split_comment(line)
        if not code.strip():
            continue
        pm = PARAM_RE.match(code)
        if not pm:
            continue
        val = eval_expr(pm.group("val"), env)
        p = Param(name=pm.group("name"), default=pm.group("val").strip(),
                  value=val, kind=(pm.group("type") or
                                   (f'[{pm.group("w")}]' if pm.group("w") else "")),
                  desc=comment or "")
        if generics and p.name in generics:
            gv = eval_expr(generics[p.name], env)
            if gv is not None:
                p.overridden = (gv != p.value)
                p.value = gv
        if p.value is not None:
            env[p.name] = p.value
        iface.params.append(p)

    # --- localparams visibles (MAGIC y companía) ----------------------------
    body = text[off:]
    for lm in re.finditer(r"^\s*localparam\s+(?:\[[^\]]*\]\s*)?(?:integer\s+)?"
                          r"([A-Za-z_]\w*)\s*=\s*([^;,]+)[;,]", body, re.MULTILINE):
        iface.localparams.setdefault(lm.group(1), lm.group(2).strip())

    # --- puertos -------------------------------------------------------------
    cur = Group()
    pending: list = []
    last_dir = "input"
    for line in port_txt.split("\n"):
        code, comment = split_comment(line)
        stripped = code.strip()

        if not stripped:                      # linea de comentario puro, o vacia
            if comment is None:
                pending = []                  # linea en blanco: corta el bloque
                continue
            bm = BANNER_RE.match(comment)
            if bm:                            # // --- grupo ---
                if cur.ports or cur.name:
                    iface.groups.append(cur)
                cur, pending = Group(name=bm.group(1).strip()), []
            else:
                pending.append(comment)
            continue

        dm = DECL_RE.match(stripped)
        if not dm:
            pending = []
            continue
        d = dm.group("dir") or last_dir
        last_dir = d
        w = (dm.group("w") or "").strip()
        msb = lsb = None
        bits = 1
        if w:
            if ":" in w:
                hi, lo = w.split(":", 1)
                msb, lsb = eval_expr(hi, env), eval_expr(lo, env)
            else:
                msb, lsb = eval_expr(w, env), 0
                if msb is not None:
                    msb = msb - 1
            if msb is not None and lsb is not None:
                msb, lsb = int(msb), int(lsb)
                bits = abs(msb - lsb) + 1

        # Que hacer con los comentarios acumulados arriba de este puerto. Hay
        # tres casos y el RTL del proyecto usa los tres:
        #
        #   una linea corta sin punto final  -> es un rotulo de grupo. Algunos
        #       archivos (mt_event_logic.v) agrupan con `// ADC` en
        #       vez de `// --- ADC ---`.
        #   varias lineas, grupo todavia sin puertos -> describen al grupo
        #       (mca_top: el bloque que explica veto_i).
        #   cualquier otra cosa -> es nota del puerto que sigue.
        notes = []
        if is_label(pending):
            lbl = pending[0].strip()
            if not cur.ports and not cur.name:
                cur.name = lbl
            else:
                iface.groups.append(cur)
                cur = Group(name=lbl)
        elif pending and not cur.ports:
            cur.doc = list(pending)
        else:
            notes = list(pending)

        names = [x.strip() for x in dm.group("names").split(",") if x.strip()]
        for k, nm in enumerate(names):
            cur.ports.append(Port(
                dir=d, name=nm, width_expr=w, bits=bits, msb=msb, lsb=lsb,
                kind=dm.group("kind") or dm.group("kind2") or "",
                signed=dm.group("sign") == "signed",
                desc=(comment or "") if k == len(names) - 1 else "",
                notes=notes if k == 0 else [],
            ))
        pending = []

    if cur.ports or cur.name:
        iface.groups.append(cur)

    iface.env = env
    assign_domains(iface)
    return iface


# --------------------------------------------------------------------------- #
# Relojes, resets y dominios
# --------------------------------------------------------------------------- #
# El nombre tiene que TERMINAR en clk/rst (salvo el sufijo _i/_o de dirección):
# asi `adc_clk_i` y `aclk` entran, y `clk_en_i`, `clk_div_i` o `rst_cnt_i` no.
# No se pide ancho 1: en este diseño `adc_clk_i` es `[N_CH-1:0]`, un reloj por
# canal.
CLK_RE = re.compile(r"(^|_)a?(clk|clock)\d*$", re.I)
RST_RE = re.compile(r"(^|_)(a?rst_?n?|reset_?n?|nrst)\d*$", re.I)


def _base(name: str) -> str:
    return re.sub(r"_[io]$", "", name)


def is_clock(p: Port) -> bool:
    return p.dir == "input" and bool(CLK_RE.search(_base(p.name)))


def is_reset(p: Port) -> bool:
    return p.dir == "input" and bool(RST_RE.search(_base(p.name)))


def clk_prefix(name: str) -> str:
    """adc_clk_i -> adc ; clk_i -> '' ; m_axi_aclk -> m_axi"""
    n = re.sub(r"_[io]$", "", name)
    n = re.sub(r"(^|_)a?(clk|clock)\w*$", "", n)
    return n.strip("_")


def assign_domains(iface: Iface) -> None:
    clocks = [p for p in iface.ports if is_clock(p)]
    for p in iface.ports:
        if is_clock(p) or is_reset(p):
            p.domain = "—"
            continue
        if len(clocks) == 1:
            p.domain = clocks[0].name
        elif not clocks:
            p.domain = "sin reloj"
        else:
            pref = [c for c in clocks if clk_prefix(c.name) and
                    p.name.startswith(clk_prefix(c.name) + "_")]
            p.domain = pref[0].name if len(pref) == 1 else "a confirmar"


# --------------------------------------------------------------------------- #
# Jerarquia interna: que submodulos instancia y como estan cableados
# --------------------------------------------------------------------------- #
# Palabras que NO pueden ser el nombre de un modulo ni de una instancia. Sin
# esto, `if (x) begin` o `always @(posedge clk) begin` se leen como
# instanciaciones (`if` seria el modulo y `x` la instancia).
RESERVADAS = {
    "module", "endmodule", "input", "output", "inout", "wire", "reg", "logic",
    "bit", "byte", "int", "integer", "real", "time", "genvar", "parameter",
    "localparam", "assign", "always", "always_ff", "always_comb", "always_latch",
    "initial", "final", "if", "else", "for", "while", "repeat", "forever", "do",
    "case", "casex", "casez", "endcase", "begin", "end", "generate",
    "endgenerate", "function", "endfunction", "task", "endtask", "return",
    "posedge", "negedge", "signed", "unsigned", "typedef", "struct", "union",
    "enum", "package", "endpackage", "import", "export", "defparam", "specify",
    "endspecify", "defaultclocking", "property", "endproperty", "assert",
    "assume", "cover", "sequence", "endsequence", "bind", "wait", "disable",
    "fork", "join", "automatic", "static", "const", "var", "ref", "pure",
    "virtual", "extern", "interface", "endinterface", "modport", "clocking",
}


@dataclass
class Conn:
    """Una conexion `.puerto(expresion)` de una instancia."""
    port: str
    expr: str
    nets: list = field(default_factory=list)   # identificadores referenciados
    dir: str = ""                              # input/output del SUBmodulo
    bits: int = 0


@dataclass
class Inst:
    module: str
    name: str
    params: dict = field(default_factory=dict)   # nombre -> valor resuelto o texto
    conns: list = field(default_factory=list)
    cond: str = ""        # expresion del generate if que la envuelve
    present: bool = True  # cond evaluada con los parametros reales
    repeat: str = ""      # limite del generate for que la envuelve
    n: int = 1            # repeat evaluado
    note: str = ""        # rotulo del banner de arriba
    external: bool = False  # no se encontro su RTL (IP del repo raiz)

    @property
    def label(self) -> str:
        return self.name


@dataclass
class Edge:
    src: str              # id de nodo
    dst: str
    net: str
    bits: int = 0
    via: str = ""         # logica intermedia; "" = conexion directa
    nets: list = field(default_factory=list)   # al agrupar, todos los del haz

    @property
    def dashed(self) -> bool:
        return bool(self.via)

    @property
    def label(self) -> str:
        """Lo que se escribe sobre la flecha. Un haz de 18 registros de config
        se rotula por lo que es, no con 18 nombres encimados."""
        ns = self.nets or [self.net]
        if len(ns) == 1:
            return f"{self.net}[{self.bits - 1}:0]" if self.bits > 1 else self.net
        if len(ns) == 2:
            return " + ".join(ns)
        return f"{len(ns)} señales"


@dataclass
class Hier:
    insts: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    src_ports: list = field(default_factory=list)   # puertos del padre que entran
    dst_ports: list = field(default_factory=list)   # puertos del padre que salen
    derivs: dict = field(default_factory=dict)      # net -> (origenes, etiqueta)

    @property
    def empty(self) -> bool:
        return not self.insts


def blank_line_comments(text: str) -> str:
    """Reemplaza cada `//…` por espacios CONSERVANDO EL LARGO y los saltos.

    `strip_block_comments()` solo saca los `/* */`: los de linea quedan, y el
    escaneo estructural los lee como codigo. En `mca_top` hay un comentario en
    prosa que dice "El mux va como part-select indexada y NO como function"; el
    escaner tomaba esa palabra por la apertura de una `function`, saltaba
    buscando un `endfunction` que nunca llega y se comia el resto del cuerpo, de
    modo que `generate_frames()` devolvia CERO frames.

    No es un caso aislado: este RTL tiene prosa larga, y cualquier `if`,
    `begin`, `end`, `for` o `case` adentro de un comentario descoloca la pila.
    Ademas `rp_scope_mt_com` tiene un `//assign adc_filt_in = …`
    comentado que el detector de derivaciones tomaba como real.

    Se conserva el largo para que las posiciones sigan mapeando 1 a 1 contra
    `iface.body`, que es lo que lee `inst_note()` —esa si necesita los
    comentarios—.
    """
    out, i, n = [], 0, len(text)
    while i < n:
        j = text.find("//", i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        k = text.find("\n", j)
        k = n if k < 0 else k
        out.append(" " * (k - j))
        i = k
    return "".join(out)


def split_top(text: str, sep: str = ",") -> list:
    """Parte por `sep` SOLO a profundidad cero de (), [] y {}. Hace falta porque
    una conexion es `.cfg_i(a[1:0]), .dat_i({x, y})`: partir por comas a secas
    rompe la concatenacion."""
    out, buf, depth = [], [], 0
    for c in text:
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == sep and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(c)
    if "".join(buf).strip():
        out.append("".join(buf))
    return out


SYSF_RE = re.compile(r"\$\w+")
IDENT_RE = re.compile(r"\b[A-Za-z_]\w*\b")


def expr_nets(expr: str, known: set) -> list:
    """Los nets que referencia una expresion de conexion. `known` es el conjunto
    de nets declarados en el padre: filtra parametros, literales y genvars sin
    tener que entenderlos."""
    e = SYSF_RE.sub(" ", expr)
    e = re.sub(r"\d+'[hdbo][0-9a-fA-F_xzXZ]+", " ", e)   # literales con base
    out = []
    for m in IDENT_RE.finditer(e):
        nm = m.group(0)
        if nm in known and nm not in RESERVADAS and nm not in out:
            out.append(nm)
    return out


def declared_nets(iface: Iface, code: str) -> set:
    """Puertos del padre + wire/reg declarados en el cuerpo (incluidos los de
    adentro de un generate, que es donde `rp_scope_mt_com` declara la
    cadena de cada canal)."""
    nets = {p.name for p in iface.ports}
    for m in re.finditer(r"^\s*(?:wire|reg|logic)\b(?:\s+signed)?\s*"
                         r"(?:\[[^\]]*\]\s*)?(?P<names>[A-Za-z_]\w*"
                         r"(?:\s*,\s*[A-Za-z_]\w*)*)", code, re.MULTILINE):
        for nm in m.group("names").split(","):
            nets.add(nm.strip())
    return nets


def skip_block(body: str, i: int) -> int:
    """Desde justo despues de un `begin`, devuelve el indice despues de su `end`."""
    depth, n = 1, len(body)
    while depth and i < n:
        m = re.search(r"\b(begin|end)\b", body[i:])
        if not m:
            return n
        depth += 1 if m.group(1) == "begin" else -1
        i += m.end()
    return i


def skip_statement(body: str, i: int) -> int:
    """Saltea UNA sentencia procedural entera desde `i`.

    Hace falta de verdad: `mca_top` tiene `always @(posedge clk) if (x) begin
    ... end else begin ... end`, sin `begin` que envuelva al always. Buscar el
    primer `begin` y balancearlo se come solo la rama del `if` y deja el `end`
    del `else` suelto, que descoloca la pila de generate y hace que las
    instancias de `generate if (EN_HIST_H)` salgan como incondicionales.
    """
    n = len(body)
    while True:
        m = re.match(r"\s*", body[i:])
        i += m.end()
        if i >= n:
            return n
        if re.match(r"\bbegin\b", body[i:]):
            i = skip_block(body, i + 5)
        elif re.match(r"\bcase[xz]?\b", body[i:]):
            e = re.search(r"\bendcase\b", body[i:])
            i = i + e.end() if e else n
        elif re.match(r"\bif\b", body[i:]):
            k = body.find("(", i)
            if k < 0:
                return n
            try:
                _, after = balanced(body, k)
            except ValueError:
                return n
            i = skip_statement(body, after)
        else:
            k = body.find(";", i)
            i = k + 1 if k >= 0 else n
        # Un `else` continua la misma sentencia; cualquier otra cosa la cierra.
        m2 = re.match(r"\s*\belse\b", body[i:])
        if not m2:
            return i
        i += m2.end()


def generate_frames(body: str, env: dict) -> list:
    """Los scopes de generate del cuerpo, como (ini, fin, cond, repeat).

    Se recorre el texto llevando una pila de `begin`/`end`. Los bloques
    procedurales (always/initial/function/task) se saltean enteros: adentro de un
    always, un `if` es una sentencia y no un generate, y contarlo descolocaria la
    pila. Una instancia no puede vivir ahi adentro, asi que no se pierde nada.
    """
    TOK = re.compile(
        r"\b(?P<proc>always_ff|always_comb|always_latch|always|initial)\b"
        r"|\b(?P<fn>function|task)\b"
        r"|\b(?P<endfn>endfunction|endtask)\b"
        r"|\b(?P<begin>begin)\b"
        r"|\b(?P<end>end)\b"
        r"|\b(?P<if>if)\b"
        r"|\b(?P<els>else)\b"
        r"|\b(?P<for>for)\b")

    frames, stack = [], []
    pending = None          # construccion esperando su `begin`
    last_if = []            # cond del ultimo `if` cerrado, por nivel
    i, n = 0, len(body)
    while i < n:
        m = TOK.search(body, i)
        if not m:
            break
        i = m.end()

        if m.group("fn"):               # function/task: saltar hasta su cierre
            e = re.search(r"\b(endfunction|endtask)\b", body[i:])
            i = i + e.end() if e else n
            continue

        if m.group("proc"):
            # always @(...) / initial: saltear la sentencia entera, incluida la
            # cadena if/else y los case.
            nxt = re.match(r"\s*@\s*\(", body[i:])      # lista de sensibilidad
            if nxt:
                try:
                    _, i = balanced(body, i + nxt.end() - 1)
                except ValueError:
                    break
            i = skip_statement(body, i)
            continue

        if m.group("if") or m.group("for"):
            k = body.find("(", m.end())
            if k < 0:
                continue
            try:
                inner, after = balanced(body, k)
            except ValueError:
                continue
            if m.group("if"):
                pending = ("if", inner.strip())
            else:
                # for (GV = 0; GV < N_CH; ...) -> el limite es lo que importa
                partes = split_top(inner, ";")
                lim = ""
                if len(partes) >= 2:
                    cm = re.search(r"<=?\s*(.+)$", partes[1])
                    lim = cm.group(1).strip() if cm else ""
                pending = ("for", lim)
            i = after
            continue

        if m.group("els"):
            prev = last_if[-1] if last_if else ""
            pending = ("if", f"!({prev})" if prev else "")
            continue

        if m.group("begin"):
            kind, data = pending if pending else ("plain", "")
            stack.append([kind, data, m.start()])
            pending = None
            continue

        if m.group("end"):
            if stack:
                kind, data, ini = stack.pop()
                if kind == "if":
                    last_if.append(data if not data.startswith("!(") else "")
                    frames.append((ini, m.end(), data, ""))
                elif kind == "for":
                    frames.append((ini, m.end(), "", data))
            continue
    return frames


def frame_of(frames: list, pos: int):
    """La condicion y la replicacion que envuelven a una posicion del cuerpo."""
    conds, reps = [], []
    for ini, fin, cond, rep in frames:
        if ini <= pos <= fin:
            if cond:
                conds.append(cond)
            if rep:
                reps.append(rep)
    return " && ".join(conds), (reps[0] if reps else "")


def inst_note(body: str, pos: int) -> str:
    """El comentario de arriba de una instancia, para usar de epigrafe. Se toma
    la ultima linea con texto del bloque de comentarios inmediatamente anterior,
    que en este RTL es el titulo del banner //=== ... ==="""
    head = body[:pos].rstrip()
    lines = head.split("\n")
    i = len(lines) - 1
    bloque = []
    while i >= 0:
        t = lines[i].strip()
        if t.startswith("//"):
            t = t[2:].strip()
            if not re.fullmatch(r"[=\-]{3,}", t) and t:
                bloque.append(t)
            i -= 1
        elif not t:
            if bloque:
                break
            i -= 1
        else:
            break
    if not bloque:
        return ""
    txt = bloque[-1]
    return txt if len(txt) <= 70 and not txt.endswith(".") else ""


_SUB_CACHE = {}


def make_resolver(module: str):
    """Devuelve `resolver(nombre) -> Iface | None`, buscando el RTL del submodulo
    primero en su propio modulo, despues en los demas de modulos/, y por ultimo
    en las rutas que declara el extra.f (el RTL del repo raiz: axi_wr_fifo,
    rp_bram_sm y compañia). Sin esto, `dsp_tap_mux` —que vive en comun/— salia
    marcado como externo desde el multitrigger."""
    def buscar(name):
        orden = ([module] if module else []) + \
                [d for d in sorted(os.listdir(MODULOS))
                 if d != module and os.path.isdir(os.path.join(MODULOS, d))]
        for mod in orden:
            try:
                return resolve_rtl(mod, name)
            except SystemExit:
                pass
        # extra.f: RTL del repo raiz, con rutas relativas a la raiz
        for mod in orden:
            xf = os.path.join(MODULOS, mod, "extra.f")
            if not os.path.exists(xf):
                continue
            with open(xf) as fh:
                for line in fh:
                    line = line.split("#")[0].strip()
                    if not line:
                        continue
                    p = os.path.join(REPO_ROOT, line)
                    if os.path.splitext(os.path.basename(p))[0] == name \
                            and os.path.exists(p):
                        return p
        return None

    def resolver(name):
        if name in _SUB_CACHE:
            return _SUB_CACHE[name]
        p = buscar(name)
        try:
            _SUB_CACHE[name] = parse_iface(p, name, {}) if p else None
        except (SystemExit, ValueError, OSError):
            _SUB_CACHE[name] = None
        return _SUB_CACHE[name]
    return resolver


def parse_hier(iface: Iface, resolver=None) -> Hier:
    """Extrae las instancias del cuerpo de `iface` y las cablea entre si.

    `resolver(nombre_modulo)` devuelve el Iface del submodulo o None. Sirve para
    saber la direccion de cada puerto, que es lo que decide el sentido de las
    flechas; sin el, se cae al sufijo _i/_o del nombre.
    """
    # `code` es el cuerpo con los comentarios de linea en blanco: es lo que se
    # escanea. `iface.body` conserva los comentarios y sirve solo para sacar el
    # epigrafe de cada instancia. Las posiciones son las mismas en los dos.
    body = iface.body
    code = blank_line_comments(body)
    env = dict(iface.env)
    nets_known = declared_nets(iface, code)
    frames = generate_frames(code, env)
    hier = Hier()

    # --- instancias ----------------------------------------------------------
    for m in re.finditer(r"\b(?P<mod>[A-Za-z_]\w*)\s*(?P<hash>#\s*)?\(", code):
        mod = m.group("mod")
        if mod in RESERVADAS:
            continue
        pos = m.start()
        try:
            if m.group("hash"):
                ptxt, after = balanced(code, code.index("(", m.end() - 1))
                nm = re.match(r"\s*(?P<name>[A-Za-z_]\w*)\s*\(", code[after:])
                if not nm:
                    continue
                name = nm.group("name")
                ctxt, _ = balanced(code, after + nm.end() - 1)
            else:
                # `modulo instancia (` : el nombre esta ANTES del parentesis, o
                # sea que `mod` de arriba es en realidad el nombre de instancia.
                pm = re.search(r"\b(?P<mod>[A-Za-z_]\w*)\s+$", code[:pos])
                if not pm or pm.group("mod") in RESERVADAS:
                    continue
                name, mod, pos = mod, pm.group("mod"), pm.start()
                ptxt = ""
                ctxt, _ = balanced(code, m.end() - 1)
        except (ValueError, IndexError):
            continue
        if name in RESERVADAS:
            continue
        # Filtro decisivo: el cuerpo tiene que tener conexiones por nombre. Deja
        # afuera llamadas a funciones y cualquier `(` que no sea una instancia.
        if not re.search(r"\.\s*[A-Za-z_]\w*\s*\(", ctxt):
            continue

        inst = Inst(module=mod, name=name)
        inst.note = inst_note(body, pos)
        inst.cond, inst.repeat = frame_of(frames, pos)
        if inst.cond:
            v = eval_expr(inst.cond.replace("!=", " != "), env)
            if v is not None:
                inst.present = bool(v)
        if inst.repeat:
            v = eval_expr(inst.repeat, env)
            if v is not None:
                inst.n = int(v)

        for pv in split_top(ptxt):
            pm2 = re.match(r"\s*\.\s*(\w+)\s*\((.*)\)\s*$", pv.strip(), re.S)
            if pm2:
                val = eval_expr(pm2.group(2), env)
                inst.params[pm2.group(1)] = (pm2.group(2).strip() if val is None
                                             else val)

        sub = resolver(mod) if resolver else None
        inst.external = sub is None
        for cv in split_top(ctxt):
            cm = re.match(r"\s*\.\s*(\w+)\s*\((.*)\)\s*$", cv.strip(), re.S)
            if not cm:
                continue
            c = Conn(port=cm.group(1), expr=cm.group(2).strip())
            c.nets = expr_nets(c.expr, nets_known)
            sp = sub.port(c.port) if sub else None
            if sp:
                c.dir, c.bits = sp.dir, sp.bits
            else:
                c.dir = "output" if c.port.endswith("_o") else "input"
            inst.conns.append(c)
        hier.insts.append(inst)

    if not hier.insts:
        return hier

    # --- derivaciones: la logica suelta entre instancias ---------------------
    # Sin esto el diagrama miente por omision: en mca_top, i_feat saca `ev_feat`
    # e i_zoom_1d toma `f_1d`, que es un mux de `ev_feat`. Son dos nets
    # distintos, asi que sin seguir el assign las cajas quedan sueltas.
    for m in re.finditer(r"^\s*assign\s+(?P<lhs>[A-Za-z_]\w*)[^=]*=\s*(?P<rhs>[^;]+);",
                         code, re.MULTILINE):
        hier.derivs.setdefault(m.group("lhs"), []).append(
            (expr_nets(m.group("rhs"), nets_known), "assign"))
    for m in re.finditer(r"^\s*(?:wire|logic)\b[^;=]*?\b(?P<lhs>[A-Za-z_]\w*)\s*"
                         r"=\s*(?P<rhs>[^;]+);", code, re.MULTILINE):
        hier.derivs.setdefault(m.group("lhs"), []).append(
            (expr_nets(m.group("rhs"), nets_known), "lógica"))
    for m in re.finditer(r"(?P<lhs>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*<=\s*"
                         r"(?P<rhs>[^;]+);", code):
        hier.derivs.setdefault(m.group("lhs"), []).append(
            (expr_nets(m.group("rhs"), nets_known), "registro"))

    # --- quien maneja cada net ----------------------------------------------
    driver = {}                     # net -> (id_nodo, etiqueta_de_puerto)
    for ins in hier.insts:
        for c in ins.conns:
            if c.dir != "input":
                for nt in c.nets:
                    driver.setdefault(nt, (ins.name, c.port, c.bits))
    port_names = {p.name: p for p in iface.ports}
    for p in iface.ports:
        if p.dir == "input" and not is_clock(p) and not is_reset(p):
            driver.setdefault(p.name, (f"port:{p.name}", p.name, p.bits))

    def origen(net, saltos=3):
        """De donde viene un net: directo, o atravesando derivaciones."""
        visto, cola = set(), [(net, [])]
        while cola:
            cur, via = cola.pop(0)
            if cur in driver:
                return driver[cur], via
            if cur in visto or len(via) >= saltos:
                continue
            visto.add(cur)
            for srcs, etq in hier.derivs.get(cur, []):
                for s in srcs:
                    cola.append((s, via + [etq]))
        return None, []

    # --- aristas -------------------------------------------------------------
    # Reloj y reset NO se dibujan: van a todas las cajas y convierten cualquier
    # diagrama en una maraña. Se dice en el epigrafe.
    vistos = set()
    for ins in hier.insts:
        for c in ins.conns:
            if c.dir != "input":
                continue
            for nt in c.nets:
                p = port_names.get(nt)
                if p is not None and (is_clock(p) or is_reset(p)):
                    continue
                org, via = origen(nt)
                if not org or org[0] == ins.name:
                    continue
                key = (org[0], ins.name, nt)
                if key in vistos:
                    continue
                vistos.add(key)
                hier.edges.append(Edge(src=org[0], dst=ins.name, net=nt,
                                       bits=c.bits or org[2],
                                       via=" + ".join(dict.fromkeys(via))))

    # --- puertos del padre que salen -----------------------------------------
    for p in iface.ports:
        if p.dir == "input" or is_clock(p) or is_reset(p):
            continue
        org, via = origen(p.name)
        if org and not org[0].startswith("port:"):
            hier.dst_ports.append(p)
            hier.edges.append(Edge(src=org[0], dst=f"port:{p.name}", net=p.name,
                                   bits=p.bits, via=" + ".join(dict.fromkeys(via))))

    hier.edges = merge_edges(hier.edges)
    usados_in = {e.src[5:] for e in hier.edges if e.src.startswith("port:")}
    hier.src_ports = [p for p in iface.ports if p.name in usados_in]
    return hier


def merge_edges(edges: list) -> list:
    """Agrupa las aristas paralelas entre el mismo par de nodos.

    Sin esto `mca_top` sale con 18 flechas de `sys_wdata` a `i_feat`, una por
    registro de configuracion: cierto, e ilegible. Una sola flecha rotulada
    "18 señales" dice lo mismo y deja ver la cadena de datos, que es lo que el
    diagrama tiene que explicar. El detalle completo va en la tabla de abajo.
    """
    out, idx = [], {}
    for e in edges:
        k = (e.src, e.dst)
        if k not in idx:
            idx[k] = e
            e.nets = [e.net]
            out.append(e)
            continue
        g = idx[k]
        if e.net not in g.nets:
            g.nets.append(e.net)
        if not e.via:                   # una directa manda sobre una con lógica
            g.via = ""
            g.net, g.bits = e.net, e.bits
    return out


# --------------------------------------------------------------------------- #
# Diagrama de bloques de la interfaz (SVG a mano)
# --------------------------------------------------------------------------- #
FS_PIN, FS_W, FS_GRP, FS_TITLE, FS_SUB, FS_PAR = 12, 9.5, 10, 16, 9.5, 10.5
ROW, BAND_GAP, STUB, CENTER_GAP = 21, 21, 58, 46
PAD, BOX_PAD_X, HDR_PAD = 14, 12, 12
CHAR = 0.60          # ancho de caracter en monoespaciada, en unidades de FS

# Paleta de las figuras TikZ de docs/osc/figuras/ (los \definecolor de
# panorama_rp_scope_com.tex): mismos colores para que datasheets y tesis se lean
# como un solo sistema. Cada region de modulos/ tiene el color de su papel en el
# panorama; el bus de sistema es rojo y el camino a DDR naranja.
PALETA = {
    "azul":     (108, 172, 228),     # acondicionamiento
    "verde":    (110, 214, 142),     # captura / histogramas en BRAM
    "amarillo": (252, 232, 160),     # trigger
    "naranja":  (252, 206, 160),     # camino a DDR (AXI maestro)
    "grisr":    (226, 226, 226),     # compartido
    "rojo":     (240, 128, 128),     # bus del sistema
}
COLOR_REGION = {"osc": "azul", "mt": "amarillo", "mca": "verde",
                "event_ring": "naranja", "comun": "grisr"}
FONT_MONO = ('&quot;Latin Modern Mono&quot;,&quot;CMU Typewriter Text&quot;,'
             'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace')
FONT_SERIF = ('&quot;Latin Modern Roman&quot;,&quot;CMU Serif&quot;,'
              '&quot;Computer Modern Serif&quot;,Georgia,serif')


def tinte(color: str, p: float = 1.0) -> str:
    """`color!p` de xcolor: mezcla con blanco, p=1 es el color pleno."""
    return "#" + "".join(f"{round(p * c + (1 - p) * 255):02x}" for c in PALETA[color])


def color_region(rel: str) -> str:
    """Color de la region a la que pertenece el RTL (modulos/<region>/...)."""
    m = re.search(r"modulos/([^/]+)/", rel)
    return COLOR_REGION.get(m.group(1) if m else "", "grisr")


def tw(s: str, fs: float) -> float:
    return len(s) * fs * CHAR


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


# Puertos de COMANDO y de RESPUESTA de un bus. Sirven para decidir de que lado
# esta el que inicia las transacciones.
CMD_KW = ("address", "addr", "wen", "ren", "we", "ce", "valid", "vld", "req",
          "start", "stb", "cyc")
RSP_KW = ("ready", "rdata", "rdy", "ack", "dout", "err", "q")


def _has_kw(name: str, kws: tuple) -> bool:
    """¿Alguno de los tokens del nombre es una de esas palabras, con a lo sumo
    dos letras de direccion pegadas adelante?

    El prefijo importa: este RTL escribe el AXI como `axi_waddr_o`,
    `axi_wvalid_o`, `axi_wrdy_i`. Pedir `addr` precedido de `_` no engancha
    `waddr`, y `event_ring_top` quedaba sin marcar pese a ser maestro. Las dos
    letras se limitan a [awrb] (aw/ar/w/r/b de AXI) para que `source` no pase
    por un `ce`.
    """
    for tok in _base(name).lower().split("_"):
        t = re.sub(r"\d+$", "", tok)
        if any(re.fullmatch(r"[awrb]{0,2}" + k, t) for k in kws):
            return True
    return False


def bus_role(ports: list) -> str:
    """maestro / esclavo / "" para un grupo de puertos.

    La regla es quien MANEJA el comando: si `addr`, `wen`, `valid`… son salidas
    del modulo, el modulo inicia las transacciones y es maestro; si son
    entradas, las recibe y es esclavo.

    Se exige que el grupo tenga comando Y respuesta. Sin eso, `mca_dat_i` +
    `mca_val_i` se marcaria como esclavo, y no es un bus: es un flujo de datos
    sin vuelta. Marcar todo de maestro o esclavo vaciaria de significado al
    punto.
    """
    cmd = [p for p in ports if _has_kw(p.name, CMD_KW)]
    rsp = [p for p in ports if _has_kw(p.name, RSP_KW)]
    if not cmd or not rsp:
        return ""
    outs = sum(1 for p in cmd if p.dir != "input")
    ins = sum(1 for p in cmd if p.dir == "input")
    if outs > ins:
        return "maestro"
    if ins > outs:
        return "esclavo"
    return ""


def wrap_text(t: str, maxc: int) -> list:
    """Corta una etiqueta en lineas de a lo sumo `maxc` caracteres. Sin esto,
    un rotulo como "muestras de los dos canales (post-calib/filtro,
    pre-decimacion)" duplicaria el ancho de la figura."""
    out, cur = [], ""
    for w in t.split():
        if cur and len(cur) + 1 + len(w) > maxc:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return out


def brace_path(x: float, y0: float, y1: float, left: bool) -> str:
    """Una llave `{` (left=True) o `}` que abarca de y0 a y1, con la punta en x."""
    w = 7.0 if left else -7.0
    ym = (y0 + y1) / 2
    r = min(8.0, max(2.0, (ym - y0) / 2))
    return (f"M{x + w:.1f},{y0:.1f} Q{x:.1f},{y0:.1f} {x:.1f},{y0 + r:.1f} "
            f"L{x:.1f},{ym - r:.1f} Q{x:.1f},{ym:.1f} {x - w * 0.6:.1f},{ym:.1f} "
            f"Q{x:.1f},{ym:.1f} {x:.1f},{ym + r:.1f} "
            f"L{x:.1f},{y1 - r:.1f} Q{x:.1f},{y1:.1f} {x + w:.1f},{y1:.1f}")


def param_lines(iface: Iface) -> list:
    """Una linea por parametro para el encabezado del simbolo. Se muestra el
    literal tal como esta escrito (asi un MAGIC sigue siendo 32'h4D434131 y no
    1296910641); solo los que pisa el TOP se muestran resueltos, con un *."""
    out = []
    for p in iface.params:
        v = f"{p.value}*" if p.overridden else p.default.strip()
        if len(v) > 16:
            v = v[:15] + "…"
        out.append(f"{p.name}={v}")
    return out


GRP_MAXC = 20        # caracteres por linea del rotulo de bus que va afuera
BUS_RX, BRACE_W, BRACE_GAP = 12.0, 9.0, 9.0


def render_svg(iface: Iface) -> str:
    # --- bandas: cada grupo ocupa max(entradas, salidas) filas ---------------
    # Cada banda lleva su rol de bus (maestro/esclavo), que se calcula sobre el
    # grupo ENTERO: es una propiedad de la interfaz, no de un lado.
    bands = []
    clocks = [p for p in iface.ports if is_clock(p) or is_reset(p)]
    clk_names = {p.name for p in clocks}
    if clocks:
        bands.append(("reloj y reset", clocks, [], ""))
    for g in iface.groups:
        ins = [p for p in g.ins if p.name not in clk_names]
        outs = list(g.outs)
        if ins or outs:
            bands.append((g.name, ins, outs, bus_role(g.ports)))

    # --- geometria -----------------------------------------------------------
    name_l = max([tw(p.name, FS_PIN) for _, i, _, _ in bands for p in i] or [0])
    name_r = max([tw(p.name, FS_PIN) for _, _, o, _ in bands for p in o] or [0])
    lbl_l = max([tw(p.width_label, FS_W) for _, i, _, _ in bands for p in i] or [0])
    lbl_r = max([tw(p.width_label, FS_W) for _, _, o, _ in bands for p in o] or [0])

    # Rotulo de bus: afuera de la llave, de cada lado que tenga pines.
    wrapped = {g: wrap_text(g, GRP_MAXC) for g, _, _, _ in bands if g}
    grp_l = max([tw(x, FS_GRP) for g, i, _, _ in bands if g and i
                 for x in wrapped[g]] or [0])
    grp_r = max([tw(x, FS_GRP) for g, _, o, _ in bands if g and o
                 for x in wrapped[g]] or [0])
    roles = any(r for _, _, _, r in bands)

    plines = param_lines(iface)
    n_col = 1 if len(plines) <= 6 else (2 if len(plines) <= 16 else 3)
    rows_pc = -(-len(plines) // n_col) if plines else 0
    col_w = [max([tw(s, FS_PAR) for s in plines[c * rows_pc:(c + 1) * rows_pc]] or [0])
             for c in range(n_col)]
    par_w = sum(col_w) + 22 * max(0, n_col - 1)

    foot = "* valor con el que lo instancia el TOP" \
           if any(p.overridden for p in iface.params) else ""
    hdr_txt_w = max(tw(iface.name, FS_TITLE), tw(iface.rel, FS_SUB), par_w,
                    tw(foot, FS_SUB))
    # El rotulo de grupo ya no va adentro de la caja, asi que no la ensancha.
    box_w = max(name_l + CENTER_GAP + name_r + 2 * BOX_PAD_X,
                hdr_txt_w + 2 * HDR_PAD)

    hdr_h = HDR_PAD + FS_TITLE + 5 + FS_SUB + (
        (10 + rows_pc * (FS_PAR + 4)) if plines else 0) + (
        (6 + FS_SUB) if foot else 0) + HDR_PAD
    body_h = sum(BAND_GAP + max(len(i), len(o)) * ROW for _, i, o, _ in bands) + 10
    box_h = hdr_h + body_h

    # De afuera hacia adentro: rotulo | llave | ancho del bus | cable | caja
    out_l = (grp_l + 6 + BRACE_W + BRACE_GAP) if grp_l else 0
    out_r = (grp_r + 6 + BRACE_W + BRACE_GAP) if grp_r else 0
    x_box = PAD + out_l + lbl_l + 6 + STUB
    x_end = x_box + box_w
    W = x_end + STUB + 6 + lbl_r + out_r + PAD
    leg_h = (FS_SUB + 12) if roles else 0
    H = PAD + box_h + leg_h + PAD
    y_box = PAD

    s = []
    a = s.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
      f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="{FONT_MONO}">')
    # Mismo lenguaje que las figuras TikZ: fondo blanco siempre (sin variante
    # oscura), trazos negros, rellenos pastel de PALETA, código en monoespaciada
    # y anotaciones en romana.
    a(f"""<style>
  .bg{{fill:#ffffff}}            .box{{stroke:#000000;stroke-width:1.3}}
  .hdr{{stroke:none}}
  .rule{{stroke:#000000;stroke-width:1.0}}
  .sep{{stroke:#8c8c8c;stroke-width:0.9;stroke-dasharray:4 3}}
  .pin{{stroke:#000000;stroke-width:1.2;fill:none}}
  .arr{{fill:#000000;stroke:none}}
  .nm{{fill:#000000}}            .wd{{fill:#595959}}
  .gp{{fill:#4d4d4d;font-style:italic;font-family:{FONT_SERIF}}}
  .ti{{fill:#000000;font-weight:700}} .sb{{fill:#595959}} .pr{{fill:#262626}}
  .lg{{fill:#4d4d4d;font-family:{FONT_SERIF}}}
  /* Tintes planos y no fill-opacity: hay renderers de SVG a PNG que ignoran la
     opacidad y dejan la elipse maciza, tapando los cables que abarca. */
  .brc{{fill:none;stroke:#8c8c8c;stroke-width:1.2}}
  .bus {{fill:{tinte("grisr")};stroke:#8c8c8c;stroke-width:1.0}}
  .busm{{fill:{tinte("naranja", 0.7)};stroke:#000000;stroke-width:1.1}}
  .buss{{fill:{tinte("rojo", 0.45)};stroke:#000000;stroke-width:1.1}}
  .dotm{{fill:{tinte("naranja")};stroke:#000000;stroke-width:1.1}}
  .dots{{fill:{tinte("rojo")};stroke:#000000;stroke-width:1.1}}
</style>""")
    # Encabezado con el color pleno de la region y cuerpo con su tinte, como
    # los estados de fsm_rp_bram_sm.tex.
    region = color_region(iface.rel)
    a(f'<rect class="bg" x="0" y="0" width="{W:.0f}" height="{H:.0f}"/>')
    a(f'<rect class="box" x="{x_box:.1f}" y="{y_box:.1f}" width="{box_w:.1f}" '
      f'height="{box_h:.1f}" rx="4" fill="{tinte(region, 0.3)}"/>')

    # --- encabezado ----------------------------------------------------------
    a(f'<rect class="hdr" x="{x_box + 0.7:.1f}" y="{y_box + 0.7:.1f}" '
      f'width="{box_w - 1.4:.1f}" height="{hdr_h - 0.7:.1f}" rx="3.5" '
      f'fill="{tinte(region)}"/>')
    xc = x_box + box_w / 2
    yt = y_box + HDR_PAD + FS_TITLE
    a(f'<text class="ti" x="{xc:.1f}" y="{yt:.1f}" font-size="{FS_TITLE}" '
      f'text-anchor="middle">{esc(iface.name)}</text>')
    a(f'<text class="sb" x="{xc:.1f}" y="{yt + 5 + FS_SUB:.1f}" font-size="{FS_SUB}" '
      f'text-anchor="middle">{esc(iface.rel)}</text>')
    y_after = yt + 5 + FS_SUB
    if plines:
        y0 = y_after + 12 + FS_PAR
        x0 = xc - par_w / 2
        for c in range(n_col):
            for r, txt in enumerate(plines[c * rows_pc:(c + 1) * rows_pc]):
                a(f'<text class="pr" x="{x0:.1f}" y="{y0 + r * (FS_PAR + 4):.1f}" '
                  f'font-size="{FS_PAR}">{esc(txt)}</text>')
            x0 += col_w[c] + 22
        y_after = y0 + (rows_pc - 1) * (FS_PAR + 4)
    if foot:
        a(f'<text class="lg" x="{xc:.1f}" y="{y_after + 6 + FS_SUB:.1f}" '
          f'font-size="{FS_SUB}" text-anchor="middle">{esc(foot)}</text>')
    a(f'<line class="rule" x1="{x_box:.1f}" y1="{y_box + hdr_h:.1f}" '
      f'x2="{x_end:.1f}" y2="{y_box + hdr_h:.1f}"/>')

    # --- pines ---------------------------------------------------------------
    def arrow(x, y, into_right=True):
        """Triangulo de 7x5 apuntando a la derecha, apoyado en x."""
        if into_right:
            return (f'<path class="arr" d="M{x - 7:.1f},{y - 3.4:.1f} '
                    f'L{x:.1f},{y:.1f} L{x - 7:.1f},{y + 3.4:.1f} Z"/>')
        return (f'<path class="arr" d="M{x:.1f},{y - 3.4:.1f} '
                f'L{x + 7:.1f},{y:.1f} L{x:.1f},{y + 3.4:.1f} Z"/>')

    def bus_group(cx, xb, y0, y1, role, lado_izq, gname):
        """Elipse SOBRE los cables del bus + llave y rotulo mas afuera, como en
        los diagramas de interfaz de un datasheet. El punto marca al maestro.

        `cx` cae dentro del tramo de cable; `xb` es la punta de la llave, que va
        por fuera de las etiquetas de ancho para no encimarse con ellas.
        """
        ym = (y0 + y1) / 2
        ry = max(9.0, (y1 - y0) / 2 + 7)
        cls = {"maestro": "busm", "esclavo": "buss"}.get(role, "bus")
        a(f'<ellipse class="{cls}" cx="{cx:.1f}" cy="{ym:.1f}" '
          f'rx="{BUS_RX:.1f}" ry="{ry:.1f}"/>')
        if role:
            # Vertice superior de la elipse: queda arriba del primer cable, asi
            # que el punto nunca se monta sobre una senal.
            a(f'<circle class="{"dotm" if role == "maestro" else "dots"}" '
              f'cx="{cx:.1f}" cy="{ym - ry:.1f}" r="3.6"/>')
        if not gname:
            return
        a(f'<path class="brc" d="{brace_path(xb, y0 - 4, y1 + 4, lado_izq)}"/>')
        lines = wrapped[gname]
        xt = (xb - 6) if lado_izq else (xb + 6)
        y_t = ym - (len(lines) - 1) * (FS_GRP + 2) / 2 + FS_GRP / 2 - 1
        for li, ln in enumerate(lines):
            a(f'<text class="gp" x="{xt:.1f}" y="{y_t + li * (FS_GRP + 2):.1f}" '
              f'font-size="{FS_GRP}" text-anchor="{"end" if lado_izq else "start"}">'
              f'{esc(ln)}</text>')

    y = y_box + hdr_h
    for bi, (gname, ins, outs, role) in enumerate(bands):
        if bi:
            a(f'<line class="sep" x1="{x_box:.1f}" y1="{y:.1f}" '
              f'x2="{x_end:.1f}" y2="{y:.1f}"/>')
        top = y + BAND_GAP
        if ins:
            bus_group(x_box - STUB * 0.42, x_box - STUB - 6 - lbl_l - BRACE_GAP,
                      top + ROW / 2, top + (len(ins) - 1) * ROW + ROW / 2,
                      role, True, gname)
        if outs:
            bus_group(x_end + STUB * 0.42, x_end + STUB + 6 + lbl_r + BRACE_GAP,
                      top + ROW / 2, top + (len(outs) - 1) * ROW + ROW / 2,
                      role, False, gname)
        for k, p in enumerate(ins):
            yy = top + k * ROW + ROW / 2
            a(f'<line class="pin" x1="{x_box - STUB:.1f}" y1="{yy:.1f}" '
              f'x2="{x_box:.1f}" y2="{yy:.1f}"/>')
            a(arrow(x_box, yy, True))
            if p.width_label:
                a(f'<text class="wd" x="{x_box - STUB - 6:.1f}" y="{yy + 3.4:.1f}" '
                  f'font-size="{FS_W}" text-anchor="end">{esc(p.width_label)}</text>')
            a(f'<text class="nm" x="{x_box + BOX_PAD_X:.1f}" y="{yy + 4:.1f}" '
              f'font-size="{FS_PIN}">{esc(p.name)}</text>')
        for k, p in enumerate(outs):
            yy = top + k * ROW + ROW / 2
            a(f'<line class="pin" x1="{x_end:.1f}" y1="{yy:.1f}" '
              f'x2="{x_end + STUB:.1f}" y2="{yy:.1f}"/>')
            a(arrow(x_end + STUB, yy, True))
            if p.width_label:
                a(f'<text class="wd" x="{x_end + STUB + 6:.1f}" y="{yy + 3.4:.1f}" '
                  f'font-size="{FS_W}">{esc(p.width_label)}</text>')
            a(f'<text class="nm" x="{x_end - BOX_PAD_X:.1f}" y="{yy + 4:.1f}" '
              f'font-size="{FS_PIN}" text-anchor="end">{esc(p.name)}</text>')
        y = top + max(len(ins), len(outs)) * ROW

    # --- leyenda del punto ---------------------------------------------------
    if roles:
        yl = y_box + box_h + 14
        xl = x_box
        a(f'<circle class="dotm" cx="{xl:.1f}" cy="{yl - 3.4:.1f}" r="3.6"/>')
        a(f'<text class="lg" x="{xl + 9:.1f}" y="{yl:.1f}" font-size="{FS_SUB}">'
          f'maestro: el módulo inicia las transacciones</text>')
        xl += 9 + tw("maestro: el módulo inicia las transacciones", FS_SUB) + 22
        a(f'<circle class="dots" cx="{xl:.1f}" cy="{yl - 3.4:.1f}" r="3.6"/>')
        a(f'<text class="lg" x="{xl + 9:.1f}" y="{yl:.1f}" font-size="{FS_SUB}">'
          f'esclavo: las recibe y contesta</text>')

    a("</svg>")
    return "\n".join(s) + "\n"


# --------------------------------------------------------------------------- #
# Datos de la sintesis y del work/Makefile
# --------------------------------------------------------------------------- #
def read_metrics(path: str) -> dict:
    out = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    out[k.strip()] = v.strip()
    except OSError:
        return {}
    return out


def read_sweep(path: str) -> list:
    try:
        with open(path, newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


MK_VAR = re.compile(r"^\s*([A-Za-z_]\w*)\s*[:?]?=\s*(.*?)\s*$")


def read_make_vars(path: str) -> dict:
    """Lee MODULE/TOP/DEPS/TBS/GENERICS del work/Makefile, con continuaciones."""
    out = {}
    try:
        with open(path) as fh:
            raw = fh.read()
    except OSError:
        return out
    raw = re.sub(r"\\\n", " ", raw)
    for line in raw.split("\n"):
        line = line.split("#")[0]      # en un Makefile el comentario es #, no //
        m = MK_VAR.match(line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def parse_generics(s: str) -> dict:
    out = {}
    for tok in (s or "").split():
        if "=" in tok:
            k, _, v = tok.partition("=")
            out[k.strip()] = v.strip()
    return out


# --------------------------------------------------------------------------- #
# Cosecha de los testbenches
#
# Lo que verifica un modulo esta escrito en sus TB, no en VERIFICACION.md: cada
# TB de este arbol numera sus escenas en comentarios
#
#     // 3) BARRIDO DE ACK - la regresion importante.
#
# y nombra cada chequeo
#
#     check("barrido de ack: ningun timeout", ack_timeouts == 0);
#
# Son ~470 chequeos con nombre en 16 TB. De ahi sale la tabla de casos
# cubiertos, en vez de pedir que alguien la transcriba a mano y la mantenga.
#
# OJO: aca los comentarios SON el dato, asi que no se puede usar
# blank_line_comments(). Lo que se blanquea son las cadenas, para que un `)` o
# un `//` dentro de un literal no descoloque el barrido. Los contadores se
# validan contra grep (ver el plan): esto es regex sobre SystemVerilog y en este
# mismo script ya mordio una vez.
# --------------------------------------------------------------------------- #
ESCENA_RE = re.compile(r"^[ \t]*//[ \t]*(\d+)[\)\.][ \t]*(.*?)[ \t]*$", re.MULTILINE)
TASK_RE = re.compile(r"\btask\b[^\n;(]*?\b(\w+)\s*[;(]", re.DOTALL)
TIMEOUT_RE = re.compile(r"#(\d[\d_]*)[ \t]*;?[^\n]*?(?:TIMEOUT|timeout)")
TIMESCALE_RE = re.compile(r"`timescale\s*([\d.]+)\s*(f|p|n|u|m)?s")
UNIT_NS = {"f": 1e-6, "p": 1e-3, "n": 1.0, "u": 1e3, "m": 1e6}

# Las tareas que CHEQUEAN de entrada. Cualquier otra tarea que llame a una de
# estas tambien cuenta: tb_osc_filter no llama a check() desde el cuerpo
# principal sino a run_case("nombre"), que adentro hace check(name, ...). Sin
# seguir esa indireccion ese TB declara 1 caso en vez de 10.
CHECK_BASE = ("check", "checkv")


def checking_tasks(code: str) -> set:
    """Nombres de tarea que, directa o indirectamente, terminan en un check.

    Punto fijo sobre el grafo de llamadas de las tareas del TB: arranca en
    check/checkv y agrega toda tarea cuyo cuerpo mencione una ya marcada.
    """
    cuerpos = {}
    for m in TASK_RE.finditer(code):
        fin = code.find("endtask", m.end())
        cuerpos[m.group(1)] = code[m.end():fin if fin > 0 else len(code)]
    marcadas = {t for t in CHECK_BASE}
    while True:
        nuevas = {name for name, body in cuerpos.items()
                  if name not in marcadas
                  and any(re.search(r"\b%s\s*\(" % re.escape(t), body)
                          for t in marcadas)}
        if not nuevas:
            return marcadas
        marcadas |= nuevas


@dataclass
class Escena:
    num: int
    titulo: str
    pos: int                # offset en el archivo, para repartir los checks
    checks: list = field(default_factory=list)


@dataclass
class Tb:
    name: str
    path: str
    escenas: list = field(default_factory=list)
    checks: list = field(default_factory=list)   # (nombre, pos), todos
    huerfanos: list = field(default_factory=list)  # checks antes de la escena 1
    modelo: str = ""        # con que modelo de referencia compara, si compara
    timeout_ns: object = None

    @property
    def dut(self) -> str:
        return self.name[3:] if self.name.startswith("tb_") else ""


def blank_strings(text: str) -> str:
    """Reemplaza el CONTENIDO de cada cadena por espacios, conservando el largo.

    Igual que blank_line_comments(), las posiciones siguen mapeando 1:1 contra
    el original, asi que un match sobre el texto blanqueado se puede ir a buscar
    al archivo de verdad.
    """
    out, i, n = [], 0, len(text)
    while i < n:
        j = text.find('"', i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j + 1])
        k, i = j + 1, j + 1
        while k < n and text[k] != '"':
            k += 2 if text[k] == "\\" else 1
        k = min(k, n)
        out.append(" " * (k - i))
        out.append(text[k:k + 1])
        i = k + 1
    return "".join(out)


def tb_modelo(code: str, simdir: str, module: str) -> str:
    """Contra que compara el TB, si compara contra algo.

    Son verificaciones de otra naturaleza y hoy la pagina no las distingue: un
    TB con vectores esperados a mano dice que el RTL hace lo que el autor creia;
    uno que corre contra un modelo de referencia dice que hace lo mismo que otra
    implementacion, para TODO el estimulo que se le pase.
    """
    # Un .v/.sv de referencia instanciado al lado del DUT (osc_filter_ref.v).
    for f in sorted(os.listdir(simdir)) if os.path.isdir(simdir) else []:
        base = os.path.splitext(f)[0]
        if not base.endswith(("_ref", "_ref_model", "_golden")):
            continue
        if re.search(r"\b%s\b" % re.escape(base), code):
            return f"RTL de referencia `{f}` instanciado al lado del DUT"
    # Vectores de un modelo externo, leidos de archivo.
    m = re.search(r"\$readmem[bh]\s*\(\s*\"([^\"]+)\"", code)
    if m:
        return f"vectores de `{os.path.basename(m.group(1))}`"
    for sub, que in (("python_model", "modelo Python"), ("c_model", "modelo C")):
        d = os.path.join(MODULOS, module, "modelos", sub)
        if os.path.isdir(d) and any(
                re.search(r"\b%s\b" % re.escape(os.path.splitext(f)[0]), code)
                for f in os.listdir(d)):
            return f"{que} de `modelos/{sub}/`"
    return ""


def parse_tb(path: str, module: str = "") -> Tb:
    """Un testbench -> sus escenas numeradas, sus chequeos con nombre y contra
    que compara. Degrada bien: un TB sin escenas numeradas deja la lista vacia y
    todos sus checks caen en `huerfanos`, para listarlos planos."""
    tb = Tb(name=os.path.splitext(os.path.basename(path))[0], path=path)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return tb

    code = blank_strings(strip_block_comments(raw))

    # Las escenas salen del texto con las cadenas blanqueadas pero los
    # comentarios intactos; el titulo se lee del original por la posicion.
    for m in ESCENA_RE.finditer(code):
        titulo = raw[m.start(2):m.end(2)].strip().rstrip(".")
        tb.escenas.append(Escena(num=int(m.group(1)), titulo=titulo, pos=m.start()))
    tb.escenas.sort(key=lambda e: e.pos)

    # Los checks se buscan sobre el original (hace falta el nombre), pero sin
    # los que quedaron dentro de un comentario de bloque.
    vivo = strip_block_comments(raw)
    tareas = checking_tasks(code)
    chk_re = re.compile(r"\b(?:%s)[ \t]*\([ \t]*\"((?:[^\"\\]|\\.)*)\""
                        % "|".join(re.escape(t) for t in sorted(tareas)))
    for m in chk_re.finditer(vivo):
        # Un check comentado con // no es un caso cubierto, y la DEFINICION de
        # la tarea tampoco (el check(name, ...) de adentro de run_case).
        linea = vivo.rfind("\n", 0, m.start()) + 1
        if "//" in vivo[linea:m.start()]:
            continue
        tb.checks.append((m.group(1), m.start()))

    for nombre, pos in tb.checks:
        dueno = None
        for e in tb.escenas:
            if e.pos <= pos:
                dueno = e
            else:
                break
        (dueno.checks if dueno is not None else tb.huerfanos).append(nombre)

    tb.modelo = tb_modelo(vivo, os.path.dirname(path), module)
    m = TIMEOUT_RE.search(vivo)
    if m:
        # El `#N` esta en la unidad del `timescale`, no en ns: con 1ns/1ps,
        # #50000 son 50 us. Dividir por 1000 a ciegas daba 50 ns.
        ts = TIMESCALE_RE.search(raw)
        unit = UNIT_NS.get(ts.group(2) or "n", 1.0) * float(ts.group(1)) if ts else 1.0
        tb.timeout_ns = int(m.group(1).replace("_", "")) * unit
    return tb


def harvest_tbs(module: str, tbs: list) -> list:
    """Los TB que declara el work/Makefile, parseados y en ese orden."""
    simdir = os.path.join(MODULOS, module, "sim") if module else ""
    out = []
    for name in tbs:
        p = os.path.join(simdir, name + ".sv")
        out.append(parse_tb(p, module) if os.path.exists(p)
                   else Tb(name=name, path=p))
    return out


def sva_vacias(svadir: str) -> list:
    """(archivo, tiene_propiedades) por cada .sv de sim/sva/.

    Los cinco modulos tienen el scaffold de create_module.py: un modulo con el
    `default clocking`, un `// TODO:` y ninguna propiedad. La pagina los
    enlazaba como si tuvieran algo.
    """
    out = []
    for f in sorted(os.listdir(svadir)) if os.path.isdir(svadir) else []:
        if not f.endswith(".sv"):
            continue
        txt = strip_block_comments(open(os.path.join(svadir, f),
                                        encoding="utf-8", errors="replace").read())
        txt = blank_line_comments(txt)
        n = len(re.findall(r"\b(?:assert|assume|cover)\s+property\b", txt))
        n += len(re.findall(r"^\s*\w+\s*:\s*(?:assert|assume|cover)\b", txt,
                            re.MULTILINE))
        out.append((f, n))
    return out


# --------------------------------------------------------------------------- #
# Secciones del Markdown
# --------------------------------------------------------------------------- #
def md_table(head: list, rows: list, drop_empty: bool = False) -> str:
    """Tabla Markdown. Con drop_empty saca las columnas en las que ninguna fila
    tiene nada: una columna "signed" o "Descripcion" vacia en los seis grupos de
    puertos es ruido, no informacion."""
    if not rows:
        return "_(nada)_\n"
    rows = [[("" if c is None else str(c)) for c in r] for r in rows]
    cols = range(len(head))
    if drop_empty:
        cols = [i for i in cols if any(r[i].strip() for r in rows)]
    out = ["| " + " | ".join(head[i] for i in cols) + " |",
           "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        out.append("| " + " | ".join(r[i] for i in cols) + " |")
    return "\n".join(out) + "\n"


def magic_ascii(expr: str):
    v = eval_expr(expr, {})
    if v is None or not isinstance(v, int) or v >> 32:
        return None
    b = v.to_bytes(4, "big")
    return b.decode("ascii") if all(32 <= c < 127 for c in b) else None


def sec_resumen(iface: Iface, ctx: dict) -> str:
    fig = ctx["fig_rel"]
    rows = [("Módulo RTL", f"`{iface.name}`"),
            ("Archivo", f"[`{os.path.basename(iface.path)}`]({ctx['rtl_rel']})"),
            ("Parámetros", len(iface.params)),
            ("Puertos", f"{len(iface.ports)} "
                        f"({len([p for p in iface.ports if p.dir == 'input'])} in / "
                        f"{len([p for p in iface.ports if p.dir != 'input'])} out)")]
    if "MAGIC" in iface.localparams:
        mg = iface.localparams["MAGIC"]
        asc = magic_ascii(mg)
        rows.append(("MAGIC", f"`{mg}`" + (f' — `"{asc}"`' if asc else "")))
    if ctx["metrics"].get("part"):
        rows.append(("Parte", f"`{ctx['metrics']['part']}`"))

    out = [md_table(["", ""], rows), "",
           f"![Interfaz de {iface.name}]({fig})", ""]
    if iface.banner:
        out += ["**Cabecera del RTL** (se copia tal cual de "
                f"[`{os.path.basename(iface.path)}`]({ctx['rtl_rel']})):", ""]
        out += ["> " + ln if ln.strip() else ">" for ln in iface.banner]
        out.append("")
    return "\n".join(out)


PROSA_CAB = """<!-- Prosa a mano del datasheet de `{top}`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro
     del bloque AUTO:prosa de la pagina en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada. Estos comentarios no se copian.

       pagina:  {pagina}

     Que va aca: que problema resuelve el bloque, como encaja en la cadena y
     las dos o tres decisiones de diseno que explican por que esta hecho asi.
     Lo que se deriva del RTL —puertos, registros, relojes, Fmax, casos de
     test— NO: eso lo escribe el generador y se desactualiza solo.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                           -->

"""


ENLACE_RE = re.compile(r"\]\(([^()\s]+)\)")


def reubicar_enlaces(txt: str, desde: str, hacia: str) -> str:
    """Recalcula los enlaces relativos de `desde` para que valgan en `hacia`.

    El archivo de prosa vive en otro directorio que la pagina. Si los enlaces
    se escribieran directamente como los necesita la pagina, el archivo de
    prosa seria markdown roto: no renderiza en GitHub y cualquier chequeo de
    enlaces del repo lo marca entero. Entonces se escriben para que valgan EN
    EL ARCHIVO —que es lo verificable— y se recalculan al copiarlos, con
    relpath, que no depende de cuantos niveles de diferencia haya.
    """
    def uno(m):
        t = m.group(1)
        if re.match(r"^(?:[a-z][a-z0-9+.-]*:|/|#)", t, re.I):
            return m.group(0)
        ruta, _, ancla = t.partition("#")
        if not ruta:
            return m.group(0)
        nueva = os.path.relpath(os.path.join(desde, ruta), hacia)
        return "](" + nueva + ("#" + ancla if ancla else "") + ")"
    return ENLACE_RE.sub(uno, txt)


def leer_prosa(path: str) -> str:
    """El texto de un archivo de prosa, sin los comentarios HTML de cabecera.

    Los comentarios que abren el archivo son la nota de servicio para quien lo
    edita —de donde sale y adonde va—, no parte del datasheet, asi que se
    descartan al copiarlo.
    """
    with open(path, encoding="utf-8") as fh:
        txt = fh.read()
    return re.sub(r"\A(?:\s*<!--.*?-->)+\s*", "", txt, flags=re.DOTALL).strip()


def sec_prosa(iface: Iface, ctx: dict) -> str:
    """La §1.1 a mano, traida del archivo de prosa.

    La prosa no vive en la pagina sino al lado, en `prosa/<top>.md`. La pagina
    se arma entera desde el RTL, asi que borrarla y regenerarla no pierde nada;
    lo escrito a mano esta en otro archivo que el generador solo crea, jamas
    pisa.
    """
    path, rel = ctx["prosa_path"], ctx["prosa_rel"]
    aviso = f"<!-- Prosa a mano: se edita en {rel}, no aca. -->"
    cuerpo = leer_prosa(path) if os.path.exists(path) else ""
    if cuerpo:
        cuerpo = reubicar_enlaces(cuerpo, os.path.dirname(path),
                                  os.path.dirname(ctx["md_path"]))
    if not cuerpo:
        cuerpo = (f"**Qué hace.** TODO — escribir en [`{os.path.basename(path)}`]"
                  f"({rel}): qué problema resuelve el bloque, cómo encaja en la "
                  "cadena y las dos o tres decisiones de diseño que explican por "
                  "qué está hecho así.")
    return aviso + "\n\n" + cuerpo


def group_title(g: Group) -> str:
    if g.name:
        return g.name[0].upper() + g.name[1:]
    if g.ports and all(is_clock(p) or is_reset(p) for p in g.ports):
        return "Reloj y reset"
    return "Señales"


def sec_interfaces(iface: Iface, ctx: dict) -> str:
    out = ["#### Parámetros", ""]
    if iface.params:
        rows = []
        for p in iface.params:
            val = f"`{p.default}`"
            if p.overridden:
                val += f" → **`{p.value}`** (del TOP)"
            elif p.value is not None and str(p.value) != p.default.strip():
                val += f" = `{p.value}`"
            rows.append((f"`{p.name}`", f"`{p.kind}`" if p.kind else "", val, p.desc))
        out.append(md_table(["Parámetro", "Tipo", "Default", "Para qué"], rows,
                            drop_empty=True))
        if any(p.overridden for p in iface.params):
            out += ["", "Los marcados **(del TOP)** son los valores con los que el "
                        "diseño se construye de verdad (`GENERICS` del "
                        "`work/Makefile`); los anchos de esta página están "
                        "resueltos con ésos, no con los defaults del RTL.", ""]
    else:
        out.append("_Sin parámetros._\n")

    out += ["", "#### Puertos", ""]
    for g in iface.groups:
        if not g.ports:
            continue
        out.append(f"##### {group_title(g)}")
        out.append("")
        if g.doc:
            out += [" ".join(g.doc), ""]
        rows = []
        for p in g.ports:
            d = {"input": "in", "output": "out", "inout": "inout"}[p.dir]
            # Los comentarios de arriba del puerto y el del final de la linea son
            # dos cosas distintas: pegarlos con un espacio hace frases falsas.
            desc = " — ".join(x for x in (" ".join(p.notes).strip(), p.desc.strip()) if x)
            rows.append((f"`{p.name}`", d, p.width_doc,
                         "signed" if p.signed else "", p.domain, desc))
        out.append(md_table(["Puerto", "Dir", "Bits", "Signo", "Dominio",
                             "Descripción"], rows, drop_empty=True))
        out.append("")
    return "\n".join(out)


def sec_regmap(iface: Iface, ctx: dict) -> str:
    # Los mapas de registros siguen viviendo en docs/<modulo>/ y la pagina en
    # docs/datasheet/, asi que el enlace se arma con relpath contra el
    # directorio de la pagina y no a secas con el nombre del archivo.
    aqui = os.path.dirname(ctx["md_path"])
    docdir = os.path.join(DOCS, ctx["module"])
    maps = sorted(f for f in os.listdir(docdir)
                  if f.startswith("register_map")) if os.path.isdir(docdir) else []
    if not maps:
        return ("No hay un mapa de registros para este módulo en "
                f"`docs/{ctx['module']}/`. Si es un esclavo del bus de sistema, "
                "falta escribirlo; si no lo es, esta sección no aplica.\n")
    bus = [p.name for p in iface.ports if p.name.startswith("sys_")]
    out = []
    if bus:
        out += [f"`{iface.name}` es esclavo del bus de sistema "
                f"(`{'`, `'.join(bus)}`). El mapa completo está en:", ""]
    else:
        out += ["Mapas de registros de la región:", ""]
    for f in maps:
        out.append(f"- [`{f}`]({os.path.relpath(os.path.join(docdir, f), aqui)})")
    bus_md = os.path.relpath(
        os.path.join(DOCS, "TOP", "bus_sistema_redpitaya.md"), aqui)
    slots_md = os.path.relpath(
        os.path.join(DOCS, "TOP", "register_map_top.md"), aqui)
    out += ["", f"Contrato del bus: [`bus_sistema_redpitaya.md`]({bus_md}) · "
                f"Mapa de slots: [`register_map_top.md`]({slots_md})", ""]
    return "\n".join(out)


def sec_clocks(iface: Iface, ctx: dict) -> str:
    clks = [p for p in iface.ports if is_clock(p)]
    rsts = [p for p in iface.ports if is_reset(p)]
    out = []
    rows = [(f"`{p.name}`", f"reloj ×{p.bits}" if p.bits > 1 else "reloj",
             "", p.desc) for p in clks]
    for p in rsts:
        pol = "activo-bajo" if re.search(r"(rstn|resetn|aresetn|nrst)", p.name, re.I) \
              else "activo-alto"
        dom = clk_prefix(p.name)
        cl = [c for c in clks if clk_prefix(c.name) == dom]
        rows.append((f"`{p.name}`", "reset", pol,
                     p.desc or (f"del dominio `{cl[0].name}`" if cl else "")))
    out.append(md_table(["Puerto", "Qué es", "Polaridad", "Notas"], rows,
                        drop_empty=True))
    out.append("")

    if len(clks) == 1 and clks[0].bits > 1:
        out += [f"**`{clks[0].name}` es un vector de {clks[0].bits} relojes** (uno "
                f"por canal): el bloque se replica, y lo que acá parece un dominio "
                f"son {clks[0].bits}. Qué se cruza entre réplicas —si algo se "
                f"cruza— va escrito abajo, no se infiere del nombre.", ""]
    elif len(clks) == 1:
        out += [f"**Un solo dominio.** Todos los puertos de datos y de control son "
                f"síncronos a `{clks[0].name}`: no hay cruce de dominio dentro de "
                f"este módulo.", ""]
    elif len(clks) > 1:
        out += [f"**{len(clks)} relojes.** El dominio de cada puerto se infiere por "
                "prefijo de nombre; los que quedan en _a confirmar_ hay que "
                "marcarlos a mano y describir el cruce abajo.", ""]
        amb = [p.name for p in iface.ports if p.domain == "a confirmar"]
        if amb:
            out += ["Sin resolver: " + ", ".join(f"`{n}`" for n in amb), ""]
    else:
        out += ["**Combinacional:** el módulo no tiene puerto de reloj.", ""]
    return "\n".join(out)


def sec_timing(iface: Iface, ctx: dict) -> str:
    m, sweep = ctx["metrics"], ctx["sweep"]
    if not m:
        return (f"Sin datos de síntesis todavía. Correr:\n\n"
                f"```bash\nmake -C modulos/{ctx['module']}/work syn\n"
                f"make -C modulos/{ctx['module']}/work sweep-all\n```\n\n"
                f"y volver a generar esta página.\n")
    if m.get("top") and m["top"] != iface.name:
        return (f"El `metrics.txt` del módulo es de `{m['top']}`, no de "
                f"`{iface.name}`: la síntesis OOC del módulo apunta a otro top, "
                f"así que acá no hay números propios de este bloque.\n")

    def f(k, nd=2, unit=""):
        try:
            return f"{float(m[k]):.{nd}f}{unit}"
        except (KeyError, ValueError):
            return "—"

    out = ["**Punto de síntesis** — Vivado out-of-context, "
           f"`{m.get('part', '?')}`.", "",
           md_table(["Métrica", "Valor"], [
               ("Período de la restricción", f("period_ns", 2, " ns")
                + f" ({f('freq_mhz', 1, ' MHz')})"),
               ("WNS", f("wns_ns", 3, " ns")),
               ("Camino crítico", f("crit_path_ns", 3, " ns")),
               ("**Fmax**", "**" + f("fmax_mhz", 1, " MHz") + "**"),
               ("Niveles de lógica", m.get("logic_levels", "—")),
           ]), "",
           "**Camino crítico**", "",
           md_table(["", ""], [
               ("startpoint", f"`{m.get('startpoint', '—')}`"),
               ("endpoint", f"`{m.get('endpoint', '—')}`"),
           ]), "",
           "**Recursos**", "",
           md_table(["LUT", "FF", "BRAM", "DSP", "CARRY", "MUXF"],
                    [[m.get(k, "—") for k in
                      ("lut", "ff", "bram", "dsp", "carry", "muxf")]]), "",
           "`lut` cuenta **primitivas** LUT, no los _Slice LUTs_ del "
           "`report_utilization` (dos LUT5 que comparten O5/O6 ocupan un solo "
           "sitio).", ""]

    if sweep:
        out += ["**Barrido de frecuencia**", "",
                md_table(["f [MHz]", "WNS [ns]", "Camino crítico [ns]",
                          "Fmax [MHz]", "Niveles", "Cierra", "LUT", "FF", "BRAM"],
                         [[r.get("freq_mhz", ""), r.get("wns_ns", ""),
                           r.get("crit_path_ns", ""), r.get("fmax_mhz", ""),
                           r.get("logic_levels", ""), r.get("timing_met", ""),
                           r.get("lut", ""), r.get("ff", ""), r.get("bram", "")]
                          for r in sweep]), ""]
        plots = os.path.join(ctx["work"], "rpt", "plots")
        if os.path.isdir(plots):
            for png in sorted(os.listdir(plots)):
                if png.endswith(".png"):
                    rel = os.path.relpath(os.path.join(plots, png),
                                          os.path.dirname(ctx["md_path"]))
                    out.append(f"![{png}]({rel})")
            out.append("")
    else:
        out += [f"_Barrido no corrido_: `make -C modulos/{ctx['module']}/work "
                f"sweep-all` y regenerar.", ""]
    return "\n".join(out)


def sec_verificacion(iface: Iface, ctx: dict) -> str:
    mod = ctx["module"]
    simdir = os.path.join(MODULOS, mod, "sim")
    aqui = os.path.dirname(ctx["md_path"])
    harvest = ctx.get("harvest") or harvest_tbs(mod, ctx["tbs"])
    rel = lambda p: os.path.relpath(p, aqui)

    rows, n_chk, propio = [], 0, None
    for tb in harvest:
        n_chk += len(tb.checks)
        if tb.dut == iface.name:
            propio = tb
        rows.append((
            f"[`{tb.name}`]({rel(tb.path)})" if os.path.exists(tb.path)
            else f"`{tb.name}` _(falta el archivo)_",
            f"`{tb.dut}`" if tb.dut else "",
            str(len(tb.escenas)) if tb.escenas else "—",
            str(len(tb.checks)) if tb.checks else "—",
            tb.modelo or "vectores a mano",
            "**sí**" if tb.dut == iface.name else "",
        ))

    out = ["Todo corre en batch y se chequea el `RESULT: PASS` del testbench; "
           "las ondas quedan en `work/waves/<tb>.wlf`.", "",
           "```bash",
           f"make -C modulos/{mod}/work            # " + plural(len(harvest), "testbench", "los"),
           f"make -C modulos/{mod}/work cov        # + cobertura",
           f"make -C modulos/{mod}/work lint",
           "```", "",
           md_table(["Testbench", "DUT", "Escenas", "Casos", "Contra qué compara",
                     "Es el de este módulo"], rows), ""]

    # El numero que importa: cuantos chequeos con nombre corren de verdad.
    n_esc = sum(len(t.escenas) for t in harvest)
    out += [f"**{plural(n_chk, 'caso')} con nombre** en "
            f"{plural(len(harvest), 'testbench')}"
            + (f" ({plural(n_esc, 'escena')})" if n_esc else "") + ". "
            "La lista completa, caso por caso, está en el plan de verificación.", ""]

    if propio is None:
        out += [f"> **`{iface.name}` no tiene testbench propio.** Ningún `TBS` del "
                f"`work/Makefile` lo instancia como DUT: lo que se verifica de "
                f"este módulo es lo que arrastre el TB de otro. Es deuda de "
                f"verificación, no una omisión de esta página.", ""]
    elif propio.escenas:
        esc = ", ".join(f"{e.num}) {e.titulo.split(':')[0][:48]}"
                        for e in propio.escenas)
        out += [f"Las escenas de [`{propio.name}`]({rel(propio.path)}): {esc}.", ""]

    svadir = os.path.join(simdir, "sva")
    sva = sva_vacias(svadir)
    if sva:
        total = sum(n for _, n in sva)
        out += ["**Assertions** — en `sim/sva/`, enganchadas por `bind` (no "
                "tocan el RTL sintetizable).", ""]
        out += [f"- [`{f}`]({rel(os.path.join(svadir, f))})"
                + (f" — {n} propiedades" if n else "")
                for f, n in sva]
        out.append("")
        if not total:
            out += ["> **Los archivos de assertions están vacíos.** Son el "
                    "scaffold de `create_module.py`: tienen el `bind`, el "
                    "`default clocking` y un `// TODO:`, pero **ninguna "
                    "propiedad**. O sea que hoy no aportan nada a la "
                    "verificación; el enganche ya está hecho y lo que falta es "
                    "escribirlas. Ver "
                    "[`verificacion_formal.md`](../verificacion_formal.md), que "
                    "discute cuáles convienen primero.", ""]

    plan = os.path.join(simdir, "VERIFICACION.md")
    if os.path.exists(plan):
        out += ["Plan de verificación, casos cubiertos y deuda: "
                f"[`{mod}/sim/VERIFICACION.md`]({rel(plan)}).", ""]
    return "\n".join(out)


def sec_transacciones(iface: Iface, ctx: dict) -> str:
    """Las figuras de TRANSACCIONES: que dato entra al bloque y que dato sale.

    Mismo contrato que `sec_ondas`, con el manifiesto `transacciones.json` que
    escribe `docs/<m>/figuras/transacciones/transacciones_<m>.py`. Son otra
    cosa que las ondas: un paso es una transaccion y no un ciclo de reloj, y
    los valores que se dibujan son datos de verdad --medidos o de simulacion--
    y no niveles logicos.
    """
    mod = ctx["module"]
    aqui = os.path.dirname(ctx["md_path"])
    tdir = os.path.join(DOCS, mod, "figuras", "transacciones")
    script = os.path.join(tdir, f"transacciones_{mod}.py")
    manif = os.path.join(tdir, "transacciones.json")

    if not os.path.exists(manif):
        if not os.path.exists(script):
            return (f"_Sin figuras de transacciones._ Se generan con un script "
                    f"en `docs/{mod}/figuras/transacciones/`, que dibuja qué "
                    f"dato entra al bloque y qué dato sale; el patrón está en "
                    f"[`docs/figuras/transacciones.py`]"
                    f"({os.path.relpath(os.path.join(DOCS, 'figuras', 'transacciones.py'), aqui)}).")
        return (f"_Las figuras no están generadas._ Correr "
                f"`python3 docs/{mod}/figuras/transacciones/"
                f"transacciones_{mod}.py`.")

    try:
        with open(manif, encoding="utf-8") as fh:
            figs = json.load(fh)
    except (OSError, ValueError) as exc:
        return f"_No pude leer `{os.path.relpath(manif, MCA_ROOT)}`: {exc}_"

    out = []
    for f in figs:
        png = os.path.join(tdir, f["archivo"])
        if not os.path.exists(png):
            continue
        out += [f"**{f['titulo']}**", "",
                f"![{f['titulo']}]({os.path.relpath(png, aqui)})", "",
                f"{f['nota']}", "",
                f"_Origen: {f['origen']}._", ""]

    if not out:
        return (f"_El manifiesto no lista ninguna figura existente._ Correr "
                f"`python3 docs/{mod}/figuras/transacciones/"
                f"transacciones_{mod}.py`.")

    # El pie enlaza SOLO lo que existe: el MCA tiene su manifiesto aca pero el
    # script, el README y los epigrafes viven un nivel mas arriba, porque sus
    # figuras son anteriores a esta convencion.
    pie = ["Las figuras **recalculan cada número al dibujar** en vez de "
           "tomarlo escrito."]
    extras = []
    if os.path.exists(script):
        extras.append(f"las genera [`transacciones_{mod}.py`]"
                      f"({os.path.relpath(script, aqui)})")
    for nombre, texto in (("README.md", "de dónde sale el dato de cada una "
                                        "está en la columna «Datos» de"),
                          ("epigrafes.txt", "los epígrafes completos, en")):
        ruta = os.path.join(tdir, nombre)
        if os.path.exists(ruta):
            extras.append(f"{texto} [`{nombre}`]"
                          f"({os.path.relpath(ruta, aqui)})")
    if extras:
        pie.append(extras[0][0].upper() + extras[0][1:] + "".join(
            "; " + e for e in extras[1:]) + ".")
    out += ["---", "", " ".join(pie)]
    return "\n".join(out)


def sec_ondas(iface: Iface, ctx: dict) -> str:
    """Las waveforms del modulo: lo que el script de ondas haya generado.

    No inventa figuras ni las nombra a mano: lee el manifiesto `ondas.json`
    que escribe `docs/<m>/figuras/ondas/ondas_<m>.py`, asi que agregar o sacar
    una figura se refleja solo en la pagina.
    """
    mod = ctx["module"]
    aqui = os.path.dirname(ctx["md_path"])
    ondir = os.path.join(DOCS, mod, "figuras", "ondas")
    script = os.path.join(ondir, f"ondas_{mod}.py")
    manif = os.path.join(ondir, "ondas.json")

    if not os.path.exists(manif):
        if not os.path.exists(script):
            return (f"_Sin figuras de ondas._ Se generan con un script en "
                    f"`docs/{mod}/figuras/ondas/`, que saca las ondas de un "
                    f"VCD de los testbenches del módulo; el patrón está en "
                    f"[`docs/figuras/ondas.py`]"
                    f"({os.path.relpath(os.path.join(DOCS, 'figuras', 'ondas.py'), aqui)}).")
        return (f"_Las figuras no están generadas._ Correr "
                f"`python3 docs/{mod}/figuras/ondas/ondas_{mod}.py`.")

    try:
        with open(manif, encoding="utf-8") as fh:
            figs = json.load(fh)
    except (OSError, ValueError) as exc:
        return f"_No pude leer `{os.path.relpath(manif, MCA_ROOT)}`: {exc}_"

    out = []
    for f in figs:
        svg = os.path.join(ondir, f["archivo"])
        if not os.path.exists(svg):
            continue
        out += [f"**{f['titulo']}**", "",
                f"![{f['titulo']}]({os.path.relpath(svg, aqui)})", "",
                f"{f['nota']}", "",
                f"_Origen: {f['origen']}._", ""]

    if not out:
        return (f"_El manifiesto no lista ninguna figura existente._ Correr "
                f"`python3 docs/{mod}/figuras/ondas/ondas_{mod}.py`.")

    out += ["---", "",
            f"Las figuras y sus epígrafes los escribe "
            f"[`ondas_{mod}.py`]({os.path.relpath(script, aqui)}): los tiempos "
            f"y las latencias se **miden sobre el VCD**, no se escriben a "
            f"mano, así que no pueden desincronizarse del RTL. Los epígrafes "
            f"completos, con los números, están en "
            f"[`epigrafes.txt`]({os.path.relpath(os.path.join(ondir, 'epigrafes.txt'), aqui)}).",
            "",
            f"```bash",
            f"python3 docs/{mod}/figuras/ondas/ondas_{mod}.py    # regenerar",
            f"```", ""]
    return "\n".join(out)


def plural(n: int, sing: str, art: str = "") -> str:
    """"1 testbench" / "6 testbenches", con articulo opcional ("el"/"los")."""
    palabra = sing if n == 1 else (
        sing + "es" if sing[-1] in "chlrnsy" else sing + "s")
    if art:
        art = {"los": "el", "las": "la"}.get(art, art) if n == 1 else art
        return f"{art} {n} {palabra}"
    return f"{n} {palabra}"


def sec_casos(iface, ctx: dict) -> str:
    """La tabla de casos cubiertos de VERIFICACION.md, desde los TB.

    Es la seccion que en los cinco modulos quedo con una fila en blanco desde
    que create_module.py la escribio. Los casos existen: estan en los
    check("...") de los testbenches. Esto los trae.
    """
    mod = ctx["module"]
    harvest = ctx["harvest"]
    aqui = os.path.dirname(ctx["md_path"])
    out = ["<!-- Esta tabla la escribe `modulos/mk/datasheet.py` leyendo los",
           "     testbenches: las escenas numeradas (`// N) ...`) y el nombre de",
           "     cada check(). No editarla a mano. Lo de abajo (casos borde,",
           "     assertions, metas) SI es a mano y no se toca. -->", ""]

    n_tot = sum(len(t.checks) for t in harvest)
    if not n_tot:
        return "\n".join(out + ["_Ningún testbench declara casos con nombre._", ""])

    out += [f"**{plural(n_tot, 'caso')} con nombre** en "
            f"{plural(len(harvest), 'testbench')}. Cada fila es un `check()` "
            f"que corre y tiene que dar PASS; el testbench entero falla si "
            f"alguno no da.", ""]

    for tb in harvest:
        if not tb.checks:
            continue
        enlace = (f"[`{tb.name}`]({os.path.relpath(tb.path, aqui)})"
                  if os.path.exists(tb.path) else f"`{tb.name}`")
        cab = [f"### {enlace} — `{tb.dut}`" if tb.dut else f"### {enlace}", ""]
        if tb.modelo:
            cab += [f"Compara contra el {tb.modelo}: no son valores esperados "
                    f"escritos a mano sino una **equivalencia** ciclo a ciclo "
                    f"sobre todo el estímulo.", ""]
        rows = []
        for e in tb.escenas:
            for i, c in enumerate(e.checks):
                rows.append((f"{e.num}" if i == 0 else "",
                             e.titulo if i == 0 else "", c))
        for c in tb.huerfanos:
            rows.append(("", "", c))
        out += cab + [md_table(["Escena", "Qué prueba", "Caso"], rows,
                               drop_empty=True), ""]
    return "\n".join(out)


VERIF_SECTIONS = [
    ("casos", sec_casos, r"^##[ \t]*Casos cubiertos[ \t]*$"),
]


# (clave, generador, ancla). El ancla es el encabezado despues del cual se
# INSERTA el bloque si la marca no esta: sin eso, agregar una seccion dejaria a
# las paginas que ya existen sin esa seccion para siempre, y la unica salida
# seria borrarlas y regenerarlas, perdiendo la prosa. Se busca por el texto del
# encabezado y no por su numero, porque los numeros se corren al agregar
# secciones.
SECTIONS = [
    ("resumen", sec_resumen, r"^#{3,4}[ \t]*[\d.]*[ \t]*Descripción breve[ \t]*$"),
    # El ancla de la prosa no es un encabezado sino el CIERRE del bloque de
    # arriba: va pegada al resumen, dentro de la misma §1.1, y no tiene titulo
    # propio. insert_after busca una linea, le da lo mismo cual.
    ("prosa", sec_prosa, r"^<!-- /AUTO:resumen -->[ \t]*$"),
    ("interfaces", sec_interfaces, r"^#{3,4}[ \t]*[\d.]*[ \t]*Interfaces[ \t]*$"),
    ("regmap", sec_regmap, r"^#{3,4}[ \t]*[\d.]*[ \t]*Mapa de registros[ \t]*$"),
    ("clocks", sec_clocks, r"^#{3,4}[ \t]*[\d.]*[ \t]*Clock domains[ \t]*$"),
    ("timing", sec_timing, r"^#{3,4}[ \t]*[\d.]*[ \t]*Frecuencia máxima de trabajo[ \t]*$"),
    ("transacciones", sec_transacciones,
     r"^#{3,4}[ \t]*[\d.]*[ \t]*Transacciones[ \t]*$"),
    ("ondas", sec_ondas, r"^#{3,4}[ \t]*[\d.]*[ \t]*Waveforms[ \t]*$"),
    ("verificacion", sec_verificacion,
     r"^#{3,4}[ \t]*[\d.]*[ \t]*Verificación realizada[ \t]*$"),
]


# --------------------------------------------------------------------------- #
# Scaffold y splice
# --------------------------------------------------------------------------- #
def auto(key: str, body: str) -> str:
    return f"<!-- AUTO:{key} -->\n{body.rstrip()}\n<!-- /AUTO:{key} -->"


def scaffold(iface: Iface, ctx: dict) -> str:
    g = {k: fn(iface, ctx) for k, fn, _ in SECTIONS}
    # Ojo con las marcas AUTO adentro de este comentario: los comentarios de
    # HTML no anidan, asi que el primer cierre cortaria el comentario y el resto
    # del texto se veria en la pagina. Por eso se nombran sin los delimitadores.
    return f"""# Datasheet — `{iface.name}`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     La §1.1 «Qué hace» se escribe en {ctx['prosa_rel']}.
     Regenerar:  make -C modulos/{ctx['module']}/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

{auto('resumen', g['resumen'])}

{auto('prosa', g['prosa'])}

### 1.2 Interfaces

{auto('interfaces', g['interfaces'])}

### 1.3 Mapa de registros

{auto('regmap', g['regmap'])}

### 1.4 Clock domains

{auto('clocks', g['clocks'])}

<!-- A mano: si hay más de un reloj, cuál es el cruce, con qué se sincroniza y
     qué se asume de la relación de frecuencias. Si hay uno solo, borrar. -->

### 1.5 Frecuencia máxima de trabajo

{auto('timing', g['timing'])}

<!-- A mano: qué hay en el camino crítico y qué se haría para romperlo si
     hubiera que subir la frecuencia. -->

### 1.6 Transacciones

{auto('transacciones', g['transacciones'])}

### 1.7 Waveforms

{auto('ondas', g['ondas'])}

<!-- A mano: lo que las figuras no pueden mostrar solas. Para agregar una,
     editar docs/{ctx['module']}/figuras/ondas/ondas_{ctx['module']}.py: la onda
     sale de un VCD de los testbenches y los tiempos los mide el script.
       make -C modulos/{ctx['module']}/work wave TB=<tb>   # mirar en Questa
       make -C modulos/{ctx['module']}/work vcd  TB=<tb>   # VCD exportable -->

### 1.8 Verificación realizada

{auto('verificacion', g['verificacion'])}

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
"""


def splice_re(key: str):
    return re.compile(r"(<!-- AUTO:%s -->)(.*?)(<!-- /AUTO:%s -->)" % (key, key),
                      re.DOTALL)


SPLICE_RE = {k: splice_re(k) for k, _, _ in SECTIONS}


def insert_after(text: str, anchor: str, block: str):
    """Mete `block` despues del encabezado que matchea `anchor`.

    Devuelve (texto, True) si pudo. Se inserta despues del encabezado y de la
    linea en blanco que le sigue, para que el bloque quede donde lo habria
    puesto el scaffold.
    """
    m = re.search(anchor, text, re.MULTILINE)
    if not m:
        return text, False
    fin = text.find("\n", m.end())
    fin = len(text) if fin < 0 else fin + 1
    # Normalizar a UNA linea en blanco a cada lado, sin importar cuantas habia:
    # si no, re-insertar sobre un archivo ya tocado va acumulando blancos y la
    # salida deja de ser idempotente respecto de la insercion.
    return (text[:fin] + "\n" + block + "\n\n" + text[fin:].lstrip("\n")), True


def splice(old: str, iface: Iface, ctx: dict, sections=None):
    """Reescribe las regiones AUTO de una pagina ya existente.

    Si una marca no esta, el bloque se INSERTA despues de su encabezado ancla:
    asi una seccion nueva llega sola a las paginas que ya existen, sin pisar la
    prosa y sin tener que borrarlas. Solo se avisa cuando tampoco hay ancla.
    """
    new, missing = old, []
    for key, fn, anchor in (sections or SECTIONS):
        body = fn(iface, ctx).rstrip()
        rx = SPLICE_RE.get(key) or splice_re(key)
        if rx.search(new):
            # El reemplazo es una funcion, no un string: lo que devuelve se usa
            # tal cual y no hay que escapar nada (un \ de un path quedaria
            # duplicado).
            new = rx.sub(lambda m: m.group(1) + "\n" + body + "\n" + m.group(3),
                         new, count=1)
            continue
        new, ok = insert_after(new, anchor, auto(key, body))
        if not ok:
            missing.append(key)
    return new, missing


# --------------------------------------------------------------------------- #
# Orquestacion
# --------------------------------------------------------------------------- #
def rel_repo(path: str) -> str:
    """La ruta como se imprime: relativa al repo, o completa si esta afuera."""
    rel = os.path.relpath(path, REPO_ROOT)
    return path if rel.startswith("..") else rel


def write_if_changed(path: str, content: str, check: bool, label: str) -> bool:
    old = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            old = fh.read()
    rel = rel_repo(path)
    if old == content:
        print(f"  [=]    {rel}")
        return True
    if check:
        print(f"  [VIEJO] {rel}  ({label} cambió)")
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"  [{'UPD' if old is not None else 'NEW'}]  {rel}")
    return True


def resolve_rtl(module: str, top: str):
    """Ubica el .sv de un top dentro del modulo, via files.f o rtl/."""
    moddir = os.path.join(MODULOS, module)
    cands = []
    flist = os.path.join(moddir, "files.f")
    if os.path.exists(flist):
        with open(flist) as fh:
            for line in fh:
                line = line.split("#")[0].strip()
                if line:
                    cands.append(os.path.join(moddir, line))
    rtldir = os.path.join(moddir, "rtl")
    if os.path.isdir(rtldir):
        cands += [os.path.join(rtldir, f) for f in sorted(os.listdir(rtldir))
                  if f.endswith((".sv", ".v"))]
    for c in cands:
        if os.path.splitext(os.path.basename(c))[0] == top and os.path.exists(c):
            return c
    for c in cands:                      # el top puede no dar nombre al archivo
        if os.path.exists(c) and re.search(r"^\s*module\s+%s\b" % re.escape(top),
                                           open(c, errors="replace").read(),
                                           re.MULTILINE):
            return c
    raise SystemExit(f"[datasheet] no encontre el RTL de `{top}` en modulos/{module}")


def tops_of(module: str) -> list:
    """Los modulos RTL que declara files.f, en orden (hojas primero)."""
    flist = os.path.join(MODULOS, module, "files.f")
    out = []
    if not os.path.exists(flist):
        return out
    with open(flist) as fh:
        for line in fh:
            line = line.split("#")[0].strip()
            if not line:
                continue
            p = os.path.join(MODULOS, module, line)
            if not os.path.exists(p):
                continue
            for m in re.finditer(r"^\s*module\s+(\w+)", open(p, errors="replace").read(),
                                 re.MULTILINE):
                out.append(m.group(1))
    return out


def build(module: str, top: str, rtl: str, outdir: str, check: bool,
          generics: dict, tbs: list, svg_only: bool) -> bool:
    iface = parse_iface(rtl, top, generics)
    work = os.path.join(MODULOS, module, "work") if module else ""
    figdir = os.path.join(outdir, "figuras")
    fig = os.path.join(figdir, f"{iface.name}_interfaz.svg")
    md = os.path.join(outdir, f"datasheet_{iface.name}.md")
    prosa = os.path.join(outdir, "prosa", f"{iface.name}.md")

    ok = write_if_changed(fig, render_svg(iface), check, "diagrama")
    if svg_only:
        return ok

    # El archivo de prosa se crea vacio si falta y despues no se toca nunca
    # mas. Tenerlo siempre presente es lo que hace que se vea de un `ls` cual
    # top todavia no tiene explicacion escrita, y que la pagina se pueda borrar
    # y regenerar entera sin perder una linea de lo escrito a mano.
    if not os.path.exists(prosa) and not check:
        write_if_changed(prosa, PROSA_CAB.format(
            top=iface.name, pagina=os.path.relpath(md, os.path.dirname(prosa))),
            check, "prosa")

    ctx = {
        "module": module,
        "work": work,
        "md_path": md,
        "fig_rel": os.path.relpath(fig, os.path.dirname(md)),
        "prosa_path": prosa,
        "prosa_rel": os.path.relpath(prosa, os.path.dirname(md)),
        "rtl_rel": os.path.relpath(rtl, os.path.dirname(md)),
        "metrics": read_metrics(os.path.join(MODULOS, module, "syn", "outputs",
                                             "metrics.txt")) if module else {},
        "sweep": read_sweep(os.path.join(work, "rpt", "sweep_results.csv")) if work else [],
        "tbs": tbs,
        "harvest": harvest_tbs(module, tbs) if module else [],
    }

    if os.path.exists(md):
        with open(md, encoding="utf-8") as fh:
            old = fh.read()
        new, missing = splice(old, iface, ctx)
        for k in missing:
            print(f"  [!]    falta la marca <!-- AUTO:{k} --> en "
                  f"{os.path.relpath(md, REPO_ROOT)}: esa sección no se actualizó")
        ok &= write_if_changed(md, new, check, "datasheet")
    else:
        if check:
            print(f"  [FALTA] {rel_repo(md)}")
            return False
        ok &= write_if_changed(md, scaffold(iface, ctx), check, "datasheet")
    return ok


def build_verificacion(module: str, tbs: list, check: bool) -> bool:
    """Actualiza la tabla de casos cubiertos de modulos/<m>/sim/VERIFICACION.md.

    Es por MODULO, no por top: el plan de verificacion es uno solo aunque el
    modulo tenga varios tops con datasheet.
    """
    path = os.path.join(MODULOS, module, "sim", "VERIFICACION.md")
    if not os.path.exists(path):
        return True
    with open(path, encoding="utf-8") as fh:
        old = fh.read()
    ctx = {"module": module, "tbs": tbs, "md_path": path,
           "harvest": harvest_tbs(module, tbs)}
    new, missing = splice(old, None, ctx, VERIF_SECTIONS)
    for k in missing:
        print(f"  [!]    {os.path.relpath(path, REPO_ROOT)}: no hay marca "
              f"AUTO:{k} ni el encabezado «## Casos cubiertos» donde insertarla")
    return write_if_changed(path, new, check, "plan de verificación")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Datasheet por modulo de RTL: diagrama de interfaz + Markdown.")
    ap.add_argument("--module", "-m", help="modulo de modulos/ (mca, osc, ...)")
    ap.add_argument("--top", "-t", help="modulo RTL; default: el TOP del work/Makefile")
    ap.add_argument("--rtl", help="archivo .sv suelto (fuera de modulos/)")
    ap.add_argument("--out", help="directorio de salida; default: docs/<modulo>/")
    ap.add_argument("--generics", default=None,
                    help='override de parametros: "H_AW=13 H2_AW=7"')
    ap.add_argument("--all", action="store_true", help="todos los modulos")
    ap.add_argument("--all-tops", action="store_true",
                    help="todos los modulos RTL del modulo, no solo el TOP")
    ap.add_argument("--svg-only", action="store_true", help="solo el diagrama")
    ap.add_argument("--check", action="store_true",
                    help="no escribe; devuelve != 0 si algo quedo viejo (para CI)")
    args = ap.parse_args(argv)

    if args.rtl:
        rtl = os.path.abspath(args.rtl)
        iface_name = args.top
        if not iface_name:
            m = re.search(r"^\s*module\s+(\w+)", open(rtl, errors="replace").read(),
                          re.MULTILINE)
            iface_name = m.group(1) if m else None
        out = os.path.abspath(args.out or os.path.dirname(rtl))
        print(f"[datasheet] {iface_name}  ({os.path.relpath(rtl, REPO_ROOT)})")
        return 0 if build("", iface_name, rtl, out, args.check,
                          parse_generics(args.generics), [], args.svg_only) else 1

    mods = []
    if args.all:
        mods = [d for d in sorted(os.listdir(MODULOS))
                if os.path.exists(os.path.join(MODULOS, d, "files.f"))]
    elif args.module:
        mods = [args.module]
    else:
        ap.error("hace falta --module, --all o --rtl")

    ok = True
    for mod in mods:
        mk = read_make_vars(os.path.join(MODULOS, mod, "work", "Makefile"))
        tbs = mk.get("TBS", "").split()
        gen = parse_generics(args.generics if args.generics is not None
                             else mk.get("GENERICS", ""))
        if args.all_tops:
            tops = tops_of(mod)
        elif args.top and len(mods) == 1:
            tops = [args.top]
        else:
            tops = [mk.get("TOP", "")] if mk.get("TOP") else tops_of(mod)[-1:]
        if not tops or not tops[0]:
            print(f"[datasheet] {mod}: no declara TOP y files.f no da modulos; salto")
            continue
        # Todas las paginas van juntas a docs/datasheet/, sin importar de que
        # modulo salga cada top: son el mismo genero de documento y se buscan
        # por nombre de modulo RTL, no por carpeta. Las figuras propias de cada
        # modulo (ondas, transacciones, las del MCA) se quedan donde estan; a
        # la pagina llegan por relpath, que lo resuelve solo.
        outdir = os.path.abspath(args.out) if args.out else DS_DIR
        for top in tops:
            rtl = resolve_rtl(mod, top)
            print(f"[datasheet] {mod} / {top}  ({os.path.relpath(rtl, REPO_ROOT)})")
            ok &= build(mod, top, rtl, outdir, args.check, gen, tbs, args.svg_only)
        if not args.svg_only:
            ok &= build_verificacion(mod, tbs, args.check)
    if args.check and not ok:
        print("\n[datasheet] hay paginas viejas: correr `make datasheet` y commitear")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Generador de datasheets por modulo de RTL.

Lee la cabecera de un modulo SystemVerilog y emite dos cosas:

  1. docs/<modulo>/figuras/<top>_interfaz.svg
     El diagrama de bloques de la INTERFAZ: un simbolo con los puertos de
     entrada a la izquierda, los de salida a la derecha, agrupados por los
     banners `// --- grupo ---` que ya tiene el RTL del proyecto, con el ancho
     de cada bus resuelto con los parametros reales de sintesis.

  2. docs/<modulo>/datasheet_<top>.md
     El datasheet. Las secciones derivables del RTL y de la sintesis se
     escriben entre marcas `<!-- AUTO:x -->` ... `<!-- /AUTO:x -->` y se
     REESCRIBEN en cada corrida; todo lo que esta fuera de esas marcas es
     prosa a mano y NO se toca nunca. O sea: se puede regenerar despues de
     cambiar un puerto sin perder lo escrito.

Lo que se autogenera:

    resumen       nombre, archivo, MAGIC decodificado, conteo de puertos,
                  el banner de cabecera del RTL y el diagrama
    interfaces    tabla de parametros + una tabla de puertos por grupo
    regmap        enlace al mapa de registros del modulo, si existe
    clocks        relojes y resets detectados + dominio inferido por puerto
    timing        Fmax, camino critico (startpoint/endpoint, niveles de
                  logica) y recursos, de syn/outputs/metrics.txt y del
                  barrido work/rpt/sweep_results.csv
    verificacion  testbenches que declara el work/Makefile, assertions por
                  bind y enlace al plan de verificacion

Lo que queda a mano (el scaffold deja el titulo y una pista):

    funcionamiento, waveforms (handshakes y flujo de utilizacion),
    estrategia de CDC y esquema de laboratorio.

Uso:
    python3 datasheet.py --module mca                 # el TOP del work/Makefile
    python3 datasheet.py --module multitrigger --top trigger_shield
    python3 datasheet.py --module multitrigger --all-tops
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
import os
import re
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
MODULOS = os.path.abspath(os.path.join(HERE, ".."))
MCA_ROOT = os.path.abspath(os.path.join(MODULOS, ".."))
REPO_ROOT = os.path.abspath(os.path.join(MCA_ROOT, "..", ".."))
DOCS = os.path.join(MCA_ROOT, "docs")


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
        """Lo que va en la tabla: ancho resuelto y la expresion si difieren."""
        if not self.width_expr:
            return "1"
        if self.msb is None:
            return f"`[{self.width_expr}]`"
        if re.fullmatch(r"\d+:\d+", self.width_expr.replace(" ", "")):
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

    @property
    def ports(self):
        return [p for g in self.groups for p in g.ports]

    @property
    def rel(self) -> str:
        return os.path.relpath(self.path, REPO_ROOT)


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


_ALLOWED_BINOP = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
                  ast.Pow, ast.LShift, ast.RShift, ast.BitOr, ast.BitAnd,
                  ast.BitXor)


def _node_eval(node, env):
    if isinstance(node, ast.Expression):
        return _node_eval(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise KeyError(node.id)
        return env[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Invert)):
        v = _node_eval(node.operand, env)
        return +v if isinstance(node.op, ast.UAdd) else (-v if isinstance(node.op, ast.USub) else ~v)
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOP):
        a, b = _node_eval(node.left, env), _node_eval(node.right, env)
        if isinstance(node.op, ast.Div):
            return a / b
        return eval(  # noqa: S307 - arbol ya restringido a nodos aritmeticos
            compile(ast.Expression(ast.BinOp(ast.Constant(a), node.op, ast.Constant(b))),
                    "<expr>", "eval"))
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
    return out


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
    port_txt, _ = balanced(text, off)

    iface = Iface(name=mod_name, path=os.path.abspath(path),
                  banner=leading_banner(lines, mod_line))

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
                p.value, p.overridden = gv, True
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

        names = [x.strip() for x in dm.group("names").split(",") if x.strip()]
        for k, nm in enumerate(names):
            cur.ports.append(Port(
                dir=d, name=nm, width_expr=w, bits=bits, msb=msb, lsb=lsb,
                kind=dm.group("kind") or dm.group("kind2") or "",
                signed=dm.group("sign") == "signed",
                desc=(comment or "") if k == len(names) - 1 else "",
                notes=list(pending) if not cur.ports else list(pending),
            ))
        # los comentarios de arriba del PRIMER puerto de un grupo describen al
        # grupo, no al puerto: es como esta escrito el RTL del proyecto
        if pending and len(cur.ports) == len(names):
            cur.doc = list(pending)
            for p in cur.ports:
                p.notes = []
        pending = []

    if cur.ports or cur.name:
        iface.groups.append(cur)

    assign_domains(iface)
    return iface


# --------------------------------------------------------------------------- #
# Relojes, resets y dominios
# --------------------------------------------------------------------------- #
CLK_RE = re.compile(r"(^|_)(clk|clock)(_|\d|$)", re.I)
RST_RE = re.compile(r"(^|_)(rst|rstn|reset|resetn|aresetn|nrst)(_|\d|$)", re.I)


def is_clock(p: Port) -> bool:
    return p.dir == "input" and p.bits == 1 and bool(CLK_RE.search(p.name))


def is_reset(p: Port) -> bool:
    return p.dir == "input" and p.bits == 1 and bool(RST_RE.search(p.name))


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
# Diagrama de bloques de la interfaz (SVG a mano)
# --------------------------------------------------------------------------- #
FS_PIN, FS_W, FS_GRP, FS_TITLE, FS_SUB, FS_PAR = 12, 9.5, 10, 16, 9.5, 10.5
ROW, BAND_GAP, STUB, CENTER_GAP = 21, 21, 58, 46
PAD, BOX_PAD_X, HDR_PAD = 14, 12, 12
CHAR = 0.60          # ancho de caracter en monoespaciada, en unidades de FS


def tw(s: str, fs: float) -> float:
    return len(s) * fs * CHAR


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def param_lines(iface: Iface) -> list:
    out = []
    for p in iface.params:
        v = p.default if p.value is None else (
            p.default if str(p.value) == p.default.strip() else f"{p.value}")
        mark = "*" if p.overridden else ""
        out.append(f"{p.name}={v}{mark}")
    return out


def render_svg(iface: Iface, generics: dict) -> str:
    # --- bandas: cada grupo ocupa max(entradas, salidas) filas ---------------
    bands = []
    clocks = [p for p in iface.ports if is_clock(p) or is_reset(p)]
    if clocks:
        bands.append(("reloj y reset", clocks, []))
    for g in iface.groups:
        ins = [p for p in g.ins if p not in clocks]
        outs = list(g.outs)
        if ins or outs:
            bands.append((g.name, ins, outs))

    # --- geometria -----------------------------------------------------------
    name_l = max([tw(p.name, FS_PIN) for _, i, _ in bands for p in i] or [0])
    name_r = max([tw(p.name, FS_PIN) for _, _, o in bands for p in o] or [0])
    lbl_l = max([tw(p.width_label, FS_W) for _, i, _ in bands for p in i] or [0])
    lbl_r = max([tw(p.width_label, FS_W) for _, _, o in bands for p in o] or [0])

    plines = param_lines(iface)
    n_col = 1 if len(plines) <= 6 else (2 if len(plines) <= 16 else 3)
    rows_pc = -(-len(plines) // n_col) if plines else 0
    col_w = [max([tw(s, FS_PAR) for s in plines[c * rows_pc:(c + 1) * rows_pc]] or [0])
             for c in range(n_col)]
    par_w = sum(col_w) + 22 * max(0, n_col - 1)

    hdr_txt_w = max(tw(iface.name, FS_TITLE), tw(iface.rel, FS_SUB), par_w)
    box_w = max(name_l + CENTER_GAP + name_r + 2 * BOX_PAD_X, hdr_txt_w + 2 * HDR_PAD)

    hdr_h = HDR_PAD + FS_TITLE + 5 + FS_SUB + (
        (10 + rows_pc * (FS_PAR + 4)) if plines else 0) + HDR_PAD
    body_h = sum(BAND_GAP + max(len(i), len(o)) * ROW for _, i, o in bands) + 10
    box_h = hdr_h + body_h

    x_box = PAD + lbl_l + 6 + STUB
    x_end = x_box + box_w
    W = x_end + STUB + 6 + lbl_r + PAD
    H = PAD + box_h + PAD
    y_box = PAD

    s = []
    a = s.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
      f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="ui-monospace,SFMono-Regular,'
      f'Menlo,Consolas,monospace">')
    a("""<style>
  .bg{fill:#ffffff}            .box{fill:#ffffff;stroke:#1b1f24;stroke-width:1.6}
  .hdr{fill:#f2f4f7;stroke:none}
  .rule{stroke:#1b1f24;stroke-width:1.1}
  .sep{stroke:#c3cad1;stroke-width:0.9;stroke-dasharray:4 4}
  .pin{stroke:#1b1f24;stroke-width:1.3;fill:none}
  .arr{fill:#1b1f24;stroke:none}
  .nm{fill:#1b1f24}            .wd{fill:#57606a}
  .gp{fill:#0b6bcb;font-style:italic}
  .ti{fill:#1b1f24;font-weight:700} .sb{fill:#57606a} .pr{fill:#24292f}
  @media (prefers-color-scheme: dark){
    .bg{fill:#0d1117}          .box{fill:#0d1117;stroke:#c9d1d9}
    .hdr{fill:#161b22}         .rule{stroke:#c9d1d9}
    .sep{stroke:#30363d}       .pin{stroke:#c9d1d9}
    .arr{fill:#c9d1d9}         .nm{fill:#e6edf3} .wd{fill:#8b949e}
    .gp{fill:#58a6ff}          .ti{fill:#e6edf3} .sb{fill:#8b949e} .pr{fill:#c9d1d9}
  }
</style>""")
    a(f'<rect class="bg" x="0" y="0" width="{W:.0f}" height="{H:.0f}"/>')
    a(f'<rect class="box" x="{x_box:.1f}" y="{y_box:.1f}" width="{box_w:.1f}" '
      f'height="{box_h:.1f}" rx="4"/>')

    # --- encabezado ----------------------------------------------------------
    a(f'<rect class="hdr" x="{x_box + 1:.1f}" y="{y_box + 1:.1f}" '
      f'width="{box_w - 2:.1f}" height="{hdr_h - 1:.1f}" rx="3"/>')
    xc = x_box + box_w / 2
    yt = y_box + HDR_PAD + FS_TITLE
    a(f'<text class="ti" x="{xc:.1f}" y="{yt:.1f}" font-size="{FS_TITLE}" '
      f'text-anchor="middle">{esc(iface.name)}</text>')
    a(f'<text class="sb" x="{xc:.1f}" y="{yt + 5 + FS_SUB:.1f}" font-size="{FS_SUB}" '
      f'text-anchor="middle">{esc(iface.rel)}</text>')
    if plines:
        y0 = yt + 5 + FS_SUB + 12 + FS_PAR
        x0 = xc - par_w / 2
        for c in range(n_col):
            for r, txt in enumerate(plines[c * rows_pc:(c + 1) * rows_pc]):
                a(f'<text class="pr" x="{x0:.1f}" y="{y0 + r * (FS_PAR + 4):.1f}" '
                  f'font-size="{FS_PAR}">{esc(txt)}</text>')
            x0 += col_w[c] + 22
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

    y = y_box + hdr_h
    for bi, (gname, ins, outs) in enumerate(bands):
        if bi:
            a(f'<line class="sep" x1="{x_box:.1f}" y1="{y:.1f}" '
              f'x2="{x_end:.1f}" y2="{y:.1f}"/>')
        if gname:
            a(f'<text class="gp" x="{x_box + BOX_PAD_X:.1f}" '
              f'y="{y + BAND_GAP - 7:.1f}" font-size="{FS_GRP}">{esc(gname)}</text>')
        top = y + BAND_GAP
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
        line = split_comment(line)[0]
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
# Secciones del Markdown
# --------------------------------------------------------------------------- #
def md_table(head: list, rows: list) -> str:
    if not rows:
        return "_(nada)_\n"
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
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


def sec_interfaces(iface: Iface, ctx: dict) -> str:
    out = ["### Parámetros", ""]
    if iface.params:
        rows = []
        for p in iface.params:
            val = f"`{p.default}`"
            if p.overridden:
                val += f" → **`{p.value}`** (del TOP)"
            elif p.value is not None and str(p.value) != p.default.strip():
                val += f" = `{p.value}`"
            rows.append((f"`{p.name}`", f"`{p.kind}`" if p.kind else "", val, p.desc))
        out.append(md_table(["Parámetro", "Tipo", "Default", "Para qué"], rows))
        if any(p.overridden for p in iface.params):
            out += ["", "Los marcados **(del TOP)** son los valores con los que el "
                        "diseño se construye de verdad (`GENERICS` del "
                        "`work/Makefile`); los anchos de esta página están "
                        "resueltos con ésos, no con los defaults del RTL.", ""]
    else:
        out.append("_Sin parámetros._\n")

    out += ["", "### Puertos", ""]
    for g in iface.groups:
        if not g.ports:
            continue
        out.append(f"#### {g.name or 'Señales'}")
        out.append("")
        if g.doc:
            out += [" ".join(g.doc), ""]
        rows = []
        for p in g.ports:
            d = {"input": "in", "output": "out", "inout": "inout"}[p.dir]
            desc = " ".join([*p.notes, p.desc]).strip()
            rows.append((f"`{p.name}`", d, p.width_doc,
                         "signed" if p.signed else "", p.domain, desc))
        out.append(md_table(["Puerto", "Dir", "Bits", "", "Dominio", "Descripción"], rows))
        out.append("")
    return "\n".join(out)


def sec_regmap(iface: Iface, ctx: dict) -> str:
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
        out.append(f"- [`{f}`]({f})")
    out += ["", "Contrato del bus: [`../TOP/bus_sistema_redpitaya.md`]"
                "(../TOP/bus_sistema_redpitaya.md) · "
                "Mapa de slots: [`../TOP/register_map_top.md`]"
                "(../TOP/register_map_top.md)", ""]
    return "\n".join(out)


def sec_clocks(iface: Iface, ctx: dict) -> str:
    clks = [p for p in iface.ports if is_clock(p)]
    rsts = [p for p in iface.ports if is_reset(p)]
    out = []
    rows = [(f"`{p.name}`", "reloj", "", p.desc) for p in clks]
    for p in rsts:
        pol = "activo-bajo" if re.search(r"(rstn|resetn|aresetn|nrst)", p.name, re.I) \
              else "activo-alto"
        dom = clk_prefix(p.name)
        cl = [c for c in clks if clk_prefix(c.name) == dom]
        rows.append((f"`{p.name}`", "reset", pol,
                     p.desc or (f"del dominio `{cl[0].name}`" if cl else "")))
    out.append(md_table(["Puerto", "Qué es", "Polaridad", "Notas"], rows))
    out.append("")

    if len(clks) == 1:
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
    tbs = ctx["tbs"]
    rows = []
    for tb in tbs:
        p = os.path.join(simdir, tb + ".sv")
        dut = tb[3:] if tb.startswith("tb_") else ""
        rows.append((f"`{tb}`" if not os.path.exists(p) else
                     f"[`{tb}`]({os.path.relpath(p, os.path.dirname(ctx['md_path']))})",
                     f"`{dut}`" if dut else "",
                     "sí" if dut == iface.name else ""))
    out = [f"Todo corre en batch y se chequea el `RESULT: PASS` del testbench; "
           f"las ondas quedan en `work/waves/<tb>.wlf`.", "",
           "```bash",
           f"make -C modulos/{mod}/work            # los {len(tbs)} testbenches",
           f"make -C modulos/{mod}/work cov        # + cobertura",
           f"make -C modulos/{mod}/work lint",
           "```", "",
           md_table(["Testbench", "DUT", "Es el de este módulo"], rows), ""]

    svadir = os.path.join(simdir, "sva")
    if os.path.isdir(svadir):
        sva = sorted(f for f in os.listdir(svadir) if f.endswith(".sv"))
        if sva:
            out += ["**Assertions** — en `sim/sva/`, enganchadas por `bind` (no "
                    "tocan el RTL sintetizable).", ""]
            out += [f"- [`{f}`]({os.path.relpath(os.path.join(svadir, f), os.path.dirname(ctx['md_path']))})"
                    for f in sva]
            out.append("")

    plan = os.path.join(simdir, "VERIFICACION.md")
    if os.path.exists(plan):
        out += ["Plan de verificación, casos cubiertos y deuda: "
                f"[`{mod}/sim/VERIFICACION.md`]"
                f"({os.path.relpath(plan, os.path.dirname(ctx['md_path']))}).", ""]
    return "\n".join(out)


SECTIONS = [
    ("resumen", sec_resumen),
    ("interfaces", sec_interfaces),
    ("regmap", sec_regmap),
    ("clocks", sec_clocks),
    ("timing", sec_timing),
    ("verificacion", sec_verificacion),
]


# --------------------------------------------------------------------------- #
# Scaffold y splice
# --------------------------------------------------------------------------- #
def auto(key: str, body: str) -> str:
    return f"<!-- AUTO:{key} -->\n{body.rstrip()}\n<!-- /AUTO:{key} -->"


def scaffold(iface: Iface, ctx: dict) -> str:
    g = {k: fn(iface, ctx) for k, fn in SECTIONS}
    return f"""# Datasheet — `{iface.name}`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre
     `<!-- AUTO:x -->` y `<!-- /AUTO:x -->` se REESCRIBE en cada corrida:
     editar ahí no sirve. Todo el resto es prosa a mano y no se toca.
     Regenerar:  make -C modulos/{ctx['module']}/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

{auto('resumen', g['resumen'])}

<!-- A mano: qué problema resuelve el bloque, cómo encaja en la cadena y las
     dos o tres decisiones de diseño que explican por qué está hecho así. -->

**Qué hace.** TODO

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

### 1.6 Waveforms

<!-- A mano. Las ondas salen de los testbenches del módulo:
       make -C modulos/{ctx['module']}/work wave TB=<tb>   # ver en Questa
       make -C modulos/{ctx['module']}/work vcd  TB=<tb>   # VCD exportable
     Para dibujarlas acá, WaveDrom en un bloque ```wavedrom. -->

#### Handshakes

TODO — una onda por protocolo de la interfaz (bus, valid/ack, pulso de
comando) con los ciclos de latencia marcados.

#### Flujo de utilización

TODO — la secuencia completa de uso, de la configuración al dato leído, en el
orden en que la hace el software.

### 1.7 Verificación realizada

{auto('verificacion', g['verificacion'])}

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
"""


SPLICE_RE = {k: re.compile(r"(<!-- AUTO:%s -->)(.*?)(<!-- /AUTO:%s -->)" % (k, k),
                           re.DOTALL) for k, _ in SECTIONS}


def splice(old: str, iface: Iface, ctx: dict):
    """Reescribe las regiones AUTO de un datasheet ya existente."""
    new, missing = old, []
    for key, fn in SECTIONS:
        body = fn(iface, ctx).rstrip()
        rx = SPLICE_RE[key]
        if not rx.search(new):
            missing.append(key)
            continue
        new = rx.sub(lambda m: m.group(1) + "\n" + body.replace("\\", "\\\\") + "\n" + m.group(3),
                     new, count=1)
    return new, missing


# --------------------------------------------------------------------------- #
# Orquestacion
# --------------------------------------------------------------------------- #
def write_if_changed(path: str, content: str, check: bool, label: str) -> bool:
    old = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            old = fh.read()
    rel = os.path.relpath(path, REPO_ROOT)
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

    ok = write_if_changed(fig, render_svg(iface, generics), check, "diagrama")
    if svg_only:
        return ok

    ctx = {
        "module": module,
        "work": work,
        "md_path": md,
        "fig_rel": os.path.relpath(fig, os.path.dirname(md)),
        "rtl_rel": os.path.relpath(rtl, os.path.dirname(md)),
        "metrics": read_metrics(os.path.join(MODULOS, module, "syn", "outputs",
                                             "metrics.txt")) if module else {},
        "sweep": read_sweep(os.path.join(work, "rpt", "sweep_results.csv")) if work else [],
        "tbs": tbs,
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
            print(f"  [FALTA] {os.path.relpath(md, REPO_ROOT)}")
            return False
        ok &= write_if_changed(md, scaffold(iface, ctx), check, "datasheet")
    return ok


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
        outdir = os.path.abspath(args.out) if args.out else os.path.join(DOCS, mod)
        for top in tops:
            rtl = resolve_rtl(mod, top)
            print(f"[datasheet] {mod} / {top}  ({os.path.relpath(rtl, REPO_ROOT)})")
            ok &= build(mod, top, rtl, outdir, args.check, gen, tbs, args.svg_only)
    if args.check and not ok:
        print("\n[datasheet] hay paginas viejas: correr `make datasheet` y commitear")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

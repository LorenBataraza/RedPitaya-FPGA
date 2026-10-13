#!/usr/bin/env python3
"""Biblioteca para dibujar diagramas de tiempo con WaveDrom a partir de
simulaciones de verdad.

Es la mitad reusable de `docs/TOP/figuras/bus_sistema/figuras_bus_sistema.py`,
que fue la primera figura de este tipo del proyecto y fijo la convencion:

  - las ondas salen de un VCD/FST de un testbench del arbol, no de un esquema
    dibujado a mano;
  - los tiempos y las latencias las MIDE el script sobre el VCD y las escribe en
    las etiquetas y en los epigrafes, asi que no pueden desincronizarse del
    dibujo cuando cambia el RTL o el testbench;
  - el WaveJSON se versiona junto al SVG, para que la figura se pueda rehacer
    sin tener el renderer instalado.

Lo que se paga es que WaveDrom es por CICLOS, no por tiempo: hay que muestrear.
`build_grid()` arma una grilla alineada a los flancos de un reloj de referencia,
asi que ese dominio cae exacto y cualquier otro reloj asincronico queda
cuantizado al medio ciclo mas cercano. Es aproximado a proposito: las columnas
son semiciclos del reloj de referencia, no nanosegundos.

Que hay aca:

    open_waves / Vcd          VCD o FST -> {nombre: [(t_ps, valor)]}
    build_grid / column_of    el puente entre el tiempo del VCD y las columnas
    sample / row / nodes      filas de WaveJSON de una senal
    filtrar_edges            saca las flechas cuyos nodos no existen
    render                    WaveJSON -> SVG (wavedrom-cli o el modulo python)
    write_html                visor que dibuja desde el CDN, sin instalar nada
    write_epigrafes           los epigrafes, con los numeros medidos
    escenas                   las escenas numeradas de un testbench
    esquema                   WaveJSON a mano, para las figuras de secuencia

Las figuras de SECUENCIA (el flujo de utilizacion) se arman con `esquema()`: ahi
una columna es una transaccion y no un ciclo, no hay VCD detras y se marca como
esquema en el epigrafe. Todo lo que afirma un numero de ciclos va por el camino
del VCD.
"""

import json
import math
import os
import re
import shutil
import subprocess
import sys
import textwrap
from bisect import bisect_left
from contextlib import contextmanager
from html import escape
from pathlib import Path

# Chars de bus de WaveDrom: '=' es el relleno neutro, los numeros son colores
# del skin. Se usan para que salten las filas donde el dato se mueve de verdad.
BUS, BUS_DATA, BUS_ADDR = "=", "3", "5"


# ----------------------------------------------------------------------
# Fuente de ondas: VCD o FST
# ----------------------------------------------------------------------

@contextmanager
def open_waves(path):
    """Entrega el texto VCD de `path`, sea un .vcd o un .fst.

    Las ondas se versionan en FST porque ocupa ~10x menos que el VCD crudo.
    fst2vcd (oss-cad-suite) lo traduce de vuelta por stdout, asi que el parser
    de abajo ve siempre el mismo formato y no queda una copia en disco.
    """
    path = Path(path)
    if path.suffix.lower() != ".fst":
        with path.open() as fh:
            yield fh
        return

    try:
        proc = subprocess.Popen(["fst2vcd", str(path)],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                text=True)
    except FileNotFoundError:
        sys.exit(f"falta fst2vcd (oss-cad-suite) para leer {path}")
    try:
        yield proc.stdout
    finally:
        proc.stdout.close()
        rc = proc.wait()
        # -13 es SIGPIPE: pasa si el parser corta antes de consumir todo.
        if rc not in (0, -13):
            sys.exit(f"fst2vcd fallo sobre {path} (codigo {rc})")


# ----------------------------------------------------------------------
# Lector de VCD (independiente a proposito: no necesita matplotlib)
# ----------------------------------------------------------------------

class Vcd:
    """VCD/FST -> {nombre: [(t_ps, valor_binario)]} del scope raiz del TB.

    Reensambla los vectores. Questa escribe los buses BIT POR BIT

        $var wire 1 5 m_addr [31] $end
        $var wire 1 6 m_addr [30] $end   ...

    asi que sin reensamblarlos los 32 bits de `m_addr` se pisarian entre si y
    las filas de direccion y dato saldrian como un bit suelto.
    """

    def __init__(self, path, scope_depth=1):
        self.timescale_ps = 1.0
        self.changes = {}
        self._parse(Path(path), scope_depth)

    def _parse(self, path, scope_depth):
        raw = {}                   # id VCD -> [(t_ps, valor)]
        bits = {}                  # nombre -> {indice de bit: id VCD}
        plain = {}                 # nombre -> id VCD (señal entera)
        scope = []
        t = 0
        in_defs = True

        with open_waves(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue

                if in_defs:
                    if line.startswith("$timescale"):
                        tok = line.replace("$timescale", "").replace("$end", "").strip()
                        if tok:
                            self.timescale_ps = _ts_to_ps(tok)
                        continue
                    if line.startswith("$scope"):
                        scope.append(line.split()[2])
                        continue
                    if line.startswith("$upscope"):
                        scope.pop()
                        continue
                    if line.startswith("$var"):
                        # $var wire 1 5 m_addr [31] $end
                        # $var reg  8 ! addr [7:0] $end
                        # $var reg  1 0 clk_ps $end
                        p = line.split()
                        if len(scope) != scope_depth:   # solo el scope pedido
                            continue
                        kind, vid, name = p[1], p[3], p[4]
                        if kind == "parameter":      # constantes: no son ondas
                            continue
                        rango = p[5] if len(p) > 6 else None
                        raw.setdefault(vid, [])
                        idx = _bit_index(rango)
                        if idx is None:
                            plain[name] = vid
                        else:
                            bits.setdefault(name, {})[idx] = vid
                        continue
                    if line.startswith("$enddefinitions"):
                        in_defs = False
                        continue
                    if not line.startswith("$") and not scope and not raw:
                        self.timescale_ps = _ts_to_ps(line)
                    continue

                if line[0] == "#":
                    t = int(line[1:])
                    continue
                if line[0] in "bB":
                    val, vid = line[1:].split()
                elif line[0] in "rR" or line[0] == "$":
                    continue
                else:
                    val, vid = line[0], line[1:]
                if vid in raw:
                    raw[vid].append((t, val))

        for name, vid in plain.items():
            self.changes[name] = raw[vid]
        for name, mapa in bits.items():
            self.changes[name] = _merge_bits(mapa, raw)

    # ---- consultas -------------------------------------------------

    def __contains__(self, name):
        return name in self.changes

    def require(self, *names):
        """Aborta con un mensaje util si falta alguna señal.

        Es el error mas comun al escribir una figura nueva: un nombre mal
        escrito, o una señal que vive en un submodulo y no en el scope del TB.
        """
        faltan = [n for n in names if n not in self.changes]
        if faltan:
            hay = ", ".join(sorted(self.changes)[:25])
            sys.exit(f"el VCD no tiene {', '.join(faltan)}\n"
                     f"  hay: {hay}{' ...' if len(self.changes) > 25 else ''}")

    def value_at(self, name, t_ps):
        """Ultimo valor de `name` en o antes de t_ps (string crudo del VCD).

        En t_ps exacto devuelve el valor NUEVO: muestrear sobre el flanco da lo
        que la señal vale DURANTE el ciclo que arranca ahi, que es justo lo que
        una columna de WaveDrom representa.
        """
        out = None
        for tc, v in self.changes[name]:
            if tc > t_ps:
                break
            out = v
        return out

    def edges(self, name, pred, after=None):
        """Tiempos en los que el valor entero pasa a cumplir pred (y antes no)."""
        res, prev = [], None
        for tc, v in self.changes[name]:
            cur = _to_int(v)
            if cur is not None and (prev is None or not pred(prev)) and pred(cur):
                if after is None or tc >= after:
                    res.append(tc)
            prev = cur
        return res

    def first_edge(self, name, pred, after):
        e = self.edges(name, pred, after)
        return e[0] if e else None

    def nth_edge(self, name, pred, n, after=None):
        """El n-esimo flanco (1 = el primero). Para ubicar una escena cuando el
        TB repite el mismo estimulo con distinta configuracion."""
        e = self.edges(name, pred, after)
        return e[n - 1] if len(e) >= n else None

    def interval(self, name, value):
        """[inicio, fin] del primer tramo en que `name` vale `value`."""
        start = None
        for tc, v in self.changes[name]:
            cur = _to_int(v)
            if start is None and cur == value:
                start = tc
            elif start is not None and cur != value:
                return start, tc
        return (start, None) if start is not None else (None, None)

    def period(self, name):
        """Periodo de un reloj, medido entre dos flancos de subida."""
        ups = self.edges(name, lambda v: v == 1)
        return (ups[1] - ups[0]) if len(ups) > 1 else 1000

    def change_after(self, name, t_start, t_end):
        """Primer instante en que `name` cambia dentro de (t_start, t_end]."""
        prev = self.value_at(name, t_start)
        for tc, v in self.changes[name]:
            if tc <= t_start or tc > t_end:
                continue
            if v != prev:
                return tc
        return None

    def event_times(self, t0, t1):
        """Instantes en que cambia algo, dentro de [t0, t1]."""
        ts = {t0}
        for ch in self.changes.values():
            for tc, _v in ch:
                if t0 <= tc <= t1:
                    ts.add(tc)
        return sorted(ts)

    def extremos(self, name, t0, t1, signed_bits=None):
        """(min, max) del valor entero de `name` en [t0, t1].

        Sirve para los epigrafes de las figuras de datapath: el valor al que se
        asienta un filtro, el pico de un pulso. Se mide del VCD y no se escribe
        a mano.
        """
        lo = hi = None
        for tc, v in self.changes[name]:
            if tc < t0 or tc > t1:
                continue
            iv = _to_int(v)
            if iv is None:
                continue
            if signed_bits and iv >> (signed_bits - 1):
                iv -= 1 << signed_bits
            lo = iv if lo is None else min(lo, iv)
            hi = iv if hi is None else max(hi, iv)
        return lo, hi


def recortar(src, dst, t0_ps, t1_ps, timescale_ps=None):
    """Copia a `dst` solo la ventana [t0_ps, t1_ps] de un VCD/FST.

    Es lo que hace versionable el FST de un testbench largo. `tb_osc_filter`
    empuja ~15000 muestras por un datapath de 14 bits y Questa escribe los
    vectores BIT POR BIT, o sea ~130 bytes por ciclo: el VCD completo son 23 MB
    y el FST 1.5 MB, para dibujar 60 columnas. Acotar las senales no sirve
    (esas senales SON el volumen); hay que acotar el tiempo.

    El recorte no es un `head`: en t0 hay que re-emitir el valor ACTUAL de cada
    senal, porque si no las filas arrancan en 'x' hasta el primer cambio dentro
    de la ventana y el dibujo miente sobre el estado inicial.
    """
    src, dst = Path(src), Path(dst)
    cab, ultimo, orden = [], {}, []
    cuerpo = []
    in_defs = True
    t = 0
    ts = timescale_ps

    with open_waves(src) as fh:
        for line in fh:
            s = line.rstrip("\n")
            if in_defs:
                cab.append(s)
                if s.strip().startswith("$timescale") and ts is None:
                    tok = s.replace("$timescale", "").replace("$end", "").strip()
                    if tok:
                        ts = _ts_to_ps(tok)
                if s.strip().startswith("$enddefinitions"):
                    in_defs = False
                continue

            st = s.strip()
            if not st or st.startswith("$"):
                continue
            if st[0] == "#":
                t = int(st[1:])
                if t > t1_ps:
                    break
                # `> t0` y no `>= t0`: lo que pasa EN t0 ya quedo en el
                # $dumpvars. Emitirlo otra vez dejaba dos valores de la misma
                # senal en el mismo instante y eso fabrica un flanco que no
                # existe -- con el reloj daba un periodo de la mitad.
                if t > t0_ps:
                    cuerpo.append(st)
                continue
            if st[0] in "rR":
                continue
            if st[0] in "bB":
                val, vid = st[1:].split()
                txt = f"b{val} {vid}"
            else:
                val, vid = st[0], st[1:]
                txt = f"{val}{vid}"
            if t <= t0_ps:
                if vid not in ultimo:
                    orden.append(vid)
                ultimo[vid] = txt
            else:
                cuerpo.append(txt)

    with dst.open("w") as fh:
        fh.write("\n".join(cab) + "\n")
        fh.write(f"#{int(t0_ps)}\n$dumpvars\n")
        for vid in orden:
            fh.write(ultimo[vid] + "\n")
        fh.write("$end\n")
        fh.write("\n".join(cuerpo) + "\n")
    return dst


def _bit_index(rango):
    """"[31]" -> 31.  "[31:0]" o None -> None (la señal viene entera)."""
    if not rango or not rango.startswith("["):
        return None
    cuerpo = rango[1:-1]
    return None if ":" in cuerpo else int(cuerpo)


def _merge_bits(mapa, raw):
    """Junta los bits sueltos de un bus en una sola lista de cambios.

    Un cambio del bus es cualquier cambio de cualquiera de sus bits; los que
    caen en el mismo instante se aplican todos antes de emitir el valor, asi
    que no aparecen valores intermedios que nunca existieron.
    """
    ancho = max(mapa) + 1
    cur = ["x"] * ancho
    evs = sorted(((t, idx, v) for idx, vid in mapa.items() for t, v in raw[vid]),
                 key=lambda e: e[0])
    out, i = [], 0
    while i < len(evs):
        t = evs[i][0]
        while i < len(evs) and evs[i][0] == t:
            _, idx, v = evs[i]
            cur[idx] = v
            i += 1
        out.append((t, "".join(cur[b] for b in range(ancho - 1, -1, -1))))
    return out


def _ts_to_ps(tok):
    tok = tok.replace(" ", "")
    for unit, mult in (("fs", 0.001), ("ps", 1), ("ns", 1000), ("us", 10**6)):
        if tok.endswith(unit):
            head = tok[: -len(unit)]
            return float(head) * mult if head else mult
    return 1.0


def _to_int(v):
    if v is None:
        return None
    v = v.lower()
    if "x" in v or "z" in v:
        return None
    try:
        return int(v, 2)
    except ValueError:
        return None


def hexf(width):
    return lambda v: f"0x{v:0{width}X}"


def decf(signed_bits=None):
    """Formato decimal, con signo si se dice de cuantos bits es la señal."""
    def f(v):
        if signed_bits and v >> (signed_bits - 1):
            v -= 1 << signed_bits
        return str(v)
    return f


# ----------------------------------------------------------------------
# Grilla de muestreo: el puente entre el tiempo del VCD y los ciclos de WaveDrom
# ----------------------------------------------------------------------

def build_grid(vcd, t0, t1, step, ref="clk_ps"):
    """Instantes de muestreo. Uno por columna de WaveDrom.

    step = "events" pone una columna por cada instante en que cambia algo: el
    orden de los eventos queda exacto, pero el ancho de columna deja de ser
    tiempo. Con step numerico (en ps) la grilla es uniforme y se ancla en un
    flanco de `ref`, para que las columnas sean semiciclos enteros de ese reloj.
    """
    if step == "events":
        return vcd.event_times(t0, t1)
    prev = [t for t, _ in vcd.changes[ref] if t <= t0]
    start = prev[-1] if prev else t0
    n = int(math.ceil((t1 - start) / float(step)))
    return [int(round(start + i * step)) for i in range(n + 1)]


def column_of(grid, t):
    """Columna donde se DIBUJA el flanco que ocurre en t.

    Es la primera muestra en t o despues, que es exactamente la columna en la
    que sample() ve el valor nuevo: asi el nodo cae sobre la transicion que se
    ve, y no una columna antes cuando el flanco viene de otro dominio de reloj y
    cae entre dos muestras.
    """
    return max(0, min(len(grid) - 1, bisect_left(grid, t)))


def sample(vcd, name, grid, fmt=None, bit=None):
    """(wave, data) de WaveJSON para una señal.

    fmt=None   -> señal de un bit
    fmt=f      -> bus, con f(valor_entero) como etiqueta
    bit=k      -> el bit k de un bus, dibujado como señal de un bit
    """
    chars, data, prev = [], [], None
    for t in grid:
        raw = vcd.value_at(name, t)
        if bit is not None:
            iv = _to_int(raw)
            cur = "x" if iv is None else str((iv >> bit) & 1)
            chars.append("." if cur == prev else cur)
        elif fmt is None:
            cur = {"0": "0", "1": "1"}.get(raw, "x")
            chars.append("." if cur == prev else cur)
        else:
            iv = _to_int(raw)
            cur = "x" if iv is None else fmt(iv)
            if cur == prev:
                chars.append(".")
            elif cur == "x":
                chars.append("x")
            else:
                chars.append(BUS)
                data.append(cur)
        prev = cur
    return "".join(chars), data


def nodes(n, marks):
    """String de nodos de WaveDrom: marks = {columna: caracter}."""
    s = ["."] * n
    for col, ch in marks.items():
        if 0 <= col < n:
            s[col] = ch
    return "".join(s)


def row(vcd, name, label, grid, fmt=None, bit=None, ch=BUS, node=None):
    wave, data = sample(vcd, name, grid, fmt, bit)
    if fmt is not None and ch != BUS:
        wave = wave.replace(BUS, ch)
    r = {"name": label, "wave": wave}
    if data:
        r["data"] = data
    if node:
        r["node"] = node
    return r


def row_clk(label, n, ch="p", node=None):
    """La fila del reloj cuando una columna es UN ciclo.

    Con esa grilla no se puede muestrear el reloj: todas las muestras caen en
    la misma fase y la fila sale plana. WaveDrom tiene el caracter 'p' justo
    para esto --un ciclo con su flanco de subida por columna--, que ademas es
    lo que la fila significa. Las figuras de semiciclo (dos relojes
    asincronicos) si muestrean el reloj de verdad, porque ahi la fase importa.
    """
    r = {"name": label, "wave": ch * n}
    if node:
        r["node"] = node
    return r


def row_multi(vcd, name, label, grids, fmt=None, bit=None, ch=BUS, node=None):
    """Una fila que recorre VARIAS ventanas separadas por el hueco de WaveDrom.

    Sirve para poner tres escenas del mismo testbench en un solo dibujo --las
    tres formas del veto de trigger_shield, por ejemplo-- sin mentir sobre el
    eje de tiempo: el `|` entre tramos dice explicitamente "aca se salteo
    tiempo", que es justo para lo que WaveDrom lo tiene. Pegar las ventanas sin
    el hueco daria a entender que una escena sigue a la otra.
    """
    waves, data = [], []
    for g in grids:
        w, d = sample(vcd, name, g, fmt, bit)
        if fmt is not None and ch != BUS:
            w = w.replace(BUS, ch)
        waves.append(w)
        data += d
    r = {"name": label, "wave": "|".join(waves)}
    if data:
        r["data"] = data
    if node:
        r["node"] = node
    return r


def cols_multi(grids):
    """Cuantas columnas ocupa cada tramo y donde arranca, contando los huecos.

    Devuelve (total, offsets): con eso se traduce un instante de un tramo a la
    columna del dibujo combinado, para poner los nodos en su lugar.
    """
    offs, acc = [], 0
    for i, g in enumerate(grids):
        offs.append(acc + i)              # +i: un caracter de hueco por junta
        acc += len(g)
    return acc + len(grids) - 1, offs


def _edge_ok(spec, *node_strings):
    """Deja pasar solo las flechas cuyos dos nodos existen de verdad.

    Si el TB cambia y un flanco no aparece, el nodo no se define y WaveDrom
    dibujaria la flecha colgando desde el origen.
    """
    m = re.match(r"^(\S)([-~<>|+*]{1,3})(\S)", spec)
    if not m:
        return False
    presentes = set("".join(s for s in node_strings if s)) - {"."}
    return m.group(1) in presentes and m.group(3) in presentes


def filtrar_edges(edges, *node_strings):
    return [e for e in edges if _edge_ok(e, *node_strings)]


# ----------------------------------------------------------------------
# Escenas de un testbench
# ----------------------------------------------------------------------

def escenas(tb_path):
    """Las escenas numeradas (`// N) ...`) de un testbench.

    Reusa el parser de `modulos/mk/datasheet.py`, que es el canonico y esta
    validado contra grep: la tabla de casos cubiertos de VERIFICACION.md sale
    del mismo lugar, asi que una figura y el plan de verificacion no pueden
    nombrar la misma escena distinto. Si no se puede importar, se degrada a una
    lista vacia en vez de reventar: la figura sigue saliendo, sin el titulo de
    la escena en el epigrafe.
    """
    mk = Path(__file__).resolve().parents[2] / "modulos" / "mk"
    try:
        if str(mk) not in sys.path:
            sys.path.insert(0, str(mk))
        import datasheet                                   # noqa: PLC0415
        return datasheet.parse_tb(str(tb_path)).escenas
    except Exception as exc:                               # noqa: BLE001
        print(f"  aviso: no pude leer las escenas de {Path(tb_path).name}: {exc}",
              file=sys.stderr)
        return []


def escena(tb_path, n):
    """El titulo de la escena `n`, o "" si no esta."""
    for e in escenas(tb_path):
        if e.num == n:
            return e.titulo
    return ""


# ----------------------------------------------------------------------
# Figuras de secuencia (sin VCD)
# ----------------------------------------------------------------------

def esquema(filas, head=None, foot=None, hscale=2):
    """WaveJSON a mano, para las figuras donde una columna es un PASO y no un
    ciclo (el flujo de utilizacion).

    No hay VCD detras y eso se dice en el epigrafe: es un esquema de la
    secuencia, no una medicion. Lo que no se puede hacer es poner numeros de
    ciclos aca: eso va por el camino del VCD.
    """
    wj = {"signal": filas, "config": {"hscale": hscale}}
    if head:
        wj["head"] = head if isinstance(head, dict) else {"text": head}
    if foot:
        wj["foot"] = foot if isinstance(foot, dict) else {"text": foot}
    return wj


# ----------------------------------------------------------------------
# Render
# ----------------------------------------------------------------------

def render_py(json_path, svg_path):
    try:
        import wavedrom                                    # noqa: PLC0415
    except ImportError:
        return False, "el modulo python `wavedrom` no esta instalado"
    try:
        draw = wavedrom.render(Path(json_path).read_text())
        draw.saveas(str(svg_path))
    except Exception as exc:                               # noqa: BLE001
        return False, f"el modulo python `wavedrom` fallo: {exc}"
    return True, None


def render_cli(json_path, svg_path, allow_npx=False):
    exe = shutil.which("wavedrom-cli")
    cmd = [exe] if exe else None
    if cmd is None and allow_npx and shutil.which("npx"):
        cmd = ["npx", "-y", "wavedrom-cli"]
    if cmd is None:
        return False, "no hay wavedrom-cli en el PATH (npm i -g wavedrom-cli)"
    proc = subprocess.run(cmd + ["-i", str(json_path), "-s", str(svg_path)],
                          capture_output=True, text=True)
    if proc.returncode != 0 or not Path(svg_path).exists():
        return False, f"wavedrom-cli fallo: {proc.stderr.strip()[:200]}"
    return True, None


def render(json_path, svg_path, mode):
    """Devuelve (ok, detalle). mode: auto | py | cli | none."""
    if mode == "none":
        return False, "render desactivado (--render none)"
    if mode == "py":
        return render_py(json_path, svg_path)
    if mode == "cli":
        return render_cli(json_path, svg_path, allow_npx=True)
    # Primero el CLI oficial: es el renderer de referencia.
    ok, err = render_cli(json_path, svg_path)
    if ok:
        return True, "wavedrom-cli"
    ok2, err2 = render_py(json_path, svg_path)
    if ok2:
        return True, "modulo python wavedrom"
    return False, (f"{err}; {err2}. Opciones: `pip install --user wavedrom`, "
                   "`npm i -g wavedrom-cli`, o --render cli para bajarlo con "
                   "npx. Mientras tanto el visor HTML lo dibuja en el browser.")


def emitir(out_dir, slug, wj, modo_render, avisado=False, info=None):
    """Escribe <slug>.json y <slug>.svg, y avisa una sola vez si no hay render.

    El WaveJSON se versiona igual que el SVG: es la fuente, pesa poco y permite
    rehacer la figura en una maquina que no tenga el renderer.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{slug}.json"
    json_path.write_text(json.dumps(wj, indent=2, ensure_ascii=False) + "\n")
    det = f"  ({info})" if info else ""
    print(f"escrito {json_path.name}{det}", flush=True)

    svg_path = out_dir / f"{slug}.svg"
    ok, detalle = render(json_path, svg_path, modo_render)
    if ok:
        print(f"escrito {svg_path.name}" + (f"  ({detalle})" if detalle else ""),
              flush=True)
    elif modo_render != "none" and not avisado:
        print(f"  sin SVG: {detalle}", file=sys.stderr, flush=True)
        avisado = True                 # el motivo es el mismo para todas
    return avisado


# ----------------------------------------------------------------------
# Visor HTML (no necesita nada instalado: WaveDrom viene del CDN)
# ----------------------------------------------------------------------

HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{titulo_tab}</title>
<script src="https://cdn.jsdelivr.net/npm/wavedrom@3.5.0/wavedrom.unpkg.js"></script>
<script src="https://cdn.jsdelivr.net/npm/wavedrom@3.5.0/skins/default.js"></script>
<style>
  :root {{ color-scheme: light; --ink: #1F2933; --muted: #6B7280; }}
  body {{ margin: 0 auto; padding: 24px 16px 64px; max-width: 1400px;
         background: #fff; color: var(--ink);
         font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, sans-serif; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  h2 {{ font-size: 16px; margin: 36px 0 2px; }}
  p.sub {{ color: var(--muted); margin: 0 0 20px; }}
  p.nota {{ color: var(--muted); margin: 2px 0 10px; max-width: 80ch; }}
  .wave {{ overflow-x: auto; }}
</style>
</head>
<body onload="WaveDrom.ProcessAll()">
<h1>{titulo}</h1>
<p class="sub">{sub}</p>
{secciones}
</body>
</html>
"""

SECCION = """<h2>{titulo}</h2>
<p class="nota">{nota}</p>
<div class="wave"><script type="WaveDrom">
{wavejson}
</script></div>
"""


def write_html(path, titulo, sub, items, titulo_tab=None):
    """Visor con todas las figuras y sus notas. No necesita nada instalado.

    Los titulos pueden traer "<-" y "->": sin escapar, el browser se come el
    "<-". El WaveJSON va crudo: adentro de un <script> es texto, no markup.
    """
    secciones = "".join(
        SECCION.format(titulo=escape(it["titulo"]), nota=escape(it["nota"]),
                       wavejson=json.dumps(it["json"], indent=2, ensure_ascii=False))
        for it in items)
    Path(path).write_text(HTML.format(
        titulo_tab=escape(titulo_tab or re.sub("<[^>]+>", "", titulo)),
        titulo=titulo, sub=sub, secciones=secciones))


# ----------------------------------------------------------------------
# Epigrafes
#
# Mismo criterio que el resto de las figuras del repo (docs/mca/figuras/,
# docs/TOP/figuras/): el texto con los numeros lo escribe el script, para que no
# pueda desincronizarse del dibujo.
# ----------------------------------------------------------------------

EPIGRAFE = """FIGURA — {archivo}
{subrayado}
{titulo}

{nota}

{detalle}

"""


def write_manifiesto(path, items):
    """`ondas.json`: que figuras hay y de donde sale cada una.

    Lo lee `modulos/mk/datasheet.py` para armar la seccion de waveforms del
    datasheet. Sin esto, la pagina tendria que traer una lista de figuras
    escrita a mano que se desactualiza en cuanto se agrega o se saca una.
    """
    datos = [{"archivo": it["archivo"], "titulo": it["titulo"],
              "origen": it.get("origen", ""), "nota": it["nota"]}
             for it in items]
    Path(path).write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n")


def write_epigrafes(path, cabecera, items, pie=""):
    """Un epigrafe por figura, con la cabecera y el pie que da el script.

    `items` son dicts con archivo, titulo, nota y (opcional) `detalle`: las
    lineas con los numeros medidos. El detalle lo arma el script de la figura,
    porque es lo unico que sabe que se midio.
    """
    cuerpo = "".join(
        EPIGRAFE.format(archivo=it["archivo"],
                        subrayado="-" * (9 + len(it["archivo"])),
                        titulo=it["titulo"],
                        nota=textwrap.fill(it["nota"], 78),
                        detalle=it.get("detalle", "").rstrip())
        for it in items)
    Path(path).write_text(cabecera.rstrip() + "\n\n" + cuerpo
                          + (pie.rstrip() + "\n" if pie else ""))


# ----------------------------------------------------------------------

def parse_step(vcd, spec, refs=("clk_ps",)):
    """--step -> paso en ps, o la cadena "events"."""
    if spec == "events":
        return "events"
    if spec == "auto":
        # Medio periodo del reloj mas rapido: ese dominio cae exacto.
        return min(vcd.period(r) for r in refs if r in vcd) / 2.0
    try:
        return float(spec) * 1000.0            # el usuario lo pasa en ns
    except ValueError:
        sys.exit(f"--step invalido: {spec} (auto | events | <ns>)")


def add_common_args(ap, aqui, fst=None):
    """Las opciones que comparten todos los scripts de ondas."""
    if fst:
        ap.add_argument("--vcd", default=str(Path(aqui) / fst),
                        help="ondas del TB, .fst o .vcd "
                             "(default: el FST versionado al lado del script)")
    ap.add_argument("--out", default=str(aqui),
                    help="directorio de salida (default: el del script)")
    ap.add_argument("--step", default="auto",
                    help="paso de muestreo: auto | events | <ns> "
                         "(default: auto = medio periodo del reloj mas rapido)")
    ap.add_argument("--hscale", type=int, default=1,
                    help="ancho de columna de WaveDrom (default: %(default)s)")
    ap.add_argument("--render", default="auto",
                    choices=("auto", "py", "cli", "none"),
                    help="como pasar de WaveJSON a SVG (default: %(default)s)")
    return ap


def need_vcd(path, como):
    """Aborta con el comando para generar el VCD si no esta."""
    if not Path(path).exists():
        sys.exit(f"no existe {path}\n  {como}")
    return Path(path)


# Para que `python3 ondas.py` diga algo util en vez de no hacer nada.
if __name__ == "__main__":
    print(__doc__.strip())
    print("\nEs una biblioteca. Los scripts que la usan:")
    raiz = Path(__file__).resolve().parents[1]
    for p in sorted(raiz.glob("*/figuras/ondas/ondas_*.py")):
        print("  ", os.path.relpath(p, raiz.parent))
    for p in sorted(raiz.glob("*/figuras/*/figuras_*.py")):
        if "ondas" in p.read_text(errors="replace"):
            print("  ", os.path.relpath(p, raiz.parent))

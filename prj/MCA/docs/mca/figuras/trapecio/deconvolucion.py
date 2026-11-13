#!/usr/bin/env python3
"""La deconvolucion sola (Jordanov / MWD) contra el trapecio: los numeros del §9.

La deconvolucion de un pulso exponencial es

    x_d[n] = y[n] - a*y[n-1],   a = e^(-1/tau)

y la amplitud se estima como la suma de x_d en una ventana de W muestras desde
el pie. Con los parametros del §7 (tau = 250 muestras, ruido blanco de 4
cuentas, A = 1000 y B = 600) imprime:

  1. que esa suma es el trapecio con k = 1 y m = W - 1;
  2. el ruido del pulso solo: pico, deconvolucion y trapecio de la placa, y el
     de la deconvolucion contra W (no baja);
  3. el barrido de k: ruido y separacion minima;
  4. el error RMS de A y de B contra dt, en pares;
  5. el sesgo de B con tau (o M) un 5 % corto;
  6. lo que mide cada uno con subida lenta y disparo corrido.

El trapecio de la placa (2 y 4) usa la misma recursion entera que mca_trap;
el del barrido (1, 3 y 6) es la misma cuenta en punto flotante, normalizada a
altura A.

Escribe ademas trap_deconvolucion.tex (el ruido y la separacion minima contra
k, con la deconvolucion sola en k = 1) en el estilo comun de las figuras TikZ y
lo compila a .pdf y .svg. Tarda unos segundos.

    python3 deconvolucion.py
"""
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from figuras_mejora import Ejes, PLANTILLA

AQUI = Path(__file__).resolve().parent
TEX = AQUI / "trap_deconvolucion.tex"

TAU = 250.0
SIGMA = 4.0
A1, A2 = 1000, 600
A_DEC = math.exp(-1.0 / TAU)
M_FLT = 1.0 / (math.exp(1.0 / TAU) - 1.0)

# el trapecio de la placa, como en figuras_mejora.py
K, M_MESETA = 64, 48
L = K + M_MESETA
MQ = round(16.0 / (math.exp(1.0 / TAU) - 1.0))        # 3992
SH = round(math.log2(16 * K * (1 + MQ / 16.0) / 8))    # 15
G = 384
OFF, W = 80, 16
W_DEC = 4                       # ventana de la deconvolucion: [pie - 1, pie + 3)

rng = np.random.default_rng(2026)


# ------------------------------------------------------------------ modelo
def pulso(a, t0, n, tc=1, entero=True):
    """Exponencial con pie en t0; con tc > 1, convolucionada con una corriente
    rectangular de tc muestras (la subida)."""
    t = np.arange(n) - t0
    y = np.where(t >= 0, a * np.exp(-np.maximum(t, 0) / TAU), 0.0)
    if tc > 1:
        y = np.convolve(y, np.ones(tc) / tc)[:n]
    return np.round(y).astype(np.int64) if entero else y


def retrasar(v, j):
    o = np.zeros_like(v)
    o[..., j:] = v[..., :v.shape[-1] - j]
    return o


def trapecio_rtl(x, mq=MQ):
    d = x - retrasar(x, K) - retrasar(x, L) + retrasar(x, K + L)
    p = np.cumsum(d, -1)
    return np.cumsum(16 * p + mq * d, -1) / 2**SH


def trapecio(x, k, m, mx=M_FLT):
    """Jordanov-Knoll en punto flotante, normalizado: la meseta vale A."""
    l = k + m
    d = x - retrasar(x, k) - retrasar(x, l) + retrasar(x, k + l)
    p = np.cumsum(d, -1)
    return np.cumsum(p + mx * d, -1) / (k * (1 + mx))


def deconv(x, a=A_DEC):
    return x - a * retrasar(x, 1)


def estimar(x, t, a=A_DEC, mq=MQ, wd=W_DEC):
    return {
        "pico": x[..., t:t + G].max(-1).astype(float),
        "deconvolucion": deconv(x, a)[..., t - 1:t - 1 + wd].sum(-1),
        "trapecio": trapecio_rtl(x, mq)[..., t + OFF:t + OFF + W].mean(-1),
    }


def error_rms(dts, r=400, n=2800, t0=200, ruido=True, **kw):
    """Error RMS en % de A y de B, contra lo que mide cada uno solo."""
    xa = pulso(A1, t0, n)
    ra = {e: v.item() for e, v in estimar(xa[None], t0, **kw).items()}
    out = {e: ([], []) for e in ra}
    for dt in dts:
        xb = pulso(A2, t0 + dt, n)
        rb = {e: v.item() for e, v in estimar(xb[None], t0 + dt, **kw).items()}
        x = (xa + xb)[None]
        if ruido:
            x = x + np.round(rng.normal(0, SIGMA, (r, n))).astype(np.int64)
        va, vb = estimar(x, t0, **kw), estimar(x, t0 + dt, **kw)
        for e in ra:
            out[e][0].append(100 * np.sqrt(np.mean((va[e] - ra[e]) ** 2)) / ra[e])
            out[e][1].append(100 * np.sqrt(np.mean((vb[e] - rb[e]) ** 2)) / rb[e])
    return out


# ------------------------------------------------------------------ las cuentas
def equivalencia():
    n, t0 = 1200, 300
    x = (pulso(A1, t0, n, entero=False) + rng.normal(0, SIGMA, n)
         + 0.7 * pulso(A2, t0 - 40, n, entero=False))
    w = 8
    s1 = deconv(x)[t0:t0 + w].sum()
    s2 = trapecio(x, 1, w - 1)[t0 + w - 1]
    print(f"1. suma de la deconvolucion, W = {w}: {s1:.6f}")
    print(f"   trapecio k = 1, m = {w - 1}, en su meseta: {s2:.6f}")


def ruido_solo():
    print("\n2. pulso solo, error RMS %")
    o = error_rms([2000])
    for e, (ea, eb) in o.items():
        print(f"   {e:14s} A {ea[0]:.3f}   B {eb[0]:.3f}")
    print(f"   (sigma*sqrt(2)/A = {100 * SIGMA * math.sqrt(2) / A1:.3f} %)")
    print("   deconvolucion contra el ancho de la ventana:")
    for wd in (2, 4, 16, 64):
        o = error_rms([2000], wd=wd)
        print(f"     W = {wd:3d}: A {o['deconvolucion'][0][0]:.3f} %")


def barrido_k():
    """Ruido del pulso solo y separacion minima contra k: la tabla del §9 y la figura."""
    gen = np.random.default_rng(7)
    d = {"sig": [], "dmin": []}
    for k in KS:
        s, dt = ruido_y_separacion(k, M_FIG, k - 1 + M_FIG // 2, 1, gen=gen)
        d["sig"].append(s)
        d["dmin"].append(dt)
    d["placa"] = ruido_y_separacion(K, M_MESETA, OFF, W, gen=gen)
    d["pico"] = pico_solo(gen)
    print(f"\n3. barrido de k (m = {M_FIG}, una muestra en el centro de la meseta: off = k + {M_FIG // 2 - 1})")
    print("     k   error de A   sigma*sqrt(2/k)   dt min de B   2k+m-1-off")
    for k, s, dt in zip(KS, d["sig"], d["dmin"]):
        print(f"   {k:3d}   {s:7.3f} %      {100 * SIGMA * math.sqrt(2 / k) / A1:7.3f} %        "
              f"{dt:4d}         {k + M_FIG // 2:4d}")
    s, dt = d["placa"]
    print(f"   la placa (k = {K}, m = {M_MESETA}, ventana [{OFF}, {OFF + W})): {s:.3f} %, dt min {dt}, "
          f"2k+m-1-off = {2 * K + M_MESETA - 1 - OFF}")
    s, dt = d["pico"]
    print(f"   pico de la compuerta: {s:.3f} %, dt min {dt} (tau*ln(1000*A/B) = "
          f"{TAU * math.log(1000 * A1 / A2):.0f})")
    return d


def pares():
    dts = [5, 10, 20, 40, 60, 95, 120]
    print("\n4. pares: error RMS %, contra dt")
    print("   dt =              " + " ".join(f"{d:7d}" for d in dts))
    o = error_rms(dts)
    for e, (ea, eb) in o.items():
        print(f"   {e:14s} B: " + " ".join(f"{v:7.2f}" for v in eb))
        print(f"   {'':14s} A: " + " ".join(f"{v:7.2f}" for v in ea))


def tau_corta():
    dts = [20, 60, 120, 300]
    print("\n5. tau 5 % corta (deconvolucion) / M 5 % bajo (trapecio): sesgo de B en %, sin ruido")
    o = error_rms(dts, ruido=False, a=math.exp(-1.0 / (0.95 * TAU)), mq=round(0.95 * MQ))
    for e in ("deconvolucion", "trapecio"):
        print(f"   {e:14s} " + " ".join(f"{v:6.2f}" for v in o[e][1])
              + "   (dt = " + ", ".join(map(str, dts)) + ")")


def subida_y_disparo(n=2400, t0=300):
    print("\n6. valor/A con la ventana fija: subida tc y disparo corrido dj")
    print("              deconv W = 6   deconv W = 24   trapecio k = 64, m = 48")
    for tc in (1, 8, 16, 32):
        for dj in (0, 3):
            x = pulso(A1, t0 + dj, n, tc, entero=False)
            d6 = deconv(x)[t0:t0 + 6].sum() / A1
            d24 = deconv(x)[t0:t0 + 24].sum() / A1
            tr = trapecio(x, K, M_MESETA)[t0 + OFF:t0 + OFF + W].mean() / A1
            print(f"   tc={tc:2d} dj={dj}     {d6:.4f}         {d24:.4f}           {tr:.4f}")


# ------------------------------------------------------------------ la figura
AZUL = "azul!85!black"
ROJO = "rojo!75!black"
KS = [1, 2, 4, 8, 16, 32, 64, 128, 256]
M_FIG = 16


def ruido_y_separacion(k, m, off, w, r=600, n=2400, t0=300, gen=None):
    """Error RMS del pulso solo (%) y el primer dt con B sesgado < 0.1 %."""
    xa = pulso(A1, t0, n, entero=False)
    v = trapecio(xa + gen.normal(0, SIGMA, (r, n)), k, m)[:, t0 + off:t0 + off + w].mean(-1)
    sig = 100 * np.sqrt(np.mean((v - A1) ** 2)) / A1
    for dt in range(1, n - t0 - off - w):
        vb = trapecio(xa + pulso(A2, t0 + dt, n, entero=False), k, m)[t0 + dt + off:t0 + dt + off + w].mean()
        if abs(vb - A2) / A2 < 1e-3:
            return sig, dt
    raise RuntimeError(f"k = {k}: B no llega a medir limpio")


def pico_solo(gen, r=600, n=4200, t0=300):
    """Lo mismo para el pico de la compuerta: ruido del pulso solo y separacion."""
    xa = pulso(A1, t0, n, entero=False)
    v = (xa + gen.normal(0, SIGMA, (r, n)))[:, t0:t0 + G].max(-1)
    sig = 100 * np.sqrt(np.mean((v - A1) ** 2)) / A1
    for dt in range(1, n - t0 - G):
        vb = (xa + pulso(A2, t0 + dt, n, entero=False))[t0 + dt:t0 + dt + G].max()
        if abs(vb - A2) / A2 < 1e-3:
            return sig, dt
    raise RuntimeError("el pico no llega a medir limpio")


def panel(e, titulo, yt, ylab, fmt_y, xs, ys, modelo, placa, pico, rot_pico):
    L = [f"\\node[anchor=south west, font=\\scriptsize\\bfseries, inner sep=0pt] at "
         f"({e.x0:.3f},{e.y0 + e.alto + 0.18:.3f}) {{{titulo}}};"]
    L += e.marco(KS, yt, "$k$, muestras", ylab, fmt_y=fmt_y)
    # el pico: una referencia horizontal
    L.append(f"\\draw[{ROJO}, line width=0.8pt, dash pattern=on 1.5pt off 1.5pt] "
             f"({e.x0:.3f},{e.Y(pico):.3f}) -- ({e.x0 + e.ancho:.3f},{e.Y(pico):.3f});")
    L.append(f"\\node[nodo, anchor={rot_pico}, text={ROJO}, fill=white, inner sep=1pt] at "
             f"({e.x0 + e.ancho - 0.06:.3f},{e.Y(pico):.3f}) {{pico}};")
    # el modelo, fino, y el Monte Carlo, en puntos
    kk = np.logspace(0, math.log10(KS[-1]), 60)
    L.append(e.curva(kk, [modelo(k) for k in kk], f"{AZUL}, line width=0.5pt"))
    for x, y in zip(xs, ys):
        L.append(f"\\fill[{AZUL}] ({e.X(x):.3f},{e.Y(y):.3f}) circle (1.5pt);")
    # la placa, en anillo, y la deconvolucion sola en k = 1
    kp, yp, ancla_p = placa
    L.append(f"\\draw[{AZUL}, fill=white, line width=0.8pt] ({e.X(kp):.3f},{e.Y(yp):.3f}) circle (2.3pt);")
    L.append(f"\\node[nodo, anchor={ancla_p}, text={AZUL}] at ({e.X(kp):.3f},{e.Y(yp):.3f}) {{la placa}};")
    L.append(f"\\draw[black!60, line width=0.5pt] ({e.X(1):.3f},{e.Y(ys[0]):.3f}) circle (3.2pt);")
    return L


def figura(d):
    sig, dmin = d["sig"], d["dmin"]
    s_placa, d_placa = d["placa"]
    s_pico, d_pico = d["pico"]

    eR = Ejes(0.0, 0.0, 6.2, 4.2, (1, KS[-1]), (0.02, 1.0))
    eS = Ejes(8.0, 0.0, 6.2, 4.2, (1, KS[-1]), (5, 3000))
    L = panel(eR, "Ruido del pulso solo", [0.02, 0.05, 0.1, 0.2, 0.5, 1], "error RMS de A",
              lambda v: f"{v:g}\\,\\%", KS, sig,
              lambda k: 100 * SIGMA * math.sqrt(2 / k) / A1,
              (K, s_placa, "north east"), s_pico, "south east")
    L += panel(eS, "Separación para que B mida limpio", [10, 20, 50, 100, 200, 500, 1000, 2000],
               "$\\Delta t$ mínimo, muestras", lambda v: f"{v:g}", KS, dmin,
               lambda k: 2 * k + M_FIG - 1 - (k - 1 + M_FIG // 2),
               (K, d_placa, "south east"), d_pico, "north east")
    # el rotulo de k = 1: arriba de la curva en el ruido, abajo en la separacion
    for e, y, ancla, dy in ((eR, sig[0], "south west", 0.06), (eS, dmin[0], "north west", -0.08)):
        L.append(f"\\node[nodo, anchor={ancla}, text=black!70] at ({e.X(1) + 0.08:.3f},{e.Y(y) + dy:.3f}) "
                 f"{{deconvolución sola}};")
    return L


def escribir_figura(d):
    TEX.write_text(PLANTILLA.replace("Cuanto mejora el trapecio. GENERADO por figuras_mejora.py",
                                     "Ruido y separacion contra k. GENERADO por deconvolucion.py")
                   % "\n".join(figura(d)))
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                        f"-output-directory={tmp}", TEX.name],
                       cwd=AQUI, check=True, capture_output=True)
        pdf = TEX.with_suffix(".pdf")
        shutil.copy(Path(tmp) / pdf.name, pdf)
    subprocess.run(["pdftocairo", "-svg", str(pdf), str(pdf.with_suffix(".svg"))], check=True)
    print(f"escrito {TEX.name}, .pdf y .svg")


def main():
    print(f"tau = {TAU:g}, a = {A_DEC:.6f}, M = {M_FLT:.2f}, Mq = {MQ}, sh = {SH}\n")
    equivalencia()
    ruido_solo()
    datos = barrido_k()
    pares()
    tau_corta()
    subida_y_disparo()
    escribir_figura(datos)


if __name__ == "__main__":
    main()

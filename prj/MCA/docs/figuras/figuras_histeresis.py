#!/usr/bin/env python3
"""El trigger con histeresis (Schmitt), contra un comparador simple.

Genera `histeresis.png`: una senal muestreada que sube y baja despacio, con
ruido, y lo que hacen con ella dos disparadores sobre el MISMO umbral:

  (a) la senal x[n], el umbral `thr` y el nivel inferior `thr - hyst`
  (b) comparador simple:  y[n] = (x[n] >= thr)
  (c) Schmitt:            sube con x >= thr, baja recien con x < thr - hyst

La regla de (c) es la de `rp_adc_trig.v` y la del modo 0 de
`modulos/mca/rtl/mca_pulse_feature.sv`. Es un ESQUEMA: no entra ningun VCD ni
`.npz`, la senal es una rampa con ruido blanco y los numeros del epigrafe los
cuenta este script sobre la misma senal que dibuja.

    python3 figuras_histeresis.py      # escribe el PNG e imprime el epigrafe
"""

from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from estilo import TINTA2, MUDO, GRILLA, AZUL, NARAN, VERDE, limpiar, panel, reflow

SALIDA = Path(__file__).with_name("histeresis.png")

# Los numeros de la campana del MCA (thr=100, hyst=40) y un ruido grande para
# que el efecto se vea en pocas muestras. Lo que importa es hyst >> sigma.
THR, HYST, SIGMA = 100, 40, 8.0
PICO = 200
N_SUBE, N_ARRIBA, N_BAJA = 60, 40, 60
N_PRE, N_POST = 20, 30


def senal(rng):
    """Trapecio lento: la pendiente es chica frente al ruido en el cruce."""
    tramos = [np.zeros(N_PRE),
              np.linspace(0, PICO, N_SUBE, endpoint=False),
              np.full(N_ARRIBA, PICO),
              np.linspace(PICO, 0, N_BAJA, endpoint=False),
              np.zeros(N_POST)]
    limpia = np.concatenate(tramos)
    return np.round(limpia + rng.normal(0, SIGMA, limpia.size))


def comparador(x):
    return (x >= THR).astype(int)


def schmitt(x):
    """Igual que el RTL: la salida no vuelve a 0 hasta bajar de thr - hyst."""
    y, q = np.zeros(x.size, dtype=int), 0
    for n, v in enumerate(x):
        if v >= THR:
            q = 1
        elif v < THR - HYST:
            q = 0
        y[n] = q
    return y


def flancos(y):
    return np.flatnonzero(np.diff(y) != 0) + 1


def elegir_senal():
    """La primera semilla donde el comparador rebota en LOS DOS cruces.

    Con una semilla fija a mano, un cambio de SIGMA o de la pendiente podria
    dar una senal donde el comparador simple no rebota y la figura dejaria de
    mostrar lo que dice el epigrafe. Asi se busca, y se verifica.
    """
    mitad = N_PRE + N_SUBE + N_ARRIBA // 2
    for semilla in range(1000):
        x = senal(np.random.default_rng(semilla))
        fc, fs = flancos(comparador(x)), flancos(schmitt(x))
        sube, baja = (fc < mitad).sum(), (fc >= mitad).sum()
        if sube >= 5 and baja >= 5 and len(fs) == 2:
            return semilla, x
    raise SystemExit("ninguna semilla rebota en los dos cruces: revisar SIGMA")


def escalon(ax, n, y, color):
    ax.fill_between(n, y, step="post", color=color, alpha=0.18, lw=0)
    ax.step(n, y, where="post", color=color, lw=1.4)
    ax.set_ylim(-0.25, 1.35)
    ax.set_yticks([0, 1])
    ax.grid(axis="y", visible=False)


def main():
    semilla, x = elegir_senal()
    n = np.arange(x.size)
    yc, ys = comparador(x), schmitt(x)
    fc, fs = flancos(yc), flancos(ys)

    fig, (a, b, c) = plt.subplots(
        3, 1, sharex=True, figsize=(7.2, 4.8),
        gridspec_kw={"height_ratios": [3, 1, 1], "hspace": 0.25})

    a.axhspan(THR - HYST, THR, color=GRILLA, alpha=0.6, lw=0,
              label="banda de histéresis")
    a.axhline(THR, color=TINTA2, lw=1.0, ls="--", label="thr")
    a.axhline(THR - HYST, color=MUDO, lw=1.0, ls=":", label="thr − hyst")
    a.plot(n, x, color=AZUL, lw=0.8, marker="o", ms=2.2, label="x[n]")
    a.set_ylabel("cuentas")
    a.legend(loc="upper right", ncol=4, fontsize=8)
    a.set_ylim(-35, PICO + 70)
    panel(a, "(a)")

    escalon(b, n, yc, NARAN)
    b.set_ylabel("x ≥ thr")
    panel(b, "(b)")

    escalon(c, n, ys, VERDE)
    c.set_ylabel("Schmitt")
    c.set_xlabel("muestra n")
    panel(c, "(c)")

    # Los dos instantes del Schmitt, a traves de los tres paneles: son los
    # unicos cruces que el sistema deberia ver.
    for ax in (a, b, c):
        for t in fs:
            ax.axvline(t, color=VERDE, lw=0.7, alpha=0.5)
        limpiar(ax)
    c.set_xlim(0, x.size - 1)

    fig.align_ylabels((a, b, c))
    fig.savefig(SALIDA, bbox_inches="tight")
    print(f"escrito {SALIDA.name}  (semilla {semilla})")

    disparos = int((np.diff(yc) == 1).sum())       # flancos de subida de (b)
    pend = PICO / N_SUBE
    print()
    print(reflow(f"""
        **Figura.** Trigger con histéresis contra un comparador simple, sobre
        la misma señal y el mismo umbral. (a) Una señal muestreada que sube y
        baja despacio ({pend:.1f} cuentas por muestra) con ruido blanco de
        σ = {SIGMA:.0f} cuentas; la línea discontinua es `thr = {THR}` y la
        punteada `thr − hyst = {THR - HYST}`. (b) El comparador simple
        `x ≥ thr`: mientras la señal pasa por el umbral, el ruido la cruza una
        y otra vez y la salida cambia {len(fc)} veces: {disparos} flancos de
        subida, o sea {disparos} disparos, donde hay un solo evento. Rebota
        también en la bajada, que es donde nadie lo espera. (c) El Schmitt: sube al cruzar `thr` y no vuelve a bajar hasta
        que la señal cae por debajo de `thr − hyst`. Como la banda
        ({HYST} cuentas) es {HYST / SIGMA:.0f} veces σ, el ruido no alcanza a
        recorrerla y la salida tiene exactamente {len(fs)} flancos, marcados en
        verde en los tres paneles. Es la regla de `rp_adc_trig.v` y del modo 0
        de `mca_pulse_feature.sv`. El costo es que el flanco de bajada llega
        tarde: la salida se queda en 1 hasta que la señal recorre la banda.
        """))


if __name__ == "__main__":
    main()

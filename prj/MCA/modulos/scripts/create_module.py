#!/usr/bin/env python3
"""
Generador de modulos de prj/MCA/modulos/.

Crea el esqueleto completo de un modulo: rtl, sim (+ sva), modelos (c_model y
python_model), lint, syn, uvm y work. Deriva del create_project.py original,
con tres diferencias:

  - Sin P&R. El flujo llega hasta sintesis y ahi para: lo que interesa por
    modulo es el costo y la Fmax, no el layout.
  - Sintesis en Vivado out-of-context (xc7z010clg400-1), no Synopsys FC con
    SAED32. El script de sintesis es UNO SOLO y compartido (mk/syn_ooc.tcl);
    lo propio de cada modulo es su syn/inputs/<top>_ooc.xdc.
  - NO PISA NADA. Escribe un archivo solo si no existe. Los modulos de este
    proyecto ya tienen RTL y testbenches: el script sirve para completar lo que
    falta, no para generar de cero. Con --force si se quiere lo contrario.

Uso:
    python3 create_module.py <nombre> [--top <modulo>] [--clk-port adc_clk_i]
    python3 create_module.py mca --scaffold-only   # solo lo que falte
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODULOS = os.path.abspath(os.path.join(HERE, ".."))

DIRS = [
    "rtl",
    "sim", "sim/sva",
    "modelos/c_model", "modelos/python_model",
    "lint",
    "syn/inputs", "syn/outputs", "syn/logs",
    "uvm",
    "work",
]


def create_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)
    print(f"  [DIR]  {os.path.relpath(p, MODULOS)}")


def create_file(p: str, content: str, force: bool) -> None:
    rel = os.path.relpath(p, MODULOS)
    if os.path.exists(p) and not force:
        print(f"  [SKIP] {rel}  (ya existe)")
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(content)
    print(f"  [FILE] {rel}")


# --------------------------------------------------------------------------- #
# Plantillas
# --------------------------------------------------------------------------- #
def files_f(mod: str, top: str) -> str:
    return f"""# RTL propio de {mod}, en orden de dependencia (hojas primero).
# Rutas relativas a la raiz del modulo.
#
# Este archivo vive en la raiz del modulo y NO dentro de rtl/, a proposito: el
# `add_files modulos/<m>/rtl` del TCL de Vivado levantaria un .f suelto como
# archivo de tipo desconocido.
rtl/{top}.sv
"""


def extra_f(mod: str) -> str:
    return f"""# RTL del repo raiz que necesita {mod}, con rutas relativas a la RAIZ DEL
# REPO (ej: rtl/classic/axi_wr_fifo.v). Opcional: si el modulo no depende de
# nada de afuera, este archivo puede no existir.
#
# module.mk lo lee tambien cuando otro modulo declara a este en DEPS, asi que
# una dependencia arrastra las suyas sin que el modulo de arriba las repita.
"""


def work_makefile(mod: str, top: str) -> str:
    return f"""MODULE := {mod}
TOP    := {top}
DEPS   :=
TBS    :=

include ../../mk/module.mk
"""


def ooc_xdc(top: str, clk: str) -> str:
    return f"""# Restricciones para la sintesis out-of-context de {top}.
#
# Vivado evalua el XDC como Tcl, asi que el periodo puede venir del entorno:
# eso es lo que hace posible el barrido en frecuencia (make sweep) sin generar
# un XDC por punto. Default 8 ns = 125 MHz, el adc_clk real de la Red Pitaya.
set PERIOD [expr {{[info exists ::env(PERIOD_NS)] ? $::env(PERIOD_NS) : 8.0}}]

create_clock -period $PERIOD -name adc_clk [get_ports {clk}]

# 10% del periodo de margen en los bordes. En OOC los puertos del modulo no son
# pines del chip: esto modela el resto del diseno, no el pad.
set D [expr {{$PERIOD * 0.10}}]
set_input_delay  -clock adc_clk $D [remove_from_collection [all_inputs] [get_ports {clk}]]
set_output_delay -clock adc_clk $D [all_outputs]
"""


def sva(mod: str, top: str, clk: str, rstn: str) -> str:
    return f"""// Assertions de {top}, enganchadas por `bind` desde sim/sva/bind_{mod}.sv.
//
// Van aparte del RTL a proposito: el RTL sintetizable no se toca, no hace falta
// un `ifndef SYNTHESIS`, y estas propiedades nunca entran a files.f, asi que
// Vivado ni las ve. Se compilan solo en el flujo de simulacion.
//
// El modulo replica los puertos del DUT que quiere observar; el bind con `.*`
// los conecta por nombre.

module {top}_sva (
    input logic {clk},
    input logic {rstn}
);

  default clocking cb @(posedge {clk}); endclocking
  default disable iff (!{rstn});

  // TODO: propiedades de {mod}. Arrancar por las invariantes que el testbench
  // hoy comprueba a mano en puntos sueltos: aca valen en TODO ciclo.
  //
  // Ejemplo de la forma:
  //   ap_handshake_estable: assert property (
  //     valid_o && !ready_i |=> valid_o && $stable(data_o)
  //   ) else $error("dato cambio con valid alto y ready bajo");

endmodule
"""


def sva_bind(mod: str, top: str) -> str:
    return f"""// Engancha las assertions a todas las instancias de {top}.
bind {top} {top}_sva u_sva (.*);
"""


def verificacion_md(mod: str, top: str) -> str:
    return f"""# Plan de verificación — {mod}

DUT principal: `{top}`

## Cómo se corre

```
make -C modulos/{mod}/work          # todos los testbenches
make -C modulos/{mod}/work <tb>     # uno solo
make -C modulos/{mod}/work cov      # + cobertura, reporte en work/cov/html/
make -C modulos/{mod}/work wave TB=<tb>   # ondas ya grabadas del último batch
```

Las ondas se graban **siempre** en batch (`work/waves/<tb>.wlf`). No se
condiciona el volcado a que haya un error: cuando el chequeo falla, el tiempo
que hay que mirar ya pasó.

## Casos cubiertos

| # | Caso | Testbench | Estado |
|---|------|-----------|--------|
| 1 | reset y valores iniciales | | |

## Casos borde conocidos

Lo que hay que probar y todavía no se prueba. Cada línea es deuda de
verificación, no una idea suelta.

| Caso borde | Por qué importa | Cubierto |
|------------|-----------------|----------|
| | | no |

## Assertions

En `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

| Propiedad | Qué garantiza |
|-----------|---------------|
| | |

## Metas de cobertura

| Métrica | Meta | Actual |
|---------|------|--------|
| statements | 100% | |
| branches | 100% | |
| toggle | 90% | |
| covergroups funcionales | 100% | |

Las metas son del código del módulo (`files.f`), no del RTL del repo raíz que
arrastre por `extra.f`.
"""


def spyglass_tcl(mod: str, top: str) -> str:
    return f"""# Lint con SpyGlass. NO corre en esta maquina (no esta instalado): queda para
# la del laboratorio. El lint que corre local es `make -C modulos/{mod}/work lint`,
# que usa vlog -lint de Questa.
#
# Las fuentes salen del mismo files.f/extra.f que usa la simulacion, asi que no
# se pueden desincronizar.

set MOD_DIR [file normalize [file dirname [info script]]/..]
new_project {mod} -projectwdir ${{MOD_DIR}}/lint/work -force

set fh [open ${{MOD_DIR}}/files.f r]
foreach line [split [read $fh] "\\n"] {{
    set line [string trim $line]
    if {{$line eq "" || [string index $line 0] eq "#"}} {{ continue }}
    read_file -type verilog ${{MOD_DIR}}/$line
}}
close $fh

set_option enableSV09 yes
set_option top {top}
read_file -type sgdc ${{MOD_DIR}}/lint/{mod}.sgdc
if {{[file exists ${{MOD_DIR}}/lint/{mod}.swl]}} {{
    read_file -type waiver ${{MOD_DIR}}/lint/{mod}.swl
}}

current_goal lint/lint_rtl
run_goal
current_goal cdc/cdc_verify_struct
run_goal
exit -force
"""


def sgdc(mod: str, top: str, clk: str, rstn: str) -> str:
    return f"""current_design {top}
clock -name {clk}
reset -name {rstn} -value 0
"""


def c_model(mod: str) -> str:
    return f"""/* Modelo de referencia en C de {mod}.
 *
 * Se compila con -DDPI_MODE para engancharlo por DPI-C desde un scoreboard de
 * UVM, o sin el flag para correrlo suelto con el main de abajo.
 *
 * Ojo: para {mod} puede convenir mas el modelo en Python (modelos/python_model),
 * sobre todo si ya existe uno del lado del software. El de C rinde cuando hace
 * falta cerrar el lazo por DPI dentro de la simulacion.
 */
#include <stdio.h>
#include <stdint.h>

void {mod}_model_reset(void)
{{
    /* TODO */
}}

#ifndef DPI_MODE
int main(void)
{{
    printf("=== modelo C: {mod} ===\\n");
    {mod}_model_reset();
    printf("=== sin casos todavia ===\\n");
    return 0;
}}
#endif
"""


def python_model(mod: str) -> str:
    return f'''"""Modelo de referencia en Python de {mod}.

Antes de escribir uno nuevo, mirar si ya existe del lado del software:
prj/MCA/software/API/modelo_rtl/ tiene los modelos que usa la API en produccion
(ring_format.py, estimadores.py). Esos NO se mueven aca — se importan, y este
modulo agrega solo lo especifico de verificacion.
"""
from __future__ import annotations


class {mod.title().replace("_", "")}Model:
    """Modelo bit-exacto de {mod}."""

    def reset(self) -> None:
        raise NotImplementedError

    def step(self, **kwargs):
        raise NotImplementedError
'''


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Generador de modulos de prj/MCA/modulos.")
    ap.add_argument("modulo", help="nombre del modulo (= carpeta en modulos/)")
    ap.add_argument("--top", help="modulo de RTL top (default: igual al nombre)")
    ap.add_argument("--clk-port", default="adc_clk_i", help="puerto de reloj (default: adc_clk_i)")
    ap.add_argument("--rstn-port", default="adc_rstn_i", help="puerto de reset activo bajo")
    ap.add_argument("--force", action="store_true",
                    help="sobreescribe archivos existentes (por defecto NO pisa nada)")
    args = ap.parse_args()

    mod = args.modulo
    top = args.top or mod
    clk, rstn = args.clk_port, args.rstn_port
    root = os.path.join(MODULOS, mod)

    if not os.path.isdir(os.path.join(MODULOS, "mk")):
        print(f"error: no encuentro {MODULOS}/mk", file=sys.stderr)
        return 1

    print(f"\n{'=' * 60}\n  modulo: {mod} | top: {top} | clk: {clk}\n{'=' * 60}\n")

    for d in DIRS:
        create_dir(os.path.join(root, d))

    f = args.force
    create_file(os.path.join(root, "files.f"), files_f(mod, top), f)
    create_file(os.path.join(root, "extra.f"), extra_f(mod), f)
    create_file(os.path.join(root, "work", "Makefile"), work_makefile(mod, top), f)
    create_file(os.path.join(root, "syn", "inputs", f"{top}_ooc.xdc"), ooc_xdc(top, clk), f)
    create_file(os.path.join(root, "sim", "sva", f"{top}_sva.sv"), sva(mod, top, clk, rstn), f)
    create_file(os.path.join(root, "sim", "sva", f"bind_{mod}.sv"), sva_bind(mod, top), f)
    create_file(os.path.join(root, "sim", "VERIFICACION.md"), verificacion_md(mod, top), f)
    create_file(os.path.join(root, "lint", "run_spyglass.tcl"), spyglass_tcl(mod, top), f)
    create_file(os.path.join(root, "lint", f"{mod}.sgdc"), sgdc(mod, top, clk, rstn), f)
    create_file(os.path.join(root, "modelos", "c_model", f"{mod}_model.c"), c_model(mod), f)
    create_file(os.path.join(root, "modelos", "python_model", f"{mod}_model.py"),
                python_model(mod), f)

    print(f"""
{'=' * 60}
  Listo: modulos/{mod}
{'=' * 60}

  Falta a mano:
    1. modulos/{mod}/files.f      poner el RTL en orden de dependencia
    2. modulos/{mod}/work/Makefile  completar DEPS y TBS
    3. prj/MCA/Makefile           agregar '{mod}' a MODS
    4. prj/MCA/rtl_files.tcl      agregar '{mod}' a rtl_modules (para el bitstream)

  Flujo:
    make -C modulos/{mod}/work          testbenches
    make -C modulos/{mod}/work cov      + cobertura
    make -C modulos/{mod}/work lint     lint
    make -C modulos/{mod}/work syn      sintesis OOC
    make -C modulos/{mod}/work sweep-all  barrido + CSV + graficos
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

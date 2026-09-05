# `prj/MCA/modulos/`

El RTL propio del proyecto, repartido en módulos autocontenidos. Cada módulo
tiene su RTL, sus testbenches, su modelo de referencia, su lint, su síntesis y
su plan de verificación, y se puede correr sin tocar los demás.

```
modulos/
├── mk/                     infraestructura compartida (una sola copia)
│   ├── module.mk           reglas de sim/lint/syn/cobertura
│   ├── syn_ooc.tcl         síntesis out-of-context en Vivado
│   ├── extract_metrics.py  barrido -> CSV + resumen.md
│   └── plot_sweep.py       barrido -> PNG
├── scripts/create_module.py   generador de módulos nuevos
├── comun/                  integration_cfg, dsp_tap_mux (región de TOP, slot 6)
├── osc/                    osc_cfg (slot 1) + osc_filter
├── multitrigger/           multitrigger_* (slot 3) + el datapath del scope
├── mca/                    cadena de análisis de altura de pulso (slot 7)
└── event_ring/             ring de slots de evento en DDR
```

Cada módulo:

```
<m>/
├── files.f        RTL propio, en orden de dependencia (rutas rel. al módulo)
├── extra.f        RTL del repo raíz que necesita (rutas rel. a la raíz)
├── rtl/
├── sim/           testbenches, sva/ (assertions por bind), VERIFICACION.md
├── modelos/       c_model/ y python_model/
├── lint/
├── syn/           inputs/<top>_ooc.xdc, outputs/, logs/
├── uvm/
└── work/          Makefile: punto de entrada. Acá caen waves/, logs/, cov/, rpt/
```

## Correr

```bash
make -C modulos/mca/work            # todos los TB del módulo
make -C modulos/mca/work tb_mca_top # uno solo
make -C modulos/mca/work wave TB=tb_mca_top   # ondas ya grabadas
make -C modulos/mca/work cov        # cobertura -> work/cov/html/index.html
make -C modulos/mca/work lint       # vlog -lint
make -C modulos/mca/work syn        # síntesis OOC a 125 MHz
make -C modulos/mca/work sweep-all FREQS_MHZ="100 125 150"
```

Desde `prj/MCA` está el dispatcher: `make rtl`, `make rtl-mca`,
`make rtl-tb_mca_top`, `make wave TB=...`.

## Cómo se declara el RTL

En `files.f` y `extra.f`, **no en el Makefile**. `module.mk` los lee para el
módulo y para cada uno de sus `DEPS`, así una dependencia arrastra las suyas
sin que el módulo de arriba las repita, y deduplica preservando el orden.

Los `.f` viven en la raíz del módulo y **no** dentro de `rtl/`, a propósito: el
`add_files modulos/<m>/rtl` del TCL de Vivado levantaría un `.f` suelto como
archivo de tipo desconocido.

## Dos cosas que NO hay que hacer

**No poner `add_files modulos` en el TCL de Vivado.** `add_files` recursa: se
llevaría `sim/`, `uvm/`, `modelos/`, `lint/`, `syn/` y `work/` — incluida la
librería de QuestaSim y los `.wlf`. El TCL agrega sólo `modulos/<m>/rtl` por
módulo; la lista está en [`../rtl_files.tcl`](../rtl_files.tcl).

**No meter las assertions en el RTL.** Van en `sim/sva/`, enganchadas por
`bind`. Así el RTL sintetizable no se toca, no hace falta `ifndef SYNTHESIS`, y
como nunca entran a `files.f`, Vivado ni las ve.

## Agregar un módulo

```bash
python3 modulos/scripts/create_module.py <nombre> --top <modulo_top>
```

El script **no pisa nada** que ya exista (usar `--force` si se quiere lo
contrario), así que también sirve para completar el andamiaje de un módulo que
ya está. Después hay que agregarlo a mano en dos lugares: `MODS` en
`prj/MCA/Makefile` y `rtl_modules` en `prj/MCA/rtl_files.tcl`.

## Síntesis por módulo

Vivado out-of-context sobre `xc7z010clg400-1`. `mk/syn_ooc.tcl` es único y
compartido; lo propio de cada módulo es `syn/inputs/<top>_ooc.xdc`, que lee el
período de `PERIOD_NS` (por eso el barrido no necesita un XDC por punto).

Las métricas salen de un `metrics.txt` en `CLAVE=VALOR` que emite el TCL
leyendo las properties de Vivado, no de parsear los `.rpt`: el formato de los
reportes cambia entre versiones, las properties no. `extract_metrics.py` sólo
los junta.

Ojo con `lut`: cuenta **primitivas** LUT, no los "Slice LUTs" del
`report_utilization` (dos LUT5 que comparten O5/O6 ocupan un solo sitio). Para
comparar entre frecuencias y módulos conviene la primitiva, que no depende de
decisiones de empaquetado.

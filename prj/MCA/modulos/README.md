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
│   ├── plot_sweep.py       barrido -> PNG
│   └── datasheet.py        RTL -> diagrama de interfaz + datasheet.md
├── scripts/create_module.py   generador de módulos nuevos
├── comun/                  integration_cfg, dsp_tap_mux (región de TOP, slot 6)
├── mt/                     mt_* + trigger_shield (multitrigger, slot 3)
├── osc/                    osc_cfg (slot 1) + osc_filter + el datapath del scope (rp_scope_mt_com)
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

## Datasheet por top de RTL

**Una página por top, no por módulo.** Los 20 tops de los cinco `files.f`
tienen la suya.

```bash
make -C modulos/mca/work datasheet                       # todos los tops del módulo
make -C modulos/mca/work datasheet DS_TOPS="mca_hist mca_top"
make -C modulos/mt/work datasheet DS_TOP=trigger_shield  # uno solo
make -C modulos/mca/work datasheet-check                 # para CI
```

`DS_TOPS` es a los datasheets lo que `TBS` a los testbenches: la lista de tops
que tienen página. Vacía —lo normal— quiere decir **todos los de `files.f`**;
se declara en el `work/Makefile` sólo para documentar menos de los que hay.

Todo sale junto en [`docs/datasheet/`](../docs/datasheet/):

```
docs/datasheet/README.md                  el índice, agrupado por módulo
docs/datasheet/datasheet_<top>.md         la página      (generada)
docs/datasheet/figuras/<top>_interfaz.svg el diagrama    (generado)
docs/datasheet/prosa/<top>.md             la §1.1 a mano (NUNCA se pisa)
```

**La prosa vive afuera de la página.** La §1.1 «Qué hace» —qué problema
resuelve el bloque, cómo encaja en la cadena, las decisiones que explican su
forma— es lo único del datasheet que no se deriva del RTL, y por eso es lo
único que se guarda aparte. El generador crea `prosa/<top>.md` vacío la primera
vez y después **no lo vuelve a escribir nunca**; en cada corrida lo copia
dentro del bloque `AUTO:prosa` de la página, descartando los comentarios HTML
de cabecera del archivo.

La consecuencia práctica es la que importa: la página es **derivable entera**.
Se puede borrar `docs/datasheet/datasheet_<top>.md` y `make datasheet` la
reconstruye idéntica, prosa incluida. Antes, borrar la página perdía lo
escrito. Los enlaces se escriben **relativos al archivo de prosa**, que es lo
que un chequeo de enlaces puede verificar, y el generador los recalcula con
`relpath` al copiarlos a la página.

Van todas al mismo directorio y no a `docs/<módulo>/` porque son **el mismo
género de documento** y se buscan por nombre de top de RTL, no por carpeta. Las
figuras propias de cada módulo —ondas, transacciones, las del MCA— se quedan
donde están: a la página llegan por ruta relativa, que el generador resuelve
con `relpath`, así que mover una página no rompe un enlace.

El diagrama se arma leyendo la cabecera del RTL: los puertos de entrada a la
izquierda, los de salida a la derecha, **agrupados por los banners
`// --- grupo ---`** que el RTL ya tiene, con el ancho de cada bus resuelto con
los `GENERICS` del `work/Makefile` (no con los defaults). También se reconocen
los rótulos sueltos de una línea (`// Fuentes de trigger`), que es como agrupa
`mt_event_logic.v`.

Cada grupo se dibuja como en un datasheet: una **elipse sobre los cables** que
lo componen, una **llave** más afuera y el nombre del grupo al costado. Los
buses llevan además un **punto que dice de qué lado está el que manda**:

```
● maestro   el módulo maneja addr/wen/valid  -> inicia las transacciones
○ esclavo   los recibe y contesta con ack/rdata
```

El rol **se infiere del RTL**, no se declara: se mira si los puertos de comando
(`addr`, `wen`, `ren`, `ce`, `valid`, `start`) son salidas o entradas. Sólo se
marca cuando el grupo tiene comando **y** respuesta (`ack`, `ready`, `rdata`,
`q`, `err`); si no, un `mca_dat_i` + `mca_val_i` se marcaría de esclavo y no es
un bus, es un flujo sin vuelta. En la práctica eso da `sys_*` → esclavo y el
AXI de `event_ring_top` → maestro, que es justo lo que dicen los banners del
RTL.

Los nombres se reconocen con hasta dos letras de dirección pegadas adelante
(`waddr`, `wvalid`, `wrdy` cuentan como `addr`, `valid`, `rdy`), porque así
está escrito el AXI de este proyecto.

**Lo que se autogenera y lo que no.** Las secciones derivables —interfaces,
mapa de registros, clock domains, Fmax y camino crítico, waveforms,
verificación— van entre marcas `<!-- AUTO:x -->` y se **reescriben** en cada
corrida. Todo lo demás —qué hace el bloque, por qué está hecho así, el esquema
de laboratorio— es prosa a mano y no se toca nunca. O sea: se agrega un puerto,
se corre `make datasheet` y la tabla se actualiza sin perder lo escrito.

Si una marca **no está** —porque la sección es nueva y la página es vieja— el
bloque se **inserta** después de su encabezado ancla en vez de saltearse. Así
agregar una sección llega sola a las páginas que ya existen, sin tener que
borrarlas y perder la prosa.

## Waveforms: de un VCD, no a mano

`§1.6` de cada datasheet sale de un script por módulo:

```
docs/<m>/figuras/ondas/ondas_<m>.py     las figuras y sus epígrafes
docs/figuras/ondas.py                   la biblioteca compartida
```

Las ondas salen de un **VCD de verdad** de los testbenches, y las latencias
—cuántos ciclos dura una ventana, cuánto tarda un ack— las **mide el script** y
las escribe en el epígrafe. Un número a mano en una figura generada es lo que
esto está para evitar: si cambia una latencia, cambia el epígrafe sin que nadie
lo toque. La ventana se ubica por **condiciones sobre las señales** (el cruce
de un umbral, el juego de coeficientes que define la escena), nunca por un
tiempo fijo.

Para que el FST se pueda versionar hay que recortarlo: el VCD completo de
`tb_osc_filter` son 23 MB porque Questa escribe los vectores bit por bit.
`make vcd` acepta `VCD_ADD` y `VCD_RUN` para acotar el volcado, y los scripts
tienen `--recortar`, que deja sólo la ventana que se dibuja.

El datasheet no nombra las figuras a mano: lee el manifiesto `ondas.json` que
escribe cada script, así que agregar o sacar una se refleja solo.

## Transacciones: qué dato entra al bloque y qué dato sale

`§1.6` de cada datasheet es otra cosa que `§1.7`. Las ondas son **ciclo a
ciclo**; las transacciones son **dato a dato**: un paso es un evento, una
ventana o una muestra, no un flanco de reloj.

```
docs/<m>/figuras/transacciones/transacciones_<m>.py   las figuras
docs/figuras/transacciones.py                         la biblioteca compartida
docs/figuras/estilo.py                                paleta y rcParams
```

Cada módulo tiene un tríptico —qué entra, qué viaja, qué sale— más los tres
paneles sueltos, siguiendo [`docs/mca/figuras/07_cadena.png`](../docs/mca/figuras/07_cadena.png),
que era la única figura del proyecto que mostraba la cuenta completa de punta a
punta. El panel del medio es el que hace a la figura una figura de
transacciones: entre los bloques no va una flecha pelada sino **el tren de
valores concretos que viajan**, y son los mismos del panel de arriba.

**De dónde sale el dato, por módulo.** La columna «Datos» del README de cada
directorio lo dice, y no es lo mismo en todos:

| Módulo | Transacción | Datos |
|---|---|---|
| `event_ring` | una ventana → un slot de DDR | ventana **medida** (campaña e2e); el slot se arma con el layout del RTL y se **decodifica con `ring_format.py`**, el mismo decodificador de producción, comprobando que las muestras vuelven bit a bit |
| `mt` | un disparo → una captura | **medidos**: los `t_ns` del barrido de tasa. La eficiencia no se copia del archivo, se **recalcula** como `1/⟨k⟩` y se compara con la que el barrido guardó |
| `osc` | un flujo de muestras → otro flujo | **del VCD** de `tb_osc_filter`, con `ref_out` superpuesto: la igualdad DUT/modelo se recalcula al dibujar |
| `comun` | una muestra y su valid → cuatro nodos | pulso **medido** + diezmado y retardo **exactos**; la calibración se dibuja pero **no se le inventan coeficientes** |
| `mca` | un evento → una cuenta del espectro | simulación con semilla fija |

Lo que tienen en común: **ningún número está escrito a mano**. Se miden o se
recalculan al dibujar, y varios se validan contra una segunda fuente que ya
existía en el repo. Si las dos dejan de coincidir, el script falla en vez de
dibujar algo que no pasó.

Los datos que una figura necesita se **recortan y se versionan al lado**
(`--extraer`), porque `software/datos/` no está versionado y un chunk de la
campaña son 14 MB: lo que queda son 120 kB para las cuatro figuras. Es la misma
disciplina que los FST recortados de las ondas.

## Las figuras van sin prosa adentro

Vale para las tres familias —las de datos, las de ondas y las de bloques—:

> Los gráficos van **sin texto adentro**: sólo ejes, leyenda y las marcas
> imprescindibles.

Cuando un diagrama necesita rotular muchas cosas, lo que lleva adentro es un
**número**, y la explicación es una **fila de tabla** del documento que lo
embebe. El patrón ya estaba declarado en
[`docs/figuras/figuras_movimiento_de_datos.py`](../docs/figuras/figuras_movimiento_de_datos.py)
y ahora lo siguen también las del TOP y las de la API. La razón no es estética:
con el texto adentro había **dos copias de lo mismo** —el dibujo y el
epígrafe— y se desincronizan.

**Y si una figura es una tabla, es una tabla.** El criterio para decidirlo es
objetivo: si el SVG no tiene flechas (`<path>` ≈ 0) es una grilla de cajas con
texto, o sea una tabla dibujada. Dos lo eran y se convirtieron —
`conformado_por_tap.svg` (64 textos, 22 rectángulos, **1** path) y
`cobertura_tests.svg` (78 textos, 44 rectángulos, **0** paths)—: ahora se
pueden copiar, las encuentra el `grep` y se corrigen sin regenerar nada.

## El plan de verificación se cosecha de los testbenches

`modulos/<m>/sim/VERIFICACION.md` tenía una tabla con una fila en blanco en los
cinco módulos. Ahora la sección «Casos cubiertos» se **genera** leyendo los
testbenches: las escenas numeradas (`// 3) BARRIDO DE ACK ...`) y el nombre de
cada `check("...")`. Son 462 casos con nombre en 16 testbenches, y ya estaban
escritos; lo único que faltaba era juntarlos.

O sea que para documentar un caso nuevo alcanza con **nombrar bien el
`check()`** en el testbench. Lo que queda a mano es lo que no es derivable:
casos borde conocidos, deuda y metas de cobertura.

Se reconocen también las tareas que chequean por indirección: `tb_osc_filter`
no llama a `check()` desde el cuerpo principal sino a `run_case("nombre")`, que
adentro hace el `check`. Sin seguir esa cadena ese testbench declararía 1 caso
en vez de 10.

§1.7 además **dice la verdad sobre las assertions**: los cinco `sim/sva/*_sva.sv`
son el scaffold de `create_module.py` y no tienen ninguna propiedad. La página
los enlazaba como si tuvieran. Qué propiedades convendría escribir primero, y
si vale la pena probarlas formalmente, está en
[`../docs/verificacion_formal.md`](../docs/verificacion_formal.md).

La sección de Fmax sale de `syn/outputs/metrics.txt` y del barrido
`work/rpt/sweep_results.csv`, así que conviene correrla **después** de `syn` o
`sweep-all`; si no, la página lo dice y queda el comando para completarla.

`make datasheet-check` no escribe nada y falla si la página quedó vieja
respecto del RTL: sirve para enganchar en CI.

Ojo con `lut`: cuenta **primitivas** LUT, no los "Slice LUTs" del
`report_utilization` (dos LUT5 que comparten O5/O6 ocupan un solo sitio). Para
comparar entre frecuencias y módulos conviene la primitiva, que no depende de
decisiones de empaquetado.

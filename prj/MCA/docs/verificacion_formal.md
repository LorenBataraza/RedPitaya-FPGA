# ¿Conviene verificación formal en este proyecto?

Este documento **no implementa nada**. Es el análisis de dónde la verificación
formal pagaría y —sobre todo— dónde no, para poder decidir con números en vez
de con entusiasmo.

La conclusión corta, por si no se lee el resto:

> **Sí, en cinco bloques de control, y el mejor candidato no es el que parece.**
> El caso con mejor relación costo/beneficio es `mca_div_restore`, porque su
> testbench es exhaustivo **a un ancho que el diseño nunca usa**. El segundo es
> el ack de latencia fija de `mca_top`, porque su modo de falla no es un dato
> malo sino un slot muerto para siempre. En los dos bloques de datapath pesado
> —`osc_filter` y `mca_pulse_feature`— el formal **no** es el camino, y el
> modelo de referencia que ya existe es mejor herramienta.
>
> Pero el obstáculo real hoy no es ninguno de esos juicios: es que **no hay ni
> una sola propiedad escrita**. Los cinco `sim/sva/*_sva.sv` son el scaffold de
> `create_module.py`, con el `bind` hecho y un `// TODO:` adentro. Escribir esas
> propiedades mejora la simulación desde el primer día, se adopte formal o no.

---

## 1. Las herramientas ya están

No hay que comprar ni instalar nada. En `/tools/oss-cad-suite/bin`:

| Herramienta | Versión | Para qué |
|---|---|---|
| `sby` (SymbiYosys) | — | el orquestador: lee un `.sby`, arma el problema y llama al solver |
| `yosys` | 0.65 | front-end de Verilog/SVA y síntesis a lógica para el solver |
| `boolector`, `yices`, `z3` | — | solvers SMT |
| `avy`, `yosys-smtbmc` | — | prueba por inducción / interpolación (`prove`), no sólo BMC |

Dos salvedades que conviene escribir ahora y no descubrir después:

- **Yosys lee un subconjunto de SVA.** `|->`, `|=>`, `##n`, `##[a:b]`,
  `$past`, `$rose`, `$stable` y las secuencias simples alcanzan para todas las
  propiedades de este documento. Lo que no entra —secuencias con `intersect`,
  `within`, propiedades recursivas, `local variables`— pide Verific, que no
  está en el build libre. Ninguna de las propiedades de abajo lo necesita.
- **`bind` habría que confirmarlo en el primer intento.** Yosys 0.65 soporta
  `bind`, así que en principio `sim/sva/` se reusa tal cual entre simulación y
  formal, que es lo que uno quiere. Si no funcionara, la salida es un wrapper
  que instancie el DUT y las propiedades juntos: media hora, no un rediseño.
  **Esto no está probado**; es el primer riesgo a despejar.

El costo de arranque, entonces, no es la herramienta. Es escribir propiedades.

---

## 2. Qué dice formal que la simulación no diga

Los testbenches de este árbol son buenos: 462 casos con nombre, un test de
equivalencia contra el RTL original, barridos exhaustivos donde se puede. La
pregunta no es si están bien hechos, sino **qué clase de afirmación pueden
hacer**.

Un testbench dice *«para estos estímulos, el RTL hizo esto»*. El formal dice
*«para TODOS los estímulos posibles, el RTL no puede hacer esto otro»*. La
diferencia importa exactamente cuando se cumplen las tres condiciones:

1. el espacio de entradas es **demasiado grande para enumerarlo**;
2. el estado del bloque es **chico** (control, no acumuladores anchos);
3. el modo de falla es **caro o silencioso** — algo que no se nota mirando una
   corrida.

Donde no se cumplen las tres, el formal es trabajo sin rédito. El resto de este
documento es aplicar ese filtro bloque por bloque.

---

## 3. Los candidatos, ordenados

| # | Bloque | Propiedad | Por qué gana al testbench | Costo | Veredicto |
|---|---|---|---|---|---|
| 1 | `mca_div_restore` | `rem < den` siempre; `q == floor(num·2^Q_W/den)`; `start \|-> ##Q_W valid` | El barrido es exhaustivo **a D_W=8**, y el diseño corre a **D_W=32** | bajo | **empezar por acá** |
| 2 | `mca_top` | `sys_ren \|-> ##[1:20] sys_ack` | 1150 lecturas a mano contra 2^20 direcciones; la falla mata el slot | bajo | **sí** |
| 3 | `mca_hist` | dos eventos al mismo bin nunca pierden una cuenta | Datos sin acotar, control mínimo | medio | sí |
| 4 | `trigger_shield` | el veto **siempre** termina; `active` no se queda pegado | El TB prueba un `dur`; el formal, todos | bajo | sí |
| 5 | `mt_trig_src` | tras un single-shot no se re-dispara sin `trig_dis_clr` | FSM chica, propiedad de secuencia | bajo | sí |
| 6 | `osc_cfg` | el contrato del bus (ack, sin `err` espurio) | **No tiene testbench**: cualquier cobertura es ganancia | bajo | sí, por descarte |
| 7 | `osc_filter` | equivalencia con `osc_filter_ref` con coeficientes **simbólicos** | El TB ya es equivalencia, pero con 12 juegos **al azar** | alto, incierto | a probar, con red |
| 8 | `mca_pulse_feature` | — | Acumuladores anchos sobre ventanas de miles de ciclos | muy alto | **no** |

### 1. `mca_div_restore` — el mejor, y por una razón que no es obvia

El testbench hace un **barrido exhaustivo**: todos los `den` de 1 a 2^D_W−1 y
todos los `num` de 0 a den−1, comparando contra la división entera de Verilog.
Son ~32 600 divisiones y no se le escapa ningún valor. Suena a que no hay nada
que agregar.

El problema está en una línea de `tb_mca_div_restore.sv`:

```systemverilog
localparam integer D_W = 8, Q_W = 6;
```

y en cómo lo instancia `mca_pulse_feature.sv:432`:

```systemverilog
mca_div_restore #(.D_W(QW), .Q_W(DIV_W)) i_div (...)   // QW=32, DIV_W=16
```

**El barrido es exhaustivo a un ancho que el diseño no usa.** Lo que corre en la
placa tiene operandos de 32 bits y 16 bits de cociente: 2^32 × 2^32 pares
posibles, de los que el test visita 32 600 a otro ancho. El argumento de que
«el algoritmo es el mismo y el ancho no cambia nada» es probablemente cierto
—la cabecera del RTL lo argumenta bien, con la invariante `rem < den`— pero es
un argumento, no una verificación.

Y es justo lo que el formal prueba barato:

```systemverilog
// La invariante que la cabecera del RTL ya declara, ahora demostrada.
ap_rem_acotado:  assert property (busy_o |-> rem < den_q);
// La latencia fija de la que depende el tiempo muerto del MCA.
ap_latencia:     assert property (start_i && !busy_o |-> ##Q_W valid_o);
// Los dos casos borde que la cabecera marca como peligrosos.
ap_sat_no_wrap:  assert property (valid_o && sat_o |-> q_o == {Q_W{1'b1}});
ap_den_cero:     assert property (valid_o && den_q == 0 |-> err_o);
```

Es un lazo de desplazamiento y resta: **no hay multiplicadores**, el estado son
dos registros y un contador de 3 bits, y el solver trabaja con operandos
simbólicos de 32 bits sin despeinarse. Es el caso de libro: espacio inmenso,
estado chico, y una invariante ya escrita en castellano arriba del módulo
esperando a que alguien la formalice.

El modo de falla también es del tipo caro: la cabecera dice que `num == den`
sin saturar da 2^Q_W, que **envuelve a 0** y manda el evento *al extremo opuesto
del eje de forma*. Un evento en el bin equivocado no se ve mirando una onda; se
ve como un pico fantasma en un mapa 2D, meses después.

### 2. `mca_top` — el ack de latencia fija

La cabecera del RTL lo marca como lo más importante del módulo, y con razón: un
esclavo que no hace ack no produce una lectura mala, deja el CDC del slot
**desincronizado para siempre**. `reg_done` sólo avanza con el ack, así que sin
ack queda `reg_do != reg_done` eternamente y ese slot no acepta una transacción
más. El timeout de 32 ciclos del `axi4_slave` rescata al ARM, pero devuelve
basura sin marcar error.

Hoy eso se verifica enumerando a mano (escena 3 de `tb_mca_top`): ~1150
lecturas sobre registros, huecos, las dos aperturas, direcciones no mapeadas y
los extremos del slot. Es un buen test, y la figura `mca_ack_borrado.svg` del
datasheet muestra que el ack llega en 4 ciclos constantes incluso durante el
barrido de borrado. Pero el slot tiene **2^20 direcciones** y la lista se
escribió a mano: lo que protege contra una dirección olvidada es la atención
del que la escribió.

```systemverilog
ap_ack_siempre: assert property (sys_ren |-> ##[1:20] sys_ack);
ap_sin_err:     assert property (sys_ack |-> !sys_err);
```

Con `sys_addr` simbólica eso cubre las 2^20 de una. Y como el ack sale de un
shift register incondicional, la prueba debería cerrar por inducción casi
inmediatamente: el estado relevante son 4 flip-flops.

Hay un corolario útil, con una aclaración importante. El proyecto tiene un
ejemplar **conocido** de exactamente esa falla:
`rp_scope_mt_com.sv:671` ata `bram_ack[GM] = 1'b0` para los canales no
construidos, y `mt_rp_scope_cfg.sv:504-507` usa `bram_ack_i[2]` y
`[3]` como ack de las aperturas 3 y 4. Con `N_CH=2`, leer `0x3????` o `0x4????`
no haría ack nunca.

**La aclaración: ese módulo ya no se instancia.** `mt_rp_scope_cfg`
quedó partido en `osc_cfg` + `mt_cfg`; sigue en `files.f` y se
compila, pero no hay ninguna instancia suya en el árbol, y el camino vivo usa
latencia fija (`rp_scope_mt_com.sv:277-279`). O sea que **el diseño
que se sintetiza no tiene este bug**: lo que hay es RTL legacy con un bug
conocido adentro.

Eso igual lo vuelve el mejor banco de pruebas posible para justificar la
inversión, justamente porque es inofensivo: se corre la propiedad sobre un
módulo del que se sabe de antemano que **tiene que fallar**, y si el flujo no
lo encuentra, el flujo está mal armado. Es un test del método, no del diseño.

### 3. `mca_hist` — el read-modify-write

Incrementar un bin es leer la BRAM, sumar y escribir. Si dos eventos
consecutivos caen en el mismo bin, el segundo leería el valor viejo. El bloque
puentea la escritura en vuelo y el testbench lo prueba con rachas de 2, 3, 4 y
20 incrementos y con un patrón alternado A,B,A,B.

Está bien cubierto. Lo que el formal agregaría es la propiedad general —*ninguna
secuencia de incrementos pierde una cuenta*— en vez de las cinco secuencias que
a alguien se le ocurrieron. El costo es medio porque hay que modelar la BRAM y
elegir bien la abstracción (un bin simbólico, no los 2^AW). Vale la pena
después de los dos primeros, no antes.

### 4 y 5. `trigger_shield` y `mt_trig_src`

Dos FSM chicas con propiedades de vivacidad acotada, que son baratas de probar
y molestas de testear:

```systemverilog
// El veto SIEMPRE termina. Hoy se prueba con dur=8 y dur=12.
ap_veto_termina: assert property (mca_veto_o |-> ##[1:$] !mca_veto_o);
// Tras un single-shot no hay segundo disparo sin limpiar el disable.
ap_single_shot:  assert property (
    adc_trig && !we_keep |=> !adc_trig throughout (!trig_dis_clr)[*1:$]);
```

La figura `mt_veto_tres_formas.svg` del datasheet mide 21, 13 y 13 ciclos para
las tres configuraciones que el testbench prueba. `shield_dur` tiene 16 bits:
el formal cubre los 65 536 valores y, más importante, demuestra que **no existe**
una combinación de fuente, destino y duración que deje el veto pegado. Un veto
que no baja es un MCA que no cuenta más y no avisa.

### 6. `osc_cfg` — el que no tiene nada

`TBS := tb_osc_filter` y se acabó: **`osc_cfg` no tiene testbench propio**. Está
anotado en §1.7 de su datasheet. Es el único bloque de esta lista donde el
formal no compite con la simulación sino con la nada, así que la propiedad del
contrato del bus —la misma del punto 2— es la forma más barata de tener
*alguna* garantía mientras no exista un `tb_osc_cfg`.

No es un argumento a favor del formal: es un argumento a favor de escribir el
testbench. Pero si hay una tarde y no una semana, la propiedad rinde más.

### 7. `osc_filter` — el interesante, con riesgo real

Este es el que más me tentó y el que más hay que matizar.

`tb_osc_filter` ya es un **test de equivalencia secuencial**: instancia
`osc_filter` y `osc_filter_ref` lado a lado, los alimenta con el mismo estímulo
y cuenta discrepancias ciclo a ciclo. Es la forma correcta de verificar un
rediseño. Pero los coeficientes se prueban en **once configuraciones elegidas a
mano más doce al azar**, y el espacio es `aa` (18 bits) × `bb`, `kk`, `pp` (25
bits cada uno) ≈ 2^93.

La versión formal es un *miter*: las dos implementaciones, el mismo estímulo,
coeficientes **simbólicos**, y la aserción `dut_out == ref_out` sobre un
horizonte acotado. Incluso un resultado de 10 o 15 ciclos es estrictamente más
fuerte que doce sorteos.

El riesgo es concreto y hay que decirlo: el camino tiene **multiplicadores de 25
bits** y bit-blastearlos sobre 15 ciclos puede hacer que el solver no cierre en
un tiempo razonable. Mitigaciones conocidas: probar primero con los
multiplicadores abstraídos como funciones no interpretadas (prueba la
*estructura*, no la aritmética), o fijar `kk` y dejar simbólicos sólo `aa`/`pp`,
que es donde estuvo el rediseño. Presupuesto honesto: una tarde para saber si
cierra, con el barrido aleatorio como red si no.

Y una cosa que el formal **no** arregla acá: si las dos implementaciones
comparten el mismo error conceptual, la equivalencia pasa igual. Es una prueba
de que el rediseño no cambió nada, no de que el filtro sea correcto.

### 8. `mca_pulse_feature` — acá no

Es el bloque más importante del MCA y es el peor candidato de la lista. Las tres
condiciones del filtro fallan todas:

- **El estado no es chico**: `q_tot` y `q_tail` son acumuladores de 32 bits que
  suman sobre ventanas de hasta `maxlen` muestras, con `maxlen` de 16 bits. La
  profundidad de BMC necesaria para ver un pulso completo es de miles de ciclos.
- **La propiedad interesante no es estructural**: «la amplitud es el pico de la
  ventana» o «q_tot es la suma de las muestras menos la línea de base» exige un
  modelo de referencia, y **ese modelo ya existe** en `modelos/python_model/` y
  `modelos/c_model/`.
- **El modo de falla no es silencioso**: un extractor de features roto se ve en
  el espectro a los diez segundos de medir.

Para este bloque la herramienta correcta es la que ya está: vectores dirigidos
con valores calculados a mano (por eso el testbench usa pulsos rectangulares) y
el modelo de referencia para el estímulo realista. Lo único que yo agregaría son
aserciones *baratas* de sanidad corriendo en simulación —`busy_o` no se queda
pegado, `ev_valid_o` no sale con la ventana abierta, los contadores no
retroceden— que no necesitan formal para pagar.

---

## 4. Lo que yo haría, en orden

1. **Escribir las propiedades de sanidad de los cinco `*_sva.sv`** (una tarde).
   No es formal todavía: corren en simulación, con los testbenches que ya
   existen, y convierten chequeos puntuales en invariantes que valen en todo
   ciclo. Esto rinde aunque el resto no se haga nunca, y es el prerrequisito de
   todo lo demás.
2. **Un `.sby` sobre `mca_div_restore`** (medio día). Es el bloque más chico,
   la invariante ya está escrita en la cabecera, no hay multiplicadores y
   despeja el riesgo de `bind`. Si el flujo anda acá, anda.
3. **El ack de `mca_top`** (medio día), y después la misma propiedad sobre
   `mt_rp_scope_cfg` —RTL legacy, no instanciado— donde **se sabe que
   tiene que fallar**. Que el flujo encuentre solo ese contraejemplo es la
   demostración que justifica seguir.
4. Recién ahí: `trigger_shield`, `trig_src`, `mca_hist`.
5. `osc_filter` como experimento acotado, con el barrido aleatorio de red.

Total hasta el punto 3: **un día y medio**, que es el presupuesto para saber si
el flujo sirve en este proyecto con un resultado concreto en la mano.

## 5. Lo que NO hay que esperar del formal

- **No reemplaza los testbenches.** Las 462 pruebas con nombre siguen haciendo
  falta: prueban comportamiento de punta a punta, que es otra cosa.
- **No encuentra errores de especificación.** Si la propiedad está mal escrita,
  el formal demuestra lo que no era. La equivalencia de `osc_filter` es el
  ejemplo: prueba que las dos implementaciones coinciden, no que el filtro esté
  bien.
- **No es gratis de mantener.** Una propiedad que deja de cerrar después de un
  cambio de RTL hay que arreglarla, y diagnosticar un contraejemplo de 40 ciclos
  lleva su tiempo.
- **No escala al top.** Esto es para bloques, no para `mca_red_pitaya_top`.

---

## Referencias

- Plan de verificación por módulo: `modulos/<m>/sim/VERIFICACION.md` — la tabla
  de casos cubiertos la genera `make datasheet` leyendo los testbenches.
- Los datasheets, §1.7: [`mca/datasheet_mca_top.md`](datasheet/datasheet_mca_top.md),
  [`osc/datasheet_osc_cfg.md`](datasheet/datasheet_osc_cfg.md),
  [`datasheet/datasheet_mt_cfg.md`](datasheet/datasheet_mt_cfg.md).
- El contrato del bus y por qué un ack perdido mata el slot:
  [`TOP/bus_sistema_redpitaya.md`](TOP/bus_sistema_redpitaya.md) §7.1.
- SymbiYosys: `sby --help`, y los ejemplos en
  `/tools/oss-cad-suite/share/yosys/` si están en el build.

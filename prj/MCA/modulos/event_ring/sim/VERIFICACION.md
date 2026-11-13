# Plan de verificación — event_ring

DUT principal: `event_ring_top`

Sigue las cinco etapas de
[`docs/etapas_de_validacion.md`](../../../docs/etapas_de_validacion.md). La etapa 2,
la verificación, va completa. De las otras cuatro dice qué corre, dónde está y qué dio.

| Etapa | Qué hay para el ring | Estado |
|---|---|---|
| [1. Simulación](#1-simulación) | el modelo de `gen_eventos` y `predecir`: qué disparo sale en cada ts y qué patrón lleva | bit-exactos contra el RTL |
| [2. Verificación](#2-verificación) | los testbenches de `sim/` | en verde |
| [3. Generación interna](#3-generación-interna) | disparo por software; la campaña de etapas con `gen_eventos` | el techo del writer en la placa es el de la simulación, en las seis ventanas |
| [4. Generación externa controlada](#4-generación-externa-controlada) | pérdidas con arribos de Poisson del Rigol | la pérdida es la del apilamiento del estímulo |
| [5. Medición con setup experimental](#5-medición-con-setup-experimental) | — | sin hacer |

# 1. Simulación

| Qué | Dónde | Para qué |
|---|---|---|
| en qué ts sale cada disparo del generador y qué dato lleva cada muestra | [`gen_eventos_model.py`](../../gen_eventos/modelos/python_model/gen_eventos_model.py); `predecir` en [`API/generadores.py`](../../../software/API/generadores.py) (en C, por libmca) | el software sabe qué tiene que haber en cada slot. Con las marcas, la campaña de etapas predice `DROP_BUSY` exacto: un disparo a menos de `2·S + 3` ciclos del último aceptado se descarta |

# 2. Verificación

## Cómo se corre

```
make -C modulos/event_ring/work          # todos los testbenches
make -C modulos/event_ring/work <tb>     # uno solo
make -C modulos/event_ring/work cov      # + cobertura, reporte en work/cov/html/
make -C modulos/event_ring/work wave TB=<tb>   # ondas ya grabadas del último batch
```

Las ondas se graban **siempre** en batch (`work/waves/<tb>.wlf`). No se
condiciona el volcado a que haya un error: cuando el chequeo falla, el tiempo
que hay que mirar ya pasó.

## Casos cubiertos

<!-- AUTO:casos -->
<!-- Esta tabla la escribe `modulos/mk/datasheet.py` leyendo los
     testbenches: las escenas numeradas (`// N) ...`) y el nombre de
     cada check(). No editarla a mano. Lo de abajo (casos borde,
     assertions, metas) SI es a mano y no se toca. -->

**162 casos con nombre** en 6 testbenches. Cada fila es un `check()` que corre y tiene que dar PASS; el testbench entero falla si alguno no da.

### [`tb_event_window_capture`](tb_event_window_capture.sv) — `event_window_capture`

| Escena | Qué prueba | Caso |
|---|---|---|
| 7 | pre=0 (captura solo post) y ventana impar (no multiplo de 4) | cantidad de muestras |
|  |  | un solo sof |
|  |  | un solo eof |
|  |  | m_nsamp |
|  |  | m_snap |
|  |  | alineacion ch0 en pre |
|  |  | alineacion ch1 en pre |
|  |  | rampa+intercalado exactos |
|  |  | drop_full pulso |
|  |  | no se emitio nada |
|  |  | no quedo busy |
|  |  | ventana intacta pese al trigger extra |
|  |  | un solo sof |
|  |  | un solo eof |
|  |  | cantidad pre=0 |
|  |  | primera muestra = trigger |
|  |  | cantidad ventana impar |
|  |  | alineacion con pre=3 |
|  |  | evento A |
|  |  | evento B |
|  |  | alineacion evento B |
|  |  | una sola ventana |
|  |  | un solo sof |
|  |  | sin drop_busy espurio |
|  |  | alineado al FLANCO, no al nivel |


### [`tb_event_stage_fifo`](tb_event_stage_fifo.sv) — `event_stage_fifo`

| Caso |
|---|
| accept con FIFO vacia |
| sin metadatos |
| evento incompleto NO se ofrece |
| evento completo SI se ofrece |
| metadato ts |
| metadato snap |
| metadato nsamp |
| ev_lvl=1 |
| sin eventos tras el pop |
| lvl=0 |
| accept antes del 1ro |
| accept antes del 2do |
| accept BAJA antes del 3ro (no entra) |
| lvl=128 |
| ev_lvl=2 |
| accept vuelve tras drenar |
| ev_lvl=1 |
| metadato del 2do evento |
| lvl=0 al final |
| ev_lvl=0 al final |
| ev_lvl=E |
| accept BAJA por meta llena (no por espacio) |
| hay espacio de sobra |
| lvl=0 tras flush |
| ev_lvl=0 tras flush |
| accept tras flush |


### [`tb_event_slot_writer`](tb_event_slot_writer.sv) — `event_slot_writer`

| Escena | Qué prueba | Caso |
|---|---|---|
| 12 | una ventana no multiplo de 4 con contrapresion: el relleno de la ultima | palabras por slot |
|  |  | hdr0 timestamp |
|  |  | hdr1 seq |
|  |  | hdr1 n_samp |
|  |  | hdr1 n_ch |
|  |  | hdr2 snapshot |
|  |  | hdr3 reservado |
|  |  | empaquetado 4 muestras/palabra little-endian |
|  |  | relleno de ceros |
|  |  | footer es la ultima palabra |
|  |  | footer despues del ultimo dato |
|  |  | wr_slot avanzo |
|  |  | seq avanzo |
|  |  | palabras por slot (2do) |
|  |  | hdr1 seq = 1 |
|  |  | footer = {~1,1} |
|  |  | wr_slot=2 |
|  |  | misma cantidad de palabras con contrapresion |
|  |  | stream identico salvo seq/footer |
|  |  | footer al final con contrapresion |
|  |  | nada emitido sin creditos |
|  |  | no_credit levantado |
|  |  | no esta busy |
|  |  | el evento salio entero al volver el credito |
|  |  | footer correcto tras el freno |
|  |  | wr_slot=4 |
|  |  | palabras por slot (impar) |
|  |  | ultima palabra de datos |
|  |  | footer al final (impar) |
|  |  | err_ovf limpio antes |
|  |  | err_slot_ovf levantado |
|  |  | no se paso del slot |
|  |  | err_ovf limpio tras el flush |
|  |  | 4 ciclos entre palabras de datos |
|  |  | no es un error |
|  |  | palabras por slot (justa) |
|  |  | ultima palabra de datos (justa) |
|  |  | footer inmediatamente despues |
|  |  | 20 eventos identicos, con el relleno en su lugar |


### [`tb_event_ring_top`](tb_event_ring_top.sv) — `event_ring_top`

| Caso |
|---|
| MAGIC |
| N_SLOTS derivado |
| slot_base latcheado |
| hdr1 seq=0 |
| hdr1 n_samp |
| hdr1 n_ch |
| hdr2 snapshot |
| footer al final del slot |
| direcciones dentro del ring |
| intercalado ch0/ch1 en todo el slot |
| WR_SLOT=1 |
| SEQ=1 |
| EV_CNT=1 |
| slot_shift NO cambio |
| err_cfg levantado |
| direcciones siempre dentro del ring |
| SEQ acumulado |
| WR_SLOT acumulado |
| footer de cada slot = seq del ultimo evento que le toco |
| capturados + drop_busy + drop_full == triggers |
| hubo perdida contada (la rafaga excedio los creditos) |
| los creditos frenaron al writer |
| el writer escribio exactamente los slots acreditados |
| ningun slot quedo a medias |
| drena el stage al volver el credito |
| el ring quedo quieto |
| y sigue tomando eventos nuevos |
| wr_slot reiniciado |
| rd_slot reiniciado JUNTO con wr_slot |
| ocupados sano (sin underflow) |
| captura tras el stop/start |
| y aterrizo en el slot fisico 0 |
| volvio a STOPPED |
| la ventana en vuelo se completo y su footer esta bien |
| cabecera del ultimo evento intacta |
| el evento salio pese a la contrapresion |
| footer bien formado con contrapresion |
| intercalado intacto con contrapresion |
| sin overflow del axi_wr_fifo |


### [`tb_event_ring_ventana`](tb_event_ring_ventana.sv) — `event_ring_ventana`

| Escena | Qué prueba | Caso |
|---|---|---|
| 8 | 1014 muestras entran justas en 4 KB, y eso no es un error | 1024 pre=32 |
|  |  | dentro del ring |
|  |  | relleno en cero hasta el footer |
|  |  | muestra `pre` = la del trigger, en 8+24 y en 32+992 |
|  |  | 1024 pre=0 |
|  |  | 1024 pre=1023 |
|  |  | post=2047: rampa sin saltos |
|  |  | capturados + drop_busy + drop_full == triggers |
|  |  | ningun trigger cayo adentro de una ventana |
|  |  | el writer no da abasto: hubo drop_full |
|  |  | todo lo capturado se escribio |
|  |  | todos los slots con la rampa exacta y su footer |
|  |  | sin overflow del axi_wr_fifo |
|  |  | el evento salio |
|  |  | footer bien formado |
|  |  | rampa exacta con contrapresion |
|  |  | sin overflow con contrapresion |
|  |  | err_slot_ovf |
|  |  | 1014: WR_SLOT |
|  |  | 1014: sin err_slot_ovf |
|  |  | 1014: n_samp |
|  |  | 1014: footer en la ultima palabra |
|  |  | 1014: rampa sin saltos |


### [`tb_event_ring_gen`](tb_event_ring_gen.sv) — `event_ring_gen`

| Caso |
|---|
| MAGIC del generador en 0x120 |
| MAGIC del ring sigue en 0x50 |
| N_SLOTS |
| A periodico 200 |
| A: sin descartes |
| B aleatorio p 0.02 |
| B: la captura pierde por DROP_BUSY |
| C PS lento |
| C: el ring se lleno (DROP_FULL) |
| ninguna escritura fuera del ring |
<!-- /AUTO:casos -->

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

# 3. Generación interna

El ring no ve la señal: ve disparos y ventanas. Por eso es la etapa que lo caracteriza.
Con el Rigol, el apilamiento del estímulo tapa la pérdida del ring
([`generador.md` §1](../../../docs/event_ring/generador.md#1-por-qué)).

## Sin generador: el disparo por software

`make verificar-placa-ring`. Un disparo por escritura a `TRIG_SW`, contado sin ambigüedad.

| Prueba | Qué mide | Resultado |
|---|---|---|
| [`hw_ring_plumbing.py`](../../../software/API/tests/placa/hw_ring_plumbing.py) | device tree, registros del slot 2, ancho de banda de la DDR contra la BRAM, una captura | pasa (2026-11-09) |
| [`hw_ring_swtrig.py`](../../../software/API/tests/placa/hw_ring_swtrig.py) | `EV_CNT + DROP_BUSY + DROP_FULL` = disparos inyectados, registro por registro | pasa (2026-11-09) |
| [`test_ring_source_placa.py`](../../../software/API/tests/placa/test_ring_source_placa.py) | el lector de C (`RingSource`) por lote: sin pérdida, la onda calibrada, la ráfaga contra 64 slots | 14 de 14 (2026-11-09) |

## Con `gen_eventos`: el estímulo conocido

Cada slot trae, en lugar del dato, un patrón que dice qué disparo es. Detalle en
[`generador.md` §6](../../../docs/event_ring/generador.md#6-cómo-se-va-a-usar-en-la-placa).

| Prueba | Resultado |
|---|---|
| `make verificar-placa-generadores`, partes C y D: un caso periódico sin pérdidas, uno aleatorio a 3 MHz, y los modos de medida del lector | la cuenta cierra, cada marca y cada snapshot son los del modelo, cada muestra es el patrón; 114 de 114 (2026-11-12) |
| la campaña de etapas ([`run_etapas_ring.py`](../../../software/campanas/run_etapas_ring.py)), A y B: 168 puntos en seis ventanas (2026-11-12) | **el techo del writer es el de la simulación** en las seis ventanas (con `writer` ciclos entre disparos no pierde; con `writer − 2`, `DROP_FULL`); `DROP_BUSY` es el del tiempo muerto `2·S + 3`; B sin errores |
| la campaña de etapas, C: la sesión entera a la SD y a `/dev/shm` | todos los archivos son el patrón y cierran con `EV_CNT`; el límite es el software de la sesión, no el disco |

**Falta:** el criterio de cero descartes en 10⁸ eventos, también con el ARM ocupado, y C
por la red.

# 4. Generación externa controlada

El estímulo es el Rigol DG4162 en IN1, con arribos de Poisson. Qué condiciona el
instrumento está en
[`resultados_validacion_hw.md` §20](../../../docs/resultados_validacion_hw.md#20-el-generador-externo-qué-condicionó-el-dg4162--2026-11-11).

| Campaña | Dónde | Resultado |
|---|---|---|
| `run_poisson_loss.py --fuente ring`, de 396 Hz a 100 kHz (2026-11-09) | [`diseno_y_register_map.md`](../../../docs/event_ring/diseno_y_register_map.md), [`arquitectura_adquisicion_software.md`](../../../docs/API/arquitectura_adquisicion_software.md) | la pérdida es la del apilamiento del estímulo, sin descartes del ring hasta 50 kHz |

Esta campaña fue la que encontró el `rdata` sin registrar del bus del top: el lector de C
se cortaba por un `WR_SLOT` roto. Está en el plan de
[`comun`](../../comun/sim/VERIFICACION.md#3-generación-interna).

# 5. Medición con setup experimental

Sin hacer. El ring no ve la física: con un detector importan la tasa y el largo de la
ventana, que la etapa 3 ya barre.

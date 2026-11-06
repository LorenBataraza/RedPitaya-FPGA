# Plan de verificación — event_ring

DUT principal: `event_ring_top`

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

**152 casos con nombre** en 5 testbenches. Cada fila es un `check()` que corre y tiene que dar PASS; el testbench entero falla si alguno no da.

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

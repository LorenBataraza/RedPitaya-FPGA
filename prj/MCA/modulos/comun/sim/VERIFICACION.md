# Plan de verificación — comun

DUT principal: `integration_cfg`

Sigue las cinco etapas de
[`docs/etapas_de_validacion.md`](../../../docs/etapas_de_validacion.md). La etapa 2,
la verificación, va completa. De las otras cuatro dice qué corre, dónde está y qué dio.

| Etapa | Qué hay para comun | Estado |
|---|---|---|
| [1. Simulación](#1-simulación) | — | no hay modelo propio |
| [2. Verificación](#2-verificación) | los testbenches de `sim/` | en verde |
| [3. Generación interna](#3-generación-interna) | la región de TOP, el reparto del slot 2 y el bus del top | pasan |
| [4. Generación externa controlada](#4-generación-externa-controlada) | — | no aplica |
| [5. Medición con setup experimental](#5-medición-con-setup-experimental) | — | no aplica |

# 1. Simulación

No hay modelo propio: `integration_cfg`, `sys_bus_split` y `dsp_tap_mux` son registros
y ruteo.

# 2. Verificación

## Cómo se corre

```
make -C modulos/comun/work          # todos los testbenches
make -C modulos/comun/work <tb>     # uno solo
make -C modulos/comun/work cov      # + cobertura, reporte en work/cov/html/
make -C modulos/comun/work wave TB=<tb>   # ondas ya grabadas del último batch
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

**36 casos con nombre** en 1 testbench. Cada fila es un `check()` que corre y tiene que dar PASS; el testbench entero falla si alguno no da.

### [`tb_integration_cfg`](tb_integration_cfg.sv) — `integration_cfg`

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | EL RESET ES EL COMPORTAMIENTO PRE-REFACTOR | ROUTE_OSC  tap = NATIVO en reset |
|  |  | ROUTE_MTRG tap = NATIVO en reset |
|  |  | ROUTE_MCA  tap = NATIVO en reset |
|  |  | ROUTE_RING tap = NATIVO en reset |
|  |  | ROUTE_OSC  enable en reset |
|  |  | ROUTE_MTRG enable en reset |
|  |  | ROUTE_MCA  enable en reset |
|  |  | ROUTE_RING enable en reset |
|  |  | run global apagado en reset |
| 2 | IDENTIFICACIÓN Y DESCRIPCIÓN | MAGIC |
|  |  | VERSION |
|  |  | GITH_0 |
|  |  | GITH_4 |
|  |  | MODULES |
|  |  | SLOTS |
|  |  | CAPS0 |
|  |  | CAPS1 |
| 3 | RUTEO: escritura, readback y efecto en los puertos | ROUTE_MCA tap = DEC_IN |
|  |  | ROUTE_MCA enable sigue en 1 |
|  |  | ROUTE_MCA readback |
|  |  | ROUTE_OSC tap = ADC |
|  |  | ROUTE_OSC enable en 0 |
|  |  | ROUTE_OSC readback |
|  |  | ROUTE_MTRG tap = BRAM_IN |
|  |  | ROUTE_RING intacto tras escribir los otros |
| 4 | CONTROL GLOBAL: run es nivel, clear/srst son de UN ciclo | run global en 1 |
|  |  | CTRL readback |
|  |  | clear no se activo |
|  |  | clear duro exactamente 1 ciclo |
|  |  | run sigue en 1 tras el clear |
|  |  | srst duro exactamente 1 ciclo |
|  |  | run bajo a 0 |
| 5 | BARRIDO DE ACK: toda dirección del slot tiene que responder | no mapeada devuelve 0 |
|  |  | tope del slot devuelve 0 |
|  |  | sin timeouts de ack |
|  |  | sin err en ningun acceso |
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

Sin señal: son registros, ruteo y el bus.

| Prueba | Qué mide | Resultado |
|---|---|---|
| [`test_integration_hw.py`](../../../software/API/tests/placa/test_integration_hw.py) (`make verificar-placa-integration`) | la región de TOP (slot 6): C contra Python, y cada consumidor por todos los taps | 27 PASS (2026-11-09) |
| `make verificar-placa-generadores`, parte A | el reparto del slot 2 por `sys_bus_split`: el generador en `0x4021_0000` con el ring en `0x4020_0000`, el bit 6 de `MODULES` y `SLOTS[23:20]` | pasa (2026-11-09 y 2026-11-12) |
| [`test_bus_lectura_viva.py`](../../../software/API/tests/placa/test_bus_lectura_viva.py) (`make verificar-placa-bus`) | que un registro que cambia mientras se lo lee llegue entero. Es el `rdata` del CDC del top (`rtl/sys_bus_cdc.sv`, verificado en `sim/tb_sys_bus_proto.sv`), no de este módulo | antes del arreglo, ~1 de cada 1000 lecturas de `wp_cur` rotas. Con los bitstreams del 2026-11-09: 0 en el del ring, y en el del MCA (6156e5a3) 1 aislada en 14 millones, que no es una mezcla ([`bus_sistema_redpitaya.md`](../../../docs/TOP/bus_sistema_redpitaya.md)) |
| [`test_rw_dev_mem.py`](../../../software/API/tests/placa/test_rw_dev_mem.py) (`make verificar-placa-mem`) | regresión: una escritura angosta por `/dev/mem` tira SIGBUS, una de 32 bits alineada no | pasa (2026-11-09) |

# 4. Generación externa controlada

No aplica: el módulo no procesa la señal. El ruteo de taps lo ejercitan las campañas del
MCA y del multitrigger.

# 5. Medición con setup experimental

No aplica.

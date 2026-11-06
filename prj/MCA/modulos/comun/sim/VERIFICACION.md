# Plan de verificación — comun

DUT principal: `integration_cfg`

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

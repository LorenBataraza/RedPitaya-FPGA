# Plan de verificación — osc

DUT principal: `osc_cfg`

## Cómo se corre

```
make -C modulos/osc/work          # todos los testbenches
make -C modulos/osc/work <tb>     # uno solo
make -C modulos/osc/work cov      # + cobertura, reporte en work/cov/html/
make -C modulos/osc/work wave TB=<tb>   # ondas ya grabadas del último batch
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

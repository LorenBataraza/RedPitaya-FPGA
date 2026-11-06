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

<!-- AUTO:casos -->
<!-- Esta tabla la escribe `modulos/mk/datasheet.py` leyendo los
     testbenches: las escenas numeradas (`// N) ...`) y el nombre de
     cada check(). No editarla a mano. Lo de abajo (casos borde,
     assertions, metas) SI es a mano y no se toca. -->

**10 casos con nombre** en 1 testbench. Cada fila es un `check()` que corre y tiene que dar PASS; el testbench entero falla si alguno no da.

### [`tb_osc_filter`](tb_osc_filter.sv) — `osc_filter`

Compara contra el RTL de referencia `osc_filter_ref.v` instanciado al lado del DUT: no son valores esperados escritos a mano sino una **equivalencia** ciclo a ciclo sobre todo el estímulo.

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | Coeficientes de RESET: aa=0, bb=0, kk=0xFFFFFF, pp=0 | coeficientes de reset (aa=0,bb=0,kk=0xFFFFFF,pp=0) |
| 2 | Compensación polo-cero tipica (aa != 0: activa el lazo recursivo, | compensacion tipica (aa=25000, bb=1e6, pp=50000) |
| 3 | aa grande positivo y negativo: el termino 2^25-aa se aleja del centro | aa maximo positivo (131071) |
|  |  | aa maximo negativo (-131072) |
| 4 | pp extremos: ejercita la reagrupacion del IIR2 | pp maximo (ejercita el IIR2 reagrupado) |
|  |  | pp maximo negativo |
| 5 | kk extremos: saturacion en la etapa de escalado | kk maximo (fuerza saturacion) |
|  |  | kk = 0 (salida nula) |
| 6 | Todo al maximo a la vez: peor caso de desborde en los intermedios | todos los coeficientes al maximo |
| 7 | Barrido aleatorio de coeficientes | barrido de 12 juegos de coeficientes aleatorios |
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

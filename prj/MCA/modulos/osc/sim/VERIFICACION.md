# Plan de verificación — osc

DUT principal: `osc_cfg`

Sigue las cinco etapas de
[`docs/etapas_de_validacion.md`](../../../docs/etapas_de_validacion.md). La etapa 2,
la verificación, va completa. De las otras cuatro dice qué corre, dónde está y qué dio.

| Etapa | Qué hay para el osciloscopio | Estado |
|---|---|---|
| [1. Simulación](#1-simulación) | — | no hay modelo propio |
| [2. Verificación](#2-verificación) | los testbenches de `sim/` | en verde |
| [3. Generación interna](#3-generación-interna) | registros y BRAM con el disparo por software | C = Python, palabra por palabra |
| [4. Generación externa controlada](#4-generación-externa-controlada) | el orden armar/disparar; el lector con el tren del Rigol | techo del lector de Python de ~3.7 kev/s |
| [5. Medición con setup experimental](#5-medición-con-setup-experimental) | — | sin hacer |

# 1. Simulación

No hay un modelo propio del osciloscopio. El tiempo muerto del lector que lo lee se
modela en [`tiempo_muerto.md`](../../../docs/mca/tiempo_muerto.md) (K = 1, periódico
contra Poisson).

# 2. Verificación

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

# 3. Generación interna

Sin generador: la captura es por software.

| Prueba | Qué mide | Resultado |
|---|---|---|
| [`test_osciloscope_hw.py`](../../../software/API/tests/placa/test_osciloscope_hw.py) (`make verificar-placa-osciloscope`) | C contra Python en los registros del slot 1, y un buffer congelado por software leído de la BRAM palabra por palabra | 53 PASS (2026-11-09) |
| [`test_capture_window_np.py`](../../../software/API/tests/placa/test_capture_window_np.py) (`make verificar-placa-buffer`) | el mismo buffer congelado, leído por `rp` y por libmca, con la calibración | 11 de 11 (2026-11-09) |

# 4. Generación externa controlada

El estímulo es el Rigol DG4162 en IN1. Qué condiciona el instrumento está en
[`resultados_validacion_hw.md` §20](../../../docs/resultados_validacion_hw.md#20-el-generador-externo-qué-condicionó-el-dg4162--2026-11-11).

| Campaña | Dónde | Resultado |
|---|---|---|
| el disparo por flanco del ADC, con la señal viva a 100 kHz | [`orden_arm_trigger_captura.md`](../../../docs/osc/orden_arm_trigger_captura.md) | con la OR-mask habilitada antes de armar, el buffer no se congelaba nunca: hay que armar la `bram_sm` primero |
| el lector de Python (`BramSource`) con el tren periódico | [`arquitectura_adquisicion_software.md`](../../../docs/API/arquitectura_adquisicion_software.md) | techo de ~3.7 kev/s; el ajuste da τ = 250 ± 2 µs, igual que la atribución por fases. El 99 % de eficiencia a 2 kHz es del estímulo periódico |
| el mismo lector con arribos de Poisson (`run_poisson_loss.py`) | ídem | las pérdidas por ρ contra `ρ/(1+ρ)`, y lo que cuesta escribir `.npz` o LH5 mientras se lee (2026-11-07 y 2026-11-08) |
| el lector con datos reales hasta el disco (`make verificar-placa-e2e`) | [`test_mca_e2e.py`](../../../software/API/tests/placa/test_mca_e2e.py) | deja las capturas en `software/datos/e2e_*` |

# 5. Medición con setup experimental

Sin hacer.

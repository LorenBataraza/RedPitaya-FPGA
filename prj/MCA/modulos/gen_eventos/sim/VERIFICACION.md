# Plan de verificación — gen_eventos

DUTs: `gen_eventos` (el generador del ring), `gen_pulsos` (el de pulsos, en el lugar
del ASG) y `gen_disparos` (el motor de disparos de los dos).

Sigue las cinco etapas de
[`docs/etapas_de_validacion.md`](../../../docs/etapas_de_validacion.md). La etapa 2,
la verificación, va completa. De las otras cuatro dice qué corre, dónde está y qué dio.
Estos generadores **son** la etapa 3 de los demás módulos.

| Etapa | Qué hay para los generadores | Estado |
|---|---|---|
| [1. Simulación](#1-simulación) | los modelos de Python de los dos generadores | bit-exactos contra el RTL |
| [2. Verificación](#2-verificación) | los testbenches de `sim/`, las SVA y las mutaciones | en verde |
| [3. Generación interna](#3-generación-interna) | los dos generadores en la placa | placa = simulación |
| [4. Generación externa controlada](#4-generación-externa-controlada) | — | no aplica |
| [5. Medición con setup experimental](#5-medición-con-setup-experimental) | — | no aplica |

# 1. Simulación

| Qué | Dónde | Para qué |
|---|---|---|
| `gen_pulsos`: los registros, ciclo a ciclo, y cada muestra | [`gen_pulsos_model.py`](../modelos/python_model/gen_pulsos_model.py) | predice la traza que mide el MCA. Es la referencia de `tb_gen_pulsos` y de la réplica del MCA2 en `test_pulsos_mca.py` |
| `gen_eventos`: en qué ts del ring sale cada disparo y qué dato lleva cada muestra | [`gen_eventos_model.py`](../modelos/python_model/gen_eventos_model.py) | lo que el software espera en cada slot; escribe los vectores de `tb_gen_eventos` |

# 2. Verificación

## Cómo se corre

```
make -C modulos/gen_eventos/work          # todos los testbenches
make -C modulos/gen_eventos/work <tb>     # uno solo
make -C modulos/gen_eventos/work cov      # + cobertura, reporte en work/cov/html/
make -C modulos/gen_eventos/work wave TB=<tb>   # ondas ya grabadas del último batch
```

Las ondas se graban **siempre** en batch (`work/waves/<tb>.wlf`). No se
condiciona el volcado a que haya un error: cuando el chequeo falla, el tiempo
que hay que mirar ya pasó.

## Casos cubiertos

<!-- Esta sección la escribe `make -C modulos/<m>/work datasheet` leyendo los
     testbenches: las escenas numeradas (`// N) ...`) y el nombre de cada
     check(). No hace falta transcribir nada a mano; alcanza con nombrar bien
     los check() en el TB. -->

## Casos borde conocidos

Lo que hay que probar y todavía no se prueba. Cada línea es deuda de
verificación, no una idea suelta.

| Caso borde | Por qué importa | Cubierto |
|------------|-----------------|----------|
| El ring sale de RUNNING con un disparo decidido en vuelo | Si `GEN_CNT` lo contara, `EV + DROP != GEN_CNT` | sí (`tb_gen_eventos` §9) |
| `PERIODO` y `DT_MIN` menores que 2 | La captura toma el flanco: dos pulsos seguidos serían uno | sí (§5; SVA `ap_sin_pulsos_seguidos`) |
| La secuencia aleatoria contra el modelo de Python | El software predice los `ts` con el modelo | sí (§7, ciclo a ciclo) |
| El ring entero, con descartes de los dos tipos | La cuenta cerrada y el patrón en la DDR | sí (`event_ring/sim/tb_event_ring_gen.sv`) |
| Cambiar `PERIODO` o `UMBRAL` con el generador andando | Entra un ciclo más tarde (`per_m1`); no se prueba | no |
| `dv_i` con huecos (decimación) | El patrón sigue a `ts_cnt`, que cuenta `dv`; en el ring de la placa `dv` es continuo | no |
| `N` mayor que 2¹⁶ | El snapshot lleva k[15:0]: se repite, el lector tiene que desenrollarlo | no |
| `gen_pulsos` contra su modelo, muestra por muestra | El software predice la traza que mide el MCA | sí (`tb_gen_pulsos`, 5 vectores) |
| Apilamiento que satura la salida, arriba y abajo | La saturación a 14 bits | sí (vectores `poisson_apilado`, `negativos_n`) |
| El desborde de `y1` | Sin caída, `y1` pasa sus 25 bits: `ESTADO[2]` | sí (vector `desborde`) |
| La tabla entera en orden y la vuelta de `AMP_N = 0` | 1024 entradas | sí (vector `rafaga_tabla`) |
| `gen_pulsos` manejando el multitrigger y el MCA | La traza del modelo es la que mide el MCA, evento por evento | sí (`sim/tb_pulsos_mca.sv` + `test_pulsos_mca.py`) |
| Cambiar `DECAE` o la tabla con el generador andando | Entra en el ciclo siguiente; el modelo no lo simula | no |
| `SEMILLA = K_AMP` o `K_RUIDO` | Las semillas derivadas son impares: nunca 0; no se prueba el caso | no |

## Assertions

En `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

| Propiedad | Qué garantiza |
|-----------|---------------|
| `ap_sin_pulsos_seguidos` | nunca dos disparos generados en ciclos seguidos |
| `ap_pulso_con_ring` | un disparo generado sólo sale con el ring en RUNNING |
| `ap_snap_marcado` | con el generador prendido el snapshot lleva el bit 16 |
| `ap_hecho_calla` | llegado a `N` no se decide ningún disparo |
| `ap_espera` | en el modo aleatorio no dispara durante `DT_MIN` |

Las de `gen_pulsos` (`sva/gen_pulsos_sva.sv`):

| Propiedad | Qué garantiza |
|-----------|---------------|
| `ap_sin_pulsos_seguidos` | nunca dos pulsos en ciclos seguidos (el multitrigger toma el flanco) |
| `ap_pulso_prendido` | apagado no sale ningún pulso |
| `ap_apagado_mudo` | apagado, la salida queda en cero en el ciclo siguiente |
| `ap_hecho_calla` | llegado a `N` no se decide ningún pulso |
| `ap_desborde_pegajoso` | `ESTADO[2]` sólo se borra con un arranque |

Mutaciones probadas a mano (2026-11-09), todas detectadas:

- **`gen_disparos`** (por `tb_gen_eventos`; repetidas después de sacar el motor a ese
  archivo): `hold` corrido en uno, otro corrimiento del xorshift, el pulso sin el gateo
  de `run`, `GEN_CNT` contando el pulso decidido en vez del que sale. `tb_gen_pulsos`
  detecta las dos primeras; las otras dos son equivalentes ahí, porque `run` vale 1.
- **`gen_pulsos`** (por `tb_gen_pulsos`): sin el redondeo hacia cero en la caída, el ruido
  corrido en uno, otros bits para el índice al azar, sin saturar abajo, el ruido sin su
  registro, `AMP_N` corrido en uno, el impulso sin su registro, la subida corrida en uno.

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

Todo en el bitstream del ring con los generadores (78e26188), sin el Rigol.
`make verificar-placa-generadores`
([`test_generadores_placa.py`](../../../software/API/tests/placa/test_generadores_placa.py)):

| Parte | Qué mide | Resultado |
|---|---|---|
| A | `gen_pulsos` por la API: el MAGIC, configurar y releer, la tabla, el lazo digital, la región de TOP | pasa |
| B | los 4 bloques de `tb_pulsos_mca` por el lazo digital, contra la réplica (`pulsos_placa_ref.json`): `GEN_CNT`, los 11 contadores, `t_ocup` y los espectros canal por canal | **igual a la simulación** |
| C | `gen_eventos` en el ring con el patrón: periódico sin pérdidas, y aleatorio más rápido que la captura | la cuenta cierra; cada marca, cada snapshot y cada muestra son los del modelo |
| D | los modos de medida del lector del ring | la cuenta cierra con lo consumido, sin errores |

114 de 114 con libmca 0.10.0 (2026-11-12); A a C ya habían pasado con 0.9.0 el
2026-11-09. Lo que estas pruebas validan de cada módulo está en los planes de
[`mca`](../../mca/sim/VERIFICACION.md#3-generación-interna),
[`mt`](../../mt/sim/VERIFICACION.md#3-generación-interna) y
[`event_ring`](../../event_ring/sim/VERIFICACION.md#3-generación-interna).

**Falta:**

- que el bitstream del MCA (6156e5a3) traiga `gen_pulsos`;
- el modo analógico (OUT1 → cable → IN1): no hay medición en placa documentada.

# 4. Generación externa controlada

No aplica: estos generadores reemplazan al externo.

# 5. Medición con setup experimental

No aplica.

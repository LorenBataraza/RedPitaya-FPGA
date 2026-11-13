# Etapas de experimentos y validación

Las pruebas del proyecto se ordenan en cinco etapas. Cada una aísla una dependencia más
de la cadena de adquisición, así que una diferencia entre dos etapas seguidas apunta a lo
que la segunda agregó.

| Etapa | Qué es | Qué agrega a la anterior | En este proyecto |
|---|---|---|---|
| **1. Simulación** (Monte Carlo) | completamente computacional; no tiene por qué contener detalles de la implementación del HW | — | [`software/monte-carlo/`](../software/monte-carlo/) y los modelos de `modulos/<m>/modelos/` |
| **2. Verificación** | simulación de la respuesta del HW: los estímulos se asignan directo a las entradas del módulo y no son sintetizables | el RTL | los testbenches `tb_*.sv` de `modulos/<m>/sim/`, con sus SVA |
| **3. Generación interna** | todo en HW: el mismo HW genera la señal y mide la salida, a partir de un comando de generación | el silicio, el bus real y sus cruces de reloj | `gen_pulsos` por el lazo digital, `gen_eventos` en el ring, el disparo por software, y las pruebas de registros que no necesitan señal |
| **4. Generación externa controlada** | los comandos de generación van a un instrumento externo, cuya salida entra al HW por una interfaz rápida | el ADC, la entrada analógica y el instrumento | el Rigol DG4162, CH1 → IN1, comandado por USB desde la placa |
| **5. Medición con setup experimental** | un detector con física real | la física y el detector | todavía no |

Para el diseño del HW lo que importa llega hasta la generación externa controlada. El
setup experimental agrega lo que es propio del detector.

**Lo que una etapa no deja medir se pasa a la etapa que lo aísla.** Por ejemplo, con el
DG4162 se sabe cuántos pulsos llegaron, pero no cuál se perdió: eso lo da la generación
interna, que conoce cada evento. Qué del DG4162 condiciona cada número, y qué etapa
cubre lo que el DG4162 no deja medir, está en
[`resultados_validacion_hw.md` §20](resultados_validacion_hw.md#20-el-generador-externo-qué-condicionó-el-dg4162--2026-11-11).

## Cómo se reconoce cada etapa en el repo

| Etapa | Dónde corre | Cómo se lanza |
|---|---|---|
| 1 | la PC | `python3 software/monte-carlo/<script>.py`; los tests van en `make -C software verificar` |
| 2 | la PC, con Questa | `make -C modulos/<m>/work` |
| 3 | la placa, sin generador | los objetivos de `software/Makefile` marcados **(P)**: `verificar-placa-*` y `campana-etapas-ring` |
| 4 | la placa, con el Rigol en IN1 | los objetivos marcados **(P,R)**: `verificar-placa-datapath`, `-e2e`, `-app`, las `campana-*` y los `rigol-*` |
| 5 | — | — |

## Las etapas de cada módulo

Cada plan de verificación (`modulos/<m>/sim/VERIFICACION.md`) sigue este orden: la
etapa 2 en detalle y, en las otras cuatro, qué corre, dónde está y qué dio.

| Módulo | 1. Simulación | 2. Verificación | 3. Generación interna | 4. Generación externa controlada | 5. Setup experimental |
|---|---|---|---|---|---|
| [`mca`](../modulos/mca/sim/VERIFICACION.md) | réplica del MCA2; Monte Carlo de apilamiento, forma, base y ruido | TB, SVA de `mca_top`, mutaciones del trapecio y el banco | registros; `gen_pulsos` por el lazo digital igual a la simulación | dos campañas del MCA1, la batería del MCA2, el banco a 1 Mcps | — |
| [`mt`](../modulos/mt/sim/VERIFICACION.md) | modelo del disparo por pendiente; el disparo de la réplica del MCA2 | TB; el disparo con polo-cero contra modelos | registros; los tres disparos con `gen_pulsos` | tiempo muerto y par-pulso; el polo-cero con la subida del Rigol | — |
| [`event_ring`](../modulos/event_ring/sim/VERIFICACION.md) | `predecir`: marcas y descartes del motor | TB | disparo por software; la campaña de etapas con `gen_eventos` | pérdidas con arribos Poisson | — |
| [`osc`](../modulos/osc/sim/VERIFICACION.md) | — | TB | registros y BRAM con disparo por software | el orden armar/disparar/capturar; el lector con señal real | — |
| [`comun`](../modulos/comun/sim/VERIFICACION.md) | — | TB | la región de TOP y el bus | no aplica | no aplica |
| [`gen_eventos`](../modulos/gen_eventos/sim/VERIFICACION.md) | los modelos de los dos generadores | TB, SVA y mutaciones | es la etapa: los dos generadores en la placa | no aplica | no aplica |

# Plan de verificación — multitrigger

DUT principal: `mt_cfg`

Sigue las cinco etapas de
[`docs/etapas_de_validacion.md`](../../../docs/etapas_de_validacion.md). La etapa 2,
la verificación, va completa. De las otras cuatro dice qué corre, dónde está y qué dio.

| Etapa | Qué hay para el multitrigger | Estado |
|---|---|---|
| [1. Simulación](#1-simulación) | el modelo del disparo por pendiente; los dos disparos en la réplica del MCA2 | hechos |
| [2. Verificación](#2-verificación) | los testbenches de `sim/` y el disparo con polo-cero contra modelos | en verde |
| [3. Generación interna](#3-generación-interna) | registros sin señal; los tres disparos con `gen_pulsos` | placa = simulación |
| [4. Generación externa controlada](#4-generación-externa-controlada) | tiempo muerto y par-pulso con el Rigol; el disparo con polo-cero con la subida del Rigol | separa pares desde 9–10 muestras, no 7–8 |
| [5. Medición con setup experimental](#5-medición-con-setup-experimental) | un detector | sin hacer |

# 1. Simulación

| Qué | Dónde | Para qué |
|---|---|---|
| el disparo por pendiente y el Schmitt de nivel | [`mt_slope_model.py`](../modelos/python_model/mt_slope_model.py) | la misma recursión que el hardware, en enteros, sin el pipeline de 5 ciclos; hace las figuras de [`procesamiento_pendiente.md`](../../../docs/mt/procesamiento_pendiente.md) |
| el disparo por pendiente y el de polo-cero, abriendo las ranuras del MCA | [`replica_mca2.py`](../../../software/monte-carlo/replica_mca2.py) | el Monte Carlo del MCA2: pérdidas y separación de pares según el disparo |

# 2. Verificación

## Cómo se corre

```
make -C modulos/mt/work          # todos los testbenches
make -C modulos/mt/work <tb>     # uno solo
make -C modulos/mt/work cov      # + cobertura, reporte en work/cov/html/
make -C modulos/mt/work wave TB=<tb>   # ondas ya grabadas del último batch
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

**193 casos con nombre** en 7 testbenches. Cada fila es un `check()` que corre y tiene que dar PASS; el testbench entero falla si alguno no da.

### [`tb_mt_cfg`](tb_mt_cfg.sv) — `mt_cfg`

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | IDENTIFICACIÓN | MAGIC |
|  |  | CAPS (HAS_PZ en 17, HAS_SLOPE en 16) |
| 2 | SHIELD: 0x210 del mapa viejo -> 0x010, mismo layout de bits | shield_src |
|  |  | shield_dst |
|  |  | shield_dur |
|  |  | SHIELD_CFG readback |
|  |  | SHIELD_STAT |
|  |  | SHIELD_STAT con trig_arm |
| 3 | SNAPSHOT y FLAGS (eran 0x218 y 0x21C) | SNAPSHOT (29 b) |
|  |  | DIS_FLAGS |
|  |  | TRG_STATE |
| 4 | MÁSCARAS OR: 0x240+4c del mapa viejo -> 0x040+4c | new_trg_src ch0 pulso |
|  |  | new_trg_src ch1 quieto |
|  |  | OR_MASK ch0 readback |
|  |  | OR_MASK ch1 readback |
|  |  | OR_MASK ch2 readback (N_CH=2) |
|  |  | OR_MASK ch3 readback (N_CH=2) |
|  |  | new_trg_src con wdata=0 igual pulsa |
|  |  | OR_MASK ch0 limpiada |
| 5 | SW-TRIGGER: registro propio (bit por canal) + PUENTE LEGACY | TRIG_SW ch0 por registro propio |
|  |  | TRIG_SW ch1 quieto |
|  |  | TRIG_SW ch1 por registro propio |
|  |  | TRIG_SW ch0 por puente legacy |
|  |  | TRIG_DIS_CLR ch0 por registro propio |
|  |  | TRIG_DIS_CLR ch1 por puente legacy |
| 6 | FAN-OUT POR indep_mode: sin modo independiente, ch1 sigue a ch0 | indep_mode=0: ch1 sigue a ch0 |
|  |  | indep_mode=1: ch1 NO sigue a ch0 |
| 7 | DISPARO POR PENDIENTE | slope_en ch0 |
|  |  | slope_len ch0 |
|  |  | slope_gap ch0 |
|  |  | ch1 no sigue a ch0 (sin fan-out) |
|  |  | SLOPE_CFG ch0 readback |
|  |  | SLOPE_CFG ch3 solo campos |
|  |  | slope_thr ch1 |
|  |  | SLOPE_THR ch1 readback |
|  |  | slope_hyst ch0 |
|  |  | SLOPE_HYST ch0 readback |
|  |  | SLOPE_HYST ch3 readback |
|  |  | reset: pz_en en 0 |
|  |  | pz_en ch0 |
|  |  | pz_k ch0 |
|  |  | pz_m ch0 |
|  |  | pz_sh ch0 |
|  |  | pz ch1 no sigue a ch0 (sin fan-out) |
|  |  | PZ_CFG ch0 readback |
|  |  | PZ_CFG ch3 solo campos |
|  |  | pz_mq ch1 |
|  |  | PZ_MQ ch1 readback |
|  |  | PZ_MQ ch0 readback |
|  |  | pz_thr ch0 |
|  |  | PZ_THR ch0 readback |
|  |  | PZ_THR ch3 satura |
|  |  | pz_hyst ch0 |
|  |  | PZ_HYST ch0 readback |
|  |  | PZ_HYST ch2 readback |
|  |  | la pendiente no se toca |
| 8 | BARRIDO DE ACK | no mapeada devuelve 0 |
|  |  | tope del slot devuelve 0 |
|  |  | sin timeouts de ack |
|  |  | sin err en ningun acceso |


### [`tb_mt_slope_trig`](tb_mt_slope_trig.sv) — `mt_slope_trig`

| Escena | Qué prueba | Caso |
|---|---|---|
| 2 | Exactitud con huecos de dv y L, G intermedios | modelo == RTL con huecos de dv (L=5 G=3) |
| 3 | L=1 G=0 es x[n]-x[n-1]; L=0 se satura a 1; L>LMAX a LMAX | L=0 -> L=1, G=0: diferencia de 1 muestra |
|  |  | L=31 satura a LMAX=16 |
| 4 | Escalón sobre una base: un pulso p, un pulso n, pico L·A | arranque sobre base 1000: sin pulsos |
|  |  | escalon de subida: exactamente 1 pulso p |
|  |  | escalon de bajada: exactamente 1 pulso n |
|  |  | modelo == RTL en el escalon |
|  |  | tras los dos escalones los dos Schmitt re-armaron |
| 5 | Continua grande y rampa lenta: no disparan | continua 6000 desde el arranque: sin pulsos |
|  |  | rampa lenta (s=176 < thr=800): sin pulsos |
| 6 | Escalones ruidosos: la histéresis evita re-disparos | modelo == RTL con ruido |
| 7 | Cambio de L en caliente: re-arranca sin pulsos y vuelve a disparar | cambio de L/G en caliente: sin pulsos |
|  |  | tras el cambio vuelve a disparar |
|  |  | y el escalon de bajada da pulso n |
| 8 | cfg_en = 0: nada | cfg_en=0: sin pulsos |
|  |  | cfg_en=0: s queda en 0 |
|  |  | cfg_en=0: desarmado (no puede disparar) |


### [`tb_mt_pz_trig`](tb_mt_pz_trig.sv) — `mt_pz_trig`

| Escena | Qué prueba | Caso |
|---|---|---|
| 5 | Pares | en = 0: ningun disparo |
|  |  | en = 0: desarmado |


### [`tb_mt_trig_src`](tb_mt_trig_src.sv) — `mt_trig_src`

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | flanco habilitado dispara adc_trig, engancha dis, single-shot limpia mascara | mascara cargada (trg_state==BIT_ADC_P0) |
|  |  | flanco ADC_P0 dispara adc_trig |
|  |  | adc_trg_dis enganchado tras disparo |
|  |  | single-shot: trg_state auto-limpiada |
| 2 | trig_dis_clr limpia el disable | trig_dis_clr limpia adc_trg_dis |
| 3 | fuente NO habilitada no dispara (mascara solo P1, pulso en P0) | fuente fuera de mascara NO dispara |
| 4 | modo continuo: la mascara persiste tras el disparo | we_keep=1: mascara persiste tras disparo |
| 5 | SW trigger gateado por dly_valp | SW trigger dispara adc_trig |
| 6 | pendiente: slope_p[0] -> bit 17, slope_n[1] -> bit 22 | slope_p[0] dispara con BIT_SLOPE_P0 (bit17) |
|  |  | slope_n[0] NO dispara con BIT_SLOPE_N1 |
|  |  | slope_n[1] dispara con BIT_SLOPE_N1 (bit22) |
|  |  | pendiente fuera de mascara NO dispara |
| 7 | polo-cero: pz_p[ch] -> bit 25 + ch, solo con su bit | polo-cero fuera de mascara NO dispara |
|  |  | bits 29..31 reservados: no disparan |
| 8 | puede_o: la mascara (sin el disable) contra el armado de cada fuente | puede: mascara vacia no puede disparar |
|  |  | puede: con las dos fuentes armadas |
|  |  | puede: con una de las dos desarmada |
|  |  | puede: con las dos desarmadas, no |
|  |  | puede: una fuente armada FUERA de la mascara no cuenta |
|  |  | puede: el disable tras un disparo lo baja |
|  |  | puede: el re-arm (trig_dis_clr) lo vuelve a subir |


### [`tb_mt_event_logic`](tb_mt_event_logic.sv) — `mt_event_logic`

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | flanco ch0 -> evento conjunto + snapshot bit1 (adc_p0) | flanco ch0 dispara trigger_event |
|  |  | snapshot engancha adc_p0 (bit1) |
| 2 | snapshot se resetea con sw_trig_dis_clr | sw_trig_dis_clr resetea el snapshot |
| 3 | flanco en ch1 (adc_trig_p bit1) tambien dispara el evento conjunto | flanco adc ch1 dispara trigger_event (OR conjunto) |
|  |  | snapshot engancha adc_p1 (bit2) |
| 4 | pendiente: slope_p[0] con BIT_SLOPE_P0 -> evento + snapshot bit 17 | slope_p0 dispara trigger_event |
|  |  | snapshot engancha slope_p0 (bit17) y nada mas |
| 5 | slope_n[1] (bit 22) | slope_n1 dispara trigger_event |
|  |  | snapshot engancha slope_n1 (bit22) |
| 6 | polo-cero: pz_p[1] (bit 26) -> evento + snapshot bit 26 | pz_p1 dispara trigger_event |
|  |  | snapshot engancha pz_p1 (bit26) y nada mas |
| 9 | trig_arm: el disparo puede salir. Modo del MCA (multitrigger_armar_mca): | trig_arm: mascaras vacias, no puede disparar |
|  |  | trig_arm: polo-cero de ch0 armado |
|  |  | trig_arm: el polo-cero de ch1 no esta en la mascara, no cuenta |
|  |  | trig_arm: el disparo sale (un evento) |
|  |  | trig_arm: sin Schmitt desarmado, un evento |
|  |  | trig_arm: con SW en la mascara puede aunque el polo-cero no |
|  |  | trig_arm: pendiente n de ch1 armada |
|  |  | trig_arm: pendiente n de ch1 desarmada |


### [`tb_trigger_shield`](tb_trigger_shield.sv) — `trigger_shield`

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | dur=0: re-arm inmediato en dst, sin holdoff | dur=0: pulso de clear en dst tras disparo src |
|  |  | dur=0: active se mantiene en 0 |
| 2 | dur=K: active durante el holdoff y clear en dst al expirar | dur=5: active se activa durante el holdoff |
|  |  | dur=5: clear en dst al expirar el holdoff |
|  |  | dur=5: active vuelve a 0 tras expirar |
| 3 | canal no escudado: transparente al clear de SW | canal no escudado pasa el clear de SW |
|  |  | canal escudado NO pasa el clear de SW (sin holdoff activo) |
| 4 | VETO de nivel: src=ext_lvl, dst=mca, dur=0 -> el veto ES el nivel | veto nivel: sube con la linea |
|  |  | veto nivel: NO usa el holdoff (active=0 con dur=0) |
|  |  | veto nivel: sigue mientras la linea esta alta |
|  |  | veto nivel: cae con la linea |
|  |  | veto nivel: no toca los canales del scope |
| 5 | VETO de nivel con cola: dur=8 -> sigue 8 ciclos despues de bajar | veto con cola: ~8 ciclos tras bajar la linea |
|  |  | veto con cola: termina |
| 6 | VETO de ventana: src=ext_p (flanco), dur=12 -> 12 ciclos y listo | veto ventana: ~12 ciclos tras el flanco |
|  |  | veto ventana: termina |
| 7 | sin dst=mca no hay veto, aunque el escudo corra | sin dst=mca: el escudo corre |
|  |  | sin dst=mca: pero no hay veto |
| 8 | los canales del scope como fuente tambien vetan (dst=mca, src=ch0) | src=ch0, dst=mca: veto de ~6 ciclos |


### [`tb_mt_top`](tb_mt_top.sv) — `mt_top`

| Escena | Qué prueba | Caso |
|---|---|---|
| 1 | IDENTIFICACIÓN | MAGIC |
|  |  | CAPS.N_CH es el del top |
|  |  | CAPS.SRC_W |
|  |  | CAPS.HAS_SLOPE |
|  |  | CAPS.HAS_PZ |
|  |  | reset: ningun evento |
| 2 | NIVEL, single-shot | trg_state: mascara activa en ch0 |
|  |  | trg_state: ch1 sigue a ch0 sin indep_mode |
|  |  | evento por flanco de nivel |
|  |  | trig_ch_o lleva el flanco de ch0 |
|  |  | event_snap_o: adc_p[0] |
|  |  | SNAPSHOT: adc_p[0] |
|  |  | event_snap_o == SNAPSHOT[16:0] |
|  |  | single-shot: mascara auto-limpiada |
|  |  | DIS_FLAGS: disable de ch0 y ch1 |
|  |  | sin mascara no re-dispara |
|  |  | trig_dis_clr_o pulso |
|  |  | TRIG_DIS_CLR limpia los disable |
|  |  | TRIG_DIS_CLR limpia el snapshot |
| 3 | PENDIENTE, configurada por registros | evento por pendiente |
|  |  | SNAPSHOT: slope_p[0] (bit 17) |
|  |  | event_snap_o no tiene los bits de pendiente |
|  |  | polo-cero sin pulso: quieto |
|  |  | trig_arm: polo-cero armado en la mascara |
|  |  | SHIELD_STAT: bit 18 (trig_arm) en 1 |
|  |  | evento por polo-cero en ch1 |
|  |  | trig_arm: tras el disparo unico, no puede disparar |
|  |  | SHIELD_STAT: bit 18 (trig_arm) en 0 |
|  |  | SNAPSHOT: solo pz_p[1] (bit 26) |
|  |  | event_snap_o no tiene los bits de polo-cero |
| 4 | EXTERNA, por el lazo trig_ext_asg | evento por flanco externo |
|  |  | trig_ext_asg_o[0] (ext_p) pulso |
|  |  | event_snap_o: ext_p |
| 5 | VETO por nivel externo | SHIELD_CFG readback |
|  |  | sin linea, sin veto |
|  |  | linea alta: veto |
|  |  | SHIELD_STAT: mca_veto |
|  |  | veto se sostiene con la linea |
|  |  | cola del holdoff (dur=20) |
|  |  | veto termina |
| 6 | SW: puente legacy y registro propio | evento por SW legacy (0x004 del slot 1) |
|  |  | event_snap_o: sw |
|  |  | disclr legacy limpia los disable |
|  |  | evento por TRIG_SW (0x020) |
| 7 | CADENA | evento por la cadena |
| 8 | MODO CONTINUO | continuo: primer evento |
|  |  | continuo: la mascara persiste |
|  |  | continuo: el disable bloquea hasta el clear |
|  |  | continuo: re-dispara tras TRIG_DIS_CLR |
| 9 | EL LAZO CON LA CAPTURA | mascara cargada |
|  |  | adc_dly_do limpia la mascara (single-shot) |
|  |  | adc_rst_do limpia la mascara |
| 10 | RELLENO Y CONTRATO | trg_state_o: canales >= N_CH siempre en 0 |
|  |  | daisy_trig_o == trigger_event_o |
|  |  | sin timeouts de ack |
<!-- /AUTO:casos -->

## Casos borde conocidos

Lo que hay que probar y todavía no se prueba. Cada línea es deuda de
verificación, no una idea suelta.

| Caso borde | Por qué importa | Cubierto |
|------------|-----------------|----------|
| | | no |

## El disparo con polo-cero (2026-11-03)

`mt_pz_trig`: un `mca_trap` corto (k = 2, m = 1) con un Schmitt, en los bits
25..28 de `OR_MASK`. Ver [`disparo_polo_cero.md`](../../../docs/mt/disparo_polo_cero.md).

| Qué | Dónde | Resultado |
|---|---|---|
| el trapecio bit a bit y el Schmitt en cada ciclo | `tb_mt_pz_trig`, contra modelos escritos aparte | 248 903 ciclos, 0 errores, con decimación y con cambios de forma (k = 0 y k + m > 31 incluidos) a mitad de la corrida |
| el arranque | `tb_mt_pz_trig` | sin falsos con −1000, 5, 1000 y 1800 cuentas de continua; el Schmitt evalúa recién a k + l + 12 muestras del re-arranque |
| la detección | `tb_mt_pz_trig` | 564 de 564 pulsos aislados (A = 100..8000, ruido 4.5) con un disparo cada uno; ningún falso. Pares 2000 → 1200 y 8000 → 300: dos disparos desde Δt = 7 |
| los registros, la máscara, el snapshot | `tb_mt_cfg`, `tb_mt_trig_src`, `tb_mt_event_logic`, `tb_mt_top` §3b | `PZ_*` con readback y saturación, `CAPS[17]`; bits 25..28 cada uno con su canal, 29..31 reservados; snapshot de 29 b; el disparo por registro de punta a punta |
| contra el modelo del banco | `tb_banco_disparo.sv` (`docs/mca/figuras/trapecio/`) | los mismos disparos que el Schmitt con el que se validó el banco, en 3600 pulsos y 6320 pares, un ciclo más tarde |

OOC de `mt_top`: WNS +1.46 ns a 125 MHz; 457 LUT, 380 FF y 1 DSP por canal, sin
BRAM.

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

| Prueba | Qué mide | Resultado |
|---|---|---|
| [`test_multitrigger_hw.py`](../../../software/API/tests/placa/test_multitrigger_hw.py) (`make verificar-placa-multitrigger`), sin señal | C contra Python en los registros del slot 3, y armar y desarmar el disparo del MCA con la API (lo único que ve el `we_keep` del RTL) | 28 PASS (2026-11-09, `software/datos/placa_generadores_20261109/`) |
| `gen_pulsos` por el lazo digital, con los 4 bloques de `tb_pulsos_mca` | los disparos por pendiente, por polo-cero y por el ASG, medidos con `F_TRISE` del MCA | por pendiente y polo-cero, lo mismo que la simulación y sin corrimiento. Con el ASG, la réplica coincide a 3 ciclos del pulso y no a 4: el top tiene un registro en `adc_dat` que el TB no tiene (`LAT_ASG`) ([`generador_pulsos.md` §8](../../../docs/gen_eventos/generador_pulsos.md#8-para-usarlo-en-la-placa)) |

# 4. Generación externa controlada

El estímulo es el Rigol DG4162 en IN1. Qué condiciona el instrumento está en
[`resultados_validacion_hw.md` §20](../../../docs/resultados_validacion_hw.md#20-el-generador-externo-qué-condicionó-el-dg4162--2026-11-11).

| Campaña | Dónde | Resultado |
|---|---|---|
| tiempo muerto (`sweep_periods`) y resolución par-pulso (`sweep_pulse_width`), con el tren periódico en modo PULSE | [`testbenches_software_mt.md`](../../../docs/mt/testbenches_software_mt.md) | el par-pulso ve el re-armado del disparo en hardware sin Python en el lazo (se esperan ~25–30 ns); el doc describe el método y sus trampas, no registra el valor medido |
| el disparo con polo-cero con la subida del Rigol (2026-11-05) | [`pruebas_banco_trapecios.md` §6](../../../docs/mca/pruebas_banco_trapecios.md#6-en-la-placa) | separa pares desde 9–10 muestras y no desde 7–8 como en la simulación: la subida no baja de ~1.5 muestras (la simulación usó 1.2). El modelo del disparo sobre las señales capturadas da lo mismo que el hardware |
| el flanco de 1 ns, con sobrepaso | ídem | ~8 % de sobrepaso: 1.65 disparos por pulso desde ~1500 cuentas, y a 1 Mcps los buenos bajan de 665 a 565 k/s. El holdoff del shield (`dur` ≥ 5) lo tapa sin tocar el RTL ([`disparo_polo_cero.md`](../../../docs/mt/disparo_polo_cero.md)) |

# 5. Medición con setup experimental

Sin hacer: todavía no hay detector. Tiene que decidir si el holdoff del shield va por
defecto: hoy no va, porque con una subida limpia cuesta 3 % de buenos a 1 Mcps, y hace
falta sólo si el detector tiene sobrepaso.

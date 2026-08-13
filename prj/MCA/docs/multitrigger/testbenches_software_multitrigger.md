# Testbench de software del scope multitrigger (`testbench_multitrigger.py`)

Qué mide la suite de caracterización del scope, cómo lo mide y —sobre todo— **qué
trampas hay que esquivar para que el número signifique algo**. Casi todo el
documento son cosas que costó descubrir midiendo en la placa.

Código: [`../software/testbench_multitrigger.py`](../../software/testbench_multitrigger.py)
Driver: [`../software/multitrigger_utils.py`](../../software/multitrigger_utils.py)

---

## 1. La división driver / caracterización

`multitrigger_utils.py` es el **driver**: `mmap` de `/dev/mem`, `arm`, captura de
ventanas, decodificación de registros. `testbench_multitrigger.py` son los
**métodos de caracterización**: sondas de hardware, análisis de tiempos con el
reloj del FPGA, y los barridos.

Tres convenciones que hacen que la suite sirva:

- **Ninguna función usa globals del notebook.** `sc` (scope) y `rg` (generador)
  se pasan explícitos, siempre.
- **`matplotlib` y `multitrigger_utils` se importan _dentro_ de las funciones**
  que los necesitan. Por eso el módulo **se importa en la PC**, sin el paquete
  `rp` ni `/dev/mem`, para reanalizar los `.npz` offline. Las constantes
  (`N_BUF`, `FS`, los bits de la máscara) están duplicadas a propósito por la
  misma razón.
- **Las funciones que guardan reciben `save=None`**, un callable
  `save(label, meta=None, **arrays)`. El notebook le pasa su propio
  `save_capture`, típicamente envuelto para que inyecte `scope_regs(sc)` en la
  metadata. La suite no decide dónde se guarda nada.

---

## 2. El concepto central: tres regímenes de tiempo muerto

Es lo que hay que tener en la cabeza antes de mirar cualquier curva. Los tres
están separados por órdenes de magnitud y **cada uno se ve con un instrumento
distinto**:

| Régimen | Escala | Con qué se ve |
|---|---|---|
| re-arm del trigger en hardware | ~24 ns | sólo `sweep_pulse_width` |
| dt entre disparos por Δ`wp_trig` | 8 ns de resolución | `events_to_hw_intervals` |
| lazo de polling en Python | ~2-6 µs | `poll_floor_us` — es el piso de `capture_n_events` |

La ambigüedad central de todo barrido de tiempo muerto es **"¿el FPGA dejó de
disparar, o el software dejó de verlo?"**. Las sondas de la sección 3 existen
para responderla sin adivinar.

---

## 3. Sondas de hardware — sin Python en el lazo

### `trigger_alive(sc, dwell_s)` — ¿el FPGA está disparando?

Mira si `adc_wp_trig` (@0x1C) se mueve durante `dwell_s`. `wp_trig` se
re-latchea en **cada disparo aceptado**, así que verlo cambiar prueba que el
camino de trigger está vivo, sin depender de que el software llegue a ver todos
los disparos. Es el discriminador entre *"el FPGA no dispara"* y *"el FPGA
dispara pero el polling no lo sigue"*.

Devuelve `alive`, `n_cambios`, `rate_min_hz`, `dt_hw_med_us`, `dt_hw_min_us` más
el estado de los registros del diagnóstico. **`n_cambios` y `rate_min_hz` son
cotas inferiores**: el polling tarda 5-10 µs por vuelta y se saltea disparos.
`dt_hw_min_us` es, al revés, una cota **superior** del tiempo muerto real.
Requiere el scope armado.

### `poll_floor_us(sc, n)` — el tiempo muerto del *método*

Mide cuánto tarda una iteración del lazo de polling de Python sobre `/dev/mem`.
Separa dos números que no son lo mismo:

- `read_us`: costo puro de una lectura (n lecturas / n, sin timestamp por
  vuelta) — lo que paga el lazo optimizado.
- `p50/p90/p99`: percentiles del intervalo midiendo con `perf_counter_ns` en
  cada vuelta; es una **cota superior**, porque incluye el costo del propio
  timestamp.

El período de pulsos tiene que ser bastante mayor que esto para que
`capture_n_events` no saltee disparos. Es el primer número que hay que mirar
antes de creerle a una curva de eficiencia.

### `we_time_since_arm_us()` — y qué **no** es

`adc_we_cnt` (@0x02C ch0 / @0x12C ch1) se resetea con
`(adc_rst_do || adc_arm_do) || (trig_dis_clr && adc_we_keep)`
(`rp_bram_sm.v:71`), y el `trig_dis_clr` que llega al `bram_sm` es el del
**registro 0x94 (clear de software)**, no el del `trigger_shield` —el clear del
shield se queda dentro de `multitrigger_event_logic`, porque
`rp_scope_multitrigger_com.sv:597` lo cablea desde el `cfg`, no desde el shield.

Consecuencia, verificada en la placa: **con `auto_rearm` este contador NO marca
el tiempo desde el último disparo**, crece libre desde el arm. Para saber si el
FPGA dispara hay que usar `trigger_alive`.

---

## 4. El reloj del FPGA: `wp_dt_us` y el des-envuelto del wrap

`adc_wp_trig` es el sample exacto en el que disparó el FPGA, así que la
diferencia entre dos lecturas mide el intervalo con **resolución de 1 sample
(8 ns)** en vez de los ±4 µs del reloj de Python. `events_to_hw_intervals()` es
el gemelo de `multitrigger_utils.events_to_intervals()` pero con este reloj.

El puntero es de 14 bits: **envuelve cada 16384 samples = 131.072 µs**, así que
Δ`wp` sólo es no-ambiguo por debajo de eso. Para des-envolver se usa `dt_sw`, el
mismo intervalo medido por software.

**El detalle que hay que respetar** (y que se pagó midiendo): `t_ns` marca
cuándo el software *se enteró* del disparo, no cuándo disparó el FPGA, así que
`dt_sw` trae la latencia del polling y algún hipo del scheduler de +100 µs.
Redondear a medio wrap (65 µs) hace que uno de esos hipos sume un **wrap
fantasma** — medido: `dt_hw` daba 101.3 µs en vez de 100.000 con un tren de
10 kHz, y el exceso era exactamente 131.072 µs concentrado en un solo intervalo.
Por eso el criterio pide **0.75 wrap (98 µs) de evidencia** antes de agregar un
wrap:

```
k  = floor((dt_sw − dwp·Ts)/wrap + 0.25)
dt = dwp·Ts + max(k,0)·wrap
```

Aguanta latencias de software de hasta ~98 µs y sigue resolviendo los intervalos
largos. Si no importa el rango >131 µs, pasar `dt_sw_us=None` y no hay
ambigüedad posible.

`missed_events(dt_hw_us, period_us)` cierra el círculo: los triggers sólo pueden
ocurrir en los pulsos, así que cada `dt_hw` es múltiplo del período del estímulo
y `round(dt_hw/period) − 1` es cuántos disparos **se perdió el software**.

---

## 5. Qué llega realmente a la entrada del ADC

`pulse_metrics(d, thr, hyst)` sobre un buffer crudo: es la evidencia que separa
*"el generador dejó de entregar el pulso"* de *"el pulso llega pero el trigger
no lo toma"*. Si `cruza_umbral` es `False` o `v_max < thr`, el problema está
**antes** del FPGA.

Usa `_hyst_edges()`, cruces con histéresis vectorizados: misma semántica que
`multitrigger_utils.pulses_from_buffer` (que hace un loop de Python y sólo da
las subidas) pero sin el loop —importa, porque corre sobre 16 k samples en la
Pitaya— y devolviendo también las **bajadas**, que son las que dan el ancho.

**Cuidado con `ventana_us`**: el buffer son 131 µs con `decim=1`. Si el período
de pulsos es del orden de la ventana o mayor, que no aparezcan pulsos **no**
significa que el generador esté mudo: significa que la ventana no los cubre.
`cobertura_ok` marca ese caso, y los barridos lo propagan para no acusar al
generador de algo que no hizo.

---

## 6. Estado del generador: preguntar, no suponer

Los setters del driver **no validan nada** (`set_pulse_period` sólo manda
`:FREQuency`), así que si el instrumento recorta el ancho o rechaza el período,
la única forma de enterarse es preguntándole:

- `rigol_state(rg, ch)` — snapshot de lo que el generador tiene puesto **de
  verdad**, no de lo que se le pidió. `err` es la cola SCPI: `0,"No error"`
  significa que aceptó el último comando.
- `rigol_limits(rg, ch)` — los límites que declara **el propio instrumento**, no
  el datasheet.

Los dos barridos consultan `rigol_state` en cada punto y lo guardan en la
metadata del `.npz`.

---

## 7. `sweep_periods()` — el test de tiempo muerto clásico

Barre la distancia entre pulsos. Por cada punto, en este orden:

1. reconfigurar el generador y **verificar el readback**;
2. mirar la señal cruda que llega al ADC (captura forzada por SW trigger,
   independiente del trigger por ADC que se está midiendo);
3. armar y preguntarle al FPGA si dispara (`trigger_alive`);
4. recién ahí contar eventos desde Python.

Además de la eficiencia de software de siempre, cada punto reporta
`hw_dt_med_us` (Δ`wp_trig`, 8 ns de resolución), `n_saltados` (disparos que el
polling no vio) y `hw_alive`. **Eso es lo que permite decir si el tiempo muerto
observado es del FPGA o del software.**

> ### La trampa: el DG4000 conserva el *duty*, no el ancho
>
> Al cambiar la frecuencia, el instrumento reescala el ancho para mantener el
> ciclo de trabajo. Medido: el ancho quedaba clavado en **1 % del período**, y
> por debajo de ~30 ns el pulso ya no cruza el umbral y el trigger deja de
> disparar. Eso era el falso "tiempo muerto": lo que se estaba midiendo era el
> ancho de banda de la entrada.
>
> Por eso `width_s` **importa**. Pasarlo explícito (p. ej. `width_s=200e-9`)
> mantiene el estímulo constante. `None` deja lo que haya, que es el
> comportamiento viejo y sólo sirve si ya se sabe lo que se está haciendo.

Guarda un `.npz` por punto más un resumen del barrido entero
(`save_sweep_summary`, vectores en un solo archivo para graficar offline sin
abrir punto por punto). `plot_deadtime_curve(results)` grafica eficiencia y dt;
**el panel del medio es el que separa las dos causas**: si `dt_hw` sigue la
diagonal y `dt_sw` se despega, el tiempo muerto es del software.

---

## 8. `sweep_pulse_width()` — resolución par-pulso sin Python en el lazo

La parte ingeniosa de la suite, y la única forma de ver el régimen de ~24 ns.

Un pulso de ancho W genera un flanco de subida y uno de bajada separados
**exactamente** por W. Armando con `OR_MASK = BIT_ADC_P0 | BIT_ADC_N0`, el
`trig_snapshot` (@0x218) guarda cuál fue el último evento aceptado:

| snapshot | significa |
|---|---|
| `adc_n0` | se aceptaron los **dos** flancos separados por W |
| `adc_p0` | el de bajada cayó dentro del tiempo muerto |

Barriendo W de µs a decenas de ns, **el W donde el snapshot cambia de `adc_n0` a
`adc_p0` _es_ la resolución par-pulso del stack** (esperado ~25-30 ns: re-arm
del trigger ~24 ns más el ancho de banda analógica). El generador va a tasa
cómoda (1 kHz por default): el resultado **no depende de la velocidad del
polling**, que es justamente el punto.

Cuatro detalles que hacen falta para que el resultado sea creíble:

- **Veredicto por mayoría** sobre `n_votos=11` lecturas separadas por más de un
  período. Una sola lectura no alcanza: si cae en la ventana de W entre subida y
  bajada ve `adc_p0` aunque los dos flancos se estén aceptando. Medido: con
  W = 2 µs el **13 %** de las lecturas caen ahí.
- **Cross-check independiente por Δ`wp`**: si se aceptan los dos flancos, los
  intervalos dejan de ser múltiplos exactos del período y aparece un residuo de
  ±W. `resid_med_ns` lo reporta.
- **El umbral baja a `thr=0.3` V** por default, porque a W chico el pulso no
  llega a amplitud plena (el ancho de banda de la entrada es ~50 MHz).
  `amp_pp`/`v_max` de cada punto dicen si el codo es tiempo muerto real o el
  pulso que se apagó.
- **`width_ok`** marca los puntos donde el instrumento no obedeció (readback
  fuera del ±20 %) y hay que **descartar**. Por la misma razón que arriba se
  setea siempre el período primero y el ancho después, y no se cambia el período
  entre medio.

`plot_width_curve(results)` grafica flancos resueltos vs ancho.

---

## 9. `diagnose_point()` — dónde se corta la cadena

Un solo período, los cuatro pasos en orden (generador → señal en el ADC → FPGA →
software), y un veredicto:

| Observación | Veredicto |
|---|---|
| señal ausente o bajo umbral | **GENERADOR** |
| señal OK + FPGA muerto | **CAMINO DE TRIGGER** (mask / dis / we) |
| señal OK + FPGA vivo + n=0 | **POLLING** (el lazo, no el hardware) |
| señal OK + FPGA vivo + n<esperado | **TIEMPO MUERTO DE SW**, cuantificado por `dt_hw` |

Con períodos comparables a la ventana del buffer (131 µs) la señal no se puede
juzgar desde una sola captura: ahí el veredicto es **INDETERMINADO** en vez de
acusar al generador. La impresión incluye `dt_hw / período`, que dice
directamente cuántos disparos se está salteando el polling.

---

## 10. Guardado

`_save()` delega en el callback del notebook; `_flat_meta()` aplana los dicts
anidados (`rigol`, `pulso`, `hw`) a claves con prefijo para que entren en la
metadata del `.npz`; `_fmt()` convierte números a nombres de archivo aptos
(`1000`, `0p5`, `2p5`). Cada punto guarda además los buffers crudos `d1`/`d2`,
así que **todo se puede reanalizar sin volver a medir**.

---

## 11. Qué NO cubre

- **Nada del MCA.** Esa suite es
  [`testbenches_software_mca.md`](../mca/testbenches_software_mca.md).
- **El camino de datos del ADC** más allá de `pulse_metrics`: calibración,
  ecualizador y decimación no se verifican acá.
- **El esclavo de bus del scope**, incluido el bug latente de `bram_ack[2]/[3]`
  descrito en [`bus_sistema_redpitaya.md`](../bus_sistema_redpitaya.md).
- **La lógica de trigger en sí**: eso lo cubren los testbenches de RTL de
  [`../sim/`](../../sim/), que reproducen el race arm-vs-máscara documentado en
  [`orden_arm_trigger_captura.md`](orden_arm_trigger_captura.md).

## Notebooks que la manejan

- [`../software/multitrigger_test_deadtime.ipynb`](../../software/multitrigger_test_deadtime.ipynb)
- [`../software/multitrigger_test_adq_dg4162.ipynb`](../../software/multitrigger_test_adq_dg4162.ipynb)
- [`../software/multitrigger_test_cfg.ipynb`](../../software/multitrigger_test_cfg.ipynb)

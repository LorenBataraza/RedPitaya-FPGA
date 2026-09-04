# Testbench de software del MCA (`testbench_mca.py` + `tests/`)

Cómo está organizada la caracterización del Analizador Multicanal, qué cierra
cada test, y **cuáles de los resultados hay que creerle y cuáles no**. Los
números de la última campaña están en
[`resultados_validacion_hw.md`](../resultados_validacion_hw.md); acá está el
*método*.

Código:

| Archivo | Qué es |
|---|---|
| [`API/mca.py`](../../software/API/mca.py) | driver (`class MCA`) + registros + API de lectura y guardado |
| [`API/analisis.py`](../../software/API/analisis.py) | helpers de análisis **puros** (sin hardware) |
| [`../software/testbench_mca.py`](../../software/testbench_mca.py) | suite de caracterización: sólo lo que necesita hardware |
| [`../software/tests/test_mca_hw.py`](../../software/tests/test_mca_hw.py) | smoke test del bus y los registros, **sin generador** |
| [`../software/tests/test_mca_datapath.py`](../../software/tests/test_mca_datapath.py) | camino de datos completo, con señal |
| [`../software/tests/diag_mca_hw.py`](../../software/tests/diag_mca_hw.py) | diagnóstico incremental, un paso por invocación |
| [`../software/tests/test_wave_builders.py`](../../software/tests/test_wave_builders.py) | estímulo y análisis, **en la PC sin instrumento** |
| [`../software/tests/test_formas_pulso.py`](../../software/tests/test_formas_pulso.py) | familias de forma de Knoll y la descomposición común/diferencial, **en la PC sin instrumento** |

---

## 1. La división driver / análisis / medición

Es la misma separación que en el scope, con una capa más:

- **`mca_utils.py`** — `class MCA` (mmap, `configure`, `clear`, `acquire`,
  `spectrum`, `map2d`, `counters`, `last_event`) **más los helpers de análisis
  puros**: `gauss_fit_peak`, `energy_calibration`, `dnl`, `fom`,
  `deadtime_fit`. Al ser funciones puras se pueden probar **contra `.npz`
  guardados, sin la placa**.
- **`testbench_mca.py`** — sólo lo que necesita hardware. Cada función devuelve
  **los datos crudos además del resultado**, para poder re-graficar y
  re-analizar sin volver a medir.

Convenciones que hacen la suite reutilizable:

- `_save(outdir, name, **arrays)` deja un `.npz` comprimido por medición.
- `plot_all(outdir)` y `--plot-only` regrafican una campaña entera **en la PC,
  sin hardware**.
- CLI: `--list`, `<test>`, `all`, `--outdir`, `--channel` (0=IN1, 1=IN2),
  `--gen-ch`.

```bash
python3 testbench_mca.py --list
python3 testbench_mca.py single_peak
python3 testbench_mca.py all --outdir datos/mca_2026-08-11
python3 testbench_mca.py --plot-only --outdir datos/mca_2026-08-11   # sin placa
```

---

## 2. Un test por fila de la tabla de parámetros de un MCA

El diseño de la suite es literal: cada función cierra una fila de la tabla de
parámetros a caracterizar (ver
[`decisiones_diseno_mca.md`](decisiones_diseno_mca.md) §1).

| Función (`TESTS`) | Eje | Qué cierra | Campaña 2026-08-11 | Estado del código |
|---|---|---|---|---|
| `single_peak` | resolución | FWHM del pulser = contribución de ruido electrónico | válido | estímulo nuevo (§6) |
| `sweep_amplitude` | amplitud | ganancia, INL, offset de cero | 3718.3 canales/Vpp; **INL 0.501 % FS con el generador incluido** | + ida y vuelta (§6) |
| `formas_inl` | amplitud | **cuánto de la INL depende de la forma del pulso** y cuánto es común-modo | — (nuevo) | **medido 2026-08-14**: con el estimador de pico la INL es común-modo (ganancias dentro de ±0.2 %, correlación +0.997); con el de carga NO (diferencial = ½ del residuo) |
| `dnl` | amplitud | no linealidad diferencial | **inválido**: líneas discretas | corregido, falta re-medir |
| `compare_estimators` | resolución | jitter de muestreo: pico vs integral | limitado por `q_shift` fijo | corregido, falta re-medir |
| `sweep_rate` | tasa | throughput, tiempo muerto, live time, corrimiento del centroide | válido hasta 100 kcps; **no se alcanzó el techo** | corregido, falta re-medir |
| `sweep_rate_poisson` | tasa | **pérdidas con arribos Poisson** (`ρ/(1+ρ)`), lo que el tren periódico no puede mostrar | — (nuevo) | escrito y validado contra un servidor K=1 simulado; falta medir |
| `pulse_pair` | tasa | resolución par-pulso | **inválido**: normalización | corregido, falta re-medir |
| `sweep_threshold` | umbral | curva S, LLD, piso de ruido | válido; LLD 1300, 262 kcps de ruido a `thr=20` | estímulo nuevo |
| `psd_fom` | forma | FOM y su dependencia con la energía | FOM global **1.462** válida; por rebanadas `nan` | corregido, falta re-medir |
| `baseline_k` | — | constante del seguidor de línea de base | válido para pulsos de 240 µs | **hay que re-correrlo primero** |
| `cross_check` | — | `cnt_total` contra la tasa conocida del generador | válido | estímulo nuevo |

> Los "corregido" son cambios de estímulo y de análisis hechos después de la
> campaña; están descritos en §6 y verificados sin hardware con
> `test_wave_builders.py`, pero **todavía no se re-midieron en la placa**.

### Los que tienen una idea no obvia atrás

**`test_psd_fom`** — las dos poblaciones tienen la **misma amplitud** y difieren
sólo en `tau`. Al no moverse en el eje de amplitud, *cualquier* separación que
aparezca viene del eje de forma: es el caso limpio para medir la FOM, y por eso
el 1.462 es creíble. FOM > 1.27 se considera buena separación.

**`compare_estimators`** — es EL experimento que justifica (o no) los 16384
canales. Con la muestra de pico la amplitud sale de una sola muestra y el
muestreo casi nunca cae en el máximo verdadero; ese error crece cuando el pulso
es rápido. La integral promedia el ruido como σ/√N y es inmune a ese jitter, así
que la diferencia entre las dos curvas mide directamente la contribución
instrumental.

**`sweep_threshold`** — la referencia es la **meseta**, no el máximo. A umbral
muy bajo el sistema dispara con ruido y la tasa se dispara (se midieron
**262 kcps a `thr=20`** con una señal de 2 kHz): tomar el máximo hacía que el
"50 %" cayera en la zona de ruido en vez de en el flanco de la curva S. Además
el rango de umbrales se deriva de la **amplitud medida** (`last_event()`), no de
un rango fijo: con un rango fijo bajo la curva sale plana y no dice nada.

**`sweep_rate`** — es el único que usa modo **PULSE y no ARB**. Con el ARB la
forma se estira sobre el período de repetición, así que al barrer la tasa el
pulso cambiaría de *ancho* al mismo tiempo; el modo PULSE da período y ancho
independientes. (El resto de los tests ya no tiene ese problema: `pulse_train_wave`
fija el ancho, ver §3.) El ancho igual escala con el período —`min(width, 0.2·T)`—
porque `set_pulse_periodic` exige `width < T/2` y a 500 kHz el período son 2 µs.

**`sweep_baseline_k`** — si la constante del seguidor (2^`bl_k` muestras, o sea
2^k · 8 ns) es comparable a la duración del pulso, el seguidor **persigue la
señal y la borra**: nunca cruza el umbral y no se detecta nada. Este barrido
encuentra el piso utilizable, y **hay que repetirlo con los pulsos reales**,
porque el valor correcto depende de cuánto duran.

---

## 3. Dos cosas de `testbench_mca.py` que hay que entender antes de leer un número

### El ancho del pulso es ahora un parámetro: `PULSE_WIDTH_S`

`set_arb(freq_hz)` estira la forma **completa** sobre `1/freq`, así que el ancho
del pulso no era un parámetro sino una consecuencia de cuántos puntos ocupaba
dentro de la forma. Con 128 puntos a 2 kHz cada punto dura 3.9 µs y **el pulso
terminaba durando ~336 µs = 42 000 muestras a 125 MSPS**. Con `maxlen=1024`
*todos* los eventos cerraban por longitud y se contaban como apilamiento sin
entrar a los histogramas (verificado en la placa), y de ahí salía el
`maxlen=60000` de la campaña — un parche sobre un estímulo mal escalado.

Ahora `rg.pulse_train_wave(width_s, rate_hz)` invierte la relación: se le pide
el ancho en segundos y devuelve la forma **junto con la frecuencia** a la que
hay que aplicarla. `PULSE_WIDTH_S = 2e-6` es el default de toda la suite y
`DEFAULT_CFG['maxlen']` bajó a 4096 en consecuencia.

**`bl_k` y `maxlen` dependen de la duración del pulso**, así que al cambiarla
hay que re-correr `sweep_baseline_k` antes que nada. `run_campana.py` ya lo hace
primero y propaga el resultado a `DEFAULT_CFG`.

### `cnt_dropped` **no** se normaliza contra `cnt_total`

`cnt_dropped` (offset `0x064`) es la suma de dos cosas
([`mca_top.sv:346`](../../rtl/mine/mca/mca_top.sv)):

```systemverilog
sys_rdata <= c_lost + hist_h_drop + hist_2d_drop;
```

- `c_lost` — eventos que llegaron con el extractor de características **ocupado**
  (divisor en curso). **Nunca entraron en `cnt_total`.**
- `hist_*_drop` — eventos descartados durante un barrido de borrado. Esos sí
  están en `cnt_total`.

Consecuencia: **`dropped / total > 1` es perfectamente posible** y no indica un
contador roto. El aviso de `_acquire()` que compara los dos es lo que produjo el
"101 % de descartes" del test de par-pulso, y se corrige normalizando por
`total + dropped`.

---

## 4. Los tests de placa (`software/tests/`)

Son la otra mitad de la verificación: mientras `testbench_mca.py` mide
*parámetros*, éstos verifican que el bloque **funciona**.

### `test_mca_hw.py` — smoke test, sin generador

Es el equivalente en hardware de `tb_mca_top.sv`: lo que allá se verifica con un
BFM, acá se verifica contra el bus real, **incluido el CDC que la simulación no
modela**. Cubre:

- identificación: magic, `H_AW = 14` (16384 canales), `H2_AW = 7`/`PSD_AW = 6`,
  y que los dos motores estén presentes;
- ida y vuelta de cada registro RW con su máscara;
- barrido de lecturas **sin colgarse**;
- borrado: espectro y mapa 2D enteros en cero, forma del mapa `(128, 64)`,
  contadores en cero;
- relojes: `realtime` avanza ~0.5 s en 0.5 s, `livetime + deadtime = realtime`,
  el reloj medido coincide con el del sistema, y con `run=0` **no** avanza;
- `chan_sel` (IN1/IN2), `clear_busy` bajo en reposo, y convergencia de la línea
  de base.

### `test_mca_datapath.py` — el lazo cerrado

Con señal real del DG4162 en IN1: pulsos → segmentador → histogramas. Si
`cnt_total` sigue a la tasa del generador y el espectro tiene un pico único,
**todo el camino está validado**.

### `diag_mca_hw.py` — la herramienta que salvó la campaña

Existe porque el smoke test completo **reinició la placa dos veces** y hubo que
aislar qué operación lo disparaba. Corre **un paso por invocación** y se chequea
`/proc/uptime` entre uno y otro, así un reinicio queda atribuido sin ambigüedad.
El orden de sospecha, del menos al más peligroso, es reutilizable para cualquier
bloque nuevo sobre este bus:

```
regs      lectura/escritura de registros sueltos (ya sabemos que anda)
sweep     barrido de ~650 direcciones, incluidas no mapeadas
bulk      lectura masiva del espectro con copia numpy   <-- principal sospechoso
word      el mismo espectro pero palabra por palabra
clear     barrido de borrado
counters  relojes y contadores
```

**Culpable encontrado:** `np.frombuffer(...).copy()` de 16384 palabras sobre la
apertura del histograma. La lectura en bloque colgaba la placa; la lectura
palabra por palabra no. De ahí sale el `_read_words()` de `mca_utils.py`, que
desenrolla el acceso con `struct.unpack_from` en un list comprehension:

```python
unpack = _U32.unpack_from
mem = self._mmap
return np.array([unpack(mem, offset + 4 * i)[0] for i in range(n)], dtype=np.uint32)
```

Cuesta ~110 ms para el espectro completo, y es el precio de no reiniciar la
placa.

---

## 5. Los runners de campaña

La campaña completa no entra en una sola sesión (entre otras cosas porque
`sweep_threshold` pide desconectar la entrada a mitad de camino), así que quedó
partida en tres scripts que comparten `--outdir`:

| Runner | Qué corre |
|---|---|
| [`run_campana.py`](../../software/run_campana.py) | `baseline_k` **primero**, después `single_peak`, `cross_check`, `compare_estimators` → `resumen.json` + `plot_all` |
| [`run_resto.py`](../../software/run_resto.py) | `sweep_amplitude`, `pulse_pair`, `sweep_rate` → `resumen_resto.json` |
| [`run_resto2.py`](../../software/run_resto2.py) | `sweep_threshold`, `psd_fom`, `dnl` → `resumen_resto2.json` |
| [`run_formas.py`](../../software/run_formas.py) | `formas_inl` + el análisis común/diferencial → `resumen_formas.json`, `inl_formas.png`, `pico_vs_carga.png` (~20 min; ver §8) |

Cada uno deja los `.npz` crudos en el mismo directorio y un JSON con los números
resumidos. La campaña del 2026-08-11 está en
[`../software/datos/mca_20260811_113136/`](../../software/datos/mca_20260811_113136/).

---

## 6. Lo que estaba roto y cómo se corrigió

**Ninguno de los problemas era del MCA**: todos eran de diseño de estímulo y de
análisis, y casi todos compartían una raíz — el ARB producía pulsos de ~240 µs,
cuatro órdenes de magnitud más largos que un pulso de detector.

| Test | Qué reportaba mal | Qué cambió |
|---|---|---|
| **todos** | el ancho del pulso no era un parámetro | `pulse_train_wave(width_s, rate_hz)`: el ancho se pide en segundos y la frecuencia sale despejada |
| `dnl` | 467 % sobre un espectro con 40 canales vacíos | estímulo con amplitud continua (AM de ruido, con recarga del ARB como alternativa); `dnl()` compara contra la **envolvente local** y **rechaza** un espectro con canales vacíos en vez de devolver un número |
| `pulse_pair` | 101 % de descartes; 1.00 por debajo del tiempo muerto | ancho y período del burst **fijos**; normalización contra la **medición a gap máximo** en vez de un número de bursts estimado; `dropped` como número absoluto |
| `compare_estimators` | "mejora" que podía ser del `q_shift` | `autoscale_q_shift()` lleva los dos estimadores a la misma escala de canales; los puntos con FWHM < 3 canales se marcan **no comparables** |
| `psd_fom` por rebanadas | `nan` en tres de cuatro | segundo estímulo con amplitud variable (`amp_range`) y `autoscale_h2_shift()`; las rebanadas sin estadística se dicen como tales |
| `sweep_rate` | 100 kcps tomado como techo | barrido hasta ~800 kcps, ancho que escala con el período, y el **techo** se reporta explícitamente; sin saturación **no se ajusta** el tiempo muerto |
| `sweep_amplitude` | INL 0.501 % sin separar del generador | pasada de **ida y vuelta**: si el residuo se repite es sistemático, si no es la estadística del ajuste |
| eficiencia (todos) | estímulo **periódico**: con K=1 no se pierde nada hasta ρ=1, así que la eficiencia medida es la del tren, no la del equipo | `sweep_rate_poisson` con arribos de Poisson (`poisson_train_wave`), que es lo que entrega una fuente real |

### Arribos Poisson (`sweep_rate_poisson` / `run_poisson_loss.py`)

El estímulo lo arma
[`poisson_train_wave`](../../software/API/rigol_dg4162.py): sortea `N ~ Poisson(λT)`
y pone las N posiciones **uniformes** en el ciclo, que es exactamente un proceso
de Poisson condicionado a N — y además deja la **costura** del lazo del ARB
limpia (un `cumsum` de exponenciales deja ahí un hueco determinista que se
repite en cada vuelta). Los pulsos se **suman**, así que el apilamiento pasa como
en un detector real.

Dos límites que conviene tener a mano:

- **memoria contra tasa**: `dt = n_events/(λ·16384)`, así que a tasas bajas el
  pulso tiene que ser ancho (a 400 ev/s con 64 eventos por ciclo, ~79 µs). Para
  medir *pérdidas* alcanza con `width ≪ τ`; `run_poisson_loss.py` elige
  `n_events` solo para que el ancho quede por debajo del 10 % de τ.
- **escala del pulso**: `load_arb` normaliza por el máximo, y con pile-up ese
  máximo depende de la semilla. Por eso la forma se escala por
  `headroom × pico de un pulso solo` y se sube con `normalize=False`; si no, el
  pico del espectro se mueve entre realizaciones.

Verificado sin hardware por
[`test_poisson_wave.py`](../../software/tests/tiempo-muerto/test_poisson_wave.py) (intervalos
exponenciales por KS, `var(N)=media(N)`, la costura sesgada por longitud como
corresponde a Poisson, pile-up contra `1−e^{−2λw}`) y por
[`test_poisson_sweep_sim.py`](../../software/tests/tiempo-muerto/test_poisson_sweep_sim.py),
que corre el barrido entero contra un servidor K=1 simulado y recupera
`ρ/(1+ρ)` con 0.45 pp de error medio, contra 18.75 pp del modelo periódico.

Los cambios están verificados sin hardware por
[`test_wave_builders.py`](../../software/tests/test_wave_builders.py), que
comprueba que el ancho y la tasa del estímulo son los pedidos, que las
combinaciones imposibles fallan con mensaje, y que `dnl()` recupera una DNL
inyectada del 3 % sobre una envolvente no plana (contra la media global el mismo
espectro daba 19.5 %, seis veces más).

**Falta re-medir todo en la placa.** El orden importa: `sweep_baseline_k`
primero, porque el resto depende del `bl_k` que salga.

## 7. `formas_inl`: cuánto de la INL es de la forma del pulso

`sweep_amplitude` mide la INL con **una sola** forma de pulso, y su pasada de
ida y vuelta alcanza para decir que el residuo es sistemático — pero no de
quién es. `sweep_formas_inl` agrega el eje que falta: repite la misma curva con
las formas de amplificador de conformado de Knoll (cap. 16), todas con el
**mismo FWHM y la misma altura de pico**, de manera que entre familia y familia
lo único que cambia es la forma.

| Familia | `f(u)`, con `u = t/escala` | Factor de forma (área/pico·FWHM) |
|---|---|---|
| `cr` | `(1−e^{−u/0.05})·e^{−u}` — una diferenciación, pulso de cola | 1.343 |
| `cr_rc` | `u·e^{−u}` — semi-gaussiana clásica, **la de referencia** | 1.111 |
| `cr_rc4` | `u⁴·e^{−u}/4!` — cuasi-gaussiana | 1.076 |
| `triangular` | rampa arriba, rampa abajo | 1.007 |
| `trapezoidal` | rampa, techo plano, rampa | 1.000 |
| `bipolar` | `(1−u/2)·u·e^{−u}` — doble diferenciación, cruza por cero | 0.979 |

Están en [`rigol_dg4162.py`](../../software/API/rigol_dg4162.py) (`FORMAS_KNOLL`,
`shaped_train_wave`), que es donde ya vivían los constructores de onda: son
funciones puras de numpy y se validan sin instrumento.

### Por qué el barrido dice algo que la ida y vuelta no puede decir

El error de consigna de amplitud del DG4162 es **común a todas las formas**:
`load_arb` normaliza cada forma a pico 1.0 y `set_arb` la escala por `amp_vpp`,
así que el mismo lazo de amplitud del instrumento actúa idéntico sobre todas.
De ahí sale la descomposición que hace `analizar_formas`:

```
residuo COMÚN a todas las familias  =  generador + INL estática del ADC
residuo DIFERENCIAL entre familias  =  cadena de medición, y sólo ella
```

**No** separa generador de INL estática del ADC — los dos son común-modo, y eso
sigue pidiendo un patrón trazable. Pero sí acota la parte que depende de la
forma, que es la que responde la pregunta de robustez.

### Tres cosas que hacen que la comparación signifique algo

1. **`n_pulses=1` forzado.** Fija `freq_hz = rate_hz` y la tasa de muestreo del
   ARB (32.77 MSa/s) iguales para todas las familias. Sin eso `n_pulses` sale
   del duty y cambiaría la forma **y** la frecuencia a la vez, con lo cual la
   diferencia medida no sería atribuible a nada.
2. **Pre-vuelo por familia.** Verifica `cnt_total ≈ rate·seconds` y apilamiento
   < 5 % antes de medir la curva. Es la guarda contra el modo de falla de
   `mca_utils` (si la constante del seguidor de línea de base no es mucho más
   larga que el pulso, el seguidor se **come** el pulso y no se detecta ningún
   evento). Una familia que no pasa se reporta como no medible y el resto de la
   campaña sigue.
3. **Réplica de cierre.** Al final se re-mide la familia de referencia: es el
   control nulo. Si la deriva de la réplica es del orden del diferencial entre
   familias, lo que se midió es deriva térmica y no forma.

### El gráfico pico-vs-carga

`pico_vs_carga.png` es el único test de linealidad del conjunto que **no
depende de la exactitud del generador**: los dos ejes son estimadores internos
del mismo pulso físico, así que un error de consigna mueve el punto *a lo largo*
de la recta y no fuera de ella.

- pendiente distinta por familia → esperado, es la geometría del pulso;
- **curvatura dentro de una familia** → no linealidad de la electrónica;
- ordenada al origen ≠ 0 → offset de cero de alguno de los dos estimadores.

Los ejes van en unidades físicas deshaciendo los desplazamientos de binning
(`cen_pico · 2^h_shift`, `cen_carga · 2^q_shift`), porque `q_shift` se autoescala
**por familia** y sin la corrección la pendiente mediría el autoescalado en vez
de la forma. La pendiente relativa medida tiene que reproducir el factor de
forma relativo de la tabla de arriba, que sale de la geometría y de ninguna
medición: es la verificación cruzada de que el eje de carga está bien escalado.

> La triangular y la trapezoidal comparten factor de forma **exactamente**
> (1.000, para cualquier ancho de techo: la recta de media altura bisecta las
> dos rampas). O sea que caen sobre la misma recta teniendo ápices
> completamente distintos — es el par de control que aísla el efecto del ápice
> sobre el estimador de pico.

---

## 8. Qué NO cubre

- **Pulsos de detector reales**: la campaña entera se hizo con el generador. El
  cambio de §6 pone el estímulo en la escala temporal correcta, pero un pulso
  sintético sigue sin tener el ruido ni la variabilidad de uno real.
- **Deriva de ganancia y offset** con el tiempo y la temperatura: pide horas de
  adquisición repetida del mismo pico. (`formas_inl` sólo la **acota** sobre los
  ~20 min que dura su campaña, con la réplica de cierre.)
- **Separar la INL del ADC de la del generador**: la pasada de ida y vuelta
  distingue sistemático de ruido, y `formas_inl` (§7) separa la parte que
  depende de la forma de la que no — pero generador e INL estática del ADC son
  los dos común-modo y siguen sin poder separarse entre sí. Eso pide un patrón
  de tensión trazable.
- **El conformado trapezoidal** *en el MCA*, fuera de alcance del diseño (ver
  [`decisiones_diseno_mca.md`](decisiones_diseno_mca.md) §5). Que `formas_inl`
  **inyecte** una forma trapezoidal desde el generador es otra cosa: no
  implementa el filtro, sólo usa la forma como estímulo.

---

## Ver también

- [`register_map_mca.md`](register_map_mca.md) — los offsets que usa el driver.
- [`decisiones_diseno_mca.md`](decisiones_diseno_mca.md) — por qué el hardware es
  como es.
- [`bus_sistema_redpitaya.md`](../TOP/bus_sistema_redpitaya.md) — el bus, el timeout de
  32 ciclos y la clase de cuelgue que `test_mca_hw.py` verifica que no ocurra.
- [`testbenches_escritura_archivos.md`](../testbenches_escritura_archivos.md) — la
  otra suite de software.

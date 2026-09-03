# Resultados de la validación en hardware del MCA

El **por qué** del diseño está en
[`decisiones_diseno_mca.md`](mca/decisiones_diseno_mca.md); acá van los números
medidos y cómo interpretarlos. Qué **limita** a esos números —y por qué el que ata
es la deriva y no el contador ni la cantidad de canales— está en
[`limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md).

> ## ⚠️ Este documento describe la PRIMERA campaña (2026-08-11), y varios de sus
> ## números están CORREGIDOS o REFUTADOS por la segunda
>
> La segunda campaña se corrió con el estímulo arreglado (pulsos de 2 µs en vez
> de 336 µs) y está en **[§13](#13-segunda-campaña--estímulo-corregido)**. Lo que
> cambió de fondo:
>
> | Magnitud | 1ª campaña | 2ª campaña | |
> |---|---|---|---|
> | Throughput | "sigue exacto a 100 kcps" | **794 kcps sin perder un evento** | la 1ª era una **lectura equivocada**: la columna de salida estaba clavada en 100 cps |
> | Tiempo muerto | 2.3 µs/evento | **~0.4 µs/evento** | |
> | Resolución par-pulso | inválida | **≤ 0.5 µs** | |
> | FOM vs energía | `nan` en 3 de 4 rebanadas | **1.31 → 1.58 al subir la amplitud** | |
> | DNL | 467 % (inválida) | **26 % pero es una cota superior** del estímulo | no se puede medir con este generador |
> | INL | 0.501 % FS | **1.13 % FS, sistemático** (correlación +1.00 entre pasadas) | |
> | Pico vs integral | "integral ≥60× mejor" | **el resultado vigente está en [§0](#0-precisión-de-los-estimadores--el-resultado-vigente)** | la 1ª comparaba escalas distintas |
> | Corrimiento con la tasa | — | **+1.28 %** en ×36 (el +6.45 % que se reportó primero está confundido con el ancho de pulso) | |
>
> Las secciones 1-12 se dejan como estaban, con su fecha, porque documentan el
> estado del hardware que se validó entonces (bus, registros, relojes) y porque
> los errores de método son parte del registro.

**Datos crudos:** [`../software/datos/mca_20260811_113136/`](../software/datos/mca_20260811_113136/)
(1ª campaña) y [`../software/datos/mca_20260528_001034/`](../software/datos/mca_20260528_001034/)
(2ª campaña; el nombre lleva la fecha del reloj de la placa, que está mal — es
del 2026-08-11 por la noche).

---

## Montaje

| | |
|---|---|
| Placa | Red Pitaya STEMlab 125-14, `10.73.28.27` |
| Bitstream | `mca_red_pitaya.bit.bin` (top `mca_red_pitaya_top`, slot 7) |
| Configuración | `H_AW=14` (16384 canales), `H2_AW=7` × `PSD_AW=6` (mapa 128×64) |
| Estímulo | Rigol DG4162, forma **arbitraria**, CH1 → IN1 |
| Forma | `detector_pulse(128 pts, t_rise, tau=16)`, 2 kHz de repetición, 0.5 Vpp |
| Config del MCA | `thr=100`, `hyst=40`, base automática `bl_k=12`, `maxlen=60000`, `tail_dly=8` |

> El reloj de la placa **no está sincronizado** (el `resumen.json` dice mayo).
> La fecha buena es la del nombre del directorio, puesta desde la PC.

---

## Resumen

| Medición | Resultado | Interpretación |
|---|---|---|
| Smoke test (`tests/test_mca_hw.py`) | **29 PASS / 0 FAIL** | bus, registros, borrado, relojes |
| Barrido de 646 direcciones | ninguna cuelga el bus, **6.1 µs** c/u | valida el ack de latencia fija |
| Borrado de 16384 canales | **0.2 ms** | |
| `livetime + deadtime = realtime` | exacto | |
| Reloj de tiempo real | **1.0014 s** medidos vs 1.0 s | error 0.14 % |
| **Conteo de eventos** | **10010 / 10010 esperados, −0.004 %** | valida todo el camino de datos |
| Pico único (pulser) | centroide **1843.1**, FWHM **4.54**, **0.247 %** | contribución de ruido de la cadena |
| Pico vs integral | *retirado — medía el piso del binado* | resultado vigente en [§0](#0-precisión-de-los-estimadores--el-resultado-vigente) |
| Constante del seguidor de base | `bl_k ≥ 9` con este pulso | §4 |
| **Ganancia de conversión** | **3718.3 canales/Vpp**, offset −7.4 canales | linealidad excelente |
| INL | **0.501 % FS** | 10× peor que un MCA comercial, §6 |
| **Throughput** | sigue al generador **exacto de 187 Hz a 100 kcps** | sin perder un evento |
| Tiempo muerto | **2.3 µs/evento**; live 99.5 % → 71.4 % | = ancho de pulso + divisor |
| Curva S de umbral | meseta limpia, corte en **1300 cuentas** | §8 |
| Piso de ruido | con `thr=20` dispara a **262 kcps** | umbral mínimo útil ~100 |
| **FOM de PSD** | **1.462** | **>1.27: buena separación** |
| DNL | **no válida** con este estímulo | §10 |
| Resolución par-pulso | **no válida** | §10 |

---

# 0. Precisión de los estimadores — el resultado vigente

La comparación entre estimadores se midió cuatro veces y las tres primeras
quedaron obsoletas; ésta es la tabla que hay que citar. Todo con el mismo
estímulo de 2 µs de FWHM.

## 0.1 Medido en placa

Cada bloque compara estimadores **en las mismas condiciones**; entre bloques no,
porque cambia la amplitud del estímulo.

| Estimador | Resolución (FWHM/centroide) | Dónde |
|---|---|---|
| muestra de **pico** | 0.33 – 0.44 % (0.344 % a 2 µs) | [§13.6](#136-pico-vs-integral-la-integral-es-peor-y-se-entiende-por-qué) |
| **integral**, ventana por histéresis | 0.53 % | [§13.6](#136-pico-vs-integral-la-integral-es-peor-y-se-entiende-por-qué) |

| Estimador | Resolución | Dónde |
|---|---|---|
| **integral**, ventana por histéresis (referencia re-medida) | 0.325 % | [§14.1](#141-el-resultado) |
| **integral, compuerta FIJA de 384 muestras** | **0.161 %** | [§14.1](#141-el-resultado) |

**El resultado de diseño es ×2.02 a favor de la compuerta fija**, y
[§14.1b](#141b-los-dos-modos-a-lo-largo-del-espectro) muestra que se sostiene en
toda una década de amplitud: **×1.58 a ×2.13, mediana ×1.91**, sin ninguna
energía donde la histéresis gane. La ventaja es mayor a energía baja.

## 0.2 Análisis offline sobre los mismos 7054 pulsos

Único bloque donde **todos** los estimadores se calculan sobre los mismos datos
crudos, así que las relaciones entre ellos son directamente comparables
([`../software/tests/estimadores/`](../software/tests/estimadores/)):

| Estimador | Resolución | Relativo al pico |
|---|---|---|
| integral, ventana por histéresis | 0.528 % | 1.94× peor |
| pico | 0.272 % | — |
| trapecio (k=192, m=160) | 0.212 % | 1.28× mejor |
| **integral, compuerta fija de 384 muestras** | **0.149 %** | **1.83× mejor** |

La réplica se valida contra el hardware por la σ **en cuentas**: da 2.78 y la
placa midió 2.81, 1 % de acuerdo.

> **El 0.528 % de este bloque no es la referencia buena.** Al re-medir la
> histéresis en placa en las mismas condiciones da 0.325 %
> ([§14.2](#142-lo-que-confirma-del-análisis-offline)), así que la mejora real de
> la compuerta fija es **×2.02 y no ×3.5**.

## 0.3 Por qué el pico le gana a la integral con esta señal

La integral gana cuando el estimador de pico sufre *jitter de muestreo*, y acá no
sufre: un pulso de 2 µs son **250 muestras a 125 MSPS**, así que la muestra de
pico cae prácticamente en el máximo verdadero. La integral, en cambio, acumula el
error de línea de base sobre toda la ventana.

Pero el problema no era la integral: **era la VENTANA**. Con `gate_mode=0` el RTL
cierra donde la cola cruza `thr − hyst`, que es la zona **más chata** del pulso —
con τ = 186 muestras y σ = 2.8 cuentas de ruido el cruce tiembla ~9 muestras, y
cada muestra vale ~60 cuentas de carga. Con compuerta de largo fijo eso
desaparece y la carga pasa a ser el mejor estimador de los cuatro.

**El trapecio queda por debajo de la compuerta fija** y costaría la mitad del
throughput, así que con esta señal no se justifica. Su valor está en otra cosa
—la cancelación polo-cero, que es lo que ataca la deriva de
[`limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md) §6—, no en
la resolución.

---

## 1. Conteo de eventos — la medición que cierra el lazo

```
esperado 10010, contado 10010  (-0.004 %)
descartados 0, apilamientos 0, rechazados por amplitud 0
```

Es la validación más fuerte de todo el trabajo: 5 s a 2 kHz, **sin un solo
evento perdido ni espurio**. Confirma de punta a punta el segmentador Schmitt,
los contadores, los relojes y la ruta de eventos hacia los histogramas.

---

## 2. Resolución con pulser — ruido de la cadena

```
centroide 1843.1 canales    FWHM 4.54    resolución 0.247 %
20021 eventos en 10.01 s (2000 cps), 19 canales poblados
```

Con un pulser de amplitud fija, **el FWHM del pico ES la contribución de la
cadena electrónica**. Se resta en cuadratura del FWHM total para separar
detector de electrónica:

```
FWHM_detector = sqrt( FWHM_total^2 - 4.54^2 )
```

> **No cites el 0.247 % como la resolución del MCA.** Está medido con el pulso de
> 336 µs de la 1ª campaña. Con el estímulo corregido de 2 µs la misma medición da
> **0.344 %** (§13.6) y con compuerta fija **0.161 %**
> ([§0](#0-precisión-de-los-estimadores--el-resultado-vigente)). Lo que sigue
> valiendo de esta sección es el **método**, no el número.

Un 0.25 % es un piso instrumental cómodo: para un NaI(Tl) (~7 % FWHM) el aporte
de la electrónica es despreciable; incluso para un HPGe (~0.2 %) queda del mismo
orden, así que ahí sí conviene usar el estimador de integral.

---

## 3. Pico vs integral — *números retirados*

Esta sección publicaba una mejora de "≥60×" a favor de la integral. **No medía
el estimador: medía el piso del binado.** Con el `cfg_q_shift` de esa campaña
todos los eventos de la integral caían en un único canal, así que el FWHM
reportado (0.68) era el desvío de una distribución uniforme de un bin,
`2.355/√12`, y no una propiedad de la integral. Los dos estimadores estaban
además en escalas de canal distintas, así que la comparación no era comparación.

Se corrigió llevando los dos a la misma escala con `autoscale_q_shift()`. El
resultado vigente, con el signo invertido respecto de lo que decía acá, está en
**[§0](#0-precisión-de-los-estimadores--el-resultado-vigente)**.

---

## 4. Constante del seguidor de línea de base

Pulso de ~62 µs (`t_rise=16`):

| `bl_k` | τ = 2^k · 8 ns | Eventos detectados |
|---|---|---|
| 3 | 0.07 µs | **0** |
| 6 | 0.5 µs | **0** |
| 9 | 4.1 µs | 2002 |
| 12 | 32.8 µs | 2002 |
| 15 | 262 µs | 2002 |

Si la constante es comparable a la duración del pulso, **el seguidor persigue la
señal y la borra**: nunca cruza el umbral y no se detecta nada. No es un
defecto, es el comportamiento propio de un restaurador de línea de base, pero
falla de forma silenciosa: se ve como "el MCA no cuenta nada".

**Regla: τ ≥ 100× la duración del pulso**, o base fija (`bl_auto=False`), que es
inmune. El default del driver quedó en `bl_k = 12`.

Hay que **repetir este barrido con los pulsos reales del detector**, porque el
valor correcto depende de cuánto duran. `testbench_mca.sweep_baseline_k()` lo
automatiza.

---

## 5. Tiempo muerto — cuidado al interpretarlo

De la corrida de pico único:

```
realtime 10.0103 s    livetime 5.1952 s    deadtime 4.8151 s   ->  48 % muerto
```

**Ese 48 % NO es una propiedad del MCA**, es del estímulo. El tiempo muerto por
evento sale 240 µs, que es exactamente lo que dura el pulso del generador: el
segmentador está ocupado toda la ventana del pulso, como corresponde.

La razón es el ARB: **el DG4000 estira la forma completa sobre el período de
repetición**. Con 128 puntos a 2 kHz cada punto dura 3.9 µs, así que un pulso
que ocupa ~60 puntos termina durando ~234 µs — cuatro órdenes de magnitud más
que un pulso de detector real.

Consecuencias prácticas:

- `cfg_maxlen` tuvo que subirse a 60000 muestras. Con el default de 1024 **todos
  los eventos cerraban por longitud** y se contaban como apilamiento sin entrar
  al histograma.
- El tiempo muerto y la curva de throughput medidos con este estímulo no
  representan al sistema real.

**Para caracterizar tiempo muerto de verdad** hay que generar pulsos de
microsegundos: usar muchos más puntos de ARB (hasta 16384) con el pulso ocupando
una fracción chica, o subir la frecuencia de repetición y aceptar la tasa alta.

---

## 6. Linealidad: ganancia, INL y offset de cero

Barrido de 20 amplitudes de 0.1 a 1.0 Vpp:

```
ganancia 3718.3 canales/Vpp    offset de cero -7.4 canales    INL 0.501 % FS
```

La linealidad es visualmente excelente (1418.6 → 3726.8 canales, monótona) y el
FWHM se mantiene entre 4.4 y 5.2 canales en todo el rango, o sea que la
resolución no se degrada con la amplitud.

**El 0.501 % de INL es ~10× peor que un MCA comercial** (<±0.05 % FS). Antes de
atribuírselo al MCA hay que descartar al generador: la INL medida incluye la del
DG4162, la del front-end analógico y la del ADC. Para separarlas haría falta una
referencia de amplitud mejor que el propio generador.

---

## 7. Throughput y tiempo muerto

Con estímulo en **modo PULSE** (ancho fijo de 2 µs, período variable), que es lo
correcto: con ARB el ancho cambia junto con la tasa y la curva no significa nada.

| Tasa de entrada | Tasa registrada | Live time |
|---|---|---|
| 187 Hz | 187 cps | 99.5 % |
| 1 233 Hz | 1 233 cps | 99.5 % |
| 8 111 Hz | 8 111 cps | 97.7 % |
| 28 480 Hz | 28 480 cps | 91.9 % |
| 53 367 Hz | 53 367 cps | 84.8 % |
| **100 000 Hz** | **100 000 cps** | **71.4 %** |

**El MCA sigue al generador exactamente en tres décadas, sin perder un solo
evento.** Medido aparte con más detalle: 1 kHz→1000, 10 kHz→10001,
50 kHz→50000, 100 kHz→100000 cps, con cero apilamientos y cero descartes.

El tiempo muerto crece de 0.5 % a 23-28 %, o sea **2.3 µs por evento**, que es
exactamente el ancho del pulso más los 6 ciclos del divisor de PSD. Como el
tiempo muerto por evento es menor que el período incluso a 100 kHz, **no hay
pérdida de cuentas en este rango**: el ajuste de tiempo muerto no converge a
nada útil porque no hay saturación que ajustar.

Para encontrar el techo real habría que ir a tasas donde el período se acerque a
los 2.3 µs, o sea >300 kcps.

El centroide se corre **+3.7 %** de la tasa mínima a la máxima — un efecto real
de desplazamiento de línea de base con la tasa, que es justamente uno de los
parámetros que había que caracterizar.

---

## 8. Umbral: curva S y piso de ruido

Rango derivado de la amplitud medida (~1845 cuentas):

| Umbral | Tasa |
|---|---|
| 20 | **262 732 cps** ← ruido |
| 111 … 1208 | 2 000 cps (meseta) |
| 1300 … 2306 | 0 cps |

Dos lecturas:

- **Piso de ruido:** con `thr = 20` el sistema dispara con ruido a 262 kcps
  frente a una señal de 2 kHz. **El umbral mínimo utilizable está en ~100
  cuentas** con la entrada conectada al generador.
- **Curva S muy abrupta:** la transición ocurre entre 1208 y 1300 cuentas, o sea
  en menos de un 8 % del umbral. Es lo esperable de un discriminador Schmitt con
  un pulser de amplitud fija y poco ruido; con un detector real la transición
  sería mucho más gradual y la curva S mediría la resolución.

> La primera versión de este test extraía el "LLD al 50 %" del **máximo** de la
> curva, y con el punto de ruido en 262 kcps eso daba un valor sin sentido. Ahora
> la referencia es la **meseta** (mediana de los puntos no nulos) y los puntos
> dominados por ruido se excluyen. Con esa lógica el LLD da **1300 cuentas**.

---

## 9. Discriminación por forma: FOM = 1.462

Dos poblaciones sintéticas con la **misma amplitud** y colas distintas
(`tau = 12` y `tau = 40`), 50 % cada una, 20 s a 500 Hz:

```
FOM global: 1.462
```

**Por encima del 1.27 que se considera buena separación.** Como las dos
poblaciones tienen idéntica amplitud, cualquier separación observada viene del
eje de forma: esto valida de punta a punta la cadena de PSD — acumuladores
`Q_total`/`Q_cola`, el divisor restaurador, y el mapa 2D.

El desglose por rebanadas de amplitud da `nan` en tres de las cuatro: con
`h2_shift = 7` toda la señal cae en la primera rebanada. Para ver la dependencia
de la FOM con la energía hay que ajustar `cfg_h2_shift` a la amplitud real.

Este resultado **sólo fue posible tras arreglar `load_arb`** (§10).

---

## 10. Dos mediciones que NO son válidas

Se documentan para que nadie las tome por buenas.

### DNL — el estímulo no es un sliding pulser de verdad

```
media 7128 cuentas/canal    DNL max 467.75 %    rms 117.89 %
```

No es estadística: con 7128 cuentas/canal el piso de Poisson es 1.2 %. El
problema es el estímulo. `sliding_pulser_wave(n_pulses=128)` genera **128
amplitudes aleatorias y después repite esa misma forma indefinidamente**, así
que el espectro son 128 líneas discretas, no un continuo. El análisis lo
confirma: **172 canales poblados con 40 canales vacíos intercalados**.

Para una DNL de verdad hace falta que la amplitud varíe de forma continua en el
tiempo: recargar el ARB con amplitudes nuevas periódicamente, o usar modulación
de amplitud del generador.

### Resolución par-pulso — normalización dudosa

El test reporta 0.10 µs, pero avisa de **más descartes que eventos totales**
(101 %), lo cual es imposible y delata un error de normalización: `cnt_dropped`
suma pérdidas de tres fuentes distintas y el test las compara contra un número
de bursts estimado, no medido. Hay que rehacer la cuenta antes de creerle.

---

## 11. Lo que queda pendiente

**Los nueve tests de `testbench_mca.py` se corrieron.** Siete dan resultados
válidos; dos (§10) están limitados por el estímulo, no por el MCA.

### La raíz común, y el cambio que la arregla

Casi todos los problemas vienen de **una sola cosa**: `set_arb` estira la forma
completa sobre el período de repetición, así que el ancho del pulso no era un
parámetro sino una consecuencia — y salía **~336 µs (42 000 muestras a
125 MSPS)**. Eso forzó `cfg_maxlen = 60000` y contaminó tiempo muerto,
apilamiento, `bl_k` y par-pulso a la vez.

`rg.pulse_train_wave(width_s, rate_hz)` invierte la relación: se le pide el
ancho en segundos y devuelve la forma **junto con la frecuencia** a la que hay
que aplicarla. Con eso el estímulo pasa a ~2 µs, la escala de un pulso de
detector, y `cfg_maxlen` baja a 4096.

### Estado de cada pendiente

| Pendiente | Cambio hecho | Falta |
|---|---|---|
| Rehacer la DNL | estímulo de amplitud continua (AM de ruido, con recarga del ARB como alternativa) y `dnl()` contra la envolvente local, que **rechaza** un espectro con canales vacíos | medir en placa |
| Rehacer par-pulso | ancho y período del burst fijos; normalización contra la medición a gap máximo; `dropped` como número absoluto | medir en placa |
| Techo real de throughput | barrido hasta ~800 kcps con ancho que escala; se reporta el techo y **no se ajusta** tiempo muerto sin saturación | medir en placa |
| Separar la INL del generador | pasada de ida y vuelta: distingue residuo **sistemático** de estadística del ajuste | medir; separar generador de ADC pide un patrón de tensión trazable |
| Cuantificar la mejora de la integral | `autoscale_q_shift()` lleva los dos estimadores a la misma escala; los puntos con FWHM < 3 canales se marcan no comparables | medir en placa |
| FOM vs energía | segundo estímulo con amplitud variable + `autoscale_h2_shift()`; las rebanadas sin estadística se dicen como tales | medir en placa |
| **Todo con pulsos de detector reales** | el estímulo ya está en la escala correcta | el detector |

**Antes de re-medir**: correr `sweep_baseline_k` primero. `bl_k` y `cfg_maxlen`
dependen de la duración del pulso, y los valores de esta campaña están
calibrados para 336 µs. `run_campana.py` ya lo hace en ese orden y propaga el
resultado.

Los cambios están verificados sin hardware por
[`../software/tests/test_wave_builders.py`](../software/tests/test_wave_builders.py):
que el ancho y la tasa del estímulo son los pedidos, que las combinaciones
imposibles fallan con un mensaje que dice qué ajustar, y que `dnl()` recupera
una DNL inyectada del 3 % sobre una envolvente no plana (contra la media global
el mismo espectro da 19.5 %).

El método de cada test, y cuáles de sus resultados son creíbles, está en
[`testbenches_software_mca.md`](mca/testbenches_software_mca.md).

---

## 12. Cómo reproducir

```bash
# en la placa
cd /home/jupyter/RedPitaya/remote_soft/mca
/opt/redpitaya/bin/fpgautil -b ./mca_red_pitaya.bit.bin
python3 test_mca_hw.py                       # smoke test, sin generador
python3 run_campana.py datos/mca_$(date +%Y%m%d_%H%M%S)
```

Para volver al bitstream del scope:
`fpgautil -b /root/multitriger_0.2/red_pitaya_top.bit.bin`

Si algo no cuenta nada, el orden de sospecha es: (1) `bl_k` demasiado chico
(§4), (2) `cfg_maxlen` demasiado chico (§5), (3) umbral mal puesto. El registro
de último evento (`0x080`-`0x08C`) y `baseline_now` (`0x024`) dicen enseguida
cuál de los tres es.

---

# 13. Segunda campaña — estímulo corregido

Misma placa y mismo bitstream; lo que cambió es el **estímulo**: `pulse_train_wave()`
fija el ancho del pulso en segundos y despeja la frecuencia de repetición, así
que los pulsos pasaron de **336 µs a 2 µs de FWHM** — la escala de un detector
real. `cfg_maxlen` bajó de 60000 a 4096 en consecuencia.

| | |
|---|---|
| Estímulo | tren de pulsos de **2 µs FWHM**, `pulse_train_wave(width_s, rate_hz)` |
| Config del MCA | `thr=100`, `hyst=40`, base automática `bl_k=12`, `maxlen=4096`, `tail_dly=8` |
| Smoke test previo | **29 PASS / 0 FAIL**, sin reinicios de la placa en toda la campaña |

## 13.1 Throughput: 794 kcps sin perder un evento

**El resultado más importante, y el que refuta el de la primera campaña.**

| Entrada | Salida | Live time |
|---|---|---|
| 182 Hz | 182 cps | 99.5 % |
| 1 995 Hz | 1 995 cps | 99.4 % |
| 21 878 Hz | 21 878 cps | 93.7 % |
| 72 444 Hz | 72 444 cps | 79.1 % |
| 239 883 Hz | 239 884 cps | 63.5 % |
| **794 328 Hz** | **794 331 cps** | **59.9 %** |

El MCA sigue al generador **exacto en todo el rango**, con cero pérdidas y cero
apilamientos. **No se alcanzó el techo**: el límite lo puso el generador, no el
MCA. Del live time sale el tiempo muerto real: 40.1 % de ocupación a 794 kHz →
**~0.5 µs por evento** (el ajuste no paralizable da 0.37 µs), contra los 2.3 µs
que decía la primera campaña.

> El punto de 100 Hz queda **inválido**: el DG4162 impone un ciclo de trabajo
> mínimo de ~0.3125 %, así que a 100 Hz entrega pulsos de **31 µs** en vez de los
> 2 µs pedidos, y todos cierran por `maxlen`. Se ve en la columna de ancho leído.

### Corrimiento del centroide con la tasa: +1.28 %, no +6.45 %

El barrido completo da +6.45 % entre el primer y el último punto, y **ése es el
número que NO hay que citar**: está confundido con el ancho de pulso. Como
`set_pulse_periodic` exige `width < T/2`, el barrido escala el ancho a
`min(2 µs, 0.2·T)`, así que arriba de 72 kHz el estímulo deja de ser el mismo.

| Tramo | Ancho | Corrimiento |
|---|---|---|
| barrido completo, 182 Hz → 794 kHz | 17 µs → 252 ns | +6.45 % |
| **1995 → 72 444 Hz (×36)** | **2000 ns fijo** | **+1.28 %** |
| 72 → 132 kHz (un solo paso) | 2000 → 1517 ns | **+2.52 %** |

El salto grande cae **exactamente donde cambia el ancho**, no donde cambia la
tasa. Con estímulo constante el corrimiento genuino es **+1.28 % sobre ×36 de
tasa**: real, pero cinco veces menor de lo que decía la primera versión de este
documento. Importa porque es el argumento principal del conformado trapezoidal
(§13.6).

## 13.2 Resolución par-pulso: ≤ 0.5 µs

Con ancho y período de burst **fijos** y normalizando contra la medición a gap
máximo, la fracción detectada da **1.00 en todos los gaps de 0.5 a 100 µs**: los
dos pulsos del par se cuentan como dos incluso separados 500 ns. Es coherente con
el tiempo muerto de §13.1 y con la resolución par-pulso del scope (~25 ns, ver
[`testbenches_software_multitrigger.md`](multitrigger/testbenches_software_multitrigger.md)).

Por debajo de 9 µs aparecen eventos perdidos por extractor ocupado (~46 % de los
que llegan) **sin que baje la fracción detectada**: son cruces de umbral extra
—ringing de los flancos de 200 ns— que caen mientras el extractor está ocupado.
Se cuentan en `cnt_dropped` y no contaminan el histograma.

## 13.3 FOM: 1.53 global, y por primera vez vs energía

Dos estímulos distintos, como corresponde:

- **misma amplitud, colas distintas** (`tau_choices=(1, 3)`) → **FOM = 1.532**,
  por encima del 1.27 de buena separación. Cualquier separación viene del eje de
  forma, porque el de amplitud no se mueve.
- **amplitud variable además de la cola**, con `h2_shift` auto-escalado de 7 a 4:

  | Rebanada de amplitud | FOM | cuentas |
  |---|---|---|
  | [32, 64) | 1.306 | 360 253 |
  | [64, 96) | 1.497 | 660 792 |
  | [96, 128) | **1.579** | 480 493 |

  **La separación se degrada a baja energía**, que es el comportamiento
  esperado y que la primera campaña no pudo ver (daba `nan` en 3 de 4
  rebanadas porque todos los eventos caían en una sola).

## 13.4 Linealidad: la INL es sistemática, y es del conjunto

Ganancia **3927 canales/Vpp**, offset de cero **−28 canales**, **INL 1.13 % FS**.

La pasada de ida y vuelta responde la pregunta que quedó abierta: la correlación
entre los residuos de las dos pasadas es **+1.00** y la dispersión entre ellas
(0.16 canales) es 150× menor que el residuo (23.4 canales). O sea que la INL
**es un desvío sistemático real y no la estadística del ajuste**.

Lo que la ida y vuelta **no** puede decir es cuál de los dos instrumentos lo
aporta: sigue siendo la INL del conjunto generador + ADC. Separarlos pide una
referencia de tensión trazable.

## 13.5 Umbral: LLD 777, piso de ruido en 57 cuentas

Meseta limpia de 2000 cps, corte en 777 cuentas, y **ningún punto del barrido
dominado por ruido** (0 de 26, contra la primera campaña donde `thr=20` disparaba
a 262 kcps). Con la entrada abierta, el umbral mínimo sin disparos espurios es
**57 cuentas**.

## 13.6 Pico vs integral: la integral es PEOR, y se entiende por qué

Con `q_shift` auto-escalado para que los dos estimadores caigan en la misma
escala de canales:

| Ancho | Resolución con pico | Resolución con integral |
|---|---|---|
| 0.5 µs | **0.44 %** | 0.54 % |
| 1 µs | **0.37 %** | 0.53 % |
| 2 µs | **0.34 %** | 0.53 % |
| 4 µs | **0.33 %** | 1.15 % |

**Es lo contrario de lo que esperaba el diseño** ([`decisiones_diseno_mca.md`](mca/decisiones_diseno_mca.md) §5).
La razón es que la integral gana cuando el estimador de pico sufre *jitter de
muestreo*, y acá no sufre: un pulso de 2 µs son **250 muestras a 125 MSPS**, así
que la muestra de pico cae prácticamente en el máximo verdadero. La integral, en
cambio, acumula el error de línea de base sobre toda la ventana y hereda el
jitter del cierre de la ventana.

La tendencia confirma el mecanismo: al acortar el pulso de 4 µs a 0.5 µs la
resolución con pico **empeora** (0.33 → 0.44 %) mientras la de la integral se
mantiene. Se cruzarían por debajo de ~0.2 µs, que es donde el ARB ya no llega.

### …y por qué la integral perdía: era la VENTANA, no la integral

El análisis offline sobre 7054 pulsos crudos
([`../../software/tests/estimadores/`](../software/tests/estimadores/))
cierra la pregunta, calculando todos los estimadores **sobre los mismos pulsos**:

| Estimador | Resolución |
|---|---|
| integral, ventana por histéresis | 0.528 % *(medido en placa)* |
| pico | 0.272 % *(réplica; placa 0.344 %)* |
| trapecio (k=192, m=160) | 0.212 % |
| **integral, compuerta FIJA de 384 muestras** | **0.149 %** |

Con compuerta de largo fijo la carga mejora **1.83× sobre el pico** dentro de
este bloque. El "3.55× sobre la integral con histéresis" que decía acá **está
retirado**: usa como referencia el 0.528 % de arriba, y al re-medir la histéresis
en placa en las mismas condiciones da 0.325 %, así que la mejora real es **×2.02**
([§14.2](#142-lo-que-confirma-del-análisis-offline)). La causa del problema quedó identificada: el
RTL cierra la ventana donde la cola cruza `thr − hyst`, que es la zona **más
chata** del pulso — con τ = 186 muestras y σ = 2.8 cuentas de ruido el cruce
tiembla ~9 muestras, y cada muestra vale ~60 cuentas de carga.

La réplica se valida contra el hardware por la σ **en cuentas**: da 2.78 y la
placa midió 2.81, 1 % de acuerdo. (La resolución en % difiere sólo porque la
amplitud de ese conjunto es 2410 cuentas y la de la campaña 1920.)

**El trapecio queda por debajo de la compuerta fija** y costaría la mitad del
throughput, así que con esta señal no se justifica.

## 13.7 DNL: no se puede medir con este generador

El estímulo ya no produce líneas discretas (0 canales vacíos en la ventana,
contra 40 de 212 en la primera campaña), y el resultado es **DNL rms 26.5 %**
con 20 437 cuentas/canal. Pero ese número **no es del MCA**:

- piso de Poisson: **0.70 %** (no es el que manda);
- piso por **discretización del estímulo**: con 1500 amplitudes distintas
  repartidas sobre 71 canales son 21 por canal, y ese reparto fluctúa como
  1/√21 = **21.8 %**.

Los 26.5 % medidos están en ese piso, así que son una **cota superior**. Bajarla
a 1 % pediría ~710 000 amplitudes distintas: inalcanzable recargando el ARB
(0.6 s por recarga). Hace falta **modulación analógica de amplitud**, y este
firmware (00.01.05) **no la soporta por SCPI**: `:SOURce1:MOD:STATe ON` responde
`-113, "Undefined header"`, igual que `:DATA:CATenate`. Queda como pendiente
hacerlo desde el panel frontal del generador.

## 13.8 Dos trampas del instrumento que hay que conocer

Las dos costaron tiempo y las dos están ahora detectadas por el código.

**1. El generador informa una frecuencia y emite otra.** Tras ciertas secuencias
de comandos, el DG4162 acepta `APPLy:PULSe`, contesta la frecuencia nueva en
`:FREQuency?` … y sigue emitiendo a la anterior. Medido: pidiendo 1 kHz y 10 kHz
contestaba 1000 y 10000 mientras el MCA contaba 100 eventos/s con la amplitud
correcta. **Así se generó la tabla de la primera campaña**: 100 cps constantes
que se leyeron como seguimiento exacto.

No pude aislar el disparador —aislado siempre funciona; encadenado detrás de
`sweep_amplitude` + `test_pulse_pair` falla; `*RST` no lo limpia y de hecho lo
provoca—, así que `sweep_rate` ahora **lo detecta** con un criterio físico:

> si el MCA no perdió **ni un** evento, entonces `total/realtime` **es** la tasa
> de entrada verdadera; que difiera de la pedida sólo puede significar que el
> generador no está entregando lo que se le pidió.

Esos puntos se marcan `INVÁLIDO` y se excluyen del análisis. **Workaround:**
correr cada test en su propio proceso (`python3 testbench_mca.py <test>`).

**2. La cola de errores SCPI es FIFO y `assert_ok` saca uno solo.** `set_am_noise`
manda 5 comandos y este firmware los rechaza todos; los 4 errores que quedaban
se los atribuía el siguiente `assert_ok` a un `load_arb` que había funcionado
bien. Lo arregla `RigolDG4162.clear_errors()`, que vacía la cola.

## 13.9 Lo que queda pendiente

| Pendiente | Por qué |
|---|---|
| DNL de verdad | pide modulación analógica de amplitud, no disponible por SCPI (§13.7) |
| Techo real de throughput | el generador se quedó sin rango a 794 kcps; el MCA no |
| Separar la INL del generador | **parcialmente resuelto y medido** (2026-08-14): `formas_inl` separa la parte que depende de la FORMA del pulso (cadena de medición) de la común-modo (generador + INL estática del ADC) — ver §13.11. Separar generador de ADC dentro del común-modo sigue pidiendo una referencia de tensión trazable (§13.4) |
| Aislar la trampa del generador | detectada y evitada, pero no explicada (§13.8) |
| **Todo con pulsos de detector reales** | el estímulo ya está en la escala correcta; falta el detector |

## 13.10 Cómo reproducir

```bash
# en la placa, un test por proceso (ver §13.8)
cd /home/jupyter/RedPitaya/remote_soft/mca
OUT=datos/mca_$(date +%Y%m%d_%H%M%S)
python3 test_mca_hw.py                          # smoke test, sin generador
python3 run_campana.py $OUT                     # baseline_k PRIMERO, luego el resto
for t in sweep_amplitude pulse_pair sweep_rate sweep_threshold psd_fom; do
    python3 testbench_mca.py $t --outdir $OUT
done
python3 run_dnl.py $OUT
```

`sweep_baseline_k` va primero siempre: `bl_k` y `cfg_maxlen` dependen de cuánto
dura el pulso. (En esta campaña dio lo mismo para `bl_k` de 3 a 18 — el
seguidor se congela durante el pulso, así que no lo persigue.)

## 13.11 INL vs forma del pulso — medido 2026-08-14

Datos en
[`../software/datos/formas_20260814_203920/`](../software/datos/formas_20260814_203920/)
(`formas_inl.npz`, `resumen_formas.json`, `campana.log`, las dos figuras).
12 amplitudes de 0.1 a 1.0 Vpp, 3 s por punto, ida y vuelta, 2 µs de FWHM a
2 kHz, `bl_k=12`, `thr=100`, `gate_mode=0` (histéresis).

§13.4 dejó la INL en **1.13 % FS, sistemática**, y la pregunta abierta de a
quién pertenece. La ida y vuelta separa *sistemático de estadístico*; no separa
*generador de MCA*. `sweep_formas_inl` ataca la separación por otro lado: mide
la misma curva con las familias de conformado de Knoll, todas con el mismo FWHM
y la misma altura de pico. Como el error de consigna del DG4162 es idéntico para
todas las formas, el residuo **común** es del generador (+ INL estática del ADC)
y el **diferencial** es de la cadena de medición.

**Cordura primero**: `cr_rc` dio **3927.4 canales/Vpp** contra los 3927.50 de
§13.4, y offset −27.5 contra −28.0. El barrido reproduce la campaña publicada.

### El resultado

| | estimador de **pico** | estimador de **carga** |
|---|---|---|
| ganancia relativa entre familias | 0.9957 – 1.0021 (**±0.2 %**) | 0.922 – 1.186 (**±19 %**) |
| INL por familia | 1.04 – 1.09 % FS | 0.38 – 0.93 % FS |
| residuo **común** | 9.69 mV | 6.54 mV |
| residuo **diferencial** | **0.57 mV** | **3.10 mV** |
| correlación mínima entre familias | **+0.997** | +0.937 |
| piso efectivo (deriva de la campaña) | 0.43 mV | 0.43 mV |
| diferencial / piso | 1.4× | 7.3× |

**Con el estimador de pico la determinación de amplitud es robusta frente a la
forma.** Las cinco familias medidas dan la misma ganancia dentro de ±0.2 % y sus
curvas de INL son indistinguibles (correlación +0.997); en `inl_formas.png` se
superponen sobre la línea de común-modo. O sea que el 1.13 % FS de §13.4 **no
sale de cómo el MCA determina la amplitud**: es del generador y/o de la INL
estática del ADC.

**Con el estimador de carga, no.** La ganancia se mueve un ±19 % siguiendo el
factor de forma —eso es geometría esperada, ver abajo— pero además el residuo
diferencial (3.10 mV) es **la mitad del residuo total**, siete veces el piso.
La INL del estimador de carga medida con una sola forma no es representativa.

> **Cuidado con el número del pico.** Los 0.57 mV de diferencial superan por
> sólo **1.4×** el piso de 0.43 mV que impone la deriva de la campaña (medida
> por la réplica de cierre, ver abajo). Es una **cota superior** de la
> dependencia con la forma, no una medición de ella. Para bajarla hay que bajar
> la deriva: campaña más corta, o familias intercaladas en vez de en bloque.
> (El piso de la ida y vuelta, 0.013–0.027 mV, es 20 veces más chico y no es el
> que manda: la ida y vuelta es rápida y no ve la deriva lenta.)

### Por qué el estimador de carga depende de la forma

Con `gate_mode=0` la ventana de integración cierra por **histéresis**, así que
su largo depende de dónde el pulso cruza `thr − hyst` — que es función de la
forma *y* crece con la amplitud. Es el mismo efecto que documenta §14 para la
resolución. La consecuencia acá es que la fracción de cola integrada varía con
la amplitud de manera distinta según la familia, y eso es exactamente una no
linealidad dependiente de la forma.

**Es una predicción falsable y barata de probar**: el RTL ya soporta
`gate_mode=1` (compuertas de largo fijo desde el disparo, inmunes al jitter del
instante de pico). Si la explicación es correcta, repetir el barrido con
compuerta fija tiene que **colapsar el diferencial de 3.10 mV**. Sin medir.

### Control nulo y verificación cruzada

- **Réplica de cierre** (`cr_rc` re-medida al final, ~18 min después): ganancia
  +0.07 %, deriva de residuo 0.43 mV. Es el piso que se usa arriba.
- **Pico vs carga** (`pico_vs_carga.png`), el único test de linealidad que no
  depende de la exactitud del generador: la pendiente relativa medida reproduce
  el factor de forma **calculado de la geometría** con un error de −2.1 % a
  +2.5 % en las cinco familias. Confirma que el eje de carga está bien escalado
  y que los `q_shift` por familia se deshacen bien.

### La bipolar no es medible con esta configuración

`bipolar` (CR-RC-CR, doble diferenciación) **no pasó el pre-vuelo**: **4004
eventos contra 2002 esperados (200 %) y 50 % de apilamiento**. El MCA cuenta
**dos eventos por cada pulso emitido**.

Hipótesis, coherente con el RTL pero **no verificada**: el seguidor de línea de
base se descongela al cerrar el lóbulo positivo, persigue el lóbulo negativo y
arrastra la base hacia abajo; cuando la señal vuelve a cero, la diferencia
contra esa base deprimida vuelve a cruzar el umbral y dispara un segundo evento.
Es el problema clásico de restaurador de línea de base con conformado bipolar
(Knoll cap. 16). Se puede discriminar con `bl_auto=False` y `baseline` fijo: si
el doble conteo desaparece, era el seguidor.

Que no sea medible **es** un resultado sobre robustez, y la guarda del pre-vuelo
hizo lo suyo — lo detectó y siguió con el resto en vez de guardar una curva de
INL sin sentido.

### Lo que sigue sin resolver

Generador e INL estática del ADC son los dos común-modo, así que este
experimento **no los separa entre sí**. Eso sigue pidiendo un patrón de tensión
trazable.

```bash
# en la placa, ~20 min
python3 run_formas.py datos/formas_$(date +%Y%m%d_%H%M%S)
# re-analizar y re-graficar en la PC, sin hardware:
python3 run_formas.py datos/formas_20260814_203920 --plot-only
```

---

# 14. Etapa B — compuertas de largo fijo, medidas en placa

Misma placa y mismo estímulo (2 µs FWHM a 2 kHz). Bitstream
`v2b_compuertas_pileup_fix`, que agrega `cfg_gate_mode` (`0x048`) y
`cfg_gate_len` (`0x04C`).

## 14.1 El resultado

| Compuerta larga | Resolución |
|---|---|
| ventana por **histéresis** (referencia) | **0.325 %** |
| 128 muestras | 0.812 % |
| 192 | 0.353 % |
| 256 | 0.211 % |
| 320 | 0.167 % |
| **384** | **0.161 %** ← mínimo |
| 448 | 0.174 % |
| 512 | 0.183 % |

**La compuerta fija mejora ×2.02 sobre la ventana por histéresis**, con cero
apilamiento en todo el rango. La curva tiene un mínimo claro: por debajo de 320
se pierde carga de la cola, por encima de 448 se integra ruido de más.

![Resolución vs largo de compuerta](../software/datos/mca_gate_20260530_023829/sweep_gate.png)

**Ojo con lo que este número NO dice: está medido en UN solo punto del
espectro**, la amplitud del estímulo (0.5 Vpp). Que la compuerta fija mejore
×2.02 ahí no implica que mejore lo mismo en todo el rango de energías, y hay un
motivo concreto para esperar que *no* sea parejo: con histéresis el largo de la
ventana lo fija dónde la cola cruza `thr − hyst`, y ese punto **se corre con la
amplitud** (un pulso más grande tarda más en bajar), así que el largo de
integración crece con la energía. Con compuerta fija no depende de la amplitud
por construcción. Los dos modos tienen entonces distinta ganancia y, muy
probablemente, distinta linealidad.

Eso se midió, y está en §14.1b.

## 14.1b Los dos modos a lo largo del espectro

`sweep_gate_espectro`: 12 amplitudes de 0.1 a 1.0 Vpp, los dos modos
**intercalados en cada punto** (para que cualquier deriva del generador les
pegue a los dos por igual), `q_shift = 7` fijo en los dos, compuerta de 384.
Datos en [`../software/datos/mca_gate_esp_v2/`](../software/datos/mca_gate_esp_v2/).

![FWHM de los dos modos a lo largo del espectro](../software/datos/mca_gate_esp_v2/gate_espectro.png)

El FWHM está **referido a la entrada** (dividido por la ganancia de cada modo:
8619 y 7425 canales/Vpp). Hay que hacerlo: los dos modos integran distinta
cantidad de muestras, así que tienen distinta ganancia y compararlos en canales
crudos no significa nada.

| Amplitud | FWHM histéresis | FWHM compuerta | Mejora |
|---|---|---|---|
| 0.100 Vpp | 1.335 mV | 0.774 mV | ×1.73 |
| 0.264 | 1.458 | 0.734 | **×1.99** |
| 0.345 | 1.615 | 0.775 | **×2.08** |
| 0.509 | 1.558 | 0.812 | ×1.92 |
| 0.755 | 1.631 | 0.914 | ×1.78 |
| 1.000 | 1.676 | 1.059 | ×1.58 |

**La compuerta gana en todo el rango: ×1.58 a ×2.13, mediana ×1.91.** No hay
ninguna energía donde la histéresis sea mejor. El ×2.02 de §14.1 no era un punto
afortunado: es el valor típico.

**Pero la mejora NO es pareja, y se degrada hacia arriba.** El FWHM de la
compuerta crece 37 % de punta a punta (0.774 → 1.059 mV) mientras el de la
histéresis crece 26 % (1.335 → 1.676 mV): las dos curvas convergen despacio. O
sea que **la ventaja de la compuerta fija es mayor a energía baja**, que es
justo donde más se necesita.

Lo que también se ve es que **ninguno de los dos estimadores tiene un FWHM
proporcional a la energía**: los dos son casi planos en mV sobre una década de
amplitud. Eso dice que el término dominante es **aditivo** (ruido de la cadena y
error de línea de base), no proporcional a la carga — y es la razón de que la
resolución en % caiga como 1/E en el panel de abajo, de 1.5 % a 0.17 %.

### La linealidad salió al revés de lo que yo esperaba

Predije que la histéresis sería el modo menos lineal, porque su ventana se
alarga con la amplitud. **La ganancia local le da la razón a esa predicción,
pero la INL del ajuste global no:**

| | ganancia local | INL |
|---|---|---|
| histéresis | 7690 → 8558 c/Vpp (**11.3 % de variación**) | 0.563 % FS |
| compuerta fija | 7305 → 7455 c/Vpp (**2.1 %**) | 0.970 % FS |

La compuerta fija es **5× más estable en ganancia**, exactamente como predecía
el argumento. Que su INL dé peor **no lo contradice: mide otra cosa**. La INL es
el residuo máximo contra una recta global, y la histéresis se curva *suave y
monótona* —una recta le pasa por el medio con residuo moderado— mientras que la
compuerta es casi plana pero con una ondulación no monótona que la recta no
sigue.

**No sé cuál de las dos ondulaciones es del MCA y cuál del generador**, y con
este montaje no se puede separar: la INL medida es la del conjunto
generador+ADC+MCA (§13.4 llegó a lo mismo por otro camino). Lo único que
sostengo de acá es la ganancia local, que es una comparación entre modos con el
*mismo* generador y por lo tanto inmune a su error.

### El punto que hubo que tirar

La primera corrida usó `target_channel = 12000` y a 1.0 Vpp el pico de
histéresis quedó en el canal 16376 de 16384: **la cola derecha se salía del
histograma**, el ajuste vio una gaussiana cortada y devolvió FWHM 17.89 cuando
la tendencia pedía ~24. Ese punto aparecía como **el mejor de todo el barrido**
justo donde el instrumento se estaba quedando sin escala.

`_medir()` ahora rechaza el punto si `centroide + 2·FWHM` se pasa del último
canal, y lo dice. Es la misma disciplina que el resto de la suite: el test tiene
que *rechazar* el resultado cuando el estímulo no da, no imprimir un número
lindo.

## 14.2 Lo que confirma del análisis offline

La predicción de [`../software/tests/estimadores/`](../software/tests/estimadores/),
hecha sobre 7054 pulsos crudos **sin tocar la placa**, era:

| | offline | en placa |
|---|---|---|
| compuerta óptima | 384 muestras | **384 muestras** |
| resolución en el óptimo | 0.149 % | **0.161 %** (8 % de diferencia) |

Acertó el largo óptimo **exacto** y la resolución dentro del 8 %. Es la
validación de que el método offline sirve para decidir cambios de RTL antes de
gastar una síntesis.

**La ganancia sí quedó por debajo de lo anunciado: ×2.02 y no ×3.5.** El motivo
es la referencia, no la compuerta: el ×3.5 se calculó contra el 0.528 % de la
integral por histéresis de la 2ª campaña, y al medirlo de nuevo en las mismas
condiciones la histéresis da 0.325 %. La compuerta llegó a donde se predijo; la
referencia estaba peor medida.

## 14.3 El bug que encontró medir en placa

La primera versión marcaba apilamiento así: *si al cerrar la compuerta la señal
sigue por encima de `thr − hyst`, el evento está contaminado*. Es incorrecto: la
cola del **propio** pulso tarda ~700 muestras en bajar de 60 cuentas, así que
descartaba el **100 % de los eventos** con cualquier compuerta más corta que la
cola — justo el rango útil.

| compuerta | apilamiento (regla vieja) |
|---|---|
| 128 a 640 | **100 %** |
| 768, 1024 | 0 % |

Y no era ni reproducible: el punto de cruce cae en la parte más chata del pulso,
así que se movía cientos de muestras con cualquier deriva de línea de base. Una
corrida dio 0.260 % con compuerta 384 y la siguiente no dio ningún evento.

**La regla correcta** es que apilamiento significa un **segundo pulso dentro de
la compuerta**: la señal bajó de `thr − hyst` y **volvió a cruzar** `thr` con la
ventana abierta. Con eso el apilamiento da 0 % en todo el rango, como debe ser
con un generador que entrega un pulso por período.

Sólo se podía encontrar midiendo: en simulación los pulsos son rectangulares y
la cola no existe.

## 14.4 Timing

| | v1 (histéresis) | v2 (compuertas) | v2b (regla corregida) |
|---|---|---|---|
| WNS | −0.114 ns | −0.027 ns | **−0.294 ns** |
| TNS | −0.570 | −0.372 | −4.195 |
| Endpoints | 14 | 22 | 49 |
| Slice LUTs | 5841 | 5874 | 5884 |

**El timing empeoró y no está explicado.** El cono de lógica que agrega v2b es
más *chico* que el de v2 (`gate_2nd` es un registro; antes era una comparación
de 15 bits), así que lo más probable es varianza de emplazamiento — pero no se
verificó con otra semilla.

El peor camino sigue siendo el mismo de siempre:
`i_mca/i_feat/q_tot_reg[29]` → desplazador por `cfg_q_shift` → ventana de
amplitud → `cnt_rej_amp_o/CE`. La solución limpia es partir el cierre en dos
ciclos (un estado `S_CLOSE` que evalúe la amplitud con valores ya registrados),
a costa de 1 ciclo de tiempo muerto por evento sobre los ~50 que ya hay.

Con −0.294 ns sobre un período de 8 ns (3.7 %) la placa funciona —el smoke test
da 29/29 y el conteo de eventos es exacto—, pero **es un bitstream que no
debería quedar como definitivo** sin resolver eso.

## 14.5 Qué queda

| Pendiente | Por qué |
|---|---|
| Arreglar el camino crítico | −0.294 ns; probar primero con otra semilla, y si persiste partir el cierre en dos ciclos |
| Separar la INL del generador de la del MCA | la ondulación de ganancia de §14.1b no se puede atribuir sin un patrón de tensión mejor que el DG4162 |
| Medir la FOM con compuertas fijas | es el método estándar de PSD y esta es su aplicación real; sólo se midió la resolución en amplitud |
| Re-medir el throughput | la compuerta fija acota la ventana, así que el tiempo muerto por evento debería bajar |
| `gate_short` sin barrer | se dejó fijo en 32 muestras; el eje de forma depende de él |
| **Campaña de amplitud con muchos más puntos** | §15.3: con 12 amplitudes el error leave-one-out (0.24 % FS) es peor que cualquier tabla de calibración, hasta con 8 nodos. La tabla no es el cuello de botella, la campaña sí |

---

# 15. Linealización del eje en software — 2026-08-15

Fase 0 de la expansión del MCA: antes de gastar una síntesis en una tabla de
calibración, contestar en software si la corrección sirve y de qué tamaño tiene
que ser la tabla. Todo offline, sobre datos ya medidos.

Implementación en [`software/mca_utils.py`](../software/mca_utils.py) (sección
*Linealización del eje de amplitud*) y verificación en
[`software/tests/test_linealizacion.py`](../software/tests/test_linealizacion.py).

## 15.1 El modelo y la condición de inversión

Con `Â = G·A + INL(A)`, recuperar `A` a partir de `Â` exige que el mapa sea
estrictamente creciente:

    dÂ/dA = G + dINL/dA > 0     ⟺     min(dINL/dA) > −G

Lo que se reporta es el **margen** `G + min(dINL/dA)`, no un booleano: un margen
chico dice que la inversión existe pero es frágil.

| Modo | G (canales/Vpp) | min dINL/dA | Margen | Margen / G |
|---|---|---|---|---|
| Histéresis | 8619 | −276.4 | 8342.6 | **96.8 %** |
| Compuerta fija | 7425 | −261.4 | 7163.7 | **96.5 %** |

El eje está **muy lejos** de plegarse: la INL medida usa menos del 4 % del
margen disponible. La preocupación de que dos regiones no conexas de energía
cayeran en el mismo canal no aplica en este régimen, y ahora es un número y no
una opinión.

## 15.2 Corregir el espectro no es renombrar los canales

Si el mapa estira una zona y comprime otra, las **alturas** del histograma
también cambian. Corregir sólo las etiquetas deja los picos en el lugar correcto
con el área equivocada, y fabrica una DNL falsa.

`linearize_spectrum()` hace **rebinning por bordes**: pasa los bordes enteros del
espectro medido por el mapa, interpola la cuenta acumulada en la grilla destino,
y diferencia. Conserva las cuentas **exactamente** (verificado a `< 1e-9`
relativo) y absorbe el jacobiano sin derivar nada — la fórmula puntual
`N(A) = N̂(g(A))·g'(A)` obliga a derivar un interpolante construido sobre datos
ruidosos y encima no conserva las cuentas sobre una grilla discreta.

El peine de DNL que introduce el rebinning, **medido y no supuesto**, sobre un
espectro plano de 16384 canales: **0.34 % rms** (histéresis) y **0.40 % rms**
(compuerta), con máximos de 2.6 y 2.9 %. Es el costo de linealizar y es chico
porque se corrige con 16 bits sobre un eje de 14.

## 15.3 El resultado que cambia la conclusión: el cuello de botella es la campaña, no la tabla

La primera versión del test medía la INL sobre los mismos 12 puntos con que se
construyó la calibración, y daba **0.0000 % FS**. Es circular: la corrección
devuelve la recta por construcción. La pregunta útil es si la calibración
**generaliza**, y eso se contesta con *leave-one-out* — calibrar sin un punto y
ver cuánto erra al predecirlo.

| Modo | INL cruda | Error leave-one-out (interior) |
|---|---|---|
| Histéresis | 0.563 % FS | **0.238 % FS** (18.6 canales) |
| Compuerta fija | 0.970 % FS | **0.260 % FS** (17.4 canales) |

O sea que la calibración saca entre la mitad y las tres cuartas partes de la
INL, no toda. Lo que queda **no es un límite de la corrección: es que 12 puntos
no determinan la curva**.

Eso se ve todavía más claro en la predicción de INL residual contra número de
nodos de la LUT, que era el entregable que tenía que dimensionar el hardware:

| Nodos | INL residual, histéresis | INL residual, compuerta |
|---|---|---|
| 8 | 0.185 % FS | 0.201 % FS |
| 16 | 0.086 % FS | 0.094 % FS |
| 32 | 0.033 % FS | 0.036 % FS |
| 64 | 0.011 % FS | 0.010 % FS |
| 128 | 0.006 % FS | 0.007 % FS |
| 256 | 0.004 % FS | 0.004 % FS |

**Todos los tamaños de tabla, incluso 8 nodos, quedan por debajo del error
leave-one-out de 0.24 %.** El tamaño de la LUT no es el factor limitante — ni
siquiera de cerca. Con 12 amplitudes medidas, una tabla de 8 nodos ya es más
fina que lo que la campaña puede determinar.

**Conclusión para la fase 4:** el trabajo no es elegir entre 64 y 128 nodos, es
**medir muchas más amplitudes**. Sin una campaña con decenas de puntos —y sin
separar antes la INL del generador de la del MCA (§14.5)— cualquier tabla que se
grabe está ajustando ruido de calibración.

## 15.4 Una calibración no significa lo mismo para cada feature

Verificado sobre 2048 ventanas de pulso reales de
`datos/e2e_20260528_013404/principal/`, replayando las réplicas bit-exactas del
RTL de [`tests/estimadores/`](../software/tests/estimadores/):

Con una corrección **en el dominio de muestra** `x → f(x)` monótona creciente:

- **Pico**: `max(f(x)) = f(max(x))` **exactamente** — error máximo `0.00e+00`
  sobre los 2048 pulsos. El máximo conmuta con `f`, así que calibrar la muestra
  y calibrar la feature son la misma cosa.
- **Integral**: `Σf(xₙ) ≠ f(Σxₙ)`. Medido: la misma `f` escala el pico ×1.0452 y
  la integral ×1.0466. **No existe ningún mapa escalar** `Q → Q'`: es un
  funcional de la forma entera del pulso, y la única forma de obtenerlo es
  replayar.
- **Cocientes**: una ganancia se cancela; un offset no.

Por eso la corrección de la fase 4 va sobre la feature tal como se mide, sin
pretender representar ninguna `f(x)` de muestra.

## 15.5 Cómo reproducir

```bash
cd prj/MCA/software
python3 tests/test_linealizacion.py       # 6 bloques, no necesita placa
```

Los tests 5 y 6 se saltean con aviso si no están los `.npz` de `datos/`.
El bloque 4 comprueba que un eje **plegado** (INL con pendiente `< −G`) haga
fallar a `apply_calibration` y `linearize_spectrum` con un mensaje explícito, en
vez de devolver un número — el mismo criterio de aceptación de toda la campaña.

---

# 16. Comparación con MCAs comerciales

Tres instrumentos de referencia, con las cifras tomadas de sus hojas de datos
(enlaces al pie). Los tres son la competencia real de este diseño: **DSPEC 50** y
**Lynx II** hacen el procesamiento digital completo desde el ADC, como éste;
el **MCA8000D** es un MCA puro que va detrás de un amplificador conformador
analógico.

## 16.1 El cuadro

| | **Este MCA** | ORTEC DSPEC 50/50A | Mirion Lynx II | Amptek MCA8000D |
|---|---|---|---|---|
| Canales | 16384 (+ zoom ×2ⁿ) | 256 – 64k | 256 – 32768 (×2 grupos) | 256 – 8k |
| Cuentas por canal | **2³²−1 = 4.3·10⁹** | — | — | 16.7·10⁶ (3 bytes) |
| ADC | 14 bit / 125 MSPS | — | — | 16 bit / 100 MHz |
| **INL** | **1.13 % FS** (ajuste global)<br>**0.028 % FS** en 0.1–0.62 Vpp | <±0.025 % (top 99.5 %) | <±0.025 % FS (top 99 %) | <±0.02 % FS |
| **DNL** | **no medible** con este generador (cota 26.5 %)<br>del binado digital: **0 exacto** | <±1 % (top 99 %) | <±1 % (top 99 %, incl. INL) | <±0.6 % (15 mV a FS) |
| Linealización | ninguna (estudiada en §15) | estabilizador digital | estabilizador digital | *sliding scale* |
| **Throughput** | **794 kcps sin perder un evento**, techo no alcanzado | >100 000 cps (LFR off) | — | — |
| Tiempo muerto/evento | ~0.4 – 0.5 µs | — | — | conversión 10 ns |
| Resolución par-pulso | **≤ 0.5 µs** | — | <500 ns (NORM) | peaking mín. 500 ns |
| Deriva de ganancia | **+1.28 % sobre ×36 de tasa**; térmica **no medida** | <50 ppm/°C (típ. <30) | <35 ppm/°C | ±10 ppm/°C |
| Deriva de cero | no medida | <5 ppm/°C FS | <3 ppm/°C | ±10 ppm/°C |
| Resolución (pulser) | **0.161 %** FWHM/centroide | — | — | — |
| **Precio** | **USD 719** (STEMlab 125-14) + software libre | consultar (sin lista pública) | consultar (sin lista pública) | **USD 3 500** (lista) |
| Incluye HV para el detector | **no** | sí | sí (150–5000 V) | no |
| Incluye conformado analógico | no lo necesita (DSP propio) | no lo necesita | no lo necesita | **no — pide amplificador externo** |

## 16.2 Cómo leer el cuadro (tres comparaciones que NO son justas)

1. **La INL no se mide igual.** La de ellos es una **especificación garantizada**
   del instrumento sobre el 99 % superior del rango. La nuestra es una
   **medición del conjunto generador + ADC + MCA**, y §13.11 ya mostró que la
   parte que le toca al MCA es indistinguible de cero con el estimador de pico.
   El 1.13 % es una **cota superior del conjunto**, no una spec del diseño.
2. **El throughput no se mide con lo mismo.** Los >100 kcps del DSPEC son con
   pulsos de detector reales y tiempos de conformado de µs, donde el límite lo
   pone el filtro trapezoidal. Los 794 kcps de acá son con un tren de 2 µs de un
   generador. Que el número sea 8× mayor dice que **la ruta de datos no es el
   cuello de botella**, no que el instrumento sea 8× mejor en el laboratorio.
3. **La deriva se especifica en otro eje.** Ellos declaran ppm/**°C**
   (estabilidad térmica); acá se midió %/**tasa**. Son dos cosas distintas y la
   térmica de este MCA **no está medida** — es un hueco de la caracterización.
4. **El precio no compra lo mismo.** Los USD 719 son una **placa de desarrollo**:
   sin gabinete, sin fuente de alta tensión para el detector, sin calibración
   trazable, sin garantía de instrumento y sin software de análisis espectral.
   El Lynx II trae una HVPS de 150–5000 V que por sí sola es una fracción
   importante de su precio. La comparación honesta es **"qué cuesta el
   procesamiento digital"**, no "qué cuesta un sistema de espectrometría
   completo". Ver §16.2b.

### 16.2b Qué hay detrás de cada precio

| | Este MCA | DSPEC 50 | Lynx II | MCA8000D |
|---|---|---|---|---|
| Precio | USD 719 | consultar | consultar | USD 3 500 |
| Origen del dato | tienda Red Pitaya | sin lista pública | sin lista pública | lista de precios Amptek |
| Fuente analógica de HV | — | incluida | incluida (150–5000 V) | — |
| Gabinete y fuente | placa desnuda + adaptador | instrumento | instrumento | instrumento de bolsillo |
| Calibración trazable | no | — | — | opción PA (+USD 400) |
| Software de espectrometría | el que escribas | GammaVision | Genie / Apex | DPPMCA (incluido) |
| Soporte y garantía | comunidad | fabricante | fabricante | fabricante |

**ORTEC y Mirion no publican lista de precios** — son venta por cotización y el
número depende de la configuración. Como referencia indicativa **y sólo como
piso**, en el mercado de segunda mano un DSPEC/DSPEC Plus (generación anterior a
la del DSPEC 50) aparece listado entre **USD 1 000 y 1 300**. No es el precio de
un equipo nuevo y no debe citarse como tal.

> **Lo que sí se puede afirmar del precio:** el hardware de este MCA cuesta
> **~1/5 del MCA8000D**, que es el más barato de los tres y encima **necesita un
> amplificador conformador externo** que este diseño no necesita porque hace el
> procesamiento desde el ADC. Lo que no está en el precio es el tiempo de
> ingeniería, el gabinete, la HV y la calibración.

## 16.3 Lo que el cuadro sí dice

**Dónde este diseño está a la par o mejor:**

- **Profundidad de contador**: 4.3·10⁹ cuentas por canal contra los 16.7·10⁶ del
  MCA8000D, 256× más. Nunca es la restricción activa
  ([`limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md) §4).
- **Throughput y tiempo muerto**: no se encontró el techo.
- **Resolución par-pulso**: ≤0.5 µs, igual que el Lynx II.
- **DNL del binado**: exactamente cero por construcción, porque el bin es un
  desplazamiento de un entero. Ellos necesitan *sliding scale* o un estabilizador
  para llegar al ±0.6–1 % porque su cadena tiene una conversión analógica que
  linealizar; acá esa fuente de DNL no existe.
- **Linealidad en el tramo lineal**: 0.028 % FS entre 0.1 y 0.62 Vpp **empata con
  la spec comercial** (±0.025 % de ORTEC y Lynx, ±0.02 % de Amptek) sobre el 60 %
  inferior del rango. Ver la salvedad de §16.2.1.

**Dónde está claramente peor, y es uno solo:**

> **La estabilidad.** Los tres instrumentos comerciales traen un **estabilizador
> digital de espectro** y especifican deriva en ppm/°C. Este MCA no tiene
> estabilizador, no tiene cancelación polo-cero, y su centroide se corre **1.28 %
> con la tasa** — que es **38× la tolerancia** que se deriva en
> [`limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md) §6 y
> **26× la deriva térmica** que declara un DSPEC sobre un ΔT de 10 °C
> (50 ppm/°C × 10 °C = 500 ppm = 0.05 %, contra 12 800 ppm medidos).

Eso ordena la lista de pendientes: no es más resolución ni más canales ni
contadores más anchos. Es **cancelación polo-cero y un pulser de referencia**,
que es exactamente lo que estos instrumentos implementan y este diseño todavía
no.

## 16.4 Fuentes

| Instrumento | Hoja de datos |
|---|---|
| ORTEC DSPEC 50/50A, 502/502A | <https://www.ortec-online.com/-/media/ametekortec/brochures/d/dspec-50-a4.pdf> |
| Mirion (Canberra) Lynx II DSA | <https://318921.fs1.hubspotusercontent-na1.net/hubfs/318921/SPC-249_Lynx-II_FINAL.pdf> |
| Amptek MCA8000D | <https://www.amptek.com/-/media/ametekamptek/documents/resources/products/specs/mca-8000d-digital-multichannel-analyzer-specifications.pdf> |

**Precios:**

| Dato | Fuente |
|---|---|
| MCA8000D USD 3 500 (y opción PA USD 3 900) | lista de precios Amptek, <https://atomfizika.elte.hu/muszerek/Amptek/Amptek-Price-List-June14.pdf> — es la lista pública más reciente que encontré, **de junio de 2014**; conviene pedir cotización actualizada antes de citarla |
| STEMlab 125-14 USD 719 | tienda oficial Red Pitaya, <https://redpitaya.com/product/stemlab-125-14/> (Starter Kit: placa + microSD + fuente + cable) |
| DSPEC 50 / Lynx II | **no publican precio**; venta por cotización |
| DSPEC / DSPEC Plus usados USD 1 000–1 300 | mercado secundario (LabX, SPW Industrial) — generación anterior, **no es precio de equipo nuevo** |

Consultadas el 2026-08-25. Las celdas con "—" son parámetros que el fabricante
no publica en la hoja de datos, no ceros. Los precios de instrumentación nuclear
se mueven y varias de estas listas tienen años: verificá antes de ponerlos en un
informe.

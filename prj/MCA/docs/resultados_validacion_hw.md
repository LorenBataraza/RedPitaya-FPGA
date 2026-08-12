# Resultados de la validación en hardware del MCA

El **por qué** del diseño está en
[`decisiones_diseno_mca.md`](decisiones_diseno_mca.md); acá van los números
medidos y cómo interpretarlos.

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
> | Pico vs integral | "integral ≥60× mejor" | **la integral es 1.3-3.5× PEOR** | la 1ª comparaba escalas distintas |
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
| Pico vs integral | integral **≥60×** mejor | ver la salvedad abajo |
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

Un 0.25 % es un piso instrumental cómodo: para un NaI(Tl) (~7 % FWHM) el aporte
de la electrónica es despreciable; incluso para un HPGe (~0.2 %) queda del mismo
orden, así que ahí sí conviene usar el estimador de integral.

---

## 3. Pico vs integral — la tesis central del diseño

| `t_rise` | FWHM pico | FWHM integral | Resolución pico | Resolución integral |
|---|---|---|---|---|
| 2 muestras | 4.99 | 0.68 | 0.269 % | 0.0041 % |
| 4 muestras | 4.58 | 0.68 | 0.248 % | 0.0041 % |

**Salvedad importante: el "≥60×" es una cota inferior, no la mejora real.** Con
la integral **todos los eventos caen en un único canal**, así que el FWHM medido
(0.68) es sencillamente el piso del binado —el desvío de una distribución
uniforme de un bin, `2.355/√12`— y no una propiedad del estimador. Lo único que
se puede afirmar es que la dispersión de la integral es **menor que un canal**.

Para medir cuánto mejor es de verdad habría que reducir `cfg_q_shift` (más
canales por unidad de carga) hasta que el pico ocupe varios bins.

Aun así, la conclusión de diseño se sostiene y queda verificada en hardware:
**la integral de carga es al menos dos órdenes de magnitud más reproducible que
la muestra de pico**, que es lo que justifica un eje de 16384 canales.

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
[`testbenches_software_mca.md`](testbenches_software_mca.md).

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

## 13.2 Resolución par-pulso: ≤ 0.5 µs

Con ancho y período de burst **fijos** y normalizando contra la medición a gap
máximo, la fracción detectada da **1.00 en todos los gaps de 0.5 a 100 µs**: los
dos pulsos del par se cuentan como dos incluso separados 500 ns. Es coherente con
el tiempo muerto de §13.1 y con la resolución par-pulso del scope (~25 ns, ver
[`testbenches_software_multitrigger.md`](testbenches_software_multitrigger.md)).

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

**Es lo contrario de lo que esperaba el diseño** ([`decisiones_diseno_mca.md`](decisiones_diseno_mca.md) §5).
La razón es que la integral gana cuando el estimador de pico sufre *jitter de
muestreo*, y acá no sufre: un pulso de 2 µs son **250 muestras a 125 MSPS**, así
que la muestra de pico cae prácticamente en el máximo verdadero. La integral, en
cambio, acumula el error de línea de base sobre toda la ventana y hereda el
jitter del cierre de la ventana.

La tendencia confirma el mecanismo: al acortar el pulso de 4 µs a 0.5 µs la
resolución con pico **empeora** (0.33 → 0.44 %) mientras la de la integral se
mantiene. Se cruzarían por debajo de ~0.2 µs, que es donde el ARB ya no llega.
**Con pulsos de detector rápidos la integral puede ganar; con este estímulo, no.**

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
| Separar la INL del generador | pide una referencia de tensión trazable (§13.4) |
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

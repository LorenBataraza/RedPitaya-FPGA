# Fuentes de jitter en la cadena digital

Tenemos una conversión analógico-digital en la base del sistema. La palabra
*jitter* se usa para tres cosas distintas que conviene separar antes de sumar
nada:

1. **Jitter del clock de muestreo** (aleatorio, en ps): el instante real en que
   el ADC toma la muestra no es exactamente `n·Ts`.
2. **Fase de muestreo** (aleatoria pero *no* del clock, en ns): el pulso llega
   asincrónico al clock, así que dónde caen las muestras sobre el pulso es una
   variable uniforme en `[0, Ts)`.
3. **Jitter de estimación** (propagación del ruido de amplitud a tiempo, o de
   tiempo a amplitud): un umbral cruzado con ruido se cruza en un instante
   incierto; un instante incierto sobre una pendiente da una amplitud incierta.

Las tres terminan en el mismo lugar — ancho del fotopico y ancho de la
distribución de timestamps — pero tienen magnitudes que difieren en órdenes de
magnitud y se atacan con herramientas distintas. Este documento las pone en la
misma unidad y las ordena.

Números fijos del sistema:

| | |
|---|---|
| `Ts` | 8 ns (125 MSPS) |
| ADC | 14 bits, 1 LSB = 2 V / 16384 ≈ 122 µV |
| Ruido total medido con pulser (§2.2 de [`decisiones_diseno_mca.md`](decisiones_diseno_mca.md)) | σ ≈ 2.8 cuentas, FWHM ≈ 6.6 canales sobre 1920 |
| Fondo de escala del MCA | 8192 canales |

---

## 1. Cómo se suman

Si las fuentes son **independientes**, las varianzas se suman:

    σ_total² = σ_detector² + σ_electrónica²
    σ_electrónica² = σ_ADC² + σ_cuantización² + σ_fase² + σ_apertura² + σ_estimador² + …

y con todo gaussiano eso se escribe en FWHM:

    FWHM_total² = FWHM_detector² + FWHM_electrónica²          (FWHM = 2.355 σ)

Dos advertencias que se saltan siempre:

- **No todo es gaussiano.** La fase de muestreo y la cuantización son
  *uniformes*; el FWHM de una uniforme es su ancho completo, no `2.355 σ`. Lo que
  se suma en cuadratura son las **varianzas**; el FWHM del total sólo vale
  `2.355 σ_total` cuando hay suficientes términos comparables para que el
  resultado sea aproximadamente gaussiano (teorema central del límite) o cuando
  domina un término gaussiano. En la práctica domina el ruido del ADC, así que la
  regla FWHM funciona — pero por eso, no por principio.
- **No todo es independiente.** La fase de muestreo afecta a la vez al
  estimador de amplitud y al timestamp del mismo evento: sus errores están
  correlacionados. Para el fotopico no importa (sólo se mira amplitud), para una
  corrección de amplitud en función de tiempo sí.

---

## 2. Jitter del clock (apertura) — el que da nombre al tema y el que menos pesa

El ADC toma la muestra en `t_n = n·Ts + ε_n`, con `ε_n` gaussiano de desvío
`σ_t`. Tiene dos componentes en cuadratura: el jitter de apertura propio del ADC
(LTC2145-14: del orden de **0.1 ps rms** según hoja de datos) y el del oscilador
de 125 MHz que lo maneja (un XO de propósito general: **1–10 ps rms** integrado
en 12 kHz–20 MHz; verificar el componente que monta la placa). El del oscilador
manda.

### Cómo se convierte en error de amplitud

Un error de tiempo sobre una señal con pendiente es un error de tensión:

    σ_v = |dV/dt| · σ_t

Para un pulso de amplitud `A` y tiempo de subida `t_r` (10–90 %) la pendiente
máxima es `≈ 0.8·A/t_r`. Con `A = 8192` cuentas (fondo de escala) y
`t_r = 100 ns`:

| σ_t | σ_v en el flanco | vs σ_ADC = 2.8 |
|---|---|---|
| 0.1 ps | 0.007 cuentas | nada |
| 1 ps | 0.07 cuentas | nada |
| 10 ps | 0.65 cuentas | 5 % del ruido, en cuadratura 2.7 % |

Y **en el pico `dV/dt = 0`**: el jitter del clock no mueve la muestra de pico a
primer orden. El estimador `cfg_amp_src = 0` es *inmune* al jitter de apertura;
sólo lo ven las muestras del flanco, o sea la integral (donde promedia `1/√N`) y
el timestamp.

La forma equivalente en dB, para comparar con la hoja de datos del ADC:

    SNR_jitter = −20·log10(2π · f_señal · σ_t)

con `f_señal ≈ 0.35 / t_r = 3.5 MHz` para `t_r = 100 ns`: 93 dB con 1 ps, 73 dB
con 10 ps. El LTC2145-14 tiene SNR ≈ 73 dB. O sea: **sólo con un oscilador
mediocre (10 ps) y en el flanco más rápido el jitter de apertura alcanza al piso
del ADC.** En todos los demás casos es despreciable, y a menos que aparezcan
pulsos con `t_r < 20 ns` no vale la pena medirlo.

### Estabilidad de frecuencia (ppm) — no es jitter, pero se confunde

Un XO tiene ±20–50 ppm de exactitud y deriva térmica. Eso **no ensancha nada**:
es un error de escala en el eje de tiempo. Afecta a

- los timestamps absolutos (`timestamp[63:0]` del event ring): 50 µs de error
  por segundo transcurrido,
- las medidas de tasa y tiempo muerto: 50 ppm relativos, invisible,
- coincidencias entre **dos placas** con clocks distintos: la diferencia de
  timestamps camina a 50 ppm × Δt, que en 1 ms ya son 50 ns. Para eso hace
  falta clock común, no mejor clock.

---

## 3. Fase de muestreo — el "jitter de muestreo" de los otros documentos

El pulso llega en un instante arbitrario respecto del clock. Llamando `φ` al
desplazamiento entre el máximo verdadero y la muestra más cercana:

    φ ~ Uniforme(−Ts/2, +Ts/2)        σ_φ = Ts/√12 = 2.31 ns

Esto no es ruido del clock: con un clock perfecto pasa igual. Es el efecto que
[`decisiones_diseno_mca.md`](decisiones_diseno_mca.md) §5 llama *jitter de
muestreo* y es la razón de fondo por la que existe `cfg_amp_src`.

### Efecto sobre la muestra de pico

La muestra de pico subestima el máximo verdadero en una cantidad que depende de
`φ` y de la **forma del pico**. Dos casos límite:

**Pico redondeado** (parábola, `V(t) ≈ A·(1 − t²/2τ_c²)`, con `τ_c` el radio de
curvatura; para un pulso gaussiano `τ_c = σ_pulso`):

    δ(φ) = A·φ² / (2τ_c²)
    E[δ]  = A·Ts² / (24·τ_c²)               ← sesgo, no ensancha
    σ_δ   = A·Ts² / (2·√180·τ_c²) ≈ A·Ts² / (27·τ_c²)

**Pico en punta** (cúspide, pendientes `±A/t_r` a cada lado):

    δ(φ) = A·|φ| / t_r
    E[δ]  = A·Ts / (4·t_r)
    σ_δ   = A·Ts / (√48·t_r) ≈ A·Ts / (6.9·t_r)

Los números para `A = 1920` cuentas (el nivel del pulser en la campaña):

| Pulso | Parábola (τ_c) | σ_δ parábola | Cúspide (t_r) | σ_δ cúspide |
|---|---|---|---|---|
| 4 µs FWHM | 1.7 µs | 0.002 cuentas | 400 ns | 5.6 cuentas |
| 2 µs FWHM | 850 ns | 0.006 cuentas | 200 ns | 11 cuentas |
| 0.5 µs FWHM | 212 ns | 0.10 cuentas | 100 ns | 22 cuentas |

Lo medido al acortar el pulso de 4 µs a 0.5 µs fue FWHM 0.33 % → 0.44 %, o sea
σ 2.7 → 3.6 cuentas: **2.4 cuentas extra en cuadratura**. La parábola lo
subestima por 20×, la cúspide lo sobreestima por 10×. La explicación es que el
pico del ARB está redondeado pero no es gaussiano: la curvatura en el máximo es
mayor que la de una gaussiana del mismo FWHM. Es una predicción medible con el
osciloscopio (§6) y de paso dice **cuál es el `τ_c` real del estímulo**, que es
lo que decide si el pico o la integral gana.

Regla práctica que sale de la tabla: mientras `Ts² / τ_c²` sea menor que
`σ_ADC / A` (acá `2.8/1920 ≈ 1.5e-3`), el estimador de pico no paga fase de
muestreo. Eso se cumple hasta `τ_c ≈ 200 ns`, es decir pulsos de ~0.5 µs de
FWHM con pico gaussiano. **Para pulsos más cortos, o con pico en punta (RC-CR
sin conformado), la integral tiene que ganar.**

### Efecto sobre la integral

La integral `Σ V(nTs + φ)` sobre una ventana que cubre todo el pulso es la
regla del rectángulo, y su error con la fase es exponencialmente chico para
señales de banda limitada muestreadas por encima de Nyquist. En la práctica es
cero: la integral **no ve la fase de muestreo**, salvo por dónde cae la ventana
(§4).

### Efecto sobre el timestamp

El timestamp es el ciclo de `adc_clk` en que se detectó el cruce del umbral: se
cuantiza a `Ts`. Error uniforme en un intervalo de `Ts`:

    σ_ts = Ts/√12 = 2.31 ns          FWHM = 8 ns (ancho completo de la uniforme)

Es el piso de resolución temporal **sin interpolar**. Con interpolación lineal
entre las dos muestras que encierran el umbral, el error de fase desaparece y
lo que queda es §4.

---

## 4. Jitter de estimación — ruido de amplitud convertido en tiempo, y vuelta

### Ruido → tiempo (cruce de umbral)

Un umbral `thr` sobre una señal con ruido `σ_v` se cruza en un instante que
fluctúa:

    σ_t = σ_v / |dV/dt|_{V = thr}

Es la fórmula clásica de timing por *leading edge*: el jitter temporal es el
ruido dividido por la pendiente **en el punto de cruce**. Con `σ_v = 2.8`
cuentas y `t_r = 100 ns`:

| Amplitud | Pendiente en el flanco | σ_t | vs σ_ts = 2.31 ns |
|---|---|---|---|
| 8192 (1 Vpp) | 65 cuentas/ns | 43 ps | despreciable |
| 1920 | 15 cuentas/ns | 0.18 ns | despreciable |
| 800 (0.1 Vpp) | 6.4 cuentas/ns | 0.44 ns | 4 % del total en cuadratura |
| 200 (cerca del umbral) | 1.6 cuentas/ns | 1.8 ns | comparable |

Conclusión: **la resolución temporal del sistema está limitada por la
cuantización a `Ts`, no por el ruido**, en todo el rango dinámico salvo la
última década sobre el umbral. Interpolar entre muestras la mejora hasta
`σ_v/pendiente`, o sea a sub-ns para pulsos grandes, sin tocar el hardware.

Dos cosas que **no son jitter** pero aparecen en la misma distribución:

- **Walk de amplitud**: el instante de cruce de un umbral fijo depende de la
  amplitud (`t_cruce ≈ t_r · thr / (0.8·A)`). Es sistemático y se corrige
  conociendo `A`, o se elimina con un discriminador de fracción constante. El
  RTL actual no tiene CFD; el walk está en el timestamp y hay que corregirlo en
  software si importa.
- **Latencia del pipeline**: el detector de cruce, el registro de timestamp y
  el CDC al bus agregan ciclos, pero **un número fijo** de ciclos. La lógica es
  síncrona con `adc_clk`; no agrega jitter. El único cruce de dominio
  (`sys_bus_cdc` hacia `clk_fpga_0`) está en el camino del bus, no del dato.

### Tiempo → amplitud (cierre de ventana)

La otra dirección de la misma fórmula. En modo histéresis (`cfg_gate_mode = 0`)
la ventana de integración cierra donde la cola cruza `thr − hyst`. La cola de
un pulso es la parte más chata, así que ahí `dV/dt` es mínima y `σ_t` máxima:

    σ_t,cierre = σ_v / |dV/dt|_{cola}

Con cola exponencial de constante `τ_d` y cierre a nivel `V_c = thr − hyst`, la
pendiente es `V_c / τ_d`. Para `τ_d = 1 µs`, `V_c = 100` cuentas:
`0.1 cuentas/ns` → `σ_t,cierre = 28 ns = 3.5 muestras`. La integral suma o
resta esas 3.5 muestras a nivel `~V_c`: `±350` cuentas de `Q_total`, que para
`Q_total ≈ A·τ_d/Ts ≈ 2.4e5` son **0.15 %** de la amplitud. Del mismo orden que
el ancho medido en modo histéresis (0.53 %) descontado el de compuerta fija
(0.15 %): `√(0.53² − 0.15²) = 0.51 %`. Lo que falta lo pone el error de línea de
base multiplicado por el largo variable de la ventana, que va en la misma
dirección.

Ese mecanismo es el "jitter del cierre de la ventana" de
[`resultados_validacion_hw.md`](../resultados_validacion_hw.md) §0.3, y es por lo
que existe `cfg_gate_mode = 1`: con compuertas de largo fijo desde el disparo,
la ventana hereda sólo la incertidumbre del cruce de **apertura** (`σ_t` del
flanco de subida, sub-ns) más la fase de muestreo (`±Ts/2`), y sus bordes caen
en zonas de pendiente ≈ 0 (línea de base antes, cola extinguida después), así
que el desplazamiento no cambia la suma.

---

## 5. Lo que no es jitter pero entra en la misma cuadratura

| Fuente | Distribución | σ | Comentario |
|---|---|---|---|
| Cuantización del ADC | uniforme, 1 LSB | 0.29 cuentas | Un 1 % del ruido total en cuadratura. No es el piso |
| Ruido del ADC + front-end | gaussiano | ≈ 2.8 cuentas (medido, incluye el pulser) | **El piso.** Separarlo del generador requiere §6 |
| Error de línea de base | lento, correlacionado | depende de `cfg_bl_*` | Sistemático por evento; en la integral se multiplica por N |
| Deriva del centroide | determinista, horas | — | No ensancha una adquisición corta; domina las largas: [`limites_resolucion_y_deriva.md`](limites_resolucion_y_deriva.md) |
| Binning del histograma | uniforme, 1 canal | 0.29 canales | Corrección de Sheppard, ya tratada en el mismo documento |

---

## 6. Presupuesto y cómo medir cada término

Resumen para `A = 1920` cuentas, `t_r = 100 ns`, pulso de 2 µs, `σ_t,clk = 1 ps`:

| Fuente | Afecta a | σ (amplitud) | σ (tiempo) | Se mide con |
|---|---|---|---|---|
| Ruido ADC + front-end | todo | 2.8 cuentas | 0.18 ns | RMS de la línea de base con la entrada terminada en 50 Ω, sin pulser |
| Fase de muestreo, pico | `cfg_amp_src = 0` | 0.006 (parábola) … 11 (cúspide) | — | `compare_estimators()` vs ancho de pulso; forma del pico con el osciloscopio |
| Fase de muestreo, timestamp | timestamp | — | 2.31 ns | Histograma de `ts` con pulser periódico: tiene que ser plano de 8 ns |
| Apertura + clock | flanco, integral | 0.07 cuentas | 1 ps | No vale la pena; sólo si aparecen `t_r < 20 ns` |
| Cierre de ventana (histéresis) | `cfg_amp_src = 1`, `gate_mode = 0` | ≈ 0.15 % de A | 28 ns | Barrido `gate_mode` 0 vs 1 sobre el mismo estímulo (ya hecho: 0.53 → 0.15 %) |
| Walk de amplitud | timestamp | — | sistemático, hasta `t_r·thr/A` | `ts` vs amplitud con el pulser barrido |

Suma en cuadratura de las columnas de amplitud con pico gaussiano: **2.8
cuentas** — el ruido del ADC solo. Todo lo demás está uno o dos órdenes de
magnitud abajo. Eso quiere decir dos cosas:

1. **No hay nada que ganar mejorando el clock.** Ni oscilador externo, ni PLL de
   bajo jitter, ni CDC más prolijo cambian el fotopico.
2. **Sí hay algo que ganar separando el ruido del ADC del ruido del pulser**,
   porque hoy los 2.8 son la suma de los dos y no sabemos cuál domina. Es la
   medida más barata del documento: entrada terminada, sin señal, RMS de la
   base.

### Medir el jitter temporal sin que el generador contamine

Con un solo canal, el histograma de timestamps contra un pulser periódico mezcla
el jitter del sistema con el del generador. La forma de sacarlo: **partir la
misma señal a las dos entradas** (`IN1`, `IN2`) y mirar la distribución de
`ts₁ − ts₂`. El jitter del generador es común y se cancela; lo que queda es
`√2·σ_t,sistema` más la fase de muestreo — que también es común si ambos canales
comparten `adc_clk`, en cuyo caso sólo queda el término de ruido de §4 y la
diferencia tiene que salir **casi siempre 0 ciclos**, con un ±1 en la fracción
de eventos que la fórmula de `σ_t` predice. Es una verificación falsable de toda
la sección 4 con hardware que ya está.

---

## 7. Qué cambia si aparecen pulsos de detector reales

Todo lo anterior está calibrado con `t_r = 100 ns` y picos redondeados de 2 µs,
que es lo que da el ARB. Un preamplificador de carga sin conformar entrega
`t_r` de 10–50 ns y **pico en punta** (subida rápida, decaimiento exponencial):
justo el caso donde la fila "cúspide" de §3 manda. Ahí:

- la muestra de pico paga `A·Ts/(6.9·t_r)`: con `t_r = 20 ns`, **6 % de A**.
  Inaceptable; hay que ir a integral o conformar antes;
- el jitter de apertura sube a `0.8·A/t_r · σ_t`: con 10 ps y `t_r = 20 ns`,
  3.3 cuentas a fondo de escala. Empieza a asomar sobre el ruido, y ahí sí
  conviene saber qué oscilador hay en la placa;
- el timing mejora: `σ_v/pendiente` baja a decenas de ps, y la cuantización a
  `Ts` pasa a ser la única barrera. Interpolar el cruce vale la pena.

El conformado digital ([`formas_de_pulso.md`](formas_de_pulso.md)) mueve el
sistema de vuelta al régimen "pico redondeado" a costa de tiempo muerto, y es la
palanca que arbitra entre las tres filas.

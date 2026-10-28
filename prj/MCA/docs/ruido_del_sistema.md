# El ruido del sistema: todas las fuentes, y por qué la más chica es la que manda

Todo el proyecto viene citando el ruido de la cadena como **un número**: "σ ≈ 2.8
cuentas", "el piso". Este documento lo abre. La tesis es que ese número esconde
la única distinción que importa, y que no es la magnitud:

> **Lo que decide cuánto ensancha una fuente de ruido no es su σ sino si
> promedia o no dentro de la ventana de medición.** Un término de 4.5 cuentas
> que promedia sobre 384 muestras pesa menos que uno de 0.9 que no promedia.

Ordenadas por magnitud, las fuentes dan una lista; ordenadas por espectro, dan
otra — y es la segunda la que dice dónde trabajar. Con los datos de la campaña
que ya estaban en el repo, este documento:

- **mide** que el ruido de la placa no es blanco: sobre un término blanco de
  4.47 cuentas hay uno correlacionado de 0.87 cuentas con τ ≈ 12 µs;
- **exonera al generador**: las 4.56 cuentas son de la placa, no del Rigol —
  la medición que [`mca/fuentes_de_jitter.md`](mca/fuentes_de_jitter.md) §6
  llamaba "la más barata del documento", hecha con datos ya tomados;
- **mide el crosstalk entre canales** en −56.5 dB, que
  [`adc_ltc2145.md`](adc_ltc2145.md) §10.2 dejaba pendiente;
- **corrige el reparto ADC / front-end** de [`adc_ltc2145.md`](adc_ltc2145.md)
  §4.1: el ADC pone el 8 % de la varianza por muestra, no el 21 %;
- **modela por primera vez el seguidor de línea de base con ruido**, con la
  aritmética entera exacta del RTL, y encuentra que **su constante de tiempo
  está mal elegida**: el `bl_k = 12` de todas las campañas pone el codo del
  seguidor en 4.9 kHz, por debajo de los 13 kHz del ruido que tiene que seguir;
- **cierra contra lo medido**: con esa configuración el presupuesto predice
  0.159 % de FWHM para la integral y la placa midió **0.161 %**;
- y termina en **una predicción falsable que cuesta una escritura de
  registro**: bajar `bl_k` de 12 a 9 tiene que llevar esa resolución a
  **≈ 0.13 %**.

Todos los números los recalcula
[`monte-carlo/ruido.py`](../software/monte-carlo/ruido.py) desde las trazas y
las fórmulas. Si el documento y el script no coinciden, manda el script.

![el ruido no es blanco, el seguidor tiene un óptimo, y qué compra atacarlo](../software/datos/ruido_20261009/ruido.png)

*(a) la autocovarianza del canal en vacío: el término blanco vive sólo en el
retardo 0 (fuera de escala, 20.2 cuentas²) y lo que queda es una meseta de 0.76
cuentas² que decae con τ ≈ 12 µs; el triángulo es el test entre ventanas, a 1 ms,
que da cero. (b) el error de base por evento contra `cfg_bl_k`, con sus tres
términos teóricos: el óptimo es plano y su piso no es el IIR sino el dither de la
base truncada. (c) lo que compra mover `bl_k`, con todos los demás términos sin
tocar; las líneas punteadas son lo medido en placa con `bl_k = 12`.*

Documentos hermanos, para no duplicar:

| Documento | Qué contiene |
|---|---|
| [`mca/fuentes_de_jitter.md`](mca/fuentes_de_jitter.md) | el presupuesto del eje de **tiempo**; esto es el del eje de **amplitud** |
| [`mca/conformado_y_ruido.md`](mca/conformado_y_ruido.md) | cómo la **forma del pulso** trabaja el ruido del conversor |
| [`adc_ltc2145.md`](adc_ltc2145.md) | el conversor, parámetro por parámetro |
| [`mca/limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md) | por qué el límite activo no es el ruido sino la deriva |
| [`platform.md`](platform.md) §2.1 | el front-end analógico de la placa |
| [`mca/decisiones_diseno_mca.md`](mca/decisiones_diseno_mca.md) §2.2 | la resolución medida, y qué significa |

---

## 1. Tres cosas distintas que se llaman "ruido"

Conviene separarlas antes de sumar nada, porque se arreglan con herramientas
distintas y dos de las tres ni siquiera ensanchan el fotopico.

| | Qué es | ¿Ensancha el pico? | ¿Las cuentas lo mejoran? |
|---|---|---|---|
| **Ruido por evento** | la fluctuación de la amplitud estimada de un pulso a otro | **sí**: es la FWHM instrumental | no |
| **Sesgos por evento** | deriva, apilamiento, *walk*: errores sistemáticos que dependen de tasa, tiempo o amplitud | sí, pero por convolución, no por varianza | no |
| **Estadística de conteo** | la raíz de N de cada bin del histograma | **no**: es ruido *del espectro*, no *del pico* | sí, como √N |

Este documento trata la primera. La segunda es
[`mca/limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md) §6, y
es —por un factor 38— el límite activo del instrumento. La tercera está en §9.

### El eje que ordena todo: ¿promedia dentro de la ventana?

Cada fuente de ruido por evento entra a la amplitud estimada a través del
estimador, y los dos estimadores del RTL la ven de forma distinta:

| | muestra de pico (`cfg_amp_src = 0`) | integral (`cfg_amp_src = 1`) |
|---|---|---|
| ruido **blanco** (descorrelacionado muestra a muestra) | entra una vez: σ | promedia: **σ·√N / N = σ/√N** |
| ruido **correlacionado** más lento que la ventana | entra una vez: σ | **NO promedia**: N·σ / N = σ |
| **fase de muestreo** (una por evento) | entra completa | no la ve |

Con N = 384 muestras de ventana, el blanco se divide por 19.6 y el
correlacionado por 1. Un término correlacionado **veinte veces más chico que el
blanco pesa lo mismo** — y acá la relación es de 5 a 1, no de 20 a 1. De ahí
sale toda la §5.

Cómo se suman (varianzas, con las dos advertencias sobre normalidad e
independencia) está en [`mca/fuentes_de_jitter.md`](mca/fuentes_de_jitter.md)
§1 y no se repite acá.

---

## 2. El inventario completo, etapa por etapa

Todo lo que puede meter ruido en esta cadena, siguiendo el recorrido de la
señal (§2.1 a §2.5), más lo que entra **por fuera** de ese recorrido (§2.6). En
todas las tablas la columna que importa es la última — §1 explica por qué.

```
         ┌───── el entorno: tierra, EMI, alimentación, RF (§2.6) ─────┐
         │        │                  │                 │             │
         ▼        ▼                  ▼                 ▼             ▼
  detector → preamp │ front-end de la placa │  ADC + reloj  │  MCA digital  │ histograma
       §2.1         │         §2.2          │     §2.3      │     §2.4      │    §2.5
   (hoy no existe)  │  ← acá está el 92 % → │               │ ← acá el 85 % │
                    │     del ruido total   │               │  de lo que    │
                    │                       │               │  ensancha     │
```

Esa aparente contradicción de la tercera línea es la tesis del documento: el
front-end pone casi todo el **ruido**, y la cadena digital decide casi todo el
**ensanchamiento**, porque lo que ensancha no es el ruido más grande sino el que
no promedia.

> **Convención de símbolos.** Cada fila es un término que se suma a la muestra o
> a la *feature* del evento. $n$ son términos de **ruido** (media nula), $e$
> **errores de estimación**, $q$ **cuantizaciones y truncamientos**, $\beta$
> **sesgos deterministas**, $\chi$ un **coeficiente de acoplamiento** y $\theta$
> una **variable de entorno**. La columna $E[\cdot]$ es la que separa las dos
> primeras filas de la tabla de §1: **media distinta de cero ⇒ corre el
> centroide** (es un sesgo, y no lo arregla promediar); **media nula ⇒ sólo
> ensancha el pico**. La última columna dice si la ventana de medición lo
> promedia, que es lo que decide cuánto ensancha.

### 2.1 Antes de la placa: el detector y su preamplificador

| # | Símbolo | Fuente | $E[\cdot]$ | σ (cuentas de ADC) | Estado | ¿Promedia en la ventana? |
|---|---|---|---|---|---|---|
| 1 | $n_F$ | Estadística de portadores del detector (Fano) | 0 | — | §8 | sí, ya está en la física |
| 2 | $n_{\mathrm{ph}}$ | Fotoestadística del centelleador + PMT | 0 | — | §8 | ídem |
| 3 | $n_{\mathrm{par}}$ | Corriente de fuga del detector (*step noise*, paralelo) | 0 | — | §8 | depende del conformado |
| 4 | $n_{\mathrm{ser}}$ | Ruido serie del preamplificador (*delta noise*) | 0 | — | §8 | depende del conformado |

**Hoy esta etapa no existe**: el estímulo es un ARB. Es la observación más
importante del inventario y está desarrollada en §8, porque fija **cuánto vale
la pena perseguir todo lo demás**. Con un centelleador estas cuatro filas son
20× más grandes que las dieciséis que siguen juntas.

### 2.2 El front-end analógico de la placa

| # | Símbolo | Fuente | $E[\cdot]$ | σ (cuentas de ADC) | Estado | ¿Promedia en la ventana? |
|---|---|---|---|---|---|---|
| 5 | $n_w$ | **Ruido blanco del front-end** | 0 | **4.29** | **medido** | **sí, $1/\sqrt{N}$** |
| 6 | $n_c$ | **Ruido correlacionado, τ ≈ 12 µs** | 0 | **0.87** | **medido** | **NO** |
| 7 | $n_w^{\mathrm{alias}}$ | Doblado de ruido > 62.5 MHz (sin antialias) | 0 | hasta 3.0 de los 4.29 | cota, §4 | dentro del 5 |
| 8 | $n_{\mathrm{gen}}$ | Ruido del generador de estímulo | 0 | **0** | **medido**, §3 | — |

Es **el 92 % de la varianza por muestra** y, salvo el 7, no hay forma de
atacarlo desde el FPGA: las palancas son analógicas (reguladores lineales,
filtro a la entrada) o son cambiar de placa. §4.

### 2.3 La conversión: ADC y reloj

| # | Símbolo | Fuente | $E[\cdot]$ | σ (cuentas de ADC) | Estado | ¿Promedia en la ventana? |
|---|---|---|---|---|---|---|
| 9 | $n_{\mathrm{adc}}$ | Ruido del ADC (térmico + cuantización + apertura) | 0 | **1.28** | hoja de datos | sí, $1/\sqrt{N}$ |
| 10 | $q_{\mathrm{adc}}$ | Cuantización sola | 0 | 0.289 | derivado | dentro del 9 |
| 11 | $\chi$ | Crosstalk del canal vecino | **$\chi\,x_{\mathrm{vec}} \neq 0$** | −56.5 dB | **medido** | determinista |
| 12 | $n_{\mathrm{clk}}$ | Jitter del reloj de muestreo | 0 a primer orden | 0.07, y **0 en el pico** | §7 | sí |
| 13 | $n_\varphi$ | Fase de muestreo | 0; en el pico **< 0** (nunca se muestrea por encima del ápice) | 0.006 … 11 según la forma | [jitter](mca/fuentes_de_jitter.md) §3 | no, pero la integral no la ve |

El 8 % restante de la varianza, más dos términos que no son ruido de amplitud
pero terminan en el mismo ancho. **Ninguno es palanca**: el ADC está soldado, el
reloj no mueve la aguja (§7) y la fase sólo molesta al estimador de pico.

> **Ojo con sumar por etapa.** Lo único observable son los códigos, o sea
> front-end **y** ADC ya sumados: las 4.47 cuentas de blanco medidas en §3 son
> las filas 5 y 9 juntas. §4 las separa con la hoja de datos del conversor, no
> con una medición independiente — que en este encapsulado es imposible
> ([`adc_ltc2145.md`](adc_ltc2145.md) §1.1).

### 2.4 La cadena digital del MCA

| # | Símbolo | Fuente | $E[\cdot]$ | σ (cuentas de ADC) | Estado | ¿Promedia en la ventana? |
|---|---|---|---|---|---|---|
| 14 | $e_{\mathrm{bl}}$ | **Error del seguidor de línea de base** | **≠ 0**: el pedestal por tasa ([`linea_base.py`](../software/monte-carlo/linea_base.py)) | **0.53 … 0.87** | **§5** | **NO** |
| 15 | $d_{\mathrm{bl}}$ | Dither del truncamiento de la base | 0, **y lo fuerza el lazo** (§5) | 0 … 0.50 | **§5** | NO, y dentro del 14 |
| 16 | $\beta_{\mathrm{rect}}$ | Rectificación del recorte `xc ≥ 0` | **$+\sigma/\sqrt{2\pi}$ por muestra recortada** | 0 con este estímulo | **§6** | sesgo, no varianza |
| 17 | $q_{\mathrm{shift}}$ | Truncamiento de `q_tot >> cfg_q_shift` | **$-\tfrac{1}{2}$ LSB**: `>>` es *floor*, no redondeo | 0.289 LSB del eje | §6 | — |
| 18 | $z$ | `mca_zoom` | 0 | **0** | §6 | — |

La etapa más chica en cuentas y **la más grande en consecuencias**: la fila 14
se lleva el 85 % de la varianza del mejor estimador, y es la única de todo el
inventario que se cambia **por registro**, sin tocar hardware ni bitstream (§5).

### 2.5 El histograma, y después

| # | Símbolo | Fuente | $E[\cdot]$ | σ | Estado | ¿Promedia en la ventana? |
|---|---|---|---|---|---|---|
| 19 | $q_{\mathrm{bin}}$ | Bineado del eje | 0 | 0.289 canales | §6 | — |
| 20 | $N_i$ | Estadística de conteo | **$\bar{N_i}$**: el contenido verdadero del bin | $\sqrt{N_i}$ por bin | §9 | — |

La 19 ya está acotada por la regla de 4–10 canales por FWHM y hoy cuesta menos
del 0.6 %. La 20 **no ensancha el pico** —es ruido del espectro, no del pico— y
es la única de las veinte filas que las cuentas mejoran.

### 2.6 El entorno: lo que entra por fuera del recorrido de la señal

Las veinte filas anteriores entran **por el recorrido de la señal** y se suman
al presupuesto. Las de acá entran **por afuera** —por la tierra, por el aire,
por la alimentación— y no se presupuestan: se **eliminan** o se **acotan**. La
distinción importa porque cambia la herramienta:

> Un término del presupuesto se mide, se modela y se optimiza por registro. Una
> fuente del montaje no se optimiza: o está, y hay que encontrarla y sacarla, o
> no está. **Ninguna cantidad de procesamiento digital arregla un lazo de
> tierra.**

Las dos consideraciones principales de un sistema de detección, una línea cada
una:

- **Ruido electrónico**: fluctuaciones indeseadas que se suman a la señal entre
  el detector y el conversor, y que el instrumento no puede distinguir de la
  señal.
- **Tierra**: todos los equipos del laboratorio tienen que estar referidos al
  **mismo punto** de masa. Si no, la diferencia de potencial entre tierras
  aparece **en serie con la señal**.

| # | Símbolo | Fuente | Cómo entra | $E[\cdot]$ | Estado acá | ¿Promedia en la ventana? |
|---|---|---|---|---|---|---|
| E1 | $v_{\mathrm{gnd}}$ | **Lazo de tierra** | corriente por la malla del coaxial → tensión en serie con la señal | 0 en el largo plazo, **≠ 0 dentro de un evento**: a 50 Hz, 3 µs es DC | **acotado**, abajo | **NO** |
| E2 | $n_{\mathrm{psu}}$ | **Ripple de la alimentación** | conducido, por los rieles analógicos | ídem | **dentro del 92 % del blanco**, §4 | según su espectro |
| E3 | $n_E$ | **Acoplamiento capacitivo** (cables como antena) | campo E externo sobre la impedancia de entrada | ídem | **sin medir** | según su espectro |
| E4 | $n_B$ | **Acoplamiento inductivo** (lazos) | campo B externo sobre el área del lazo | ídem | **sin medir** | **NO** (50 Hz y armónicos) |
| E5 | $n_{\mathrm{RF}}$ | **Pickup de RF > 62.5 MHz** | se **dobla** a la banda: queda indistinguible del blanco | 0 | cota de §4 | sí, como el blanco |
| E6 | $n_{\mathrm{dig}}$ | **Actividad digital de la propia placa** | DAC, Ethernet, SD, el otro canal | **≠ 0 si está correlacionada con el disparo** | medición 5 de §11 | depende |
| E7 | $n_{\mathrm{HV}}$ | **Ripple de la fuente de alta tensión** | **multiplicativo**: modula la ganancia del detector | 0, pero escala con la amplitud | **no existe hoy** | NO |
| E8 | $n_{\mathrm{mic}}$ | **Microfonía y efecto triboeléctrico** | vibración → carga en el coaxial y en el detector | 0 | **no existe hoy** | NO (banda acústica) |
| E9 | $n_{\mathrm{luz}}$ | **Fugas de luz** (centelleador/PMT) | fotones parásitos → corriente de ánodo | **≠ 0**: corre la línea de base | **no existe hoy** | — |
| E10 | $\theta$ | **Temperatura del laboratorio** | ganancia del PMT y del centelleador | **≠ 0**: es deriva pura | → [`mca/limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md) | NO (horas) |

**Las filas E7 a E10 no existen todavía**, por la misma razón que las filas 1–4
de §2.1: el estímulo es un ARB y no hay detector. Es la advertencia de §8
aplicada al montaje — **con un centelleador, E7–E10 pueden ser más grandes que
todo el presupuesto electrónico junto**.

#### Por qué la tierra, con números

El mecanismo de E1/E4 es un lazo: la malla del coaxial une la masa del generador
con la masa de la placa, y si las dos están además unidas por la tierra de red,
el circuito se cierra. Ese lazo encierra un área, y cualquier campo magnético
que lo atraviese induce una fem $V = 2\pi f B A$. Con un lazo modesto de 0.1 m²
y un campo de 0.5 µT —el orden de magnitud a decenas de centímetros de un cable
de red— a 50 Hz:

```
  V = 2π · 50 Hz · 0.5 µT · 0.1 m² ≈ 157 µV
```

Y la escala de la placa en LV (±1 V, 14 bits) es **122 µV por cuenta**:

| | σ [µV] | σ [cuentas] | ¿promedia en la ventana? |
|---|---|---|---|
| lazo de tierra del ejemplo | ~157 | **~1.3** | **NO** |
| $n_c$, el correlacionado medido (§3) | 106 | 0.87 | **NO** |
| $n_w$, el blanco medido (§3) | 546 | 4.47 | sí, ÷19.6 |

**Un lazo de tierra de aula sería la fuente dominante del mejor estimador**, por
encima del término correlacionado que §5 pelea con el seguidor de línea de base.
Ése es el orden de magnitud que justifica tratar la tierra como una decisión de
diseño del montaje y no como una recomendación general.

Un detalle que conviene tener claro: **pasar el jumper a HV (±20 V) no ayuda.**
El pickup que entra por el cable se atenúa junto con la señal, así que la
relación no cambia; lo único que cambia es la escala en µV por cuenta.

#### Qué ya está descartado, con datos que ya estaban tomados

El test entre ventanas de §3 no se hizo pensando en esto, pero **acota el pickup
de red**. Un término de 50 Hz con fracción de varianza $f$ daría correlación
$f\cos(2\pi \cdot 50\,\Delta)$, y —esto es lo que lo hace sensible— **sobrevive
entero al promedio de las 9 muestras de pre-disparo**, porque a 50 Hz esas 72 ns
son DC:

| retardo | si fuera 50 Hz | medido (±0.012) |
|---|---|---|
| 1 ms | $+0.95\,f$ | −0.010 |
| 2 ms | $+0.81\,f$ | +0.016 |
| 5 ms | 0 | −0.003 |
| **10 ms** | **$-f$** (media vuelta) | **+0.006** |
| **100 ms** | **$+f$** (5 vueltas justas) | +0.019 |

Los retardos de 10 y 100 ms son los que discriminan, porque predicen signos
opuestos. De ellos sale $f \lesssim 0.02$ y, con la varianza de la media de
pre-disparo que normaliza esos ρ (2.98 cuentas², no la varianza por muestra),
**σ₅₀ ≲ 0.24 cuentas ≈ 30 µV**: no hay ningún lazo de tierra parecido al del
ejemplo de arriba. El mismo test descarta además cualquier deriva más lenta que
100 ms.

Las otras dos cosas del montaje que ya están cerradas, las dos en §3:

- **el generador no aporta ruido**: 4.49 cuentas con el Rigol colgado contra
  4.55 en vacío. El estímulo está limpio;
- **el crosstalk entre canales es −56.5 dB**, que es el acoplamiento interno más
  grande medido del montaje.

#### El pickup de RF: por qué esta placa es más frágil que una cadena NIM

Es la consecuencia menos obvia, y la que más cambia las prácticas de montaje. El
S/H del ADC tiene **750 MHz** de ancho de banda y el único filtro antialias de
la cadena es la caída del front-end a 60 MHz
([`adc_ltc2145.md`](adc_ltc2145.md) §2.1). Entonces:

- **todo lo que entre por encima de 62.5 MHz se dobla a la banda base** y se
  suma a la línea de base como si fuera blanco, sin ninguna firma que permita
  reconocerlo;
- **ningún filtro digital lo saca**, porque una vez doblado ya no se distingue
  de la señal (la asimetría está en §4);
- una cadena NIM clásica **no tiene este problema**: el conformador analógico de
  la etapa 4b filtra *antes* de convertir, con un ancho de banda de ~1 MHz
  ([`cadena_de_medicion.md`](cadena_de_medicion.md) §1).

Consecuencia práctica: un cable de entrada largo, mal apantallado o sin terminar
es, acá, **una antena de VHF cuyo producto termina dentro del espectro sin
manera de distinguirlo del ruido del front-end**. La cota de §4 dice que hasta
el 49 % del blanco podría ser ruido doblado; cuánto de eso es del front-end y
cuánto es pickup externo **no está medido**, y lo separa la medición 4 de §11.

#### Reglas de montaje, en orden de lo que compran

| # | Regla | Qué ataca | Costo |
|---|---|---|---|
| 1 | Todos los equipos en **la misma regleta**, con la misma tierra de red | E1, E4 | nada |
| 2 | **Un solo camino de masa** entre generador y placa: el del coaxial | E1 | nada |
| 3 | Cables de entrada **cortos**, coaxiales, **terminados en 50 Ω** | E3, E5 | nada |
| 4 | **Terminar también el canal que no se usa**, en vez de dejarlo abierto | E3, E4 sobre 1 MΩ | un tapón |
| 5 | Alimentar la placa con una fuente de 5 V propia, no del USB de la notebook | E2, E1 | una fuente |
| 6 | Apagar lo que no se usa de la placa (DAC, el canal vecino, WiFi) | E6 | una escritura |
| 7 | Alejar luminarias, motores y fuentes conmutadas del montaje | E3, E4 | mover la mesa |
| 8 | Pasabajos pasivo a la entrada | **E5**, y la parte doblada del blanco | un RC, ≤ ×1.34 |

Dos notas sobre masas y alimentación de esta placa en particular
([`platform.md`](platform.md) §2.1):

- **el enlace Ethernet está aislado** por los transformadores de su propio
  conector, así que la PC de adquisición **no cierra lazo de tierra**;
- **la alimentación USB de 5 V no está aislada**: la masa de la placa queda atada
  a la del equipo que la alimenta. Si eso es una notebook enchufada a otra toma,
  el lazo se cierra por ahí, y es el camino de entrada más probable de E1 en
  este montaje.

Las mediciones que cierran esta sección son las **E-a a E-e de §11**, y todas
son la misma captura de la medición 3: una traza larga, repetida con la entrada
abierta, terminada y con un cable colgando.

---

## 3. Lo primero que hay que medir: el ruido no es blanco

### De dónde salen estos datos

La campaña `e2e_20260528_013404` guardó 7054 ventanas de 512 muestras de **los
dos canales**, y el canal 2 estaba **en vacío**. Son **3.61 millones de muestras
de línea de base pura**, con dos escalas de tiempo accesibles: dentro de la
ventana (hasta 4 µs) y entre ventanas (1 ms). Nadie las había mirado como ruido.

La autocovarianza se calcula **sin quitarle a cada ventana su propia media** —
se quita el perfil medio *sobre eventos*, que es la señal determinista. Quitar la
media por ventana induce una correlación negativa espuria de −1/(n−1), y peor:
borra exactamente el término que se busca.

### El resultado

| término | σ [cuentas] | σ [µV] | varianza | correlación |
|---|---|---|---|---|
| blanco (descorrelacionado a 8 ns) | 4.47 | 546 | 96.4 % | ninguna |
| **correlacionado (τ ≈ 12 µs)** | **0.87** | 106 | 3.6 % | meseta plana hasta ~12 µs |
| **total por muestra** | **4.56** | 556 | 100 % | — |

La autocovarianza es la figura (a): un pico en el retardo 0 de 20.2 cuentas² y,
a partir del retardo 1, **una meseta de 0.76 cuentas² que no se va**. Entre 16 ns
y 3.2 µs cae apenas un 30 %, lo que ajustado a una exponencial da **τ = 12 µs**,
o sea un codo en **13 kHz**.

### El test que lo decide: no es deriva lenta

Un término correlacionado podría ser deriva térmica o de red. Si lo fuera, las
bases de dos ventanas consecutivas —separadas 1 ms— correlacionarían
ρ = σ_c²/var = **0.246**. Medido sobre 7054 ventanas (error ±0.012):

| retardo | ρ medido | si fuera lento | si fuera rápido |
|---|---|---|---|
| 1 ms | −0.010 | +0.246 | 0 |
| 2 ms | +0.016 | +0.246 | 0 |
| 5 ms | −0.003 | +0.246 | 0 |
| 10 ms | +0.006 | +0.246 | 0 |
| 100 ms | +0.019 | +0.246 | 0 |

**Cero a 21σ del valor que tendría una deriva lenta.** El término correlacionado
vive en una banda angosta alrededor de los 13 kHz: no es deriva térmica, no es
50 Hz, y —esto es lo que importa— **es más rápido que la constante de tiempo con
la que el seguidor de línea de base está configurado hoy** (§5).

### El generador no aporta ruido

Mismo estimador sobre el pre-disparo de los dos canales de la misma campaña: uno
con el Rigol colgado de la entrada, el otro en vacío.

| canal | σ por muestra [cuentas] |
|---|---|
| 1, con el generador | 4.49 |
| 2, en vacío | 4.55 |

La diferencia en varianza es **+0.5 cuentas², del signo contrario** al que
tendría un generador ruidoso, y del orden del error del propio estimador.
**Las 4.56 cuentas son de la placa.** Eso cierra la pregunta que
[`mca/fuentes_de_jitter.md`](mca/fuentes_de_jitter.md) §6 y
[`adc_ltc2145.md`](adc_ltc2145.md) §2.1 dejaban abierta — y resulta que los datos
para contestarla ya estaban tomados desde mayo.

### Crosstalk entre canales

Del mismo perfil medio: el pulso de 2403 cuentas del canal 1 aparece en el canal
2, en vacío, como un perfil de 3.61 cuentas. **−56.5 dB.** Es el número que
[`adc_ltc2145.md`](adc_ltc2145.md) §10.2 pedía para poner un número a la prueba
de coincidencias entre canales. Consecuencia práctica: partir la misma señal a
`IN1` e `IN2` para medir `ts₁ − ts₂` sesga la diferencia en 1/670 de la amplitud,
despreciable para timing y **no** despreciable si alguna vez se quisiera medir
amplitud en coincidencia.

---

## 4. El término blanco: de quién es y qué lo baja

| fuente | σ [cuentas] | varianza | de dónde sale |
|---|---|---|---|
| ADC (SNR = 73.1 dBFS) | 1.28 | **8.2 %** | hoja de datos |
| front-end de la placa | 4.29 | **91.8 %** | por diferencia |
| **total medido** | **4.47** | 100 % | autocovarianza en el retardo 0 |

### Esto corrige a `adc_ltc2145.md` §4.1

Ese documento reparte 21 % / 79 % entre ADC y "front-end + generador". El reparto
comparaba **dos cosas distintas**: los 2.8 cuentas del ancho del *fotopico* —que
ya es la salida de un estimador, y el estimador de pico es un máximo sobre el
ápice, que angosta la distribución ([`mca/conformado_y_ruido.md`](mca/conformado_y_ruido.md)
experimento B)— contra los 1.28 cuentas de ruido del ADC **por muestra**. En la
misma unidad, por muestra, el reparto es **8 % / 92 %**, y el "+ generador"
sobra. La conclusión cualitativa de aquel documento no cambia —el ADC no es el
que manda— pero el margen es mayor del que decía: arreglar el front-end por
completo mejora ×3.5, no ×2.2.

### Cuánto de ese 92 % podría ser ruido *doblado*

El S/H del ADC tiene 750 MHz de ancho de banda y **el único filtro antialias de
la cadena es la caída del front-end a 60 MHz** ([`adc_ltc2145.md`](adc_ltc2145.md)
§2.1). Todo lo que entre por encima de 62.5 MHz se dobla a la banda y se suma a
la línea de base, indistinguible. Con el ruido del front-end blanco hasta mucho
más allá de su propio corte:

| caída del front-end | ENBW de ruido | dentro de Nyquist | fracción doblada | σ con antialias perfecto |
|---|---|---|---|---|
| 1 polo a 60 MHz | 94 MHz | 48 MHz | **49 %** | 3.33 cuentas |
| 2 polos a 60 MHz | 67 MHz | 53 MHz | 20 % | 4.04 cuentas |
| 3 polos a 60 MHz | 63 MHz | 55 MHz | 12 % | 4.22 cuentas |

Es una **cota, no una predicción**: el supuesto de ruido blanco hasta 750 MHz es
justo lo que no está medido, y el orden de la caída del front-end tampoco. Pero
acota el premio: un filtro pasivo a la entrada compra como mucho **×1.34** en σ,
y nunca puede bajar de las 1.28 cuentas del ADC, que entran *después* del filtro.

Hay una asimetría que conviene tener clara y que se confunde seguido:

- **El ruido entre 0 y 62.5 MHz lo saca igual de bien un filtro digital**, y el
  pulso sólo ocupa hasta ~3.5 MHz (`0.35/t_r` con `t_r` = 100 ns). O sea que casi
  todo el blanco es filtrable **en la PL, gratis**: es el `boxcar` del
  experimento B de [`mca/conformado_y_ruido.md`](mca/conformado_y_ruido.md), y
  para el estimador de integral ya está pasando (la ventana *es* el filtro).
- **El ruido de más de 62.5 MHz sólo lo saca un filtro analógico**, porque una
  vez doblado ya no se distingue de la señal. Ésa, y sólo ésa, es la parte que
  justifica poner hardware a la entrada.

### Y la palanca que no cuesta RTL

Las variantes **LN** de la placa (125-14 LN y Z7020 LN) cambian los reguladores
conmutados por lineales en los rieles analógicos. Atacan exactamente este 92 %
sin tocar una línea de RTL ([`adc_ltc2145.md`](adc_ltc2145.md) §9.3). Están
discontinuadas.

---

## 5. El término correlacionado: el que manda en el mejor estimador

### Por qué 0.87 cuentas pesan más que 4.47

Con la compuerta fija de 384 muestras, el blanco se divide por √384 = 19.6 y el
correlacionado —que es prácticamente constante a lo largo de los 3.07 µs de la
ventana, porque su τ es 12 µs— **no se divide por nada**. La descomposición de
[`varianza_estimadores.py`](../software/monte-carlo/varianza_estimadores.py)
sobre la forma real del estímulo, reescalada al σ_c medido en §3 (aquel script
usa su propia estimación, 1.00 cuentas, sacada de las 9 muestras de pre-disparo
del canal con señal; el término es lineal en σ_bl, así que se reescala):

| estimador | término blanco | término de base | término de fase | σ/A total |
|---|---|---|---|---|
| muestra de pico | 0.123 % | 0.045 % | 0.000 % | 0.131 % |
| **integral, compuerta fija** | 0.024 % | **0.069 %** | 0.020 % | 0.075 % |

**En el mejor estimador del instrumento, el 85 % de la varianza es el término
correlacionado**, que es el 3.6 % del ruido total. Ésa es la tesis del documento
en una línea.

### El seguidor de línea de base, modelado con ruido por primera vez

El RTL tiene exactamente la herramienta para atacarlo: un seguidor IIR que resta
la base en vivo. Y **estaba encendido** —
[`campanas/testbench_mca.py`](../software/campanas/testbench_mca.py),
`DEFAULT_CFG = dict(..., bl_auto=True, bl_k=12, ...)`— así que la pregunta no es
si usarlo sino **si está bien configurado**.
[`linea_base.py`](../software/monte-carlo/linea_base.py) lo modela, pero
determinista: sin ruido, para el pedestal por tasa. Nadie había puesto un número
a su ruido propio, y sin eso no había con qué elegir `bl_k`.

El seguidor es ([`mca_pulse_feature.sv`](../modulos/mca/rtl/mca_pulse_feature.sv)):

```
  bl_acc      <= bl_acc + dat - bl_acc_shr      (congelado durante el pulso + holdoff)
  bl_acc_shr  <= bl_acc >>> k                   (registrado: un ciclo más tarde)
  baseline    <= bl_acc_shr[DW-1:0]             (registrado otra vez)
```

y su error tiene **tres** términos, no uno:

| término | fórmula | de qué depende | a k = 9 |
|---|---|---|---|
| ganancia de ruido del IIR | `σ_w·√(α/(2−α))`, `α = 2⁻ᵏ` | baja con k | 0.140 |
| **dither del truncamiento** | `√(p(1−p))`, `p` = parte fraccionaria de la base | **no depende de k** | 0.384 |
| residuo de seguimiento | `σ_c·√(τ_f/(τ_f+τ_c))` | **sube** con k | 0.438 |

Los dos primeros bajan con k y el tercero sube: hay un óptimo. El Monte-Carlo
corre la recurrencia con **aritmética entera exacta** —`>>>` es `floor`, el
acumulador es ancho a propósito, y el freeze durante pulso + holdoff está
modelado— sobre un proceso de ruido que no se postula: su σ y su τ son los
medidos en §3.

| `bl_k` | τ seguidor | σ_pico | σ_int | con 2 bits fraccionarios |
|---|---|---|---|---|
| 4 | 0.1 µs | 0.853 | 0.919 | 0.938 |
| 6 | 0.5 µs | 0.539 | 0.628 | 0.539 |
| 7 | 1.0 µs | 0.524 | 0.606 | 0.520 |
| 8 | 2.0 µs | 0.509 | 0.587 | 0.511 |
| **9** | **4.1 µs** | **0.527** | **0.584** | 0.597 |
| 10 | 8.2 µs | 0.592 | 0.647 | 0.639 |
| 11 | 16.4 µs | 0.683 | 0.686 | 0.674 |
| **12 (el de las campañas)** | **32.8 µs** | **0.728** | **0.757** | 0.716 |
| 13 | 65.5 µs | 0.765 | 0.751 | 0.791 |
| *apagado* (`bl_auto = 0`) | — | **0.87** | **0.87** | — |

Error estadístico de cada σ: ±3.5 % (400 eventos por punto).

Tres cosas que salen de esta tabla y que no son obvias:

1. **El piso del seguidor no es el IIR: es el truncamiento.** Para `k ≥ 8` la
   ganancia de ruido del IIR ya bajó a 0.2 cuentas y lo que queda es el dither
   de entregar la base redondeada a enteros. Y **ese dither no es la uniforme de
   1/√12 = 0.289 que uno escribiría de memoria**: el truncamiento está *dentro
   del lazo*, así que el acumulador guarda la información fraccionaria y la base
   entregada oscila entre los dos enteros vecinos con la frecuencia que marca la
   parte fraccionaria `p`. Su σ es `√(p(1−p))`: **cero si la base cae sobre un
   entero, 0.5 en el peor caso**. Con la base medida del canal con señal
   (5.18 cuentas), 0.384.

   Y de ahí sale una rareza que conviene tener anotada: **ese término depende de
   dónde cae el offset analógico**, que nadie controla ni calibra. Los dos
   canales de la misma campaña tienen bases distintas —5.18 y 5.95 cuentas— y
   eso solo les da dithers de 0.38 y 0.22. O sea que dos canales idénticos
   pueden diferir un 20 % en el término de base del presupuesto por un offset de
   0.8 cuentas. Es inocuo hoy porque no domina, pero explica por qué conviene
   medir `baseline_now` antes que suponerlo (medición 6 de §11).
2. **El óptimo es plano entre k = 6 y 9**, todo dentro del error del
   Monte-Carlo. Así que el ruido no elige el valor: lo elige la cota por abajo,
   que está medida en placa y es que el seguidor no se coma el pie del pulso
   antes de que cruce el umbral ([`API/mca.py`](../software/API/mca.py),
   `mca_set_bl_k`: con un pulso de 62 µs, `k = 6` da 0 eventos y `k ≥ 9` da los
   2000 esperados). **`bl_k = 9` es el más chico verificado y está adentro del
   óptimo.**
3. **El `bl_k = 12` con el que corrieron todas las campañas es una mala
   elección**, y por una razón que sólo se ve con el espectro del ruido en la
   mano: su τ de 32.8 µs pone el codo del seguidor en **4.9 kHz, por debajo de
   los 13 kHz del ruido que tiene que seguir**. Sigue la parte equivocada, y por
   eso saca tan poco: de 0.87 cuentas baja a 0.76, un 13 %. El valor se eligió
   pensando sólo en no comerse el pulso, que es una cota **por abajo**; nunca
   hubo una cota por arriba porque nunca se había medido el espectro de la base.
   Éste es el aporte concreto del documento: **la cota por arriba existe, y vale
   `τ_seguidor ≲ τ_ruido`.**

### Lo que compra, y lo que no

| configuración de la base | σ_bl (pico / int.) | pico: FWHM/A | integral: FWHM/A |
|---|---|---|---|
| sin seguidor, de referencia | 0.87 | 0.309 % | 0.178 % |
| **`bl_k = 12` — lo que corrió** | 0.73 / 0.76 | 0.303 % | **0.159 %** |
| **`bl_k = 9` — propuesto** | 0.53 / 0.58 | 0.297 % | **0.131 %** |
| `bl_k = 9` + 2 bits fraccionarios | 0.53 / 0.60 | 0.297 % | 0.133 % |
| *medido en placa, con `bl_k = 12`* | — | *0.344 %* | ***0.161 %*** |

- **El presupuesto cierra con lo medido en la integral**: 0.159 % predicho
  contra 0.161 % medido, con todos los términos sacados de mediciones
  independientes y ningún parámetro ajustado. Es la validación del modelo.
- **No cierra igual de bien en el pico**: 0.303 % predicho contra 0.344 %
  medido, un 13 % de más que el modelo no explica. No es nuevo —
  [`varianza_estimadores.py`](../software/monte-carlo/varianza_estimadores.py)
  ya predecía 0.250 % contra los mismos 0.344 %— y apunta a algo que le pasa al
  estimador de pico en la placa y no en el modelo. **Queda abierto**, y es una
  razón más para mirar la integral.
- **Bajar `bl_k` de 12 a 9 vale un factor 1.21 en FWHM de la integral**, con
  **una escritura de registro** y sin tocar el bitstream. Es la mejora más
  barata que queda en el instrumento.
- **Para el pico no vale casi nada** (0.303 → 0.297 %), porque ahí manda el
  blanco de una sola muestra. Coherente con §1: el pico no promedia nada, así
  que no le sirve que le saquen el término que no promediaba.
- **Los 2 bits fraccionarios no compran nada a `k = 9`** y por eso la propuesta
  queda descartada: a ese k el que manda es el residuo de seguimiento, no el
  dither. Sólo valdrían la pena si un pulso más corto permitiera bajar a
  `k = 6–8`, donde el dither sí domina (en la tabla, 0.628 → 0.539 a `k = 6`).
  Es un resultado útil igual: **mide que la propuesta no se justifica**, en vez
  de dejarla como idea plausible.

---

## 6. Lo que pone la aritmética de la cadena digital

| término | σ | comentario |
|---|---|---|
| cuantización del ADC | 0.289 cuentas | ya está dentro del SNR; **no se suma aparte** |
| truncamiento de la base | 0 … 0.5 cuentas | §5: dither, **no** uniforme de 1/√12 |
| truncamiento de `q_tot >> cfg_q_shift` | 0.289 LSB del eje | un LSB del eje de amplitud |
| `mca_zoom` | **0** | rebanado de bits exacto: no agrega nada propio |
| bineado del histograma | 0.289 canales | Sheppard: a 6.6 canales/FWHM infla σ un 0.53 % |
| contador de 32 bits | — | satura, no envuelve; a 4 órdenes de magnitud de importar |

El zoom merece una línea porque es contraintuitivo: como la ventana está
alineada a potencias de 2, el mapeo feature → bin es un comparador y una
rebanada, **sin resta ni multiplicación**, así que no hay redondeo que agregue
DNL. Un bin de nivel `z` es la suma entera de dos de nivel `z+1`
([`mca_zoom.sv`](../modulos/mca/rtl/mca_zoom.sv)). Un offset arbitrario, en
cambio, obligaría a resamplear y metería el peine de DNL de
[`mca/limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md) §5.

### El recorte `xc ≥ 0`: un acoplamiento ruido → centroide, y por qué acá es cero

`mca_pulse_feature` satura cada muestra a ≥ 0 antes de acumular (lo necesita el
divisor: protege la invariante `q_tail < q_tot`). Donde la señal vale ~0 eso
**rectifica** el ruido: una variable de media cero pasa a tener media
`σ/√(2π)` = 1.78 cuentas. El sesgo se calibra; lo que no se calibra es que
**depende de σ**, así que un cambio del ruido corre el centroide sin que la
señal haya cambiado. Era candidato a explicar la deriva.

Con el estímulo de la campaña **el término es exactamente cero**: de las 384
muestras de la ventana fija, **una sola** queda por debajo de 2σ, porque la cola
del ARB todavía vale 528 cuentas cuando la compuerta cierra. Y aun en el caso
general la cuenta no alcanza: si `n` muestras quedan en cero el acoplamiento es
`d(q_tot)/dσ = n/√(2π)`, y para que un cambio del 10 % en el ruido corriera el
centroide un 0.1 % harían falta **3206 muestras en cero** — más que cualquier
ventana razonable. **No es el mecanismo que falta en
[`mca/limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md) §6.**

Donde sí hay que tenerlo presente: con una compuerta mucho más larga que el
pulso, o en modo histéresis cuando la cola baja al nivel del ruido.

---

## 7. El reloj

Está entero en [`mca/fuentes_de_jitter.md`](mca/fuentes_de_jitter.md) §2 y el
resultado es que **no hay nada que ganar ahí**: el jitter de apertura del
LTC2145-14 es de 0.08 ps y el del oscilador de 1–10 ps, lo que a `t_r` = 100 ns
da 0.07 cuentas — y **cero en el pico, donde la pendiente se anula**. Contra las
4.56 cuentas de §3 es dos órdenes de magnitud. La única forma de que asome es
que aparezcan pulsos con `t_r < 20 ns`, que es el caso de un preamplificador sin
conformar (§8).

La estabilidad en ppm del oscilador **no es ruido**: es un error de escala del
eje de tiempo, y entra en la deriva, no en el ancho.

---

## 8. Lo que todavía no está en la cadena: el detector

Todo lo anterior se midió con un ARB. Con un detector real aparecen cuatro
fuentes nuevas (filas 1–4 del inventario) y **las dos primeras son mucho más
grandes que todo este documento junto**.

La estadística de portadores da `FWHM = 2.355·√(F·E/ε)` en portadores, con `F` el
factor de Fano y `ε` la energía por portador:

| Detector | A 662 keV | Contra la cadena (0.13–0.31 %) |
|---|---|---|
| NaI(Tl) | ~6–7 % de FWHM | la cadena es **invisible**: aporta < 0.3 % de la varianza |
| HPGe (`ε` = 2.96 eV, `F` = 0.11) | ~0.17 % intrínseco | la cadena es **del mismo orden o peor**: la limita |
| Si(Li), CdTe | intermedios | caso por caso |

De ahí salen dos consecuencias que ordenan las prioridades del proyecto:

1. **Para un centelleador, el trabajo de este documento no compra resolución.**
   `√(7² + 0.3²) = 7.006`. Compra otras cosas —estabilidad, menor umbral
   efectivo, mejor rechazo por forma— pero no ancho de pico.
2. **Para un semiconductor, la cadena es el límite**, y además cambia el
   régimen: un preamplificador de carga sin conformar entrega `t_r` de 10–50 ns
   y pico en punta, que es justo donde la fase de muestreo pasa a valer 6 % de la
   amplitud y el jitter de apertura empieza a asomar
   ([`mca/fuentes_de_jitter.md`](mca/fuentes_de_jitter.md) §7). Ahí **el orden
   de Nicholson vuelve a aplicar** y el conformador analógico (o el trapezoidal
   digital) pasa a decidir el ruido antes de que el ADC lo vea
   ([`mca/conformado_y_ruido.md`](mca/conformado_y_ruido.md), experimento A).

**El presupuesto de este documento es, entonces, el de la electrónica sola**, y
sólo se vuelve el término dominante con un detector de semiconductor.

---

## 9. Estadística de conteo: ruido del espectro, no del pico

Cada bin es una Poisson: `σ = √N`. No ensancha el fotopico —ensancha la
*incertidumbre de dónde está* el fotopico— y es la única fuente de la lista que
las cuentas mejoran.

- La incertidumbre del centroide va como `σ_pico/√N`: a N = 10⁶,
  **0.00042 FWHM**.
- La separación de dos picos vecinos va como `N^(-1/4)`, no como `N^(-1/2)`:
  duplicar el poder resolutivo cuesta **16×** más cuentas.

Las dos están derivadas en
[`mca/limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md) §3 y
su apéndice A, y la lectura que importa acá es la comparación: la deriva medida
es **2.8 × 10⁴ veces** la incertidumbre estadística del propio centroide. El
instrumento no está limitado por varianza; está limitado por un sesgo.

---

## 10. El presupuesto, ordenado

Para el estímulo de la campaña (A = 1920 cuentas, 2 µs de FWHM), por estimador,
en % de la amplitud, y en la configuración con la que corrieron las campañas
(`bl_auto = 1`, `bl_k = 12`):

```
  muestra de pico                        integral, compuerta fija de 384
  ──────────────────────────────         ──────────────────────────────
  blanco (4.47 c, una muestra)  0.123    base, tras el seguidor (0.76 c) 0.060
  base, tras el seguidor (0.73 c) 0.038  blanco (4.47 c / √384)          0.024
  fase de muestreo              0.000    fase (borde de la ventana)      0.020
  ─────────────────────────────────      ──────────────────────────────────────
  σ total                       0.129    σ total                         0.067
  FWHM predicho                 0.303    FWHM predicho                   0.159
  FWHM medido en placa          0.344    FWHM medido en placa            0.161
  sin explicar                 +13 %     sin explicar                   +1 %
```

Tres lecturas:

- **La integral cierra y el pico no.** El 13 % del pico es el único hueco que
  deja el presupuesto, y es anterior a este documento (§5).
- **Los dos estimadores están limitados por fuentes distintas.** El pico, por el
  blanco de una sola muestra: se arregla promediando (un `boxcar` en la PL, o
  conformando). La integral, por el término correlacionado: se arregla
  siguiendo la base.
- **Ningún término del inventario queda sin dueño.** Todo lo demás —reloj,
  cuantización, zoom, recorte, crosstalk— está uno o dos órdenes de magnitud por
  debajo, y ahora con un número cada uno en vez de con un "despreciable".

---

## 11. Qué medir, en orden de costo

Todo falsable, y ordenado por lo que cuesta.

| # | Medición | Qué decide | Costo | Predicción |
|---|---|---|---|---|
| 1 | Repetir la campaña con `bl_k = 9` en vez de 12 | si el seguidor con el codo arriba del ruido lo saca | **una escritura de registro** | integral: 0.161 % → **≈ 0.133 %**; pico: casi igual |
| 2 | Barrer `bl_k` de 6 a 13 con el mismo estímulo | la curva de la figura (b), medida | un barrido | mínimo plano en 6–9, peor hacia 12–13 |
| 3 | Traza larga sin pulser (entrada terminada) y su **PSD** | fija τ_c sin extrapolar, y si hay 1/f debajo de 1 kHz | una captura de 16 k muestras | meseta hasta ~13 kHz y caída |
| 4 | La misma traza con un pasabajos externo de 10 MHz | cuánto del blanco es doblado (§4) | un RC a la entrada | σ baja hasta ×1.34 si el front-end es de 1 polo |
| 5 | σ de la base contra actividad digital (DAC, otro canal) | si el acoplamiento digital es parte del 92 % | dos capturas | — |
| 6 | Leer `baseline_now` (0x024) en corrida | el ruido del seguidor **medido**, no simulado | ya está en el mapa | σ ≈ 0.5 cuentas a `bl_k = 9` |

Y las del montaje (§2.6), que son **la misma captura de la 3** repetida con la
entrada en distintas condiciones:

| # | Medición | Qué decide | Costo | Predicción |
|---|---|---|---|---|
| E-a | La PSD de la 3, mirando si hay **líneas** a 50/100 Hz y a la frecuencia de conmutación | E1, E2 de forma directa | ninguno: es la misma traza | sin líneas de red, por la cota de §2.6 |
| E-b | La misma traza con el generador **desenchufado de la red** | E1, aislado de todo lo demás | desenchufar | σ igual |
| E-c | La misma traza alimentando la placa de una **batería** | separa E2 conducido de E3/E4 radiado | un *power bank* | — |
| E-d | La misma traza con la entrada **terminada en 50 Ω** y con **1 m de coaxial colgando** | si $n_c$ depende de la impedancia de fuente, o sea si entra por el nodo de 1 MΩ ‖ 10 pF | dos tapones | si entra por ahí, **terminar lo hace desaparecer** |
| E-e | σ de la base con y sin **actividad digital** (DAC, canal vecino) | E6 | dos capturas | es la medición 5 |

La **3** es la que más información compra por unidad de trabajo: el τ = 12 µs de
este documento sale de ajustar una caída del 30 % sobre una ventana de 3.7 µs, o
sea de extrapolar. Si el verdadero τ fuera mucho mayor, el seguidor lo sacaría
mejor de lo que predice §5; si fuera menor, peor. **Es el único número del
documento cuya barra de error es grande.**

La **1** es la que hay que hacer primero igual, porque es gratis.

---

## 12. Qué se puede arreglar y qué no

| Palanca | Qué ataca | Costo | Ganancia esperada |
|---|---|---|---|
| `bl_k` de 12 a 9 | el término correlacionado | **nada** | integral ×1.21 en FWHM |
| `boxcar` / conformado en la PL antes del pico | el blanco, para el estimador de pico | RTL + tiempo muerto | pico → ~0.9 cuentas de blanco |
| Pasabajos analógico a la entrada | sólo la parte **doblada** del blanco | un RC | ≤ ×1.34, y nunca por debajo de 1.28 cuentas |
| Placa LN (reguladores lineales) | el 92 % del blanco | conseguir la placa (discontinuada) | sin medir |
| Pedestal de −1 V a la entrada | nada de ruido: gana **un bit de rango** | hardware analógico | ×2 en resolución de amplitud ([`adc_ltc2145.md`](adc_ltc2145.md) §4.3) |
| Cambiar de ADC | el 8 % | cambiar de placa | ×1.07–1.11 ([`adc_ltc2145.md`](adc_ltc2145.md) §9.4) |
| Mejor oscilador | nada | — | **cero** (§7) |
| Más canales de histograma | nada | BRAM | **cero** |

Y lo que **no** se arregla con nada de esto: la deriva del centroide con la tasa,
que es el límite activo y es un **sesgo**, no una varianza
([`mca/limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md) §6).
Este documento aporta a esa discusión un descarte: el recorte `xc ≥ 0` no la
explica (§6).

---

## 13. Supuestos, y lo que este análisis no cubre

- **τ_c = 12 µs sale de extrapolar** una caída del 30 % sobre 3.7 µs, suponiendo
  una sola exponencial. Es el supuesto más débil del documento y el que la
  medición 3 de §11 levanta. Lo que **no** depende de él: que el término existe,
  que vale 0.87 cuentas, y que está por encima de 1 kHz (eso lo fija el test
  entre ventanas, que es directo).
- **El proceso correlacionado se modela como Ornstein-Uhlenbeck**, que es el
  estacionario más simple con autocovarianza exponencial. Si el espectro real
  tuviera varios codos, el óptimo de `bl_k` se correría.
- **El reparto ADC / front-end usa el SNR de hoja de datos**, no una medición del
  conversor aislado — que es imposible en este encapsulado
  ([`adc_ltc2145.md`](adc_ltc2145.md) §1.1).
- **La cota de doblado supone el ruido del front-end blanco** hasta mucho más
  allá de su corte, y una caída de orden conocido. Ninguna de las dos cosas está
  medida.
- **Las filas 1–4 del inventario (el detector) no se modelan**: se citan de la
  literatura para fijar la escala.
- **Los términos de base del presupuesto se reescalan** desde la descomposición
  de [`varianza_estimadores.py`](../software/monte-carlo/varianza_estimadores.py),
  que es lineal en σ_bl. Los términos blanco y de fase se toman de ahí sin
  tocar. Ojo que aquel script estima la base con la media de 9 muestras de
  pre-disparo, que **no** es ninguno de los dos estimadores de la placa: su
  σ_bl = 1.00 se usa como escala y nada más.
- **La fila de `bl_k = 12` está validada contra la placa** (0.159 % predicho
  contra 0.161 % medido en la integral); **las de `bl_k = 9` son predicciones**
  y la medición 1 de §11 las confirma o las refuta.
- **El +13 % del estimador de pico no está explicado** por este presupuesto ni
  por el anterior. Si lo que falta fuera un término de ruido todavía no
  identificado, entraría también en la integral y rompería el acuerdo de la otra
  fila — así que lo más probable es que sea propio del estimador de pico (sesgo
  del `max`, no linealidad cerca del ápice) y no una fuente de ruido faltante.
  Es una hipótesis, no un resultado.

---

## Cómo reproducir

```bash
cd prj/MCA/software
python3 monte-carlo/ruido.py                 # todas las tablas + la figura (~40 s)
python3 monte-carlo/ruido.py --rapido        # menos estadística en el barrido de k
python3 monte-carlo/varianza_estimadores.py  # la descomposición por estimador
```

Las trazas son `datos/e2e_20260528_013404/principal/`, las mismas del análisis de
`API/modelo_rtl/`. La salida va a `datos/ruido_<fecha>/` con `resumen.json` y la
figura.

## Bibliografía

| Ref | Para qué |
|---|---|
| **G. F. Knoll**, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010 | cap. 4 (estadística y factor de Fano), cap. 17 (ruido y conformado) |
| **V. Radeka**, *Low-noise techniques in detectors*, Ann. Rev. Nucl. Part. Sci. **38** (1988) 217 | los índices de forma y la separación serie/paralelo que usa el experimento A de `conformado_y_ruido.md` |
| **V. T. Jordanov, G. F. Knoll**, *Digital synthesis of pulse shapes in real time…*, Nucl. Instrum. Methods A **345** (1994) 337 | el trapezoidal y la cancelación polo-cero |
| **W. R. Bennett**, *Spectra of quantized signals*, Bell Syst. Tech. J. **27** (1948) 446 | por qué el error de cuantización sólo es uniforme y blanco bajo hipótesis que acá **no** se cumplen (§5, el dither del seguidor) |
| Hoja de datos **LTC2145-14** (ADI, `21454314fa`) | SNR, ruido de transición, jitter de apertura |

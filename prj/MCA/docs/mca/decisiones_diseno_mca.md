# Decisiones de diseño del Analizador Multicanal (MCA)

Documento de por qué el MCA quedó como quedó. El **qué** está en
[`register_map_mca.md`](register_map_mca.md) (mapa de registros) y en el RTL;
acá va el **por qué**, incluidas las alternativas que se descartaron y las que
se probaron y fallaron.

Estado: **validado en hardware** (ver §13). Bitstream
`prj/MCA/out/mca_red_pitaya.bit.bin`, simulación con 9 testbenches / 163 checks,
smoke test en placa con 29 PASS / 0 FAIL y dos campañas de caracterización.

Documentos hermanos, para no duplicar:

| Documento | Qué contiene |
|---|---|
| [`register_map_mca.md`](register_map_mca.md) | el **qué**: offsets y bits |
| [`resultados_validacion_hw.md`](../resultados_validacion_hw.md) | los **números medidos** y sus salvedades |
| [`testbenches_software_mca.md`](testbenches_software_mca.md) | el **método** de cada medición |
| [`bus_sistema_redpitaya.md`](../TOP/bus_sistema_redpitaya.md) | el bus sobre el que cuelga |
| [`figuras/`](figuras/README.md) | las **figuras** que explican INL, DNL, FWHM y el bineado |

---

## 1. Motivación

El scope multitrigger ya detectaba pulsos y congelaba ventanas en BRAM, pero
**todo el análisis era offline en NumPy** (`pulses_from_buffer`,
`pulse_metrics`). Eso ata la tasa de eventos al costo de leer 16384 muestras por
evento a través del bus de registros, que además cruza un CDC por acceso.

El MCA mueve la estadística al FPGA: el ARM lee **espectros ya formados** en vez
de formas de onda. Acumula dos indicadores:

1. **Espectro 1D de amplitud de pulso** — el MCA clásico.
2. **Mapa 2D amplitud × factor de forma** (PSD = `Q_cola / Q_total`) — para
   discriminación por forma de pulso.

---

## 2. Qué parámetros hay que caracterizar en un MCA

Esta sección es la que determinó **qué contadores expone el hardware**: sin
ellos, la mitad de las mediciones no se puede hacer. Por cada parámetro va qué
significa, qué implica para la medición, qué quiere decir que salga alto o bajo,
y —lo más útil en la práctica— **si se puede compensar o no**.

Los valores medidos y sus salvedades están en
[`resultados_validacion_hw.md`](../resultados_validacion_hw.md); acá se citan sólo
para dar escala. El método de cada test está en
[`testbenches_software_mca.md`](testbenches_software_mca.md).

> ### La confusión que conviene evitar de entrada
>
> Las tres métricas del eje de amplitud son **independientes** y arruinan cosas
> distintas. Se mezclan todo el tiempo:
>
> | Métrica | Qué arruina | Analogía |
> |---|---|---|
> | **INL** | dónde cae el pico (exactitud) | la regla está mal graduada |
> | **DNL** | cuántas cuentas hay en cada canal (forma) | las marcas de la regla están desparejas |
> | **FWHM** | cuán ancho es el pico (resolución) | la regla está borrosa |
>
> Un espectro con INL alta se ve **perfectamente limpio** y aun así miente la
> energía. Uno con DNL alta tiene picos deformados aunque la energía esté bien.
>
> Las tres, dibujadas sobre el mismo pico:
> [`figuras/04_tres_metricas.png`](figuras/04_tres_metricas.png).

### 2.1 Eje de amplitud

#### Ganancia de conversión y offset de cero

La recta que convierte amplitud en canal, `canal = a·E + b`. Medido: **3927
canales/Vpp** y **−28 canales** de offset.

La ganancia no es "buena" ni "mala" — la elegís con `cfg_h_shift` según cuántos
canales querés por keV. Lo que importa es que **no derive** con el tiempo ni la
temperatura. El offset sí importa conceptualmente: que no sea cero significa que
el espectro **no es proporcional** a la energía y hace falta calibrar con dos
puntos como mínimo. Con −28 canales sobre 3938 (0.7 %), suponer proporcionalidad
te erra 0.7 % arriba y muchísimo más cerca de cero.

**Compensable:** sí, trivialmente — *es* la calibración. Sólo molesta si deriva,
y ahí se re-calibra periódicamente contra una fuente conocida.

#### INL — no linealidad integral

**Qué es.** Cuánto se aparta la relación real amplitud→canal de la **recta
ideal**: el residuo del ajuste lineal, en % del fondo de escala. En
`mca_utils.energy_calibration()` el fondo de escala es **el rango barrido**, no
los 16384 canales:

```
INL = max|residuo| / (canal_max − canal_min)
```

Medido: **1.13 % FS**, o sea **40 canales** de desvío máximo sobre un rango de
3547. La curva, con el FWHM como barra de error y las dos pasadas superpuestas,
está en [`figuras/02_linealidad_inl.png`](figuras/02_linealidad_inl.png). Esa
barra de error, desplegada sobre el eje —el FWHM punto a punto, separado en su
término aditivo y el proporcional—, está en
[`figuras/09_fwhm_vs_eje.png`](figuras/09_fwhm_vs_eje.png).

**Qué implica.** Que si calibrás con dos puntos e **interpolás**, las energías
intermedias salen corridas hasta 40 canales — unos 10 mV, ~1 % de un pulso de
1 V. En espectroscopía eso es **identificar mal un isótopo**: buscás una línea en
662 keV y el pico aparece en 655. La INL **no ensancha** el pico: lo *mueve*.

**Alto/bajo.** Un MCA comercial decente está por debajo de ±0.05 % FS. Nuestro
1.13 % es ~20 veces peor, pero la comparación no es justa: **incluye al
generador** y no se pudieron separar.

**Compensable: sí, y es el caso más compensable de todos**, precisamente porque
es **sistemático** — la pasada de ida y vuelta dio correlación **+1.00** entre
residuos, con dispersión entre pasadas 150× menor que el residuo. Un desvío que
se repite se puede tabular: se calibra con muchos puntos y se ajusta un polinomio
o un spline en vez de una recta, o se guarda la curva de residuos como tabla de
corrección.

> **La salvedad que importa:** sólo se puede compensar la parte que es *del MCA*.
> Como el 1.13 % es generador + ADC mezclados, aplicar la corrección a ciegas
> **inyectaría** el error del DG4162 al medir un detector real.

#### DNL — no linealidad diferencial

**Qué es.** La variación del **ancho de cada canal** respecto del promedio. Se
mide llenando el espectro con amplitud uniformemente distribuida: si todos los
canales fueran iguales recibirían la misma cuenta, así que la desviación relativa
*es* la DNL.

**Qué implica.** Un canal más ancho junta más cuentas y **crea estructura que no
está en la señal**: deforma los picos, sesga área y centroide, y en el peor caso
genera picos falsos. Cuando es periódica (típico de los ADC, en los límites de
bit) produce un rizado regular en todo el espectro.

**Alto/bajo.** La spec típica es <±1 %. Cómo se ve —la regla despareja, la
medición con sliding pulser y el pico deformado— en
[`figuras/03_dnl_esquema.png`](figuras/03_dnl_esquema.png).

> **Dato de diseño:** la DNL del *binado digital* es **exactamente cero por
> construcción** — el bin es un desplazamiento a la derecha de un entero, así que
> todos los canales miden lo mismo. Toda la DNL que midas viene del **ADC y del
> estimador de amplitud**, que es justamente lo interesante.

**Compensable:** parcialmente, con *flat-field*: se divide el espectro por el
mapa de anchos de canal medido, igual que en imagen. Cuesta estadística (el mapa
tiene su propio ruido) y hay que rehacerlo si cambia la ganancia. La alternativa
preventiva es **dithering**: sumar un ruido pequeño y conocido para repartir los
eventos entre canales vecinos.

#### Deriva

Corrimiento de ganancia y offset con el tiempo y la temperatura. Se mide con
adquisiciones repetidas del mismo pico durante horas. **No medida todavía.**

### 2.2 Resolución

#### FWHM y resolución en %

**Qué es.** El ancho a media altura del pico, en % del centroide. Con un **pulser
de amplitud fija** no hay ensanchamiento estadístico del detector, así que lo que
se mide es puramente instrumental: ruido electrónico + digitización + jitter del
estimador. Medido: **6.56 canales sobre 1920 = 0.342 %** — el pico, con el FWHM y
el desvío en la misma imagen, en
[`figuras/01_pico_unico.png`](figuras/01_pico_unico.png); qué le hace el bineado,
en [`figuras/05_bineado.png`](figuras/05_bineado.png).

**Qué implica.** Es el **piso** del sistema. Los anchos se suman en cuadratura:

```
FWHM_total² = FWHM_detector² + FWHM_electrónica²
```

así que ese 0.342 % se resta en cuadratura del ancho total para aislar al
detector. Para un NaI(Tl) (~7 % a 662 keV) es despreciable; para un HPGe (~0.2 %)
es del mismo orden y ahí sí molesta.

**Alto/bajo.** Alto = picos cercanos se solapan y no se pueden separar dos líneas
de energías próximas. Es *la* métrica que define para qué sirve un espectrómetro.

**Compensable: NO.** Es la única de la lista sin arreglo por software: la
resolución perdida está perdida, no hay post-proceso que desensanche un pico sin
inventar información. Sólo se mejora **antes** del histograma — filtrando,
conformando (§5) o integrando más muestras.

#### Ensanchamiento por jitter de muestreo

Se mide comparando los dos estimadores de amplitud sobre el mismo estímulo; ver
§5, donde está también el resultado medido, **que contradijo la expectativa**.

### 2.3 Comportamiento con la tasa

#### Tiempo muerto y live time

**Qué es.** El tiempo después de cada evento en que el sistema no puede aceptar
otro. Hay dos modelos y la diferencia importa:

- **No paralizable:** cada evento aceptado bloquea un τ fijo; la salida **satura**
  en 1/τ.
- **Paralizable:** cada llegada extiende el período muerto aunque no se cuente;
  la curva **tiene un máximo y después baja**. Es el modo peligroso: a tasa muy
  alta contás *menos*, y una fuente intensa parece débil.

Medido: **τ ≈ 0.4 µs/evento**, con live time de 99.5 % a **59.9 %** en 794 kcps.

**Compensable:** la *tasa*, sí, y gratis — para tiempo muerto no paralizable
`tasa_verdadera = cuentas / livetime` es exacta, y por eso el reloj de tiempo
vivo existe en el hardware. Lo que **no** se corrige con un escalar es la
**distorsión del espectro**: apilamiento y corrimiento de línea de base deforman
los picos.

#### Curva de throughput

Tasa registrada vs incidente. Dice a qué actividad de fuente podés trabajar.
Medido: **sigue al generador exacto hasta 794 kcps** sin perder un evento; el
techo no se alcanzó porque se acabó el rango del generador.

#### Resolución par-pulso

**Qué es.** La separación mínima entre dos pulsos para contarlos como dos.
Medido: **≤ 0.5 µs**.

**Qué implica.** Fija el umbral de **apilamiento**. Dos pulsos más cerca se
funden en un evento con amplitud *sumada*: perdés una cuenta y ensuciás el
espectro con un "pico suma" que no corresponde a ninguna energía real.

**Compensable:** no se corrige a posteriori, pero se **detecta y descarta** —
es lo que hace `cnt_pileup` cerrando por `cfg_maxlen`. Descartar es lo correcto:
mejor perder la cuenta que meter una energía falsa.

#### Corrimiento del pico con la tasa

**Qué es.** Cuánto se mueve el centroide entre la tasa mínima y la máxima.

Medido: **+1.28 % sobre un rango de tasa de ×36** (1995 → 72 444 Hz).

> **Ojo con el número que se reporta.** El barrido completo da +6.45 %, pero
> **está confundido con el ancho de pulso**: `sweep_rate` escala el ancho como
> `min(width, 0.2·T)` porque `set_pulse_periodic` exige `width < T/2`, así que a
> tasas altas el estímulo deja de ser el mismo. El salto grande cae **exactamente**
> donde el ancho cambia (72 → 132 kHz, de 2000 a 1517 ns: +2.52 % de golpe), no
> donde cambia la tasa — se ve en
> [`figuras/06_limites_estimulo.png`](figuras/06_limites_estimulo.png), junto con
> el techo de throughput que pone el generador. El único tramo con estímulo constante son los 7 puntos de
> 2000 ns, y ahí el corrimiento es **+1.28 %**. Es el número que hay que citar.

**Qué implica.** La **calibración de energía depende de la actividad de la
fuente**: medís una muestra intensa y otra débil y el mismo isótopo aparece en
canales distintos. La causa es el corrimiento de línea de base a alta densidad de
pulsos, más apilamiento.

**Compensable:** sí — restaurador de línea de base (`cfg_bl_auto`), cancelación
polo-cero, o calibrar a la tasa de trabajo. Con +1.28 % en ×36 de tasa es un
efecto real pero moderado, y hay que volver a medirlo con el detector: es el
argumento principal del conformado trapezoidal, así que de este número depende
que se justifique o no.

### 2.4 Umbral

**Qué es.** La curva S es la fracción de pulsos detectados vs umbral; el punto
del 50 % define el umbral efectivo (LLD). El **piso de ruido** es el umbral
mínimo que se puede poner sin que dispare solo con la entrada terminada.

Medido: corte abrupto en **777 cuentas** y piso de ruido en **57 cuentas**. El
primero es la amplitud del pulso de prueba, así que mide **lo abrupta que es la
curva** (meseta hasta 739, cero en 777: discriminador limpio), no un límite del
MCA. El número intrínseco es el 57.

**Qué implica.** Todo lo que esté por debajo del umbral es invisible. Y ponerlo
demasiado bajo es peor que inútil: con `cfg_thr = 20` se midieron **262 kcps de
puro ruido**, y esos disparos **consumen tiempo muerto** — el MCA se pasa ocupado
sin medir nada.

**Compensable: no**, es un piso físico. Lo que da es el **rango dinámico por
abajo**: entre 57 cuentas y la amplitud de la señal más chica que quieras ver.

### 2.5 Discriminación por forma

**Qué es.** La figura de mérito, sobre la proyección del eje de forma:

```
FOM = |c₁ − c₂| / (FWHM₁ + FWHM₂)
```

Es una separación medida en unidades de ancho. El umbral convencional de **1.27**
no es arbitrario: corresponde a picos separados ~6σ, o sea cada población a 3σ
del punto de corte, con ~0.1 % de clasificación errónea.

Medido: **1.532** global, y por rebanadas de amplitud **1.306 → 1.497 → 1.579**.

**Qué implica.** Que se puede clasificar **evento por evento qué tipo de
partícula** lo produjo, no sólo su energía. Es lo que convierte al MCA en un
discriminador n/γ.

**Alto/bajo.** Por debajo de ~1 las poblaciones se mezclan y la clasificación
deja de ser confiable. La degradación a baja energía que se midió es el
comportamiento esperado: menos fotones en la cola, peor estadística relativa
sobre `Q_cola / Q_total`.

**Compensable:** no se "compensa", se **usa bien**. Como la FOM depende de la
energía, el corte de discriminación no debería ser un umbral único sino una
**línea que dependa de la amplitud** en el mapa 2D — y la medición por rebanadas
es exactamente el insumo para trazarla. Del lado del hardware se mejora ajustando
`cfg_tail_dly` y la ventana de cola.

#### Dos features de forma, y miden cosas distintas

El RTL calcula **dos** cocientes, en paralelo y con el mismo denominador. Las dos
son **invariantes de ganancia** (numerador y denominador escalan juntos), así que
las dos son ejes de forma independientes de la energía — que es la condición para
que un mapa 2D tenga ejes separables.

| | `Q_cola/Q_total` (`F_PSD`) | `Q/P`, implementado como `P/Q` (`F_INVW`) |
|---|---|---|
| Qué mide | La **fracción de carga en la cola**: peso del componente lento, asimetría | El **ancho efectivo**: `Σx / max(x)` es el número equivalente de muestras a altura plena |
| Unidades | Fracción en `[0,1)` | Muestras (su inverso) |
| Sensible a | *Dónde* está la carga | *Cuánta* carga hay por unidad de altura |
| Ruido | Dos integrales, las dos promediadas: buena relación señal-ruido | El denominador es **una muestra** (el pico): arrastra el ruido completo del ADC |
| Error de base | Entra en numerador (`N_cola·ε`) y denominador (`N_tot·ε`): **se cancela parcialmente** | Entra sólo en el numerador (`N·ε`): **sesgo puro** |
| Perilla | Depende de dónde se parte (`gate_short`) | No tiene perilla |

Dos pulsos del mismo ancho pero distinto balance cabeza/cola dan **el mismo `Q/P`
y distinto `Q_cola/Q_total`**. Por eso `Q_cola/Q_total` es el estándar de PSD en
centelladores orgánicos (Brooks 1959; Knoll cap. 17) y `Q/P` es un discriminante
de **ancho** — útil para rechazar apilamiento y ruido, no para separar n/γ.

**Y para apilamiento el estándar no sirve.** Medido por Monte-Carlo sobre el
espectro de una línea a 100 kcps, donde el **40–47 %** de los eventos contiene más
de un pulso y `cnt_pileup` marca entre 0.00 % y 0.45 %:

| Modo de ventana | Discriminador | Continuo sobre el fotopico | Apilados rechazados |
|---|---|---|---|
| 0 (histéresis) | *sin corte* | 32.4 % | — |
| 0 | **`Q/pico`** | **0.8 %** | **99.1 %** |
| 0 | `Q_cola/Q_tot` | 28.9 % | 29.6 % |
| 1 (compuertas) | *sin corte* | 22.7 % | — |
| 1 | `Q/pico` | 7.2 % | 45.6 % |
| 1 | `Q_cola/Q_tot` | 22.7 % | **0.0 %** |

`Q_cola/Q_total` rechaza **exactamente nada** en modo compuerta: con
`gate_short = 32` medido desde el disparo, la cola se lleva el 94 % de la carga,
el cociente vive en 60/64 y le quedan **tres valores útiles de los 64** del eje.
No hay rango dinámico para discriminar. Ver
[`software/monte-carlo/`](../../software/monte-carlo/).

**Y hay una tensión de diseño que conviene tener explícita**: lo que hace bueno
al modo compuerta para la *resolución* —que el largo no dependa de la señal, ×1.91
mejor (§14.1b de los resultados)— es exactamente lo que lo deja **ciego al
apilamiento**, porque la ventana no se estira cuando llega el segundo pulso y las
dos poblaciones se cruzan en el eje de forma. La combinación que gana para
apilamiento es **modo histéresis + corte por `Q/pico`**.

**Por qué `P/Q` y no `Q/P`.** El divisor restaurador exige `num < den`, y
`Q/P > 1` no entra. `P/Q` sí, porque `q_tot = Σxc ≥ max(xc) = peak` siempre. Es la
misma información, monótona decreciente en vez de creciente. Cuesta un segundo
`mca_div_restore`, **en paralelo** con el primero: los dos arrancan al cerrar y
terminan juntos, así que no agrega ni un ciclo de tiempo muerto, y cero DSP.

**El cociente se amplió de 6 a 16 bits** (`DIV_W`). Con 6 no había rango para el
ancho: los valores útiles de `Q/P` van de ~250 (limpio) a ~1200 (apilado), o sea
`P/Q ∈ [0.0008, 0.004]`, que con 6 bits se cuantiza a **cero**. Con 16 caen en
`[52, 262]`, que sí separa las poblaciones. El eje del mapa 2D sigue teniendo
`PSD_AW` bits tomando los **bits altos** del cociente, y eso es **bit-exacto**
respecto del comportamiento anterior —`floor(floor(a·2¹⁶/b)/2¹⁰) = floor(a·2⁶/b)`—
así que ampliar el divisor no movió ni un evento del mapa ya caracterizado.

### 2.6 Una que no es métrica pero rompe todo

La **constante del seguidor de línea de base** (`cfg_bl_k`): si 2^k·8 ns es
comparable a la duración del pulso, el seguidor **persigue la señal y la borra**
— nunca cruza el umbral y no se cuenta nada. No da un número malo: da **cero**,
en silencio. Por eso hay que barrerlo cada vez que cambia la duración del pulso.

---

**Consecuencia de diseño:** para que todo lo anterior sea medible, el hardware
expone `cnt_total`, `cnt_accepted`, `cnt_rej_amp`, `cnt_rej_psd`, `cnt_pileup`,
`cnt_dropped` y tres relojes de 64 bits (`realtime`, `livetime`, `deadtime`).

---

## 3. Dónde conectarlo: bus de sistema, slot 7

**Decisión: slot 7 del bus personalizado, base `0x4070_0000`.**

No había alternativa real:

- **`M_AXI_GP0` *es* ese bus** (`red_pitaya_ps.sv:404-416` → `axi4_slave` →
  `ps_sys` → el interconnect de 8 slots). No es un puerto libre.
- **`M_AXI_GP1` ya lo consume el XADC** dentro del block design
  (`prj/MCA/ip/systemZ10.tcl:849-850`, mapeado en `0x83C0_0000`) y ni siquiera
  sale al top level.
- **Los 4 puertos AXI-HP están tomados**: HP0/HP1 por el scope, HP2/HP3 por el
  ASG.

El interconnect decodifica `bus.addr[22:20]`
(`rtl/sys_bus_interconnect.sv:50-51`) → 8 slots de 1 MB desde `0x4000_0000`. Los
slots 6 y 7 estaban libres (`sys_bus_stub`).

**Por qué el 7 y no el 6:** el stub del slot 6 vive dentro de un
`` `ifdef Z20_G2 / `else `` (`red_pitaya_top.sv:705-751`), así que el MCA
desaparecería silenciosamente en esa variante. El del slot 7 es una línea
incondicional. Además el XDC ya trae las 32 restricciones CDC de
`for_bus[0..7]`, así que el slot 7 queda constrained sin tocar nada.

**Latencia:** cada acceso cruza `sys_bus_cdc` (~8-12 ciclos ida y vuelta). Es la
misma penalidad que paga el scope hoy, y una conexión GP directa no sería más
rápida. Irrelevante acá: leer un espectro una vez por segundo no es cuello de
botella — a diferencia de leer 16k muestras por evento, que era el problema
original.

---

## 4. Presupuesto de memoria

**Unidad de cuenta:** un RAMB36 son 36 Kb configurables como 1024×36, o sea
**1024 bins de 32 bits = 4 KB**. Toda la aritmética de dimensionamiento sale de
ahí.

**Ancho de contador: 32 bits.** A 100 kcps concentrados en un pico, saturar un
bin lleva ~12 horas. Con 18 bits serían 44 minutos: no vale la pena ahorrar.
Los contadores **saturan**, no envuelven.

### Configuración instanciada

| Motor | Parámetros | Bins | RAMB36 |
|---|---|---|---|
| Espectro 1D | `H_AW = 14` | 16384 | 16 |
| Amplitud × forma | `H2_AW = 7`, `PSD_AW = 6` | 128 × 64 | 8 |
| | | **Total MCA** | **24** |

Utilización final del bitstream: **40/60 RAMB36 (67%)**, 33% LUT, 58% slices.

### Justificación de los tamaños

- **16384 canales en el 1D**: sólo se justifica con el estimador de integral
  (§5). Con la muestra de pico, el ruido de una sola muestra hace que todo lo
  que pase de ~4096 canales sea sobremuestrear ruido.
- **64 bins en el eje de forma**: un gráfico PSD sirve para **separar
  poblaciones**, no para resolver. 64 bins dan 1.56% de resolución en
  `Q_cola/Q_total`, contra separaciones típicas del 10-20%.
- **128 bins de amplitud en el 2D**: grueso a propósito. Con `H2_AW = 12` el
  mapa sería 2^18 bins = **256 RAMB36**, imposible. El detalle en amplitud vive
  en el espectro 1D; el eje del 2D es un rebineado configurable
  (`cfg_h2_shift`).

### Lo que liberó espacio

Sacar el ASG del top del MCA liberó ~17 RAMB36 (dos tablas de onda de 16384×14b
más los FIFOs). Sin eso, los dos indicadores no entraban juntos y habría hecho
falta elegir uno.

**Si 40/60 llegara a ser poco**, sacar el ASG además libera HP2/HP3, con lo que
acumular en DDR por AXI-HP pasa a ser viable. Es un motor DMA aparte y quedó
fuera de alcance, pero la puerta está abierta.

---

## 5. El estimador de amplitud — la decisión más importante

**Más bins no dan más precisión por sí solos.** Lo que la da es cómo se estima
la amplitud, y por eso el registro `cfg_amp_src` existe.

- **Muestra de pico** (`cfg_amp_src = 0`): la amplitud sale de *una* muestra, o
  sea arrastra el ruido completo del ADC. Peor: el muestreo casi nunca cae en el
  máximo verdadero, y esa subestimación variable **ensancha el fotopico** por
  razones puramente instrumentales. A 125 MSPS con subida de 100 ns hay ~12
  muestras en el flanco y el error es chico; con subida de 20 ns hay 2.5 y es
  severo.
- **Integral de carga** (`cfg_amp_src = 1`, `Q_total >> cfg_q_shift`): el ruido
  blanco promedia como σ/√N y desaparece el jitter de muestreo. Es lo que hace
  cualquier MCA digital serio. Con N = 256 muestras, `Q_total` tiene ~21 bits
  significativos: **ahí sí** los 16384 canales están justificados.

Poder alternar entre los dos **en el mismo bitstream** no es un lujo: *es* el
experimento que mide la contribución de jitter de muestreo
(`compare_estimators()` en `testbench_mca.py` lo barre contra el ancho del
pulso).

### Lo que dijo la medición: con este estímulo, la integral es PEOR

Con `cfg_q_shift` auto-escalado para que los dos estimadores caigan en la misma
escala de canales — sin eso la comparación no significa nada, porque un shift
grande comprime el pico en pocos canales y el FWHM se cuantiza:

| Ancho de pulso | Resolución con pico | Resolución con integral |
|---|---|---|
| 0.5 µs | **0.44 %** | 0.54 % |
| 1 µs | **0.37 %** | 0.53 % |
| 2 µs | **0.34 %** | 0.53 % |
| 4 µs | **0.33 %** | 1.15 % |

**Es lo contrario de lo que decía la tesis de arriba**, y la razón es que la
integral gana cuando el estimador de pico sufre jitter de muestreo — y acá no lo
sufre. Un pulso de 2 µs son **250 muestras a 125 MSPS**: la muestra de pico cae
prácticamente en el máximo verdadero, no hay error que corregir. La integral, en
cambio, acumula el error de línea de base sobre toda la ventana y hereda el
jitter del cierre de la ventana.

La tendencia confirma el mecanismo y salva la tesis para el caso que importa: al
acortar el pulso de 4 µs a 0.5 µs la resolución con pico **empeora** (0.33 →
0.44 %) mientras la de la integral se mantiene plana. Se cruzarían por debajo de
~0.2 µs, que es donde el ARB del DG4162 ya no llega. **Con pulsos de detector
rápidos la integral debería ganar; con este estímulo sintético, no.**

Conclusión de diseño: `cfg_amp_src` sigue justificándose —es el registro que
permite decidirlo **midiendo** en vez de suponiendo—, pero el default razonable
es **muestra de pico** hasta tener pulsos reales que digan otra cosa.

> **Fuera de alcance, pero es el paso siguiente natural:** el conformado
> trapezoidal (Jordanov-Knoll) es el estándar real para espectroscopía de alta
> resolución — corrige el déficit balístico y el corrimiento de línea de base a
> alta tasa, que es el corrimiento de centroide de §2.3 (+1.28 % en ×36 de tasa,
> **no** el +6.45 % del barrido completo, que está confundido con el ancho).

---

## 6. Arquitectura RTL

Cuatro módulos en [`prj/MCA/rtl/mine/mca/`](../../rtl/mine/mca/), todos en el
dominio `adc_clk`. El cruce a `clk_fpga_0` lo hace `sys_bus_cdc` por slot, así
que no hay CDC propio.

### `mca_hist.sv` — motor de histograma genérico

Una sola implementación, instanciada N veces. Memoria inferida **simple dual
port**: puerto A sólo escritura, puerto B sólo lectura.

**Por qué no un read-modify-write de 3 estados** (como el `axis_histogram.v` de
pavel-demin que estaba en el repo): un puerto de BRAM tiene UNA dirección por
ciclo, así que no puede leer `addr(n)` y escribir `addr(n-2)` a la vez. Con la
lectura en el puerto B y la escritura en el A se consigue **1 incremento por
ciclo**; el de 3 estados acepta 1 evento cada 3 y obligaría a decimar un futuro
mapa de persistencia.

**Forwarding de 2 etapas**: el evento que lee en el ciclo *m* tiene su dato en
*m+1* y escribe en *m+2*. Un evento a la misma dirección en *m+1* o *m+2* leería
un valor viejo, así que hay que puentear la escritura en vuelo (distancia 1) y
la del ciclo anterior (distancia 2). A distancia ≥3 la memoria ya está
actualizada.

**El barrido de borrado usa sólo el puerto de escritura**, así que el de lectura
queda vivo durante todo el barrido. Es un requisito duro: un barrido de 16384
bins son 131 µs, ~500 veces el timeout de 32 ciclos de `rtl/axi4_slave.sv:193`.
Si frenara el ack, el bus se colgaría.

### `mca_pulse_feature.sv` — segmentador y extractor

Emite **un registro de evento coherente** `{amp, psd}` por pulso. Que salga de
un único registro es lo que garantiza que el espectro 1D y el mapa 2D cuenten
exactamente los mismos pulsos.

- **Línea de base**: seguidor IIR `bl_acc += x − (bl_acc >> k)` con acumulador
  ancho. Con la forma ingenua `bl += (x−bl)>>k` el incremento se cuantiza a cero
  cuando `|x−bl| < 2^k` y el seguidor se congela. Se congela durante el pulso
  **y durante `cfg_bl_holdoff` muestras después**: si se descongelara al cruzar
  la histéresis hacia abajo, agarraría el undershoot de la cola y arrastraría la
  base hacia el lado equivocado.
- **Segmentación**: Schmitt igual que `rp_adc_trig.v`, para que los umbrales del
  MCA y del scope sean comparables.
- **Pico con comparación estricta (`>`)**: en un techo plano con ruido gana la
  *primera* ocurrencia. Con `>=` el instante de pico se correría hasta el final
  de la meseta.
- **Apilamiento**: si la ventana llega a `cfg_maxlen`, el evento se cuenta en
  `cnt_pileup` pero **no** se histogramea — su integral y su pico están
  contaminados por el segundo pulso.
- **Cargas**: cada muestra se satura a ≥ 0 antes de acumular. Sin eso, una cola
  con undershoot resta de `Q_total` mientras `Q_cola` sigue sumando, y se llega
  a `Q_cola > Q_total`, que rompe la premisa del divisor.

### `mca_div_restore.sv` — el divisor del factor de forma

Calcula `q = floor(Q_cola · 2^PSD_AW / Q_total)`.

**El truco**: como `Q_cola < Q_total`, arrancando con `rem = Q_cola` y haciendo
`rem = 2·rem; if (rem >= Q_total) { rem -= Q_total; q |= 1; }` se obtiene un bit
de cociente por iteración. Hacen falta **exactamente `PSD_AW` iteraciones sin
importar el ancho de los operandos**, y no hace falta normalizar previamente.
Con `PSD_AW = 6` son 6 ciclos y **cero DSP**.

Latencia **fija** de `PSD_AW` ciclos incluso en los casos de error: es
deliberado, hace predecible el tiempo muerto por evento (uno de los parámetros
a caracterizar).

Tres casos borde que rompen si no se tratan, y que el testbench barre
exhaustivamente (32640 combinaciones):

| Caso | Sin la guarda | Con la guarda |
|---|---|---|
| `Q_total == 0` | `rem >= 0` siempre true → cociente todo unos → **todos esos eventos al bin superior** | `err_o`, evento rechazado y contado |
| `Q_cola == Q_total` | cociente `2^PSD_AW`, no entra en `PSD_AW` bits y **envuelve a 0** → evento al extremo *opuesto* del eje | satura a `2^PSD_AW − 1` |
| `Q_cola == 0` | — | `q = 0`, resultado válido |

### `mca_top.sv` — esclavo de bus

Instanciación condicional por parámetro (`EN_HIST_H`, `EN_HIST_H_PSD`), con la
rama `else` alimentando `32'h0` al mux de lectura. El RTL deja lugar para dos
motores más que quedaron apagados por defecto: **amplitud × tiempo de subida** y
**mapa de persistencia** (amplitud × tiempo dentro del pulso). Agregarlos es
cambiar un parámetro, no reescribir.

---

## 7. El idioma del esclavo de bus (y el bug que evita)

**Ack de latencia fija a los 4 ciclos para *cualquier* dirección**, desde un
shift register incondicional. **No existe ninguna ruta de ack por motor.**

Esto es deliberado y no cosmético. Un esclavo que no hace ack **no produce sólo
una lectura mala: deja el CDC del slot desincronizado** — `reg_done` sólo avanza
con `bus_m.ack`, así que sin ack el handshake queda trabado y ese slot no acepta
más transacciones. Al ARM lo rescata el timeout de 32 ciclos de
`rtl/axi4_slave.sv:193`, pero la lectura devuelve un valor sin sentido y sin
ninguna indicación de error. El mecanismo completo está en
[`bus_sistema_redpitaya.md`](../TOP/bus_sistema_redpitaya.md) §7.1.

El scope **tenía** un bug exactamente de esa clase: ataba
`bram_ack[2]/[3] = 0` para los canales no construidos
(`rp_scope_multitrigger_com.sv:572-573`) y el viejo
`multitrigger_rp_scope_cfg.sv:506-507` lo usaba como ack de las aperturas de los
canales 2 y 3, así que cualquier lectura en `0x4013_0000`–`0x4014_FFFF` colgaba
el slot. **Está ARREGLADO**: `osc_cfg.sv` reemplazó a ese módulo y saca el ack
de un shift register incondicional, igual que el MCA. Ver
[`../osc/register_map_osc.md`](../osc/register_map_osc.md).

En el MCA, un motor apagado por parámetro simplemente devuelve 0 en su apertura;
no hay forma de colgar el bus.

`tb_mca_top.sv` es la regresión contra eso: un BFM que imita a `sys_bus_cdc`
(sostiene `wen`/`ren` hasta el ack) y **falla el test si el ack no llega en ≤20
ciclos**, barriendo registros, huecos, aperturas, offsets fuera de rango,
motores apagados y direcciones no mapeadas — con dos DUT de parámetros
distintos.

Otras dos cosas que impone el entorno:

- **Estrobo de escritura de un ciclo.** `sys_bus_cdc` sostiene `wen` hasta el
  ack (~5 ciclos); sin estrobo, cada transacción ejecutaría el `case` 5 veces y
  `clear` quedaría activo 5 ciclos en vez de uno.
- **`sys_rdata` tiene que ser un registro plano.** El XDC trae un
  `set_false_path` sobre `inst_sys_bus_cdc/reg_rdata*`, pero `sys_bus_cdc.sv` no
  tiene ese registro (hace un `assign`), así que la restricción **no engancha
  nada** y el cruce de datos de lectura se timea de verdad, con 0.94 ns de
  margen. Nada de lógica combinacional ancha ahí.

---

## 8. El ecualizador `osc_filter`: qué se intentó y por qué se abandonó

Ésta es la parte que más tiempo llevó y la que más vale documentar.

### El problema

El diseño **ya no cerraba timing antes de tocar nada**: WNS −1.820 ns, 221
endpoints en falla. De ésos, **137 (62%) estaban en las dos instancias de
`osc_filter`, y se llevaban toda la severidad** (−1.820 y −1.672 ns; el resto no
pasaba de −0.2 ns).

El camino crítico es el lazo IIR (`osc_filter.v:129-141`):

```
aa_mult = r3_reg_dsp1 * coeff_aa;
r3_sum  = (r2_reg <<< 23) + (r3_reg_dsp2 <<< 25) - aa_mult;
r3_reg_dsp1 <= r3_sum >>> 25;
```

Registro → multiplicador DSP → suma de 48 bits → vuelta al registro, **todo en
un ciclo**: 15 niveles de lógica (12 CARRY4 + 1 DSP), **9.421 ns contra 8 ns de
período**, con el 70% del retardo en lógica y sólo 30% en ruteo.

### El malentendido que hubo que aclarar

La señal **no** "pasa de largo" el filtro cuando no está configurado. Son dos
cosas distintas:

1. `set_filt_byp` (registro 0x98) **resetea a `4'h0`**
   (`multitrigger_rp_scope_cfg.sv:317`): por defecto `adc_dec_in = adc_filtered`,
   o sea los datos **sí** atraviesan el filtro.
2. La respuesta unitaria con los coeficientes por defecto es un **resultado
   matemático, no un bypass**: con `bb=0` la primera etapa queda como derivador
   y con `aa=0` la segunda como integrador, y se cancelan. Pero la señal recorre
   físicamente todas las etapas en cada muestra.

Y los endpoints en falla dentro del filtro **no son sólo los del `aa_mult`**:
incluyen `r5_reg_*` (el registro de **salida**) y `pp_mult_*`, que están activos
con cualquier configuración porque `kk = 0xFFFFFF ≠ 0`. O sea que **aplica
siempre**.

### Los dos intentos de rediseño, y por qué fallaron

Ambos verificados **bit a bit** contra una copia congelada del original
(`prj/MCA/sim/osc_filter_ref.v` + `tb_osc_filter.sv`, 10 casos: coeficientes por
defecto, extremos de `aa`/`pp`/`kk`, todos al máximo, 12 juegos aleatorios).

| Intento | Idea | Resultado |
|---|---|---|
| Original | — | −1.820 ns / 221 endpoints |
| **1** | Identidad `(y<<<25) − y·aa ≡ y·(2^25 − aa)`, para dejar un solo `P = C + A·B` | **−3.514 ns**: el coeficiente pasa a 27 bits, el multiplicador de 23×27 no entra en un DSP48E1 y Vivado lo parte en **dos DSP en cascada dentro del lazo**, más lento que la cadena de acarreo que eliminaba |
| **2** | Reasociar: `p = (r2<<<23) − aa_mult` en el DSP y `+ (y<<<25)` en fabric | **−1.957 ns**: sigue quedando un sumador en el lazo |

También se probó un `set_multicycle_path` con re-implementación completa:
−1.820 → −1.160. **No sirve**: el lazo es genuinamente de un ciclo y no se puede
relajar; el registro de coeficiente aparecía como origen sólo por atribución.

**Conclusión: es una limitación estructural, no de codificación.** Un IIR de un
polo con coeficiente general necesita multiplicación + suma en un ciclo, y a
125 MHz en un `-1` eso es marginal por diseño.

### La decisión

**El MCA no instancia el filtro.** Parámetro `EN_FILT` en
`rp_scope_multitrigger_com`, con **default 1** para que el bitstream del scope
no cambie de comportamiento; el top del MCA lo pone en 0.

Motivos:

- Elimina los 137 endpoints severos del build del MCA y libera DSP.
- Para espectroscopía el ecualizador de respuesta del ADC no hace falta.
- Con los coeficientes de reset era pass-through de todos modos.
- **Cero riesgo sobre el diseño que ya funciona**: un rediseño con desenrollado
  del lazo (look-ahead) sí cerraría, pero cambia el redondeo, y con un polo en
  ~0.996 (Q≈250, prácticamente un integrador) los errores de redondeo **se
  acumulan** en vez de promediarse. Validar eso exige medir la respuesta en
  frecuencia en la placa.

**Queda pendiente**: el bitstream del scope sigue con su WNS de −1.820 ns
preexistente. Mitigación gratis mientras tanto: escribir `0x98 = 0x3` hace que
el mux tome la señal pre-filtro, con lo que nadie consume la salida del filtro.

---

## 9. Cómo se construye

`red_pitaya_vivado_Z10.tcl` lo usan **los 18 proyectos de `prj/`** y es un
archivo de upstream que sigue recibiendo cambios, así que **no se toca**. En su
lugar hay una copia, [`red_pitaya_vivado_Z10_mca.tcl`](../../../../red_pitaya_vivado_Z10_mca.tcl),
con **cinco diferencias** de una línea:

| # | Cambio | Por qué |
|---|---|---|
| 1 | `synth_design -top mca_red_pitaya_top` | el top nuevo |
| 2-3 | `write_bitstream` → `mca_red_pitaya.bit` / `.bin` | que no pise los artefactos del scope |
| 4 | `write_sysdef -bitfile/-file` → `mca_red_pitaya.*` | el original referencia el `.bit` **por nombre**: sin este cambio apunta a un archivo inexistente |
| 5 | `add_files` de `sdc/red_pitaya_mca.xdc` | restricciones propias del MCA |

```bash
vivado -nojournal -mode batch -source red_pitaya_vivado_Z10_mca.tcl -tclargs MCA
```

**No hace falta regenerar FSBL ni device tree**: ambos salen de la configuración
del PS7 (`ip/systemZ10.tcl`), que es la misma en los dos tops.

El encabezado de la copia documenta de qué commit salió, para que
re-sincronizar ante un cambio de upstream sea mecánico.

### El top del MCA

[`mca_red_pitaya_top.sv`](../../rtl/mine/tops/mca_red_pitaya_top.sv) es una copia de
`red_pitaya_top.sv` con cinco diferencias: `mca_top` en el slot 7, `i_scope` con
`EN_FILT(0)`, **sin ASG (slot 2) ni PID (slot 3)**, y —desde el refactor del
mapa de registros— `multitrigger_cfg` en el slot 3 e `integration_cfg` en el 6.
Que el ASG y el PID no estén es justamente lo que deja libre el slot 3 para el
multitrigger; en `red_pitaya_top`, que sí los conserva, el multitrigger va al
slot 7 (ver [`../TOP/register_map_top.md`](../TOP/register_map_top.md)).

Conserva a propósito la lista de puertos y los nombres de instancia `i_ams` y
`sys_bus_interconnect`, **porque el XDC engancha por esos nombres**
(`sdc/red_pitaya.xdc:1` para el LOC del XADC, y las 32 restricciones CDC de
`for_bus[0..7]`).

Lo que se pierde al sacar el ASG: las salidas del DAC quedan mudas y desaparece
`trig_asg_out`, o sea las fuentes de disparo `BIT_ASG_P`/`BIT_ASG_N` del OR-mask
del scope. Con el estímulo migrado al Rigol DG4162 por USB, no molesta.

---

## 10. Bugs encontrados por los testbenches

Cuatro de diseño, todos corregidos. Se documentan porque son la justificación de
haber escrito los testbenches antes de sintetizar.

1. **La línea de base absorbía la primera muestra de cada pulso.** `st` todavía
   vale `S_IDLE` en el flanco en que se abre el pulso, así que el IIR se comía la
   muestra del flanco de subida. A tasa alta eso arrastra la base hacia arriba de
   forma sistemática y **corre el centroide de todo el espectro**.
2. **El re-armado Schmitt sólo ocurría en `S_IDLE`.** Si la señal volvía a la
   base durante los 6 ciclos del divisor y subía otra vez, el pulso se perdía
   **en silencio**, sin contarse ni siquiera en `cnt_lost_busy`.
3. **Abría a mitad del pulso siguiente** tras liberarse el divisor, midiendo una
   amplitud truncada que habría metido una **cola espuria de baja energía** en el
   espectro. Ahora se desarma si la señal cruza el umbral mientras el módulo está
   ocupado: se pierde el pulso entero pero se cuenta, que es un tiempo muerto
   medible y corregible.
4. **En `mca_hist`, el dato de lectura vivía un solo ciclo.** El puerto B vuelve
   a la dirección del pipeline de incremento apenas baja `rd_i`, y como el ack
   llega 4 ciclos después, **toda lectura devolvía el bin del último evento** en
   vez del pedido. El espectro entero se habría leído como un valor repetido.
   Se corrigió con un enable en el registro de salida.

Además, dos errores de *test* que vale la pena recordar: el BFM no esperaba a
que bajara el `ack` de la transacción anterior (muestreaba datos viejos), y el
estímulo inicial no armaba el Schmitt antes del primer pulso.

---

## 11. Evolución del timing

| Etapa | WNS | Endpoints |
|---|---|---|
| `red_pitaya_top` (referencia, con ASG y filtro) | −1.874 ns | 650 |
| MCA inicial | −0.674 | 266 |
| + línea de base y desplazador registrados | −0.313 | 106 |
| + multicycle en los registros de config | −0.260 | 60 |
| + registro de entrada en `mca_top` | **−0.114** | **14** |

De los 14 finales: **6 en `ps/system_i`** (el `axi_protocol_converter` del block
design de Xilinx, preexistente, peor −0.114) y **8 en `i_mca/i_feat`** (peor
−0.057 ns, 0.7% del período). **El peor camino del diseño ya no es del MCA.**

Dos aprendizajes concretos:

- El registro de entrada de `mca_top` fue el cambio de mayor impacto: cortaba el
  camino que venía desde el registro de salida de la calibración del scope y
  atravesaba el mux de canal, el decimador y toda la lógica de umbral. 34 de 60
  endpoints.
- **El parser de XDC de Vivado no soporta `if`**
  (`CRITICAL WARNING [Designutils 20-1307]`). Una guarda condicional anula la
  restricción **en silencio**: la primera versión de `red_pitaya_mca.xdc` no hizo
  nada y el timing no se movió.

### Sobre la restricción multicycle

Los registros de configuración del MCA los escribe el software y cambian a lo
sumo una vez por adquisición. El caso que la motiva es `cfg_q_shift`: alimenta un
barrel shifter de 32 bits seguido de los comparadores de la ventana de amplitud
y la lógica de control — 91 de 106 endpoints nacían ahí.

Es **legítima** acá, a diferencia del caso de `osc_filter`: allá el registro de
coeficiente aparecía como origen pero el camino real era el lazo **recursivo**
del IIR (que sí necesita cerrar en un ciclo). Acá el camino es genuinamente
cuasi-estático.

Única consecuencia: reconfigurar **en medio** de una adquisición puede dar
valores mezclados durante ~4 ciclos. `mca_utils.MCA.configure()` escribe con
`run = 0` y después arranca, así que no se da.

---

## 12. Software

Misma separación que ya existía entre `multitrigger_utils.py` (driver) y
`testbench_multitrigger.py` (mediciones):

- [`API/mca.py`](../../software/API/mca.py) — `class MCA` (mmap de `/dev/mem`,
  `identify()`, `configure()`, `acquire()`) más helpers de análisis **puros**
  (`gauss_fit_peak`, `energy_calibration`, `dnl`, `fom`, `deadtime_fit`). Los
  helpers no tocan hardware a propósito: se validan contra `.npz` guardados, sin
  la placa. Están verificados contra datos sintéticos de parámetros conocidos.
- [`testbench_mca.py`](../../software/campanas/testbench_mca.py) — un test por parámetro de
  §2, con CLI y graficado. **Qué mide cada uno y qué resultados son creíbles está
  en [`testbenches_software_mca.md`](testbenches_software_mca.md)**; acá van sólo
  las decisiones que condicionan el diseño.
- `rigol_dg4162.py` — se le agregó soporte de **forma de onda arbitraria**, sin
  el cual no se puede sintetizar un pulso de detector realista, ni las dos
  poblaciones con colas distintas que hacen falta para medir la FOM, ni el
  sliding pulser de la DNL.

  De la guía de programación de la serie DG4000, **dos cosas no existen en este
  firmware** (00.01.05) y se descubrieron contra el instrumento: `:DATA:CATenate`
  para trocear la forma (hay que mandar los 16384 puntos en un solo comando) y
  **toda la modulación** (`:SOURce1:MOD:STATe ON` responde `-113, "Undefined
  header"`). Lo segundo es lo que deja la DNL sin poder medirse: hace falta
  amplitud continua y sólo se puede conseguir desde el panel frontal.

  Corolario del driver: la cola de errores SCPI es **FIFO** y `assert_ok()` saca
  uno solo, así que un método que manda 5 comandos rechazados deja 4 errores que
  el próximo `assert_ok()` le achaca a un comando que funcionó bien. Para eso
  está `clear_errors()`.

Dos detalles heredados del driver del scope que hay que respetar:

- **Escrituras por asignación de slice, no `struct.pack_into`.** `pack_into`
  hace un `memset` previo que sobre memoria de dispositivo sale como stores de a
  byte; el esclavo AXI no los reconoce y el puente GP0 tira un *external abort* →
  SIGBUS.
- **Los contadores de 64 bits se leen palabra baja primero**: leer `lo` congela
  `hi` en un registro sombra del RTL. Al revés la lectura se parte.

---

## 13. Validación en hardware

Hecha sobre la placa (10.73.28.27) con el DG4162 en IN1, en dos campañas. **Los
números completos, con sus salvedades y con las correcciones de la segunda
campaña sobre la primera, están en
[`resultados_validacion_hw.md`](../resultados_validacion_hw.md)** — acá va sólo lo
que valida el *diseño*:

| Lo que valida | Resultado |
|---|---|
| El esclavo de bus y su ack de latencia fija (§7) | barrido de 646 direcciones, **ninguna cuelga el bus**, 6.1 µs c/u |
| El barrido de borrado sin frenar el ack | 16384 canales en **0.2 ms** |
| Los tres relojes | `livetime + deadtime = realtime` exacto; 1.0014 s medidos contra 1.0 s |
| **El camino de datos completo** | conteo **10010 contra 10010 esperados, error 0.00 %** |
| El segmentador a alta tasa | sigue al generador **exacto hasta 794 kcps**, sin perder un evento |
| El divisor y el mapa 2D (§6) | **FOM 1.532**, y 1.31→1.58 por rebanadas de amplitud |

El smoke test (`API/tests/placa/test_mca_hw.py`) da **29 PASS / 0 FAIL**, y la simulación
9 testbenches / 163 checks.

La medición de conteo es la que cierra el lazo: segmentador, contadores y
relojes. La de throughput valida que el ack de latencia fija y el CDC aguantan la
tasa real. Y la FOM valida de punta a punta la cadena de forma —acumuladores
`Q_total`/`Q_cola`, divisor restaurador y mapa 2D—, que era la parte del diseño
sin precedente en el repo.

> La comparación pico vs integral **refutó** la expectativa de §5. El resultado y
> su explicación están ahí, no acá.

### Cuatro cosas que sólo aparecieron en la placa

**1. Las lecturas masivas reinician la Pitaya.** `np.frombuffer(...).copy()` de
16384 palabras sobre una apertura **reinicia el sistema**; las mismas
direcciones leídas de a una funcionan. El `memcpy` emite accesos anchos o en
ráfaga que `axi4_slave` rechaza, y el *external abort* resultante no da SIGBUS
sino reinicio. `mca_utils._read_words()` lee de a 32 bits por eso: cuesta
~110 ms por espectro, irrelevante para un MCA. Detalle en
[`bus_sistema_redpitaya.md`](../TOP/bus_sistema_redpitaya.md) §7.3.

**2. El seguidor de línea de base puede comerse el pulso.** Si su constante de
tiempo (2^`cfg_bl_k` muestras) es comparable a la duración del pulso, lo persigue
y lo borra: la señal nunca cruza el umbral y **no se detecta nada**. Con pulsos
largos (~62 µs de la primera campaña) `bl_k = 6` daba **0 eventos** y `bl_k ≥ 9`
funcionaba.

Con pulsos de 2 µs el barrido salió **plano de `bl_k` 3 a 18** (~2002 eventos en
todos), porque el seguidor se **congela durante el pulso** y no llega a
perseguirlo. O sea que el modo de falla es real pero depende por completo de la
duración del pulso: **hay que rebarrer `bl_k` cada vez que cambia el estímulo**,
y por eso `run_campana.py` lo corre primero y propaga el resultado.

Regla conservadora: `tau_base` ≥ 100× la duración del pulso, o base fija
(`cfg_bl_auto = 0`), que es inmune.

**3. `fpgautil` no acepta el `.bit` de Vivado**: falla con
`write init error: 0xffffffea` y deja la PL en estado de error. Necesita el
`.bit.bin` de `bootgen`, que ahora genera el propio script de build.

**4. El generador puede informar una frecuencia y emitir otra.** No es del MCA,
pero condiciona toda medición de tasa: tras ciertas secuencias de comandos el
DG4162 acepta `APPLy:PULSe`, contesta la frecuencia nueva en `:FREQuency?` y
**sigue emitiendo la anterior**. Así se generó una tabla entera de throughput
falsa. `sweep_rate` ahora lo detecta con un criterio físico —si el MCA no perdió
ni un evento, `cnt_total/realtime` **es** la tasa de entrada— y marca los puntos
inválidos. Ver [`resultados_validacion_hw.md`](../resultados_validacion_hw.md)
§13.8.

---

## 14. Lo que queda abierto

### Del hardware

1. **Compuertas de largo fijo** para la carga (método de comparación de carga,
   Brooks 1959). Es lo que sale primero: medido offline sobre 7054 pulsos reales
   da **0.149 %** contra 0.272 % del pico y 0.528 % de la ventana por histéresis
   — la integral no era mala, lo era la definición de ventana (§5).
2. **Conformado trapezoidal** como estimador de amplitud (§5). Queda **detrás**
   de las compuertas fijas: offline da 0.212 %, peor que 0.149 %, y costaría la
   mitad del throughput (`2k+m` por evento contra 794 kcps medidos). Su
   argumento sigue siendo el corrimiento de centroide con la tasa, pero ese
   número bajó de +6.45 % a **+1.28 %** al descontar el artefacto del ancho
   (§2.3), así que hay que volver a medirlo antes de decidir.
2. **Los dos motores apagados**: amplitud × tiempo de subida, y mapa de
   persistencia. El RTL ya los contempla.
3. **Acumulación en DDR** por AXI-HP si 40/60 RAMB36 llegara a quedar corto.
4. **El timing del bitstream del scope** sigue en −1.820 ns, con el filtro como
   causa. El MCA no lo arregla ni lo empeora de forma significativa.
5. **El build del scope no quedó bit-idéntico**: envolver `osc_filter` en un
   `generate if` agrega un nivel de jerarquía y con `-flatten_hierarchy none`
   eso mueve los límites de optimización (+22 LUT, WNS de −1.820 a −1.874).
   Funcionalmente idéntico.

### De la caracterización

6. **La DNL no se puede medir con este generador.** Pide amplitud continua y la
   modulación no existe por SCPI en este firmware (§12); queda hacerla desde el
   panel frontal. Lo medido es una cota superior impuesta por el estímulo.
7. **La INL no está separada del generador.** Se demostró que es sistemática
   (correlación +1.00 entre pasadas), o sea compensable, pero no de quién es.
   `sweep_formas_inl` (**medido 2026-08-14**) mostró que con el estimador de
   PICO la INL es común a todas las formas (ganancias dentro de ±0.2 %,
   correlación +0.997), o sea que no sale de la determinación de amplitud sino
   del generador y/o de la INL estática del ADC; distinguir esos dos sigue
   pidiendo una referencia de tensión trazable. Con el estimador de CARGA y
   ventana por histéresis, en cambio, la INL sí depende de la forma. Ver
   [`../resultados_validacion_hw.md`](../resultados_validacion_hw.md) §13.11.
8. **El techo de throughput no se alcanzó**: a 794 kcps el MCA seguía sin perder
   un evento y el que se quedó sin rango fue el generador.
9. **Deriva de ganancia y offset** con tiempo y temperatura: sin medir.
10. **Todo con pulsos de detector reales.** El estímulo ya está en la escala
    temporal correcta (~2 µs), pero un pulso sintético no tiene el ruido ni la
    variabilidad de uno real — y §5 depende de eso para saber cuál de los dos
    estimadores de amplitud conviene.

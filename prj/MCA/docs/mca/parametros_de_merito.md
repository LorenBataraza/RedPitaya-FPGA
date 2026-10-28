# Parámetros de mérito: qué mide la performance del sistema, y qué etapa mueve cada uno

Los documentos hermanos miden **un** efecto cada uno: la resolución, el
apilamiento, el tiempo muerto, el jitter. Este documento es el de arriba: qué
números describen la performance del instrumento **como sistema**, cuál etapa de
la cadena fija cada uno, y cuál es el escalar que decide el punto de operación
cuando dos méritos se pelean — que es casi siempre.

La tesis del documento, en una línea: **el largo de la ventana de medición es la
única variable que acopla el mundo espectroscópico con el mundo de tasa**, y casi
toda perilla del MCA termina moviéndolo. Elegir la ventana *es* elegir el punto
de operación; todo lo demás es ajuste fino.

| Documento | Qué contiene |
|---|---|
| [`ventana_de_medicion.md`](ventana_de_medicion.md) | las dos reglas de ventana, el walk, quién decide el cierre |
| [`apilamiento.md`](apilamiento.md) | cuánto deforma el apilamiento y cuánto saca el corte por forma |
| [`tiempo_muerto.md`](tiempo_muerto.md) | los tres modelos de pérdida y por qué el estímulo periódico engaña |
| [`limites_resolucion_y_deriva.md`](limites_resolucion_y_deriva.md) | binning, poder resolutivo, y la deriva como límite real |
| [`fuentes_de_jitter.md`](fuentes_de_jitter.md) | el presupuesto de jitter término por término |
| [`conformado_y_ruido.md`](conformado_y_ruido.md) | qué forma de pulso se deja medir mejor, y por qué Nicholson no aplica directo |
| [`../movimiento_de_datos.md`](../movimiento_de_datos.md) | los techos de transporte de cada ruta |
| [`register_map_mca.md`](register_map_mca.md) | el registro de cada perilla |

> **Convención de este documento.** Cada número lleva su procedencia:
> **[P]** medido en placa · **[MC]** Monte-Carlo · **[OF]** análisis offline de
> pulsos reales · **[D]** derivado acá a partir de los anteriores. Los **[D]** son
> predicciones falsables, no resultados: §5 y §8 son casi todos **[D]** y dicen
> cómo medirlos.

---

## 1. Las cuatro capas, y por qué la cuarta no se puede omitir

La confusión más común al hablar de performance es mezclar lo que el mundo
impone, lo que uno elige, lo que se mide y lo que se quiere.

| Capa | Qué es | Ejemplos |
|---|---|---|
| **Condiciones de operación** | lo que impone el experimento; no se elige | tasa incidente `n`, proceso de arribos, forma y altura del pulso, ruido |
| **Perillas** | lo que se configura, en caliente o por bitstream | `cfg_thr`, `cfg_gate_mode`, `cfg_amp_src`, `H_AW`… |
| **Parámetros de mérito** | lo que se mide del sistema ya configurado | FWHM %, τ, continuo sobre el fotopico, tasa de datos |
| **Función objetivo** | el escalar que ordena las configuraciones | tiempo hasta la precisión pedida |

**La cuarta capa no es un lujo retórico.** Los méritos de las dos familias
—espectroscópicos y de tasa— se mejoran unos a costa de otros, así que sin un
escalar que los combine no hay forma de elegir: "tasa de datos generada" y
"throughput máximo" no son criterios de elección sino **restricciones**, es
decir, cosas que hay que cumplir y que no premian nada por cumplirse mejor. La
función objetivo está en §8, y la conclusión que sale de ella —que perder
eventos cuesta **cuadrático** y medirlos peor cuesta **lineal**— es lo que
desempata los modos de ventana.

---

## 2. Condiciones de operación

Las tres obvias son la tasa, la altura y el ancho. Las que faltan pesan tanto o
más.

| Condición | Por qué importa | Número de referencia |
|---|---|---|
| **Tasa incidente `n`** | entra en todos los méritos de tasa a través de `ρ = n·L/f_s` | campañas de 2 ev/s a 150 kcps **[P]** |
| **Proceso de arribos** | **la variable oculta del proyecto.** Periódico pierde 0 hasta ρ=1; Poisson pierde ≈ρ a cualquier tasa | a 100 kcps: 28.6 % de tiempo muerto y **0 eventos perdidos** con el Rigol, contra 22 % que predice Poisson **[P]** |
| **Distribución de altura**, pero como **`thr/A`** | la carga sub-umbral perdida depende del margen sobre el umbral, no de la altura | 0.003 % de `Q_total` a 1920 cuentas, **1.3 %** a 150 **[MC]** |
| **Ancho del pulso `L_pulso`** | fija el piso de `L` y por lo tanto τ y el apilamiento | 779 muestras de ventana con histéresis para la línea de referencia **[OF]** |
| **Ancho del *ápice*** | no es el ancho del pulso: decide si el estimador de pico ve o no la fase de muestreo | ápice de 3 muestras (cusp) → σ = 2.84; de 128 (trapecio) → σ = **1.19** **[MC]** |
| **Número de líneas del espectro** | el walk de amplitud **no tiene dispersión**: no ensancha nada en una medición monoenergética y aparece recién con dos líneas | 39.4 ns entre el cruce de 1600 y 150 cuentas **[MC]** |
| **Ruido y deriva de base** | σ del ADC es el piso; la deriva es el límite que ata | σ ≈ 2.8 cuentas **[P]**; deriva +1.28 % con ×36 de tasa **[P]** |
| **Canales activos y ciclo de veto** | multiplican la tasa de datos y recortan el tiempo vivo sin tocar la física | `vetotime` lo exporta el FPGA |

> **La más barata de corregir y la más caras de ignorar es la segunda.** Toda la
> caracterización de eficiencia se hizo con el Rigol en modo PULSE, que es un
> tren periódico. Un 99.1 % de eficiencia medido así no dice nada sobre lo que va
> a pasar con una fuente. Ver [`tiempo_muerto.md`](tiempo_muerto.md).

---

## 3. Los parámetros de mérito

### 3.1 Espectroscópicos — calidad del número que se le asigna a cada evento

| Mérito | Definición | De dónde sale | Valor |
|---|---|---|---|
| **Resolución** | FWHM % del pico de un pulser a energía fija | ajuste del espectro | 0.528 % histéresis → **0.149 %** compuerta fija **[OF]** |
| **Bits efectivos** | `log2(FS/FWHM)` | ídem | 9.2–10.3 **[P]** |
| **Canales por FWHM** | cuánta resolución se tira al binear | `H_AW`, zoom | 8.6 → σ inflado 0.31 % **[P]** |
| **No linealidad integral** | `Â = G·A + INL(A)` | pulser deslizante | concentrada en la primera década sobre el umbral; corregible con LUT |
| **DNL** | dispersión del ancho de bin | pulser deslizante | el zoom alineado a potencias de 2 **no** la introduce |
| **Deriva del centroide** | corrimiento con tasa, con tiempo y con temperatura | campaña larga | **+1.28 %** con ×36 de tasa; **12 FWHM**, 38× la tolerancia **[P]** |
| **Continuo sobre el fotopico** | altura del fondo de apilamiento relativa al tope | MC con espectro de referencia | 32.4 % → **0.8 %** con corte `Q/pico` **[MC]** |
| **Distancia L1** | `‖h_medido − h_referencia‖₁` normalizada | ídem | 0.894 → **0.135** **[MC]** |
| **FOM de separación de formas** | `Δcentroide / (FWHM₁ + FWHM₂)`, el clásico de PSD | mapa 2D | **sin medir** |
| **Resolución temporal** | σ del timestamp | barrido de amplitud | σ_ts = **2.31 ns** (cuantización a `Ts`), domina sobre el ruido en todo el rango salvo la última década **[D/P]** |
| **Walk de amplitud** | sesgo determinista `t ∝ 1/A` | pulser deslizante | **sin medir** — la única entrada abierta del presupuesto de jitter |

> **La resolución y el continuo son méritos distintos y se mueven en direcciones
> opuestas** al cambiar de modo de ventana. Es el conflicto central del
> instrumento y lo resuelve §8, no una preferencia.

### 3.2 De tasa — cuántos eventos sobreviven, y en qué estado

| Mérito | Definición | De dónde sale | Valor |
|---|---|---|---|
| **Tiempo muerto por evento `τ`** | tiempo de servicio | pendiente de `(1 − live)` vs tasa | **2.86 µs** **[P]** |
| **Ocupación `ρ`** | `n·τ`, la fracción de tiempo ocupado | `deadtime/realtime` | 28.6 % a 100 kcps **[P]** |
| **Throughput `m(n)`** | tasa registrada | contadores | 99.95 % de `n` hasta 100 kcps **[P]** |
| **Techo de throughput** | `max m` | **depende del modo** | §5 |
| **Fracción de apilamiento** | eventos con más de un pulso | MC | **40–47 %** a 100 kcps **[MC]** |
| **Apilamiento *no detectado*** | lo anterior menos `cnt_pileup` | contadores vs MC | `cnt_pileup` marca **0.00–0.45 %**: el mecanismo del RTL **no detecta nada** **[MC]** |
| **Par (eficiencia, rechazo)** | del discriminador; es un ROC, no un número | MC con corte calibrado | **(100.0 %, 99.1 %)** modo 0 · (100.0 %, 45.6 %) modo 1 **[MC]** |
| **Ventana ciega del corte** | Δt bajo el cual dos pulsos son indistinguibles de uno | MC contra el lugar geométrico | **Δt ≲ 80 ns**, irreducible salvo acortando el pulso **[MC]** |
| **Eficiencia de eventos limpios `ε`** | limpios aceptados / incidentes | `e^{−ρ}` | 53.6 % (modo 0) · 73.6 % (modo 1) a 100 kcps **[D]** |

> **`tiempo muerto` no es `eventos perdidos`**, y es la confusión más fácil de
> cometer: a 100 kcps el MCA estuvo ocupado el 28.6 % del tiempo y perdió **0**
> eventos, porque los arribos eran periódicos. Con K=1 y Poisson sí coinciden,
> y valen las dos `ρ/(1+ρ)`.

### 3.3 De sistema — lo que cuesta sacar los datos y confiar en ellos

| Mérito | Definición | Valor |
|---|---|---|
| **Tasa de datos generada** | `m × bytes/evento` | 144 B/evento por default → 14.4 MB/s a 100 kev/s **[D]** |
| **Techo de transporte** | el mínimo de la cadena de salida | SD 12.4 MB/s = **86 kev/s** · NFS 60–90 = 417–625 kev/s · TCP 90–110 = **625–764 kev/s** **[P/D]** |
| **Tolerancia a ráfagas** | tiempo hasta desbordar el buffer | ring de 32 MiB = 233 k eventos = **2.3 s** a 100 kev/s **[D]** |
| **Techo de captura** | de la ruta, no del MCA | 3.7 kev/s (GP0, K=1) · 52 kev/s (el mismo en C) · **3.9 Mev/s** (`event_ring`) **[P]** |
| **Cierre de la contabilidad** | que `accepted + rej_* + pileup + dropped + full_supp` cierre contra los incidentes | es un mérito del **diseño**: cada pérdida tiene su contador y se puede atribuir |
| **Recursos y timing** | BRAM, DSP, WNS | 8192 canales liberan **8 RAMB36 de 16**, que es lo que habilita un segundo MCA **[P]** |
| **Saturación del contador** | 32 bits por bin | 13.8 h a tasa máxima con todo en un pico → 0.0028 en unidades de FWHM **[D]** |

> **La tasa de datos y el tiempo muerto los fijan dos ventanas distintas**, y
> conviene no confundirlas: el tiempo muerto lo fija la **ventana de medición**
> (`L`, decenas a cientos de muestras según el modo), y la tasa de datos la fija
> la **ventana guardada** en el ring (8+24 muestras por default). Son
> independientes en el diseño actual: se puede medir con una ventana larga y
> guardar pocas muestras.

---

## 4. El largo de la ventana es la variable de acoplamiento

Acá está el mecanismo que ordena todo lo anterior. El largo `L` de la ventana de
medición entra en cuatro méritos de familias distintas:

```
L  →  resolución    : el ruido blanco promedia como σ/√L …
                      … pero el error de línea de base entra ×L
L  →  tiempo muerto : τ ≈ L/f_s      →   ρ = n·L/f_s
L  →  apilamiento   : P_apilado ≈ 1 − e^{−n·L/f_s}
L  →  eficiencia    : ε_limpios = e^{−n·L/f_s}
```

Y **casi toda perilla del MCA termina moviendo `L`**:

- `cfg_gate_larga` lo fija directamente (modo 1);
- `cfg_thr` y `cfg_hyst` lo fijan indirectamente en modo 0, vía
  `L ≈ τ_d · ln(A/thr_lo)` — de ahí que la ventana de un pulso de 8000 cuentas
  (1073 muestras) dure **tres veces y media** la de uno de 200 (309) **[MC]**;
- `cfg_maxlen` lo acota por arriba;
- `cfg_dec` cambia la relación entre muestras y tiempo.

La consecuencia práctica es incómoda y vale decirla explícita: **el trade
resolución ↔ tasa no es una decisión de alto nivel que se tome en una reunión,
está determinado por dos registros de 32 bits.** Y como `L` aparece en el
exponente de la eficiencia y bajo una raíz en la resolución, el trade no es
simétrico — §8.

---

## 5. `cfg_gate_mode` no cambia el valor de τ: cambia la clase de modelo

Éste es el resultado menos obvio del documento y no está escrito en ningún otro.

| | modo 0 (histéresis) | modo 1 (compuerta fija) |
|---|---|---|
| Qué hace un segundo arribo | **estira** la ventana | no la toca |
| Clase de modelo | **paralizable**, `m = n·e^{−nL₀}` | **no paralizable**, `m = n/(1+nτ)` |
| Validación | el MC lo reproduce dentro del **2.1 %**, contra 14.8 % del no paralizable **[MC]** | por construcción: el largo es constante |
| Forma de `m(n)` | tiene un **máximo** y después **colapsa** | satura y se queda arriba |

Que la clase cambie, y no sólo el parámetro, tiene una consecuencia dura sobre
el techo de throughput. Con `L₀ = 779` muestras (modo 0, línea de referencia) y
`gate_larga = 384` (modo 1), a `f_s = 125 MHz`:

| | modo 0 | modo 1 |
|---|---|---|
| τ equivalente | 6.23 µs | 3.07 µs |
| `ρ = 1` en | 160 kcps | 326 kcps |
| **Throughput máximo** | **59.0 kcps**, en `n` = 160 kcps | **→ 326 kcps** (asíntota) |
| Más allá del máximo | **se desploma** | se queda |

Los cuatro números de esa tabla son **[D]**: salen de evaluar
`m = n·e^{−nL₀}` y `m = n/(1+nτ)` con los largos medidos. La cuenta del máximo
paralizable es `m_max = 1/(e·L₀)`.

**Esto acota por arriba la conclusión de [`apilamiento.md`](apilamiento.md)**
("a tasa alta conviene el modo 0"). Es cierta a 100 kcps y es cierta *en
fidelidad espectral*; pero el modo 0 tiene su techo de throughput a 160 kcps
incidentes y después va para atrás. La recomendación completa es:

> **Modo 0 + corte `Q/pico` mientras `n` ≲ 100 kcps. Por encima de eso el modo 0
> deja de ser una opción**, y no por razones espectrales sino de tasa: el
> instrumento registra *menos* eventos cuanto más fuerte es la fuente.

### La verificación que falta, y que ya se puede hacer

El τ = 2.86 µs medido **[P]** son ~358 muestras: consistente con la compuerta de
384 y **no** con los 779 de la histéresis. Si esa campaña corrió en modo 1
—como parece—, entonces el barrido en modo 0 debería dar:

- `ρ = 1` a ~160 kcps en vez de ~350;
- y, con estímulo Poisson, el **colapso** de `m` arriba de esa tasa.

Es una predicción falsable con `sweep_rate_poisson(mca, gen, …)` corriendo el
barrido dos veces, una por modo. Hoy no hay ningún barrido de tasa en modo 0.

---

## 6. Punto por punto: qué mérito fija cada etapa de la cadena

Ésta es la sección operativa. Una fila por etapa, desde el detector hasta el
disco. La lectura útil es la de las dos columnas del medio: **casi toda etapa fija
un mérito y arruina otro**, y ahí está el trade que le corresponde a cada una.

### 6.1 Antes del ADC — lo que no es configurable, y manda

| Etapa | Perilla | Fija | Arruina | Número |
|---|---|---|---|---|
| **Detector + conformador analógico** | la forma del pulso | el **piso** de todo: `L_pulso`, ancho del ápice, S/N del preamp | nada, pero **determina el techo de los demás**: ningún corte por forma saca las coincidencias de Δt ≲ 80 ns | el orden de Nicholson: cusp 1.000 … CR 0.581 **[MC]** |
| **Front-end (atenuador, jumper LV/HV)** | ±1 V o ±20 V de fondo de escala | el rango dinámico y por lo tanto `thr/A` | la no linealidad sub-umbral si `A` queda cerca de `thr` | 1.3 % de `Q_total` perdido a 150 cuentas **[MC]** |
| **ADC LTC2145-14** | nada (125 MS/s, 14 b) | el **piso de ruido** que todo lo demás promedia, y la cuantización temporal | — | σ ≈ 2.8 cuentas **[P]** · σ_ts = 2.31 ns · cuantización 0.29 cuentas |

> **El ruido del ADC entra *después* del conformador**, así que el conformador no
> lo puede filtrar. Es por eso que el orden de Nicholson **se invierte** en
> nuestra cadena: el cusp y el triángulo, los dos mejores para un preamp, son los
> dos **peores** para el estimador de pico del RTL, y el trapecio —el peor de los
> unipolares en Nicholson— es el mejor. Son dos preguntas distintas.
> Ver [`conformado_y_ruido.md`](conformado_y_ruido.md).

### 6.2 El datapath del MCA — donde están las perillas que importan

| Etapa | Perilla | Fija | Arruina | Número |
|---|---|---|---|---|
| **Seguidor de línea de base** | `cfg_bl_ctrl` = {`auto`, `k`, `holdoff`} | el rechazo de deriva lenta y del pedestal de tasa | con `k` alto el lazo se deja **arrastrar por los propios pulsos**; `baseline_stale` avisa cuando lleva demasiado congelado | a 72 kcps baja el corrimiento de +0.208 % a **+0.096 %**, con 53.4 % del tiempo congelado **[MC]** |
| **Schmitt de apertura** | `cfg_thr`, `cfg_hyst` | la eficiencia a baja energía y la inmunidad a re-disparos por ruido | el **walk** (sesgo `∝1/A`), la carga sub-umbral, y **`L` en modo 0** | σ_t de apertura = 0.06 ns, despreciable; σ_t de cierre = **92 ns ≈ 11 muestras** **[MC]** |
| **Regla de cierre** | `cfg_gate_mode`, `cfg_gate_len`, `cfg_maxlen` | **`L` y su varianza** → resolución, τ, clase de modelo de pérdida, visibilidad del apilamiento | lo que mejora un modo lo empeora en el otro: §5 y §8 | 765 ± 6.1 muestras (modo 0) contra **384 ± 0** (modo 1) **[MC]** |
| **Estimador de amplitud** | `cfg_amp_src`, `q_shift` | la resolución: el pico arrastra el ruido de **una** muestra, la integral promedia `σ/√N` | la integral **sólo sirve si `L` es estable**: con histéresis, el jitter del cierre se le suma entero | σ = 2.8 (una muestra) contra ~0.2 con filtro adaptado sobre 180 muestras **[MC]** |
| **Arranque de la cola** | `cfg_tail_dly` (modo 0) · `gate_corta` (modo 1) | el rango útil del eje de forma | con el default de 4 la cola se lleva el 94 % de la carga y al cociente le quedan **3 de 64** valores útiles | es la razón de que `Q_cola/Q_total` rechace **0.0 %** de apilados en modo 1 **[MC]** |
| **Divisores restauradores** | — (6 ciclos de `S_DIV`) | el rango dinámico del eje de forma | un pulso que llega durante la división se pierde | 48 ns contra ventanas de ~780 muestras: **2.4 e−5** de los eventos a 500 kcps **[MC]** |
| **Discriminador** | `cfg_discr_*` | el **par (eficiencia, rechazo)**, y por lo tanto el continuo y el L1 | nada en resolución; pero el corte **hay que calibrarlo contra la amplitud** o es un corte en amplitud disfrazado | continuo 32.4 % → **0.8 %**; `Q/pico` deriva **+21 %** entre 110 y 7000 cuentas **[P]** |
| **Zoom** | `cfg_zoom_*` | dónde cae el eje; permite un histograma más chico | **amplifica la deriva**: la misma deriva ocupa 4× más de la ventana a `z=3` | 6.45 % de deriva = 5.2 % de la ventana a `z=0` y **41.3 %** a `z=3` **[P]** |
| **Motores de histograma** | `H_AW`, `hist_ctrl` | canales por FWHM, y el costo en BRAM | bins de 32 b saturan; el barrido de `clear` descarta eventos mientras dura | 8.6 can/FWHM → σ inflado **0.31 %**; `clear` = 66 µs con 8192 canales **[P/D]** |

> **Las tres perillas que más mueven la aguja** son, en orden: `cfg_gate_mode`
> (3.5× en resolución, y la clase de modelo de pérdida), `cfg_amp_src` (el jitter
> de muestreo entero), y `cfg_discr_*` (40× en el continuo). `cfg_zoom_*`,
> `H_AW` y `cfg_h_shift` **no mueven la resolución** — mueven dónde cae el eje y
> cuánta BRAM cuesta.

### 6.3 La salida — fija techos, no calidad

| Etapa | Fija | Arruina | Número |
|---|---|---|---|
| **Lectura del espectro por GP0** (ruta A) | nada: el dato ya viene reducido | la colisión de un evento con `rd_i` descarta ese evento | ~**0.8 %** durante cada lectura de espectro; se elimina con un skid buffer de un registro **[P]** |
| **Scope + GP0, K=1** (ruta B) | el techo de captura de muestras crudas | **es el cuello**: el PS está en el camino crítico | τ = **252.7 µs** → 3.7 kev/s medido; reescrito en C, 19.2 µs → 52 kev/s **[P]** |
| **`event_ring` → DDR** (ruta C) | el techo de captura, y la tolerancia a ráfagas | nada en el lazo: el PS sale del camino crítico | 3.9 Mev/s de techo · ring de 32 MB = **2.3 s** a 100 kev/s **[P/D]** |
| **microSD** | el techo de transporte si no hay red | lo recorta **por debajo del techo del MCA** | 12.4 MB/s = **86 kev/s** a 144 B/evento **[P/D]** |
| **GbE (NFS o TCP)** | el techo de transporte | — | 90–110 MB/s = **625–764 kev/s**: la red deja de ser el límite **[P/D]** |
| **Veto externo** (`DIO0_P` → `trigger_shield`) | el tiempo vivo | recorta la estadística por el ciclo de trabajo del veto | `livetime + deadtime + vetotime = realtime`, exacto por construcción **[P]** |

> **El techo de la microSD cae por debajo del techo del MCA.** A 144 B/evento la
> tarjeta se satura en ~86 kev/s, que es menos que el throughput del
> instrumento en los dos modos de ventana (§5). Para cualquier campaña a tasa
> alta la salida por red no es una optimización: es un requisito.

---

## 7. Resumen: perilla → qué mueve, y en qué dirección

| Perilla | Mejora | Empeora |
|---|---|---|
| `cfg_thr` ↓ | eficiencia a baja energía; menos carga sub-umbral perdida | `L` ↑ → τ y apilamiento; disparos por ruido |
| `cfg_hyst` ↑ | inmunidad a re-disparos | `L` ↑ y σ del cierre (σ_t = 92 ns) |
| `cfg_gate_mode` 0→1 | resolución **3.5×**; `Q/pico` constante; τ a la mitad; throughput **5.5×** | ciego al apilamiento: rechazo 99.1 % → 45.6 %, continuo 0.8 % → 7.2 % |
| `cfg_gate_larga` ↓ | τ ↓, throughput ↑, `ε` ↑ | déficit balístico y sesgo de la integral |
| `cfg_maxlen` ↓ | acota `L` en modo 0 | marca como apilados eventos limpios grandes |
| `cfg_amp_src` pico→integral | `σ/√N` y mata el jitter de muestreo | **sólo si `L` es estable**: en modo 0 le suma el jitter del cierre |
| `cfg_tail_dly` | ubica el rango útil del eje de forma | con 0 el RTL rechaza el evento (`cnt_rej_psd`) |
| `cfg_bl_ctrl.k` ↑ | sigue deriva más rápida | el lazo se deja arrastrar por los pulsos → pedestal de tasa |
| `cfg_dec` ↑ | contadores más holgados, ventanas más largas en muestras | σ × √dec; resolución temporal |
| `cfg_zoom_*`, `H_AW` | ubica el eje; libera BRAM | **nada en resolución**; el zoom **amplifica la deriva** |
| `cfg_discr_*` | continuo **40×**, L1 **6.6×** | hay que calibrar el lugar geométrico contra la amplitud |

---

## 8. La función objetivo: por qué perder eventos cuesta el cuadrado

Todo lo anterior son méritos sueltos. El escalar que los ordena, para una
campaña de conteo, es el **tiempo hasta la precisión pedida**.

### La cuenta

Para un pico sobre un fondo, la actividad mínima detectable sigue el criterio de
Currie, `S_min ≈ 2.71 + 4.65·√B`, con el fondo `B` proporcional al ancho de la
región de interés —o sea al FWHM— y al tiempo. Despejando:

```
A_min  ∝  √(FWHM) / (ε · √T)        →        T  ∝  FWHM / (ε² · A²)
```

**El FWHM entra lineal y la eficiencia al cuadrado.** Eso es, cuantitativamente,
"perder eventos cuesta más que medirlos un poco peor", y es la regla que
desempata los modos de ventana. No es una opinión sobre prioridades: sale de que
la precisión estadística va como `1/√N`.

### El punto de operación óptimo

Las dos dependencias en `L` son conocidas: con ruido blanco dominante,
`FWHM ∝ L^{−1/2}`, y la eficiencia de eventos limpios es `ε = e^{−ρ}` con
`ρ = n·L/f_s`. Entonces

```
T(L)  ∝  L^{−1/2} · e^{2nL/f_s}
```

y derivando `ln T`:

```
−1/(2L) + 2n/f_s = 0        →        L_opt = f_s / (4n)        →        ρ_opt = 1/4
```

**El óptimo cae en ocupación ρ ≈ 1/4**: la ventana tiene que medir un cuarto del
intervalo medio entre arribos. En números:

| `n` | `L_opt` | en tiempo |
|---|---|---|
| 20 kcps | 1562 muestras | 12.5 µs |
| 100 kcps | **312 muestras** | **2.5 µs** |
| 500 kcps | 62 muestras | 0.5 µs |

Lo notable es que a 100 kcps da **312 muestras contra las 384 de la compuerta
que ya está configurada**: la elección empírica estaba en el óptimo sin que se
lo hubiera calculado. Y la regla dice qué hacer a otras tasas, que es lo que
antes no se tenía.

> **Las dos salvedades, que acotan la regla.** (1) `FWHM ∝ L^{−1/2}` vale
> mientras el ruido blanco domine y la ventana no pase el largo del pulso: más
> allá de ahí, agregar muestras sólo agrega ruido de base y error de línea de
> base, y el FWHM **empeora**. El óptimo real es
> `L_opt = min(f_s/4n, L_pulso)`, y a tasa baja lo fija el pulso, no la tasa.
> (2) `ε = e^{−ρ}` es la eficiencia de eventos **limpios**, así que la regla
> supone que los apilados se descartan — es decir, que el corte por forma está
> andando. Sin corte, el óptimo se corre hacia ventanas más cortas.
>
> Toda esta subsección es **[D]**. Se verifica barriendo `cfg_gate_larga` a tasa
> fija y graficando `FWHM/ε²`: el mínimo tiene que caer en `ρ = 1/4`. Es un
> barrido que el Monte-Carlo existente puede hacer sin placa.

### El desempate de los modos, con la función objetivo

A 100 kcps, combinando la resolución **[OF]** con las eficiencias **[D]**:

| | modo 0 + corte | modo 1 |
|---|---|---|
| FWHM | 0.528 % | **0.149 %** |
| `ε = e^{−ρ}` | 53.6 % | **73.6 %** |
| `T ∝ FWHM/ε²` (relativo) | **6.7** | **1** |
| Continuo residual | **0.8 %** | 7.2 % |

**El modo 1 llega a la misma precisión estadística 6.7× más rápido; el modo 0
deja el espectro 9× más limpio.** Cuál gana depende de la pregunta, y ahora se
puede decir con qué pregunta va cada uno:

- **"¿Cuánta actividad hay?" / "¿dónde está la línea?"** → modo 1. Son preguntas
  cuya precisión va como `1/√N` y el fondo se resta.
- **"¿Qué forma tiene el espectro?" / "¿hay una línea débil al lado de una
  fuerte?"** → modo 0 + corte `Q/pico`. Son preguntas donde el continuo de
  apilamiento es un **sesgo**, y un sesgo no se arregla con estadística.

> La cuenta mezcla números de dos campañas distintas (resolución offline sobre
> 7054 pulsos reales, eficiencias derivadas del MC de apilamiento a 100 kcps).
> Es una cuenta de orden para ordenar la decisión, no un resultado medido. La
> medición que la cerraría es un barrido de tasa con los dos modos sobre el mismo
> estímulo, reportando FWHM y `ε` en cada punto.

---

## 9. Qué falta medir

En orden de cuánto cierran:

| # | Medición | Qué resuelve | Costo |
|---|---|---|---|
| 1 | **Barrido de tasa en modo 0**, con Poisson | confirma el régimen **paralizable** y el techo de 59 kcps (§5). Hoy no existe ningún barrido en modo 0 | una tarde de placa |
| 2 | **Barrido de `gate_larga`** a tasa fija, graficando `FWHM/ε²` | verifica `ρ_opt = 1/4` (§8) y da el óptimo real donde la aproximación de ruido blanco se rompe | MC, sin placa |
| 3 | **Walk vs. amplitud** con pulser deslizante | la única entrada abierta del presupuesto de jitter; da el `k` de la corrección `ts − k/A` | una tarde de placa |
| 4 | **FOM de separación** del eje de forma | el mérito estándar de PSD, hoy sin número | offline sobre datos que ya hay |
| 5 | **Barrido de tasa con estímulo Poisson** sobre la eficiencia | toda la eficiencia medida hasta hoy es con estímulo periódico (§2) | ya está el generador |

---

## 10. Dónde está cada cosa

| Qué | Dónde |
|---|---|
| El registro de cada perilla | [`register_map_mca.md`](register_map_mca.md) |
| Las dos reglas de ventana, con cronogramas | [`ventana_de_medicion.md`](ventana_de_medicion.md) |
| El corte por forma y su calibración | [`apilamiento.md`](apilamiento.md) |
| Los modelos de pérdida | [`tiempo_muerto.md`](tiempo_muerto.md) |
| Binning, deriva y poder resolutivo | [`limites_resolucion_y_deriva.md`](limites_resolucion_y_deriva.md) |
| El presupuesto de jitter | [`fuentes_de_jitter.md`](fuentes_de_jitter.md) |
| Conformado y el orden invertido de Nicholson | [`conformado_y_ruido.md`](conformado_y_ruido.md) |
| Los techos de transporte de cada ruta | [`../movimiento_de_datos.md`](../movimiento_de_datos.md) |
| Las réplicas offline del RTL | [`../../software/API/modelo_rtl/`](../../software/API/modelo_rtl/) |
| Los Monte-Carlo | [`../../software/monte-carlo/`](../../software/monte-carlo/) |

## Bibliografía

- **G. F. Knoll**, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010 —
  cap. 4 (tiempo muerto, paralizable y no paralizable), cap. 17 (conformado y
  comparación de carga).
- **L. A. Currie**, *Limits for qualitative detection and quantitative
  determination*, Anal. Chem. **40** (1968) 586 — el criterio de `S_min` que usa
  §8.
- **V. Radeka**, *Optimum signal-processing for pulse-amplitude spectrometry in
  the presence of high-rate effects and noise*, IEEE Trans. Nucl. Sci. **15**
  (1968) 455 — el trade entre conformado y efectos de tasa, que es §4 en versión
  analógica.
- **V. T. Jordanov, G. F. Knoll**, *Digital synthesis of pulse shapes in real
  time for high resolution radiation spectroscopy*, Nucl. Instrum. Methods A
  **345** (1994) 337 — el trapezoidal digital, donde el largo de las rampas y el
  del techo son perillas separadas: la respuesta "correcta" al trade de §4.
- **J. W. Müller**, *Dead-time problems*, Nucl. Instrum. Methods **112** (1973)
  47 — combinación de tiempos muertos en serie y los límites de validez.

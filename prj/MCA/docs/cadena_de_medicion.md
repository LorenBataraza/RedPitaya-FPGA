# La cadena de medición: las etapas clásicas, y cuál de ellas es este proyecto

El MCA es el **último eslabón** de la adquisición de un esquema experimental: no
ve radiación, ve pulsos. Todo lo que esté antes decide qué pulsos le llegan, y
por lo tanto decide casi todo lo que el MCA puede o no puede hacer.

Este documento hace tres cosas:

1. **subdivide** la cadena histórica en etapas por *función*, no por módulo —
   porque la lista corta (detector → preamplificador → conformado →
   discriminador → contador) junta en una sola caja cosas que se diseñan,
   fallan y se ajustan por separado;
2. la recorre sobre **un sistema de ejemplo** concreto (NaI(Tl) + PMT midiendo
   el fotopico de 662 keV del ¹³⁷Cs), con órdenes de magnitud a cada paso;
3. dice **qué etapa hace este proyecto, cuál delega y cuál no existe** — con el
   registro o el módulo que la implementa, para que la comparación sea
   verificable y no retórica.

> **La lista corta termina en un contador, y eso no es un espectrómetro.** Un
> discriminador seguido de un contador entrega **un número por configuración**:
> la tasa de eventos por encima de un umbral. Para obtener un espectro con esa
> cadena hay que **barrer la ventana del discriminador** y repetir la medición
> canal por canal: N mediciones secuenciales, con la deriva del sistema metida
> entre la primera y la última. El salto conceptual del analizador multicanal es
> dejar de preguntar *"¿cuántos pasan este umbral?"* y pasar a *"¿cuánto vale
> este evento?"*, para clasificar **todos los canales a la vez y en una sola
> corrida**. El contador, visto así, es un MCA degenerado de un solo bin.

Las familias de detectores y qué mide cada una están en el **Apén. 1**; acá el
detector entra sólo como la primera etapa de la cadena.

---

## 1. Las etapas, subdivididas por función

Nueve etapas funcionales. La columna que importa es la última: cada etapa
impone un límite distinto, y confundirlas es confundir qué hay que arreglar
cuando el espectro sale mal.

| #   | Etapa                                      | Función (una sola)                                                       | Qué entra → qué sale                                     | Quién la hace, históricamente                   | Qué límite impone                                                                                    |
| --- | ------------------------------------------ | ------------------------------------------------------------------------ | -------------------------------------------------------- | ----------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| 1   | **Detector**                               | convertir energía depositada en carga o luz                              | radiación → portadores / fotones                         | cristal, diodo, gas                             | **la resolución intrínseca** (Fano, fotoestadística): el piso que ninguna electrónica baja           |
| 2   | **Polarización (HV/bias)**                 | fijar el campo que colecta la carga                                      | tensión → ganancia y corriente de fuga                   | fuente de alta tensión                          | ganancia (y su deriva), ruido paralelo por fuga                                                      |
| 3   | **Preamplificador**                        | convertir **carga** en **tensión**, sin perder relación de señal a ruido | pulso de carga → escalón con cola larga (τ ≈ 50 µs)      | preamp sensible a carga, **pegado al detector** | **el piso de ruido de la electrónica**: acá se definen el ruido serie y el paralelo                  |
| 4a  | **Cancelación polo-cero**                  | anular la cola del preamplificador antes de filtrar                      | escalón con cola → escalón limpio                        | red P/Z del amplificador                        | si se desajusta, **undershoot**: el evento siguiente mide de menos                                   |
| 4b  | **Filtro de conformado**                   | elegir el **ancho de banda** del estimador de amplitud                   | escalón → pulso semigaussiano o trapezoidal de ancho τ_s | amplificador conformador                        | el **compromiso ruido ↔ apilamiento**: τ_s grande promedia más ruido pero apila; τ_s chico, al revés |
| 4c  | **Ganancia / mapeo de rango**              | llevar la amplitud al rango dinámico del medidor                         | mV → 0–10 V                                              | ganancia grosa + fina                           | **cuánto del rango del conversor se usa**: medio rango vacío es medio bit tirado                     |
| 4d  | **Restaurador de línea de base**           | devolver el cero entre pulsos                                            | pulso + base que se mueve → pulso sobre cero             | BLR del amplificador                            | el **pedestal dependiente de la tasa**, que corre el centroide                                       |
| 5a  | **Discriminador integral (LLD)**           | decidir **que hay un evento**                                            | pulso analógico → pulso lógico                           | discriminador de umbral                         | el **umbral efectivo**: por debajo, el instrumento es ciego                                          |
| 5b  | **Discriminador diferencial (SCA)**        | decidir **si el evento es el que interesa**                              | pulso + ventana [min, max] → pulso lógico                | analizador monocanal                            | el par **(eficiencia, rechazo)**: qué se acepta y qué se tira                                        |
| 5c  | **Tiempo muerto / rechazo de apilamiento** | garantizar que cada evento se mida una vez y sin contaminar              | tren de pulsos → eventos separados                       | inspector de apilamiento, hold-off              | la **tasa máxima útil** y la corrección por tiempo muerto                                            |
| 6a  | **Compuerta lineal + estirador de pico**   | retener la amplitud el tiempo que el conversor necesita                  | pulso de µs → nivel quieto                               | *linear gate* + *stretcher*                     | el **error de retención** (droop) y un tiempo muerto propio                                          |
| 6b  | **Conversión A/D**                         | medir la amplitud retenida                                               | nivel → número                                           | ADC Wilkinson o SAR                             | **linealidad diferencial (DNL)** y el tiempo de conversión                                           |
| 7   | **Clasificación (histograma)**             | incrementar el bin correspondiente                                       | número → dirección de memoria                            | memoria del MCA                                 | el **bineado**, y el tiempo de acceso a memoria                                                      |
| 8   | **Contabilidad (scaler + reloj)**          | contar eventos y medir el tiempo vivo                                    | pulsos lógicos → cuentas y segundos                      | escalador + temporizador                        | sin tiempo vivo **no hay tasa absoluta**, sólo forma de espectro                                     |
| 9   | **Registro y análisis**                    | guardar, calibrar, ajustar                                               | espectro → energías y actividades                        | registrador, hoy la PC                          | la **calibración**, y lo que se perdió antes de llegar acá                                           |

Tres uniones que la lista corta hace y que conviene deshacer:

- **La etapa 4 no es una caja, son cuatro.** El "amplificador" clásico hace a la
  vez P/Z, filtro, ganancia y restauración de base, y cada una se ajusta con una
  perilla distinta por una razón distinta. El filtro (4b) es el único que
  trabaja la **relación señal a ruido**; la ganancia (4c) no mejora nada, sólo
  acomoda el rango. Mezclarlas lleva a creer que "subir la ganancia mejora la
  resolución", que es falso.
- **"Discriminador" son dos decisiones distintas.** *Que haya evento* (5a) y
  *que el evento sirva* (5b) se implementan en el mismo módulo y se suelen
  nombrar igual, pero la primera define el umbral del instrumento y la segunda
  define su selectividad.
- **Medir la amplitud son dos etapas, no una** (6a y 6b), y la primera existe
  **sólo porque el conversor es lento**: hay que congelar el pulso porque el ADC
  tarda más que el pulso en pasar.

---

## 2. Un sistema de ejemplo, etapa por etapa

NaI(Tl) de 2″×2″ acoplado a un fotomultiplicador, fuente de ¹³⁷Cs, cadena NIM
clásica, midiendo el fotopico de **662 keV**. Los números son **órdenes de
magnitud típicos** de ese tipo de montaje, para fijar escalas:

| # | Etapa | Instrumento del ejemplo | Número a la salida |
|---|---|---|---|
| 1 | Detector | NaI(Tl) 2″×2″, ~38 fotones/keV, decaimiento 230 ns | ≈ 2.5 × 10⁴ fotones por evento de 662 keV |
| 2 | Polarización | fuente de HV, 800–1200 V al divisor del PMT | ganancia del tubo ≈ 10⁶ |
| 1+2 | Fotomultiplicador | fotocátodo (QE ≈ 25 %) + 10 dinodos | ≈ 6 × 10³ fotoelectrones → ≈ 1 nC de carga anódica |
| 3 | Preamplificador | sensible a carga, en la base del PMT | escalón de decenas de mV, subida ~0.5 µs (la marca el centelleador), cola τ ≈ 50 µs |
| 4a–4d | Amplificador conformador | ganancia 10–1000, τ_s = 0.5–2 µs, P/Z y BLR | pulso semigaussiano **unipolar de 0–10 V**, ancho total ≈ 2.5 τ_s ≈ 1–5 µs |
| 5a | Discriminador integral | LLD por encima del ruido | pulso lógico NIM (−0.8 V sobre 50 Ω) |
| 5b | Monocanal (SCA) | ventana alrededor del fotopico | sólo los eventos de la ventana |
| 5c | Tiempo muerto | hold-off del orden del ancho del pulso | tasa útil ≲ 10⁴–10⁵ s⁻¹ antes de que el apilamiento mande |
| 6a | Compuerta + estirador | dentro del MCA | nivel retenido durante la conversión |
| 6b | ADC del MCA | 1024–8192 canales, 0–10 V | canal ∈ [0, 8191], unos µs de conversión por evento |
| 7 | Histograma | memoria del MCA | espectro de 8192 bins |
| 8 | Contabilidad | escalador + temporizador de tiempo vivo | cuentas y tiempo vivo, para dar s⁻¹ |
| 9 | Análisis | ajuste del fotopico | **FWHM ≈ 6–7 % a 662 keV** |

**La lectura que importa de esta tabla es el último número.** Con un
centelleador, la resolución del sistema la fija la etapa 1 y las ocho que siguen
son prácticamente invisibles: la electrónica aporta menos del 0.3 % de la
varianza total. Con un semiconductor —HPGe, ~0.17 % intrínseco a 662 keV— se
invierte el orden y la cadena pasa a ser **el** límite. Ese cálculo, con los
números medidos de este instrumento, está en
[`ruido_del_sistema.md`](ruido_del_sistema.md) §8, y es lo que fija cuánto vale
la pena perseguir cada etapa.

---

## 3. La misma cadena, en este proyecto

Qué hace este instrumento de las nueve etapas, qué delega y qué simplemente no
existe:

| # | Etapa clásica | Acá | Dónde | Estado |
|---|---|---|---|---|
| 1 | Detector | **fuera de alcance**: el estímulo es un generador arbitrario | [`ruido_del_sistema.md`](ruido_del_sistema.md) §8 | no existe |
| 2 | Polarización | **fuera de alcance** | — | no existe |
| 3 | Preamplificador | **externo**: habría que agregarlo | [`ruido_del_sistema.md`](ruido_del_sistema.md) §2.1 | no existe |
| 4a | Cancelación polo-cero | **no hace falta**: no hay preamplificador que deje cola; la cola del estímulo la ve la ventana | — | — |
| 4b | Filtro de conformado | **no hay filtro analógico**: el único es la caída del front-end a 60 MHz. Digitalmente, **la ventana de medición *es* el filtro** (un `boxcar` de N muestras) | [`mca/conformado_y_ruido.md`](mca/conformado_y_ruido.md), [`adc_ltc2145.md`](adc_ltc2145.md) §2.1 | sustituido |
| 4c | Ganancia / rango | **no hay ganancia programable**: jumper LV (±1 V) / HV (±20 V) y nada más. El pulso unipolar usa **la mitad del rango**, que es un bit perdido | [`platform.md`](platform.md) §4, [`adc_ltc2145.md`](adc_ltc2145.md) §4.3 | **limitación real** |
| 4d | Restaurador de base | seguidor IIR en la PL, `cfg_bl_ctrl` (`auto`, `k`, `holdoff`), con `baseline_now` legible para calibrar | [`ruido_del_sistema.md`](ruido_del_sistema.md) §5, [`mca/register_map_mca.md`](mca/register_map_mca.md) | **implementado, y configurable por registro** |
| 5a | Discriminador integral (LLD) | `cfg_thr` + `cfg_hyst` sobre la base seguida: el cruce **abre la ventana** | [`mca/ventana_de_medicion.md`](mca/ventana_de_medicion.md) | implementado |
| 5b | Discriminador diferencial (SCA) | `cfg_discr_*`: ventana `[min, max]` (o su complemento) sobre **cualquiera de las 16 features** del evento, **después de los divisores** | [`mca/parametros_de_merito.md`](mca/parametros_de_merito.md), [`mca/register_map_mca.md`](mca/register_map_mca.md) | **generalizado**: el SCA clásico corta en amplitud, éste corta en forma |
| 5c | Tiempo muerto / apilamiento | `holdoff`, `cfg_maxlen`, modo histéresis vs. compuerta fija, y relojes `realtime` / `livetime` / `deadtime` / `vetotime` de 64 bits | [`mca/tiempo_muerto.md`](mca/tiempo_muerto.md), [`mca/apilamiento.md`](mca/apilamiento.md) | **implementado y medido**, no estimado |
| — | Compuerta de coincidencia | veto al MCA desde el escudo de disparo (`mca_veto_i`), en tres formas: nivel, nivel con cola, ventana por flanco | [`datasheet/datasheet_mt_cfg.md`](datasheet/datasheet_mt_cfg.md) | implementado |
| 6a | Compuerta lineal + estirador | **no existe, y no hace falta**: el ADC no se dispara, convierte siempre a 125 MS/s. No hay nada que retener | [`platform.md`](platform.md) §2.1 | **eliminado** |
| 6b | Conversión A/D | LTC2145-14, 14 bit, 125 MS/s, continuo. La amplitud **se calcula**, no se convierte: `cfg_amp_src` elige muestra de pico o integral de la ventana | [`adc_ltc2145.md`](adc_ltc2145.md), [`mca/ventana_de_medicion.md`](mca/ventana_de_medicion.md) | **reemplazado**: no hay tiempo muerto de conversión por evento |
| 7 | Histograma | `mca_zoom` + BRAM: 8192 canales en 1D más un mapa 2D, con zoom alineado a potencias de 2 | [`mca/register_map_mca.md`](mca/register_map_mca.md) | implementado |
| 8 | Contabilidad | contadores `cnt_*` por causa de rechazo (umbral, amplitud, discriminador, histograma lleno) más los cuatro relojes | [`mca/register_map_mca.md`](mca/register_map_mca.md) | **más fino que un escalador**: la pérdida se atribuye a su causa |
| 9 | Registro y análisis | API en el ARM, y el `event_ring` para sacar **evento por evento** (modo lista) además del histograma | [`API/README.md`](API/README.md), [`event_ring/salida_por_red.md`](event_ring/salida_por_red.md), [`recorrido_del_usuario.md`](recorrido_del_usuario.md) | implementado |

---

## 4. Qué cambia de fondo, y no sólo de implementación

Cuatro diferencias que no son "lo mismo pero en FPGA":

1. **La cadena analógica decide antes de medir; ésta mide antes de decidir.**
   El umbral y la ventana del SCA se aplican sobre la señal, y lo que se
   descarta se pierde para siempre. Acá el evento se mide completo —16 features,
   incluidas las de forma— y el corte se aplica después, sobre números. Con el
   `event_ring` en modo lista, el corte deja de ser irreversible: se puede
   rehacer offline sobre los datos ya tomados.
2. **El corte puede ser por forma, no sólo por amplitud.** Un SCA no puede
   distinguir dos eventos de la misma amplitud y distinta forma; `cfg_discr_*`
   sobre una feature de forma sí. Es el corte que de verdad importa para separar
   el fotopico del continuo, y el que mide la mejora de 32.4 % a 0.8 % de
   contaminación de [`mca/parametros_de_merito.md`](mca/parametros_de_merito.md).
3. **Las constantes de tiempo son registros, no perillas ni componentes.** La τ
   del conformador era una decisión de hardware; acá el ancho de la ventana, la
   histéresis, el hold-off y la constante del seguidor de base se escriben en
   caliente. Lo que habilita es **barrerlos y medir el óptimo** en vez de
   elegirlos de memoria: así se encontró que el `bl_k` de todas las campañas
   estaba mal elegido ([`ruido_del_sistema.md`](ruido_del_sistema.md) §5).
4. **El tiempo muerto cambia de estructura y de estatus.** Deja de ser el tiempo
   de conversión del ADC y pasa a ser ventana + hold-off, y deja de estimarse:
   los relojes de tiempo vivo y muerto lo **cuentan** en hardware, con los
   rechazos separados por causa.

Y una que no cambia: **las etapas 1 a 3 siguen siendo analógicas y siguen
mandando.** Nada de lo digital mejora la estadística de portadores del detector
ni el ruido del preamplificador. Por eso el presupuesto de ruido de este
instrumento es, hoy, el de la electrónica sola.

---

## Ver también

| Documento | Qué contiene |
|---|---|
| [`ruido_del_sistema.md`](ruido_del_sistema.md) | el presupuesto de ruido de amplitud, etapa por etapa, con lo medido |
| [`mca/conformado_y_ruido.md`](mca/conformado_y_ruido.md) | la etapa 4b: cómo la forma del pulso trabaja el ruido |
| [`mca/ventana_de_medicion.md`](mca/ventana_de_medicion.md) | las etapas 5a y 6: cómo se abre la ventana y cómo se estima la amplitud |
| [`mca/tiempo_muerto.md`](mca/tiempo_muerto.md) | la etapa 5c, con los relojes y las correcciones |
| [`mca/parametros_de_merito.md`](mca/parametros_de_merito.md) | qué mide cada parámetro del instrumento, y cuál mueve qué |
| [`mca/limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md) | por qué el límite activo no es el ruido sino la deriva |
| [`platform.md`](platform.md) §2.1 | el front-end analógico de la placa, que es todo lo que queda de la etapa 4 |
| [`recorrido_del_usuario.md`](recorrido_del_usuario.md) | la cadena vista desde quien la usa |

## Bibliografía

| Ref | Para qué |
|---|---|
| **G. F. Knoll**, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010 | caps. 16–18: preamplificadores, conformado, discriminadores y MCA, módulo por módulo |
| **V. Radeka**, *Low-noise techniques in detectors*, Ann. Rev. Nucl. Part. Sci. **38** (1988) 217 | la etapa 3 y el compromiso de la 4b, con los índices de forma |
| **V. T. Jordanov, G. F. Knoll**, *Digital synthesis of pulse shapes in real time…*, Nucl. Instrum. Methods A **345** (1994) 337 | la 4b hecha digital: trapezoidal y cancelación polo-cero |

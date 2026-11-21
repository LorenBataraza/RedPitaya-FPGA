# Figuras: los problemas de la determinación de resolución

Siete figuras y tres videos sincronizados para explicar, sin fórmulas, por qué
medir la resolución de este MCA es más difícil de lo que parece. Los videos no
entran en un informe impreso, así que cada uno tiene además su **gemelo
estático**. Las generan [`figuras_resolucion.py`](figuras_resolucion.py),
[`animacion_cadena_mca.py`](animacion_cadena_mca.py),
[`figuras_cadena_tikz.py`](figuras_cadena_tikz.py) y
[`figuras_cadena_estatica.py`](figuras_cadena_estatica.py):

```bash
cd prj/MCA/docs/mca/figuras
python3 figuras_resolucion.py       # las siete figuras
python3 animacion_cadena_mca.py     # los tres videos (--gif para GIF)
python3 figuras_cadena_tikz.py      # 07a, 07b y 07c estáticas, en TikZ (.tex → .pdf y .svg)
python3 figuras_cadena_estatica.py  # 07_cadena.png, las tres juntas, y el manifiesto del datasheet
```

Los tres últimos salen de la **misma simulación** que los videos —misma semilla y
mismo número de cuadros—, así que los pulsos, las amplitudes y el espectro final
son los mismos: lo único que cambia es cómo se muestra el paso del tiempo.

Los gráficos van **sin texto adentro**: sólo ejes, leyenda y las marcas
imprescindibles. Los epígrafes de todas —con los números, el peso estadístico de
cada medición y el límite que en cada caso pone el **sistema de excitación** en
vez del MCA— están juntos en **[`epigrafes.txt`](epigrafes.txt)**, que escribe el
mismo script a partir de los datos para que no puedan desincronizarse.

Cinco figuras salen de **datos medidos** (los `.npz` de la 2ª campaña, en
[`software/datos/mca_20260528_001034/`](../../../software/datos/mca_20260528_001034/));
las otras dos y los videos son **esquemas sintéticos**.

| Figura | Qué muestra | Datos |
|---|---|---|
| [`01_pico_unico.png`](01_pico_unico.png) | El mismo pulso 20 020 veces: debería dar una raya en un canal y da un pico de 22, corrido del lugar. **FWHM e INL en la misma imagen** | medidos |
| [`02_linealidad_inl.png`](02_linealidad_inl.png) | La curva de linealidad con el **FWHM como barra de error**, y el residuo donde vive la INL | medidos |
| [`03_dnl_esquema.png`](03_dnl_esquema.png) | Qué es la DNL: la regla con las marcas desparejas, cómo se mide y qué le hace al pico | esquema |
| [`04_tres_metricas.png`](04_tres_metricas.png) | INL vs DNL vs FWHM sobre el mismo pico: arruinan cosas distintas | esquema |
| [`05_bineado.png`](05_bineado.png) | Qué pasa al rebinar el pico real: `h_shift` sólo puede empeorar | medidos |
| [`06_limites_estimulo.png`](06_limites_estimulo.png) | Dónde termina el MCA y empieza el generador (techo de throughput, ancho de pulso) | medidos |
| [`07a_senal.mp4`](07a_senal.mp4) | **Video**: la señal de entrada, con pulsos de distinta altura y el umbral | simulados |
| [`07b_cadena.mp4`](07b_cadena.mp4) | **Video**: `pulse_feature` emite un número por pulso y viaja al `histograma` | simulados |
| [`07c_histograma.mp4`](07c_histograma.mp4) | **Video**: el espectro que se acumula, una barra por cuenta | simulados |
| [`07a_senal.svg`](07a_senal.svg) | **Estática** (TikZ): 26 µs con los seis pulsos numerados y las dos bandas de `pulse_feature` — la ventana abierta (dispara en `thr`, cierra en `thr − hyst`) y el reposo previo, donde se re-arma y sigue la línea de base. Ojo: parten el eje de tiempo en estados, **no** la señal en eventos | simulados |
| [`07b_cadena.svg`](07b_cadena.svg) | **Estática** (TikZ): el tren de registros de evento sobre el cable, cada uno con el número de su pulso, y la tabla de los seis pulsos como los ve el `histograma` | simulados |
| [`07c_histograma.svg`](07c_histograma.svg) | **Estática** (TikZ): el espectro final en **barras apiladas**, una capa por tramo de la acumulación (hasta 12, 64 y 227 cuentas): la evolución en un solo gráfico | simulados |
| [`07_cadena.png`](07_cadena.png) | **Estática, las tres juntas**: la que conviene poner si en el informe entra una sola | simulados |
| [`09_fwhm_vs_eje.png`](09_fwhm_vs_eje.png) | La barra de error de la figura 2 **desplegada**: el FWHM a lo largo del eje, separado en su término aditivo y el proporcional | medidos |
| [`10_sintesis_triangular.png`](10_sintesis_triangular.png) | Cómo se aproxima un triángulo sumando CR-RC^n de distinto orden (Knoll fig. 17.6, de Goulding). Genera [`figuras_conformado.py`](figuras_conformado.py) | esquema |
| [`11_trapezoidal_tiempo_subida.png`](11_trapezoidal_tiempo_subida.png) | El conformador trapezoidal (Jordanov-Knoll) con tres tiempos de subida: si el techo dura más que su dispersión, los tres llegan a la misma amplitud — **sin déficit balístico** (Knoll fig. 17.7). Genera [`figuras_conformado.py`](figuras_conformado.py) | esquema |
| [`12_varianza_estimadores.png`](12_varianza_estimadores.png) | Dónde cae cada estimador de amplitud sobre cada familia de forma, contra la cota de Cramér-Rao, y de qué término está hecha su varianza. Genera [`varianza_estimadores.py`](../../../software/monte-carlo/varianza_estimadores.py) | simulados sobre ruido **medido** |
| [`13_estimadores_vs_ancho.png`](13_estimadores_vs_ancho.png) | Los cuatro estimadores contra el ancho del pulso, de 0.1 a 4 µs: dónde se cruzan y dónde empieza a pesar la fase de muestreo. Mismo script | simulados sobre ruido **medido** |
| [`12_varianza_estimadores_mca2.png`](12_varianza_estimadores_mca2.png), [`13_estimadores_vs_ancho_mca2.png`](13_estimadores_vs_ancho_mca2.png) | Las mismas dos sobre el MCA2: sin la integral por histéresis, con el trapecio | [`varianza_estimadores.py`](../../../software/monte-carlo/varianza_estimadores.py) |
| [`14_cuentas_vs_separacion.png`](14_cuentas_vs_separacion.png) | **Qué compran las cuentas**: un doblete de 1.2 FWHM que emerge del ruido entre 10² y 10⁴ cuentas, otro de 0.13 FWHM que no se ve en ninguna N, y la curva de significancia que explica a los dos. Genera [`figuras_limites.py`](figuras_limites.py) | esquema |
| [`15_bineado_vs_deteccion.png`](15_bineado_vs_deteccion.png) | **Qué compran los canales**, a N fija: la misma muestra con 1 a 16 canales/FWHM, y la información de Fisher que sobrevive al bineado — plana por encima de 4. Genera [`figuras_limites.py`](figuras_limites.py) | esquema |

---

## Qué dice cada figura

En [`epigrafes.txt`](epigrafes.txt), una entrada por figura y en el mismo orden.
Lo que sigue acá abajo no son epígrafes: son las dos preguntas de fondo que las
figuras dejan planteadas.


## Qué parámetros tengo sobre el bineado

Cinco registros tocan el eje de amplitud, y sólo uno de ellos puede **agregar**
resolución:

| Registro | Qué hace | ¿Sirve para medir mejor una región? |
|---|---|---|
| `cfg_h_shift` (`0x03C`) | `bin = amp >> h_shift` en el espectro 1D | **No.** Sólo agrupa: 0 ya es el máximo detalle |
| `cfg_amp_src` + `q_shift` (`0x038`) | `0` = muestra de pico, `1` = `Q_total >> q_shift` | **Sí, es el único con ganancia real** |
| `cfg_amp_min/max` (`0x030`/`0x034`) | Ventana de aceptación: rechaza afuera, cuenta en `cnt_rej_amp` | No mueve ni reescala el eje: **no es un zoom** |
| `cfg_gate_mode` + `gate_len` (`0x048`/`0x04C`) | Ventana por histéresis vs **compuertas de largo fijo** | **Sí, y es lo que más mejora** |
| `cfg_h2_shift` (`0x040`) | Sólo el eje de amplitud del mapa 2D (128 rebanadas) | No afecta al espectro 1D |

### Con la muestra de pico ya estás en el piso

Con `amp_src = 0` y `h_shift = 0`, **un canal es exactamente una cuenta del
ADC**: 122 µV a la entrada, 0.255 mV de consigna del generador. No hay nada
entre canales que el hardware pueda mostrar, así que:

- `h_shift` sólo puede **empeorar** (figura 5);
- hacer **zoom sobre el gráfico** de una región no agrega ninguna información —
  es recortar el array, no medir mejor.

### Con la integral sí hay ganancia, y es la respuesta a "más precisión"

`Q_total` de un pulso de 2 µs son ~250 muestras acumuladas: ~21 bits
significativos. Bajar `q_shift` **multiplica los canales por volt** y esos bits
son reales (el ruido blanco promedia como σ/√N). Medido en la 2ª campaña, con
`q_shift = 6` el mismo pulso de 0.5 Vpp cae cerca del canal **8400** en vez del
1920: **más de 4× canales sobre la misma región**.

El techo es doble: `amp` satura a 16 bits y el histograma a 2^14 canales, así que
todo lo que se pase cae en el bin superior. Eso lo vuelve un **zoom hacia abajo**:
podés desparramar la región de baja amplitud sobre todo el eje a costa de apilar
lo de arriba en el último canal.

> **Pero cuidado con la conclusión fácil:** con este estímulo, los 4× canales
> dieron **peor** resolución (0.53 % contra 0.34 % de la muestra de pico). Más
> bins no dan más precisión por sí solos — cuando el estimador no mejora, los
> canales de más resuelven ruido. Lo que sí mejora es **cambiar el estimador**:
> con **compuertas de largo fijo** (`gate_mode = 1`), medido offline sobre 7054
> pulsos reales, la integral pasa de 0.528 % a **0.149 %**.

### ¿Y para mirar una región chica en detalle?

Combinación recomendada, en este orden:

1. `gate_mode = 1` con `gate_short`/`gate_long` ajustadas al pulso, `amp_src = 1`;
2. `q_shift` bajado hasta que la región de interés ocupe buena parte de los 16384
   canales (con `autoscale_q_shift(target_channel=...)` de `mca_utils`);
3. `amp_min`/`amp_max` alrededor de la región, para no gastar tiempo muerto ni
   estadística en eventos que no te interesan;
4. `h_shift = 0` siempre, salvo que necesites achicar el espectro a propósito.

---

## ¿Estos números trabajan sobre canales o sobre volts?

Sobre **canales**. El hardware no sabe qué es un volt: `thr`, `hyst`, `amp`,
`amp_min/max` y los bins son enteros en cuentas de ADC, y los helpers de
`mca_utils` (`gauss_fit_peak`, `energy_calibration`, `dnl`) devuelven canales.
Los volts aparecen sólo al pasar por la calibración `canal = a·V + b`
(medida: **a = 3927 canales/Vpp**, **b = −28 canales**).

Eso importa porque **no todas las métricas se comportan igual** al cambiar de
unidad o de ganancia:

| Métrica | ¿Cambia si cambia la ganancia? | ¿Es igual en canales que en volts? |
|---|---|---|
| **FWHM** (canales) | **Sí**, escala con `a` | Es la misma magnitud: `FWHM_V = FWHM_ch / a` |
| **Resolución %** (`FWHM/centroide`) | No | **Casi**: sólo son iguales si el offset `b` es cero |
| **INL % FS** | No | **Sí**: es un cociente de dos magnitudes en las mismas unidades |
| **DNL** | **Sí, mucho** | Es por canal: sin decir `h_shift` no significa nada |
| **Corrimiento con la tasa %** | No | Igual que la resolución: sensible al offset |

Los dos casos que muerden:

- **El offset se cuela en los porcentajes.** La resolución en canales da
  `6.565/1920.1 = 0.342 %`; en volts, `6.565/(1920.1+28) = 0.337 %`. Un 1.5 %
  relativo de diferencia, chico pero sistemático, y **el número correcto es el de
  volts** — el de canales sólo coincide si el espectro es proporcional a la
  energía, que con `b = −28` no lo es.
- **La DNL depende del bineado.** Rebinar de a dos promedia canales vecinos y la
  DNL baja ~1/√2 sin que el ADC haya mejorado en nada. Es la única de las tres
  que cambia al hacer "zoom", así que siempre va acompañada del `h_shift` con el
  que se midió.

La INL, en cambio, es inmune a la ganancia: es el residuo dividido por el rango
barrido, los dos en canales. Lo que **sí** hay que declarar es **cuál es el fondo
de escala**: acá es el rango efectivamente barrido (3547 canales), no los 16384
del eje. Con la otra convención el mismo dato daría 0.24 % en vez de 1.13 %.

---

## Los límites que pone el generador, no el MCA

Es la distinción que más contamina estos números, y por eso tiene figura propia:
el techo de throughput de la figura 6 es del **DG4162**, no del MCA, y el
corrimiento del pico con la tasa está confundido con el ancho de pulso que el
propio generador cambia. Los detalles, con los números, en el epígrafe de la
figura 6.

Los otros dos límites del estímulo están en las figuras 2 y 3: la **INL no
separada** de la exactitud del generador, y la **DNL que no se puede medir** sin
modulación de amplitud.

---

## Enlaces

- El **por qué** de cada parámetro: [`decisiones_diseno_mca.md`](../decisiones_diseno_mca.md) §2
- Los **números medidos** con sus salvedades: [`resultados_validacion_hw.md`](../../resultados_validacion_hw.md)
- El **método** de cada test: [`testbenches_software_mca.md`](../testbenches_software_mca.md)
- Los **registros**: [`register_map_mca.md`](../register_map_mca.md)
- Los **límites** de resolución y la deriva: [`limites_resolucion_y_deriva.md`](../limites_resolucion_y_deriva.md) — su figura la genera [`figuras_limites.py`](figuras_limites.py)
- El **panorama de `mca_top`** (de la muestra al histograma en estilo datapath, para una A4 vertical, con un color por función y cada decisión marcada **Dn**): [`panorama_mca_top.tex`](panorama_mca_top.tex), en TikZ con la paleta de los demás panoramas — `pdflatex` da el `.pdf` de la tesis y `pdftocairo -svg` el `.svg` de los documentos
- Los **datapaths de nivel 2**, con el mismo estilo y los mismos colores: [`panorama_mca_window.tex`](panorama_mca_window.tex) (el disparo, el asignador, el banco de trapecios, las ranuras y la contabilidad) y [`panorama_mca_slot.tex`](panorama_mca_slot.tex) (una ranura: las compuertas, el estado y una fila por acumulador). Los epígrafes, en `panorama_mca_window.txt` y `panorama_mca_slot.txt`
- Las **figuras de opciones** de cada decisión D1–D13 (las alternativas, el mux y el registro que elige): [`decisiones/`](decisiones/), una `.tex` por decisión con el mismo estilo y el macro `\muxdec` de [`estilo_tikz.tex`](../../figuras/estilo_tikz.tex). Las usa [`vista_general_mca.md`](../vista_general_mca.md). Para regenerarlas: `for f in decisiones/d*.tex; do (cd decisiones && pdflatex $(basename $f) && pdftocairo -svg $(basename ${f%.tex}).pdf); done`. [`d08_ranuras.tex`](decisiones/d08_ranuras.tex) es el detalle de D8: los estados de una ranura y lo que guarda. La de D13 no se dibuja a mano: [`d13_trapecio.py`](decisiones/d13_trapecio.py) calcula las curvas con el modelo de referencia del RTL (`estimadores.trapecio`, el de `tb_mca_trap`) y escribe `d13_trapecio.tex`. [`d13_recuperacion.py`](decisiones/d13_recuperacion.py) es el detalle de D13: la entrada, el escalón que deja el polo-cero, `r`, la salida y la salida con M un 5 % bajo, con la misma recursión que el RTL **Históricas** (de antes de las ranuras, que retiraron D4, D5 y D6): `d04_apertura`, `d05_cierre`, `d06_rearmado` y [`d06_rearmado_logica.tex`](decisiones/d06_rearmado_logica.tex), el detalle de quién ponía y quién sacaba `armed`
- El **trapecio por dentro**, en [`trapecio/`](trapecio/): [`figuras_separacion.py`](trapecio/figuras_separacion.py) dibuja un pulso registro por registro de `mca_trap` (`trap_etapas`) y dos pulsos con la ventana de cada ranura y el error contra Δt (`trap_separacion`), con la misma recursión que el RTL; [`figuras_mejora.py`](trapecio/figuras_mejora.py) compara pico, integral, trapecio y la integral menos la cola del anterior contra Δt, con parámetros de la placa y ruido (`trap_mejora`). Las usa [`separacion_trapezoidal.md`](../separacion_trapezoidal.md). [`figuras_recuperacion.py`](trapecio/figuras_recuperacion.py), sobre el modelo de [`recuperacion_modelo.py`](trapecio/recuperacion_modelo.py) (ranuras y publicador como en el RTL, tren Poisson), dibuja cuántos pulsos buenos captura cada número de ranuras (`trap_ranuras`) y cómo recuperan los solapados un banco de trapecios y la descomposición de los estimadores (`trap_recuperacion`); las usa [`ranuras_y_recuperacion.md`](../ranuras_y_recuperacion.md). [`pruebas_banco.py`](trapecio/pruebas_banco.py) prueba el banco antes del RTL con el ruido y la subida de las capturas e2e, la latencia y la resolución de pares del multitrigger y del disparo con polo-cero (k = 2, m = 1) simuladas en Questa con [`tb_banco_disparo.sv`](trapecio/tb_banco_disparo.sv) (resultados en `banco_latencias*.txt` y `banco_pares*.txt`), modelos de los dos disparos validados contra ese RTL, un tren de Poisson completo y el inspector de apilamiento; escribe `banco_pruebas.json` y la figura `banco_pruebas`, y [`banco_vectores_trap.py`](trapecio/banco_vectores_trap.py) arma los vectores para probar `mca_trap` bit a bit con esas formas. Con el RTL ya hecho, `tb_banco_disparo.sv` simula la fuente real del multitrigger (un segundo `mt_top`), y [`banco_e2e.py`](trapecio/banco_e2e.py) corre [`tb_banco_e2e.sv`](trapecio/tb_banco_e2e.sv) (`mt_top` con el polo-cero y `mca_top` con el banco) sobre el tren de Poisson y compara el volcado contra el modelo (`banco_e2e_g112_p16.json`). Los usa [`pruebas_banco_trapecios.md`](../pruebas_banco_trapecios.md).
- El **banco de trapecios**, en [`trapecio/`](trapecio/): [`figuras_banco.py`](trapecio/figuras_banco.py) dibuja, con el golden model, qué son k, m y la ventana ([`banco_formas_anatomia.svg`](trapecio/banco_formas_anatomia.svg)), un par medido con cada forma ([`banco_formas_par.svg`](trapecio/banco_formas_par.svg)), la regla que elige la forma ([`banco_formas_regla.svg`](trapecio/banco_formas_regla.svg)), cómo los disparos vecinos deciden la forma de cada pulso ([`banco_uso.svg`](trapecio/banco_uso.svg)), y cómo usa las ranuras el banco, con las 3 ranuras y 3 formas de hoy ([`banco_ranuras.svg`](trapecio/banco_ranuras.svg)). `python3 figuras_banco.py banco_ranuras` rehace sólo las nombradas.
- La **publicación**, en [`publicacion/`](publicacion/): el bus de features, de dónde sale cada ranura y quién lo consume ([`bus_features.tex`](publicacion/bus_features.tex), a mano), y el publicador en dos figuras: su FSM ([`fsm_publicador.svg`](publicacion/fsm_publicador.svg)) y un cronograma de dos eventos ([`cronograma_publicador.svg`](publicacion/cronograma_publicador.svg)). Las dos las escribe [`fsm_publicador.py`](publicacion/fsm_publicador.py), que dibuja el CSV de [`tb_fsm_publicador.sv`](publicacion/tb_fsm_publicador.sv) (`--sim` re-simula). Los epígrafes, en `bus_features.txt`, `fsm_publicador.txt` y `cronograma_publicador.txt`
- El **costo de las ranuras**, en [`recursos/`](recursos/): [`recursos_ranuras.py`](recursos/recursos_ranuras.py) sintetiza `mca_top` con `N_ACC` = 1..7 (`--sintetizar`, unos 5 minutos) y dibuja LUT, FF y WNS por bloque desde el CSV versionado
- La **vista de entrada a la contabilidad**, [`contabilidad/mca_freno_descarte.tex`](contabilidad/mca_freno_descarte.tex): dónde descarta el MCA (por falta de lugar), dónde bloquea y dónde rechaza por criterio, cada pérdida con su contador. Usa las convenciones de [`etapas_vs_descartes.tex`](../../figuras/etapas_vs_descartes.tex) y [`ring_freno_descarte.tex`](../../event_ring/figuras/ring_freno_descarte.tex). El epígrafe está en `mca_freno_descarte.txt`
- La **lógica del tiempo muerto**, en [`contabilidad/`](contabilidad/): cómo se reparte cada ciclo entre los casilleros ([`tm_teselado.tex`](contabilidad/tm_teselado.tex)), cada cruce de umbral entre los contadores de arribos ([`tm_arribos.tex`](contabilidad/tm_arribos.tex)) y cómo se miden los períodos muertos ([`tm_periodo.tex`](contabilidad/tm_periodo.tex)). El **cronograma** ([`tm_cronograma.svg`](contabilidad/tm_cronograma.svg)) no se dibuja a mano: [`tb_tm_cronograma.sv`](contabilidad/tb_tm_cronograma.sv) corre dos `mca_top`, uno con una ranura y otro con dos, sobre el mismo tren de pulsos y los mismos disparos, y vuelca el CSV, y [`tm_cronograma.py`](contabilidad/tm_cronograma.py) lo dibuja (`--sim` re-simula con Questa; sin el flag usa el CSV versionado)

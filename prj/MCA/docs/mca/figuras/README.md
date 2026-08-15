# Figuras: los problemas de la determinación de resolución

Seis figuras y una animación para explicar, sin fórmulas, por qué medir la
resolución de este MCA es más difícil de lo que parece. Las generan
[`figuras_resolucion.py`](figuras_resolucion.py) y
[`animacion_cadena_mca.py`](animacion_cadena_mca.py):

```bash
cd prj/MCA/docs/mca/figuras
python3 figuras_resolucion.py       # las seis figuras
python3 animacion_cadena_mca.py     # el video (--gif para GIF)
```

Los gráficos van **sin texto adentro**: sólo ejes, leyenda y las marcas
imprescindibles. Los epígrafes de todas —con los números, el peso estadístico de
cada medición y el límite que en cada caso pone el **sistema de excitación** en
vez del MCA— están juntos en **[`epigrafes.txt`](epigrafes.txt)**, que escribe el
mismo script a partir de los datos para que no puedan desincronizarse.

Cuatro figuras salen de **datos medidos** (los `.npz` de la 2ª campaña, en
[`software/datos/mca_20260528_001034/`](../../../software/datos/mca_20260528_001034/));
las otras dos y el video son **esquemas sintéticos**.

| Figura | Qué muestra | Datos |
|---|---|---|
| [`01_pico_unico.png`](01_pico_unico.png) | El mismo pulso 20 020 veces: debería dar una raya en un canal y da un pico de 22, corrido del lugar. **FWHM e INL en la misma imagen** | medidos |
| [`02_linealidad_inl.png`](02_linealidad_inl.png) | La curva de linealidad con el **FWHM como barra de error**, y el residuo donde vive la INL | medidos |
| [`03_dnl_esquema.png`](03_dnl_esquema.png) | Qué es la DNL: la regla con las marcas desparejas, cómo se mide y qué le hace al pico | esquema |
| [`04_tres_metricas.png`](04_tres_metricas.png) | INL vs DNL vs FWHM sobre el mismo pico: arruinan cosas distintas | esquema |
| [`05_bineado.png`](05_bineado.png) | Qué pasa al rebinar el pico real: `h_shift` sólo puede empeorar | medidos |
| [`06_limites_estimulo.png`](06_limites_estimulo.png) | Dónde termina el MCA y empieza el generador (techo de throughput, ancho de pulso) | medidos |
| [`07_cadena_mca.mp4`](07_cadena_mca.mp4) | **Video**: pulsos → `pulse_feature` → un número → `histograma` → el espectro creciendo | simulados |

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

# Figuras: la geometría N1 × N2 del mapa 2D contra el límite de memoria

Cuatro figuras para decidir el par `H2_AW` × `PSD_AW` del mapa de amplitud ×
factor de forma: qué geometrías se pueden construir, cuál es el límite que ata
en cada caso, y qué par pide cada aplicación. Las genera
[`figuras_mapa2d.py`](figuras_mapa2d.py), con la misma convención que el resto
de [`figuras/`](../): sin texto adentro, paleta y rcParams de
[`../../../figuras/estilo.py`](../../../figuras/estilo.py).

```bash
cd prj/MCA/docs/mca/figuras/mapa2d
python3 figuras_mapa2d.py      # las cuatro figuras, epigrafes.txt y las tablas
```

Son **esquemas de diseño**: no entra ningún `.npz`. Los dos únicos números
medidos son el **FWHM del eje** (8.6 canales sobre 2¹³, 2ª campaña, de
[`../../register_map_mca.md`](../../register_map_mca.md)) y el **costo en tiles
del build actual** (25 tiles, de [`../../../platform.md`](../../../platform.md)
§4.7), con el que se valida el modelo de ocupación de BRAM. El script
**comprueba** esas dos cosas antes de dibujar: si el modelo deja de predecir los
8 tiles del histograma 1D o el 0.31 % de pérdida por binning a 8.6 bins/FWHM,
falla con un `assert` en vez de dibujar un gráfico mentiroso.

| Figura | Qué muestra | Datos |
|---|---|---|
| [`01_plano_decision.png`](01_plano_decision.png) | **El plano (N1, N2) entero**, con cada geometría coloreada según qué hace falta para construirla, las diagonales de costo constante y el build de hoy | esquema |
| [`02_limite_memoria.png`](02_limite_memoria.png) | (a) tiles contra bins totales para tres anchos de contador, con los techos del 7010/7020 y la apertura; (b) por qué `CW = 32` sale gratis y qué cuesta bajarlo | esquema, modelo validado |
| [`03_requisito_vs_alcance.png`](03_requisito_vs_alcance.png) | El N1 que pide cada aplicación contra los tres techos alcanzables con N2 = 64 | esquema + un punto medido |
| [`04_bineado_y_zoom.png`](04_bineado_y_zoom.png) | (a) la pérdida por binning (Sheppard) contra bins/FWHM; (b) cómo el zoom recupera resolución sin agregar bins, y dónde deja de poder | esquema |

Los **epígrafes**, con todos los números recalculados, están en
[`epigrafes.txt`](epigrafes.txt), que escribe el mismo script.

---

## Las aplicaciones numeradas

Son las mismas en las figuras 1 y 3. El N1 sale de meter 4 bins dentro del FWHM
del pico más angosto de esa familia de detector; el N2, de que las dos
poblaciones de forma están separadas ~0.12 con FWHM ~0.04 en unidades de
`Q_cola/Q_total`, o sea ~3 bins por FWHM con 64 bins sobre el rango completo.

**Los FWHM por familia son valores típicos de literatura, no medidos.** La única
fila medida es la estrella roja de la figura 3, que es el eje de esta placa.

| # | Aplicación | N1 × N2 | FWHM / FS | ¿Se construye? |
|---|---|---|---|---|
| 1 | Rechazo de apilamiento (el corte es en forma) | 64 × 64 | — | **sí** |
| 2 | n/γ PSD, centelleador plástico o líquido | **128 × 64** | 5.4 × 10⁻² | **sí, es el build de hoy** |
| 3 | α/β/γ, phoswich o CsI(Tl) | 256 × 128 | 3.1 × 10⁻² | **sí** |
| 4 | NaI(Tl) con compuerta | 512 × 64 | 1.6 × 10⁻² | pide apertura de 128 KB |
| 5 | CdZnTe, corte por tiempo de subida | 1024 × 64 | 6.7 × 10⁻³ | pide un 7020 |
| 6 | Telescopio ΔE-E | 512 × 512 | — | no entra en BRAM |
| 7 | HPGe, limpieza del fotopico | 4096 × 128 | 5.4 × 10⁻⁴ | no entra en BRAM |
| 8 | Matriz γ-γ | 4096 × 4096 | 5.4 × 10⁻⁴ | no entra en BRAM, por tres órdenes |

---

## Lo que sale de las cuatro figuras

**El costo depende de la suma de los exponentes, no del reparto.** El mapa ocupa
`2^(H2_AW+PSD_AW)` palabras, así que moverse por una anti-diagonal del plano es
gratis: 256 × 64 y 128 × 128 cuestan exactamente lo mismo. Eso convierte la
decisión en dos preguntas separadas — *cuántos bins en total me puedo permitir* y
*cómo los reparto* — y sólo la primera toca el hardware.

**Con `CW = 32` el límite que ata no es la BRAM, es la apertura del bus.** La
apertura de 64 KB se llena a 2¹⁴ bins, que son 16 tiles, cuando en el 7010 quedan
**43 libres**. Hay un factor 2.7 de BRAM comprada y no usada, y para llegar a
ella hay que tocar el decode de `sys_addr[19:16]`, no el chip:

| | Bins totales | Tiles | Ejemplos |
|---|---|---|---|
| Hoy (apertura 64 KB) | 2¹⁴ | 16 de 43 | 256 × 64, 128 × 128 |
| 7010, apertura 128 KB | 2¹⁵ | 32 de 43 | 512 × 64, 256 × 128 |
| 7020, apertura 256 KB | 2¹⁶ | 64 de 123 | 1024 × 64, 256 × 256 |

**`CW = 32` sale gratis y `CW = 24` es el peor punto de la curva.** El RAMB36
tiene anchos nativos 1K×36, 2K×18 y 4K×9, así que cualquier contador de 19 a 36
bits cuesta *exactamente* lo mismo. El único ahorro real es cruzar a ≤18 bits,
que duplica los bins por tile; el precio, con el bin caliente llevándose el 2 %
de los eventos a 50 kev/s, es saturar en **66 s** con 16 bits contra **50 días**
con los 32 de hoy.

**Duplicar una vez es barato; más allá, la respuesta no es más BRAM.** Una matriz
γ-γ de 4096 × 4096 son 2²⁴ palabras: tres órdenes de magnitud por encima de lo
que hay en el chip. Esa familia pide **modo lista en DDR e histogramado
offline**, que es la arquitectura clásica de los sistemas de dos parámetros
justamente por esto.

**Y antes de pedir más bins, conviene gastar el zoom.** Con los 128 de hoy y sin
zoom el bin del eje X mide 7.4 veces el FWHM medido y el pico aparece ensanchado
5.1×. Pero [`mca_zoom`](../../../../modulos/mca/rtl/mca_zoom.sv) entra con los 16
bits de la feature y no con los 7 del eje, así que `z` llega a 9: con `z = 6` los
mismos 128 bins cubren 1/64 del fondo de escala y el bin vuelve a valer lo que el
del espectro 1D. Las ventanas están anidadas en potencias de 2, así que dos tomas
con zoom distinto se suman con aritmética entera sin re-samplear. El límite está
en `k`: el enmascarado `8'hFF >> (4'd8 - z)` envuelve en 4 bits para `z ≥ 9` y
deja `k = 0`, o sea que con esos niveles sólo se entra a la ventana más baja del
rango — lo que hace falta para `F_INVW`, que vive cerca de cero, y lo que arruina
a `F_PSD`, cuyo cociente cae en 0.3–0.6 del fondo.

---

## Enlaces

- Los **registros** del mapa y del zoom: [`../../register_map_mca.md`](../../register_map_mca.md)
- El **RTL**: [`mca_top.sv`](../../../../modulos/mca/rtl/mca_top.sv) §`i_hist_2d`, [`mca_zoom.sv`](../../../../modulos/mca/rtl/mca_zoom.sv)
- El **presupuesto de BRAM** del build: [`../../../platform.md`](../../../platform.md) §4.7
- Qué discrimina el eje de forma: [`../../apilamiento.md`](../../apilamiento.md)
- La **FOM** de separación: [`../../parametros_de_merito.md`](../../parametros_de_merito.md)

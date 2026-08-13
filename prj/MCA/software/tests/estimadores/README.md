# Comparación de estimadores de amplitud (etapa A)

Responde offline la pregunta que dejó abierta la campaña: **por qué la integral
de carga dio peor resolución que la muestra de pico** (0.528 % contra 0.344 %),
cuando la teoría dice que debería promediar el ruido como σ/√N.

**Corre en la PC, sin placa.** Usa las trazas crudas que ya dejó el pipeline de
adquisición: `../../datos/e2e_20260528_013404/principal/`, **7054 ventanas de
pulso** de 512 muestras, mismo estímulo de 2 µs y misma noche que la campaña.

```bash
python3 test_estimadores.py     # valida la réplica del RTL
python3 analizar.py             # el análisis (~3 min)
python3 analizar.py <dir>       # sobre otro conjunto de chunks
```

## Resultado

| Estimador | Resolución | |
|---|---|---|
| integral, ventana por histéresis | 0.528 % | *medido en placa* |
| **pico** | **0.272 %** | réplica; en placa 0.344 % |
| **trapecio** (k=192, m=160) | **0.212 %** | |
| **integral, compuerta fija de 384** | **0.149 %** | **el mejor** |

**La integral no era mala: lo era la definición de ventana.** Con compuerta de
largo fijo la carga mejora **1.83× sobre el pico** y **3.55× sobre la integral
con ventana por histéresis** que se midió en placa. Eso justifica la etapa B.

El trapecio queda **por debajo de la compuerta fija** y además costaría la mitad
del throughput (`2k+m` por evento contra los 794 kcps medidos). Con esta señal
no se justifica; su argumento sigue siendo el corrimiento de centroide con la
tasa (+6.45 %), que este conjunto **no puede medir** porque se tomó a una sola
tasa.

## Por qué la ventana por histéresis pierde

El RTL cierra la ventana donde la cola cruza `thr − hyst`
([`mca_pulse_feature.sv:152`](../../../rtl/mine/mca/mca_pulse_feature.sv#L152)),
que es la zona **más chata** del pulso: con τ = 186 muestras medidas y σ = 2.8
cuentas de ruido, el punto de cruce tiembla ~9 muestras, y cada muestra de más o
de menos suma o resta ~60 cuentas a la carga. La compuerta fija no depende del
ruido: por eso gana.

El otro término, cuantificado acá, es el **error de línea de base × N**: con una
base estimada de 8 muestras (σ = 1.80 cuentas) sobre una compuerta de 384, el
error es 690 cuentas sobre 590 931 = 0.117 %, y se ve en la tabla del bloque 3
(0.149 % con base global contra 0.263 % con base por evento). El seguidor IIR
del RTL promedia sobre miles de muestras, así que en la placa este término es
mucho menor — pero **crece con el largo de la compuerta**, y hay que tenerlo en
cuenta al elegirlo.

## Validación de la réplica

`estimadores.segmentar_rtl()` es una réplica ciclo a ciclo de
`mca_pulse_feature.sv`. Se valida por dos caminos independientes:

1. **Contra el testbench de RTL**: reproduce los valores exactos que ya verifica
   [`tb_mca_pulse_feature.sv`](../../../sim/tb_mca_pulse_feature.sv) — pulso
   rectangular de 20×500, `thr=100`, `hyst=50`, `tail_dly=1` → `q_tot = 10000`,
   `q_tail = 9500`, `psd = 60`. Más el clamp a ≥0, el pico estricto y la muestra
   de cierre que no se acumula.
2. **Contra la placa**: la σ del pico da **2.78 cuentas** y el hardware midió
   **2.81**. Coinciden al 1 %. (La resolución en % difiere porque la amplitud de
   este conjunto es 2410 cuentas y la de la campaña 1920: es la *misma* σ.)

## Límite de este conjunto de datos

Las capturas tienen 512 muestras y la ventana por histéresis del MCA se cerraría
recién en la **~786**, así que el 100 % de los pulsos quedan truncados: **la
integral por histéresis no se puede reproducir offline con estos datos**. La
comparación pico contra compuerta fija sí es rigurosa, y es la que decide.

Para reproducirla habría que recapturar con `post ≥ 835` muestras. `analizar.py`
lo detecta y lo dice en vez de devolver un número.

## Archivos

| Archivo | Qué es |
|---|---|
| `estimadores.py` | funciones puras: réplica del RTL, compuertas fijas, trapecio |
| `test_estimadores.py` | valida la réplica y las alternativas, sin datos ni placa |
| `analizar.py` | corre todo sobre los pulsos reales y da el veredicto |

## Bibliografía

- **F. D. Brooks**, *A scintillation counter with neutron and gamma-ray
  discriminators*, Nucl. Instrum. Methods **4** (1959) 151 — el método de
  comparación de carga con dos compuertas fijas.
- **V. T. Jordanov, G. F. Knoll**, *Digital synthesis of pulse shapes in real
  time for high resolution radiation spectroscopy*, Nucl. Instrum. Methods A
  **345** (1994) 337 — el trapecio recursivo.
- **G. F. Knoll**, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010 —
  cap. 17 (discriminación por forma), cap. 4 (tiempo muerto).

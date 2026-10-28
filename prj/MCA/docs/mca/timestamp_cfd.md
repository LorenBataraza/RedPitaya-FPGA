# El timestamp con CFD: cuánto mejora y dónde conviene hacerlo

Hoy el instante de un evento es la muestra en que la señal cruzó un umbral
fijo: un disparo de **nivel** (*leading edge*, LED). Eso tiene dos defectos,
documentados en [`ventana_de_medicion.md`](ventana_de_medicion.md) §5 y en
[`fuentes_de_jitter.md`](fuentes_de_jitter.md) §3–4:

- **walk**: un pulso chico cruza el umbral más tarde que uno grande que llegó al
  mismo tiempo;
- **cuantización**: el instante se redondea a la muestra, `Ts = 8 ns`, lo que da
  `σ = Ts/√12 = 2.31 ns`.

Este documento cuantifica qué gana el timestamp con un **discriminador de
fracción constante (CFD)** digital, frente a las otras dos correcciones posibles
(interpolar el cruce y corregir el walk por software), y dónde conviene
implementarlo.

**Cómo se obtuvo.** Monte Carlo de
[`figuras/cfd/figuras_cfd.py`](figuras/cfd/figuras_cfd.py), que tarda unos 4 s:

- el mismo modelo de pulso que [`figuras/ventana/`](figuras/ventana/): subida
  exponencial y cola de 1650 ns;
- el ruido blanco medido, σ_w = 4.47 cuentas por muestra;
- umbral de 100 cuentas;
- la fase de arribo al azar dentro de la muestra.

Se simulan dos formas: subida de **100 ns** (el pulso del generador, unas 12
muestras de flanco) y de **20 ns** (un detector rápido, 2.5 muestras).

---

## 1. El CFD

![Principio del CFD](figuras/cfd/01_cfd_principio.png)

*Figura 1. (a) El walk del disparo de nivel. (b) La construcción del CFD.
(c) Las tres amplitudes cruzan cero en el mismo instante.*

El CFD forma

```
y[n] = f·x[n] − x[n−D]
```

la señal atenuada por `f` menos una copia retardada `D` muestras. Es otra vez
una superposición de dos copias del mismo pulso, como el trapezoidal de
[`../mt/procesamiento_pendiente.md`](../mt/procesamiento_pendiente.md). `y`
empieza positiva, cruza cero cuando la copia retardada alcanza a la atenuada,
y el instante es el de ese cruce.

**Por qué no tiene walk.** `y` es lineal en `x`: si todos los pulsos tienen la
misma forma y solo cambia la amplitud, `y` es la misma curva escalada y su cero
no se mueve (figura 1c).

**Lo que hace falta agregarle:**
- **Armado.** Un umbral de nivel decide que hay un pulso. Sin él, el CFD
  dispararía en cada cruce por cero del ruido.
- **Interpolación del cruce.** El cero cae entre dos muestras. Sin interpolar,
  el CFD vuelve a cuantizar a 8 ns.

## 2. Resultados: walk y jitter contra la amplitud

![Walk y jitter](figuras/cfd/02_walk_jitter.png)

*Figura 2. Walk (izquierda) y jitter (derecha) de cinco estimadores. Arriba
subida de 100 ns; abajo, 20 ns.*

Los cinco estimadores:

| Estimador | Qué es | Costo |
|---|---|---|
| **LED** | lo que hace el RTL hoy | — |
| **LED + interpolación** | recta entre las dos muestras que encierran el umbral | software |
| **LED + interp. + corrección de walk** | lo anterior menos una curva `w(A)` calibrada con pulser, evaluada en la amplitud medida del mismo evento | software |
| **CFD** | primer cruce de `y` después del armado | RTL o software |
| **CFD + interpolación** | ídem, con el cruce interpolado | RTL o software |

Resultados con subida de 100 ns (f = 1/4, D = 8):

| Estimador | walk 150→8192 | σ a A=150 | σ a A=400 | σ a A=2000 | σ a A=8192 |
|---|---|---|---|---|---|
| LED (RTL actual) | **41.6 ns** | 3.82 | 2.38 | 2.31 | 2.29 ns |
| LED + interpolación | 44.3 ns | 2.54 | 0.50 | 0.75 | 1.50 ns |
| LED + interp. + corr. walk | 3.1 ns | 2.72 | 0.50 | 0.75 | 1.50 ns |
| CFD | 0.04 ns | 2.82 | 2.40 | 2.32 | 2.29 ns |
| **CFD + interpolación** | **0.03 ns** | **1.32** | **0.51** | **0.12** | **0.061 ns** |

Con subida de 20 ns (f = 1/2, D = 3), el CFD interpolado da walk 0.01 ns y σ
de 0.58 ns (A = 150) a 0.29 ns (A = 8192). El LED actual da 9.5 ns de walk y
2.3 ns de σ.

Cuatro lecturas:

1. **El walk es lo que manda en el RTL actual.** Con el pulso del generador son
   **42 ns** de punta a punta del rango, 18 veces la cuantización. Lo eliminan
   tanto el CFD como la corrección por software. La corrección deja 3 ns cerca
   del umbral, porque ahí la amplitud medida (con la que se corrige) ya es
   ruidosa.
2. **Sin interpolar, el CFD no mejora el jitter.** Elimina el walk pero se queda
   en `Ts/√12`. La interpolación no es opcional.
3. **Interpolar el LED empeora los pulsos grandes.** Para A ≫ thr, el umbral cae
   en el quiebre donde arranca el pulso, y la recta entre una muestra en la base
   y otra en el flanco no sigue esa curva. El error depende de la fase y crece
   con la amplitud (1.5 ns a 8192; 2 ns con flanco rápido). El CFD no tiene
   este problema porque cruza en el medio del flanco, donde `y` es casi recta.
4. **El CFD interpolado sigue a `σ_w/pendiente`** en todo el rango. Con pulsos
   grandes baja a 60 ps: dos órdenes de magnitud mejor que hoy.

## 3. El caso de uso: coincidencias entre canales

![Coincidencias](figuras/cfd/03_coincidencias.png)

*Figura 3. Δt entre dos canales que reciben pulsos simultáneos de amplitudes
independientes (log-uniformes entre 150 y 8192 cuentas).*

Donde el timestamp importa de verdad es al **comparar** dos eventos: una
coincidencia entre ch0 y ch1, un tiempo de vuelo o una correlación con una
referencia externa. Ahí el walk de cada canal **no se cancela**, porque las
amplitudes son distintas.

| Estimador | FWHM (100 ns) | σ (100 ns) | FWHM (20 ns) | σ (20 ns) |
|---|---|---|---|---|
| LED (RTL actual) | 13.7 | 14.0 | 9.7 | 4.5 |
| LED + interpolación | 13.0 | 14.5 | 10.1 | 5.2 |
| LED + interp. + corr. walk | 2.9 | 1.6 | 4.6 | 1.9 |
| CFD sin interpolar | 8.6 | 3.4 | 8.2 | 3.3 |
| **CFD + interpolación** | **0.45** | **0.68** | **0.85** | **0.49** |

(ns)

- Con el pulso del generador, el CFD interpolado angosta la distribución de Δt
  de **13.7 a 0.45 ns** de FWHM, unas **30 veces**.
- La corrección de walk por software, que no requiere hardware nuevo, lleva el
  FWHM a 2.9 ns, unas 5 veces, pero deja colas de los eventos cerca del umbral
  (σ = 1.6 ns).

## 4. Elección de f y D

![Parámetros](figuras/cfd/04_parametros_cfd.png)

*Figura 4. Jitter del CFD interpolado a A = 400 contra D, para f = 1/8, 1/4 y
1/2.*

- **D tiene un mínimo duro.** El cruce de `y` tiene que caer **después** del
  armado, incluso para el pulso más chico, donde el armado llega más tarde.
  Con D corto el cruce se adelanta al armado y el evento se pierde. Esos puntos
  faltan en la figura: D ≥ 6 para la subida de 100 ns y D ≥ 2 para la de 20 ns.
  Por encima de ese mínimo, D casi no importa.
- **f depende del flanco.**
  - Con flanco lento, f = 1/2 cruza arriba en el flanco, donde la pendiente ya
    bajó, y es la peor. Entre 1/8 y 1/4 gana 1/4, porque 1/8 se degrada cerca
    del umbral.
  - Con flanco rápido manda el error de la interpolación, y f = 1/2 lo
    minimiza porque cruza en el medio del flanco.
- **Las tres fracciones se implementan con desplazamientos**, sin
  multiplicador.

## 5. Dónde implementarlo

**En el event ring: en software, ya, sin tocar el RTL.**

Cada slot del ring
([`event_slot_writer.sv`](../../modulos/event_ring/rtl/event_slot_writer.sv))
guarda el timestamp del disparo y `pre + post` muestras de **los dos canales**.
O sea que el flanco ya está en DDR. El CFD se calcula sobre esas muestras:

```
t_evento = ts + (n_cruce_interpolado − pre)       [en muestras]
```

y la Δt entre canales sale de las dos series del **mismo** slot, que comparten
`ts`.

La única condición es que `pre` alcance para ver `D` muestras antes del cruce.
Con la forma de 100 ns el cruce cae unos 73 ns después del arribo y el disparo
de nivel puede llegar hasta 46 ns tarde, así que alcanzan unas 5 muestras. El
default es `pre = 8`.

**Esto da el resultado de la fila CFD + interpolación de las tablas sin costo
de hardware.** Es el primer paso, y el que conviene validar en placa antes de
decidir nada más (§7).

**En RTL, solo si hace falta en tiempo real.** Por ejemplo, para una ventana de
coincidencia hecha por hardware (en el `trigger_shield`) o como fuente de
disparo del multitrigger. El costo es parecido al de `mt_slope_trig`, sin el
acumulador:

| Pieza | Implementación |
|---|---|
| retardo `D ≤ 16` | una línea en SRL, 14 bits |
| `f·x` | desplazamientos (1/4 = `>>2`, 1/2 = `>>1`) |
| `y` | una resta |
| cruce | cambio de signo de `y`, habilitado por el armado de nivel |
| interpolación | `y[n−1] / (y[n−1] − y[n])`: o se reusa el divisor de `mca_div_restore`, o se guardan `y[n−1]` e `y[n]` y divide el PS. La palabra `w3` del slot está **reservada** y le caben los dos valores |

Esta tabla es una estimación por analogía con `mt_slope_trig`; no está
sintetizado.

**En el MCA (`mca_pulse_feature`): no para el timestamp, sí para las
compuertas.** El MCA no emite timestamp: publica features para el histograma.
Donde un CFD sí le cambiaría algo es en el **inicio de las compuertas del modo
1**. Hoy `gate_short` se cuenta desde el disparo de nivel, que camina con la
amplitud, así que la compuerta corta cubre una parte distinta del pulso según
su tamaño, y el cociente de forma (PSD) se sesga con la amplitud. Contadas
desde el cruce del CFD, las compuertas arrancarían siempre en el mismo punto
del pulso. Requiere la línea de retardo de muestras de la Fase 3, porque el
cruce llega después del arribo.

## 6. Lo que el modelo no incluye

- **Pulsos de forma variable.** El CFD no tiene walk solo si todos los pulsos
  tienen la misma forma. Con tiempos de subida variables (detectores de
  germanio grandes, por ejemplo) aparece un walk residual. La variante que lo
  compensa es el **ARC** (amplitude and rise-time compensated): un CFD con D más
  corto que la subida.
- **Línea de base.** Se supuso conocida y en cero. Un error de base `δ` corre
  el cruce como `δ·(1−f)` dividido por la pendiente de `y` en el cruce.
- **Apilamiento.** Un pulso sobre la cola de otro corre el cruce. El caso no se
  simuló.
- **Jitter del reloj del ADC.** Es despreciable a estas pendientes
  ([`fuentes_de_jitter.md`](fuentes_de_jitter.md) §2).
- **Las formas reales del generador.** Se usó la doble exponencial del resto de
  la documentación, no las formas de Knoll de `rigol_dg4162.py`.

## 7. Cómo validarlo en placa

Con los dos canales del DG4162 sincronizados, ch0 a amplitud fija y ch1 con
barrido de amplitud (el pulser deslizante), y el event ring capturando los dos:

1. **Δt por LED:** `ts` es común a los dos canales, así que la Δt por LED se
   obtiene interpolando el cruce de umbral de cada canal sobre las muestras del
   slot. Tiene que reproducir el walk de la figura 2a.
2. **Δt por CFD:** con el mismo slot. Tiene que quedar plana con la amplitud y
   angosta como en la tabla de §3.

Es un experimento solo de software sobre datos que el ring ya produce.

## Bibliografía

| Ref | Para qué |
|---|---|
| **G. F. Knoll**, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010, cap. 17 | leading edge, CFD, ARC y cruce por cero analógicos |
| **A. Fallu-Labruyère, H. Tan, W. Hennig, W. K. Warburton**, *Time resolution studies using digital constant fraction discrimination*, Nucl. Instrum. Methods A **579** (2007) 247–251 | CFD digital con interpolación: 576 ps con LaBr₃ a 75 MS/s |
| [`fuentes_de_jitter.md`](fuentes_de_jitter.md) | el presupuesto de jitter: cuantización, ruido → tiempo |
| [`ventana_de_medicion.md`](ventana_de_medicion.md) §5 | el walk y los tres lugares donde entra en este MCA |

# Cancelación polo-cero: cuánto del corrimiento con la tasa cancelaría

## La pregunta

[`resultados_validacion_hw.md`](../resultados_validacion_hw.md) §19.3 atribuye
el corrimiento de centroide con la tasa a un pedestal de la línea de base. Los
números son:

- +1.17 % de centroide (ida) entre 1995 Hz y 72 kHz;
- la base en vuelo pasa de −60 a −101 cuentas en el mismo tramo.

Ese pedestal se atribuye a su vez a un **undershoot** de la cola de cada pulso.
De ahí sale que la cancelación polo-cero (PZ) lo eliminaría, y que esa es la
justificación por deriva del conformado trapezoidal de Jordanov-Knoll.

El undershoot, sin embargo, nunca se había medido: se infirió del corrimiento.
Este Monte Carlo lo mide y pone a prueba la cadena completa:

```
undershoot medido  →  predicción de la campaña  →  qué haría la PZ
```

**Cómo se reproduce.** [`software/monte-carlo/polo_cero.py`](../../software/monte-carlo/polo_cero.py)
tarda unos 15 s. Escribe las figuras, los epígrafes y `resumen.json` en
[`figuras/polo_cero/`](figuras/polo_cero/). Corre sobre datos ya medidos, no
necesita placa.

---

## 1. El undershoot existe, y es chico

![Undershoot medido](figuras/polo_cero/01_undershoot_medido.png)

*Figura 1. (a) Un período de una captura cruda del scope. (b) El tramo
posterior al pulso, con el ajuste del modelo polo-cero.*

Se ajustó el modelo `y = c + p − η·LP_τ{p}` a las muestras **fuera** de los
pulsos de tres capturas crudas del 2026-05-27 (tren de 100 kHz, pulsos de unas
8000 cuentas). El modelo es un acople de continua parcial: la ganancia en
continua es `1 − η`, y una fracción η del área de cada pulso vuelve como cola
negativa con constante τ.

| captura | η | τ |
|---|---|---|
| `191742_in1` | 0.0391 | 5.05 µs |
| `191742_in2` | 0.0378 | 4.86 µs |
| `215917_in1` | 0.0425 | 5.38 µs |

- Las tres coinciden, y el rms del ajuste (6.5 cuentas) queda cerca del ruido
  blanco (4.5). **Un solo polo describe bien el undershoot.**
- Promedio: **η = 0.040, τ = 5.1 µs**. Es decir, el 4 % del área de cada pulso
  vuelve como cola negativa de unos 5 µs.

## 2. Ese undershoot explica menos de un tercio del corrimiento

![Campaña contra modelo](figuras/polo_cero/02_campana_vs_modelo.png)

*Figura 2. La campaña de deriva contra la cadena simulada: (a) caída de la base
en vuelo, (b) corrimiento de centroide.*

**Qué se simuló.** La cadena con el mismo estímulo que la campaña de deriva del
2026-09-08: rectángulos de 2 µs del DG4162 en modo PULSE, tren periódico. También
la misma configuración (`DEFAULT_CFG`: thr 100, hyst 40, `bl_k` 12, holdoff 64,
estimador de pico) y el seguidor de base del RTL.

**El modelo del seguidor.** Para poder barrer parámetros se usa una réplica
vectorizada del seguidor. Se validó contra `pileup.segmentar_base`, el modelo
fiel al RTL muestra a muestra, con ruido: coinciden dentro de 0.02 cuentas en
base y 0.1 cuentas en amplitud, a 12 y a 72 kHz.

Resultados a 72 kHz:

| | medido | con el undershoot medido | fracción explicada |
|---|---|---|---|
| caída de la base | −40.8 cuentas | −19.0 cuentas | **47 %** |
| corrimiento de centroide | +1.17 % (ida), +1.59 % (vuelta) | +0.34 % | **29 %** (ida), 21 % (vuelta) |

**Ni el mejor modelo lineal reproduce la campaña.** Con η y τ libres, ajustados
a la base y al centroide a la vez:
- hace falta **η = 0.12, el triple de lo medido**;
- y aun así no reproduce la **forma**: χ²/gl = 6.2.

La razón es general y no depende de η ni de τ. Con un ciclo de trabajo chico,
cualquier mecanismo lineal mueve la base en proporción a la tasa. La medición
es cóncava: a 12 kHz la base y el centroide ya se movieron la mitad de lo que
se mueven a 72 kHz, cuando un mecanismo lineal da una sexta parte.

**El corrimiento tiene, entonces, dos partes:**

1. **Una lineal**, el undershoot de 5 µs. Es alrededor de 0.34 % a 72 kHz. Es la
   que una PZ cancela.
2. **Una no lineal** con la tasa, de 0.8 a 1.2 %, que además tiene la
   histéresis entre la ida y la vuelta de §19.4. No responde a una PZ.

Punto a punto, el centroide sigue a la base en las dos partes
(`Δcentroide ≈ −Δbase`). Lo que sea que mueve la parte no lineal hace bajar el
nivel **entre** pulsos sin bajar el nivel **sobre** el pulso.

Esto es justo lo que haría un generador cuyo nivel bajo depende de la
configuración (frecuencia, historia de consignas) mientras el alto queda fijo.
Si es así, el instrumento no se equivoca: el estímulo realmente cambió de
amplitud. Es coherente con §19.4, que ya apuntaba "aguas arriba del MCA", pero
**es una hipótesis**: el Monte Carlo solo dice que ese mecanismo no es lineal.

### El salto entre 72 y 132 kHz no es de tasa

En la figura 2(a), la base cae de −41 a −99 cuentas entre 72 y 132 kHz y queda
plana hasta 794 kHz. El centroide sube de 1937.9 a 1989.3 canales y también
queda plano.

**La causa es el estímulo.** `sweep_rate` fija el ancho en
`min(2 µs, 0.2·período)`, porque el DG4162 exige que el ancho sea menor que
medio período ([`testbench_mca.py`](../../software/campanas/testbench_mca.py),
en `_punto`). Hasta unos 100 kHz el ancho es fijo y el ciclo de trabajo crece
con la tasa. Por encima, el ancho se achica con el período y el ciclo de
trabajo queda **fijo en 20 %**.

| tasa | ancho | ciclo de trabajo | Δ base medida | Δ base, undershoot medido | Δ base, mejor lineal |
|---|---|---|---|---|---|
| 72 kHz | 2000 ns | 14.5 % | −40.8 | −19.0 | −48.4 |
| 132 kHz | 1520 ns | 20.0 % | −99.2 | −27.7 | −75.2 |
| 240 kHz | 832 ns | 20.0 % | −100.8 | −28.2 | −79.8 |
| 437 kHz | 456 ns | 19.9 % | −102.8 | −27.9 | −80.4 |
| 794 kHz | 248 ns | 19.7 % | −103.2 | −25.9 | −75.1 |

De ahí salen tres lecturas:

1. **La meseta confirma que el efecto depende del ciclo de trabajo, no de la
   tasa.** Con el ciclo de trabajo fijo, multiplicar la tasa por 6 no mueve la
   base más de 4 cuentas.
2. **El salto es demasiado grande para ser el undershoot.** El ciclo de trabajo
   sube 1.38 veces. El undershoot medido predice 8.7 cuentas más de caída y el
   mejor modelo lineal 27; se midieron 58.
3. **El pulso mismo cambió de altura.** En ese paso el centroide sube 103
   cuentas, y la base explica solo 58 de ellas: el pulso quedó unas 49 cuentas
   (1.3 %) más alto al cambiar la consigna de ancho del generador. El modelo,
   con un rectángulo ideal, no da ningún cambio de altura.

Es la misma firma que la parte no lineal de abajo de 72 kHz: los niveles que
entrega el generador dependen de su configuración. Por eso los puntos de más de
72 kHz no se pueden juntar con los de menos (ya lo advertía §13.1 de los
resultados de placa).

**Para separar las dos causas**, a tasa fija:
- variar solo el ancho, por ejemplo 1, 1.5 y 2 µs a 50 kHz;
- y, al revés, variar la tasa con el ancho fijo y más corto (0.5 µs en todo el
  barrido), o usar el tren Poisson del ARB (`sweep_rate_poisson`), que no
  cambia el ancho.

## 3. Qué hace cada corrección sobre la parte lineal

![Correcciones](figuras/polo_cero/03_correcciones.png)

*Figura 3. (a) Corrimiento de centroide contra la tasa, con cada corrección.
(b) Sensibilidad de la PZ al error de sus parámetros.*

Sobre el undershoot medido, a 72 kHz:

| corrección | Δ centroide | costo |
|---|---|---|
| ninguna (holdoff 64) | +0.336 % | — |
| **PZ exacta** | **0.000 %** | RTL: un acumulador y dos coeficientes, más calibrar η y τ |
| PZ con τ +20 % | +0.024 % | |
| PZ con η +20 % | −0.079 % (sobrecorrige) | |
| **holdoff de 1024 muestras** (8.2 µs), sin PZ | **+0.041 %** | ninguno en RTL: es `cfg_bl_holdoff`. El seguidor actualiza el 26 % del tiempo a 72 kHz |

- **La PZ cancela exactamente la parte lineal**, porque es la inversa del
  modelo: `G(z) = (1 − a z⁻¹) / ((1 − η(1−a)) − a z⁻¹)`, con `a = e^{−Ts/τ}`.
  Es estable mientras η < 1.
- **Su sensibilidad la domina η.** Un 10 % de error en η deja el 12 % de la
  parte lineal, y sobreestimarlo hace que el centroide **baje** con la tasa. El
  error en τ casi no importa: con ±30 % el residuo no pasa de 0.04 %.
- **El holdoff largo logra casi lo mismo sin tocar hardware**, mientras el
  período alcance para pulso + holdoff + algunas muestras de actualización.
  A 72 kHz alcanza (1736 muestras por período contra 1275 congeladas). Por
  encima de unos 98 kHz, el seguidor ya no actualizaría nunca.

## 4. Conclusiones

1. **El undershoot existe y es lineal**: η = 0.040, τ = 5.1 µs, medido en tres
   capturas.
2. **Explica el 29 % del corrimiento de centroide medido** (0.34 de 1.17 %) y
   el 47 % de la caída de base. La afirmación de §19.3, "la PZ existe
   exactamente para eliminarlo", vale solo para esa fracción.
3. **El resto (0.8 a 1.2 %) no es lineal con la tasa, así que una PZ no lo
   toca.** El sospechoso es el generador, como ya proponía §19.4.
4. **La justificación por deriva del conformado trapezoidal queda en un tercio
   del efecto.** Antes de gastar una síntesis en PZ conviene el experimento de
   abajo.

## 5. El experimento que lo decide, sin tocar el RTL

Repetir `sweep_rate` dos veces, con `bl_holdoff = 64` y con `bl_holdoff = 1024`,
dentro del tramo de 2 a 72 kHz.

- **Si el modelo vale**, el corrimiento a 72 kHz baja **unos 0.3 puntos** (la
  parte lineal, figura 3) y el resto queda igual.
- **Si no baja**, el undershoot no es lo que mueve el centroide en esa campaña.
- **Si baja todo**, la parte "no lineal" también vive en la cola y el modelo de
  un polo es incompleto.

Para la parte no lineal, la medición directa es una captura cruda (scope o
event ring con ventana larga) a cada tasa, que mida el nivel alto y el nivel
bajo del generador por separado. Si el nivel bajo cae con la tasa y el alto no,
es el estímulo y no el instrumento. El instrumento que lo dirime de raíz es el
pulser de referencia digital de §17.3.

## Lo que el modelo no incluye

- **El estimador integral (modo 1).** La campaña usó el de pico. Con la
  integral, el error de base se multiplica por el largo de la compuerta, y el
  undershoot también recorta la carga del propio pulso.
- **Un undershoot de varios polos.** El ajuste con uno solo deja un rms cerca del
  ruido, así que no hay evidencia de un segundo polo. Un polo muy largo, de
  amplitud chica, no se distinguiría en capturas de 131 µs.
- **Las capturas del undershoot y la campaña son de días y estímulos distintos**
  (ARB a 1 V contra PULSE a 0.5 V). El modelo supone que el undershoot es una
  propiedad lineal de la cadena analógica, y por eso se escala.

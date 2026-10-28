# Procesamiento digital del disparo por pendiente

Este documento explica **cómo** se obtiene la señal sobre la que dispara
[`mt_slope_trig`](../../modulos/mt/rtl/mt_slope_trig.sv): primero como
superposición de copias del mismo pulso, en la línea de los esquemas de Knoll
(caps. 16–17); después como lo calcula el hardware, y por último qué gana
frente al disparo de nivel sobre pulsos de detector.

La referencia de uso (registros, API, costo, testbenches) está en
[`trigger_pendiente.md`](trigger_pendiente.md).

Las figuras las genera
[`figuras/pendiente/figuras_pendiente.py`](figuras/pendiente/figuras_pendiente.py)
y ninguna se dibuja a mano. Todas salen del modelo de referencia
[`mt_slope_model.py`](../../modulos/mt/modelos/python_model/mt_slope_model.py),
que hace la misma recursión, el mismo arranque y el mismo Schmitt que el RTL.
El script verifica, antes de dibujar, que la recursión coincide con la
convolución directa. Los epígrafes completos están en
[`figuras/pendiente/epigrafes.txt`](figuras/pendiente/epigrafes.txt).

```
python3 docs/mt/figuras/pendiente/figuras_pendiente.py      # ~2 s
```

---

## 1. El filtro

El disparo de nivel compara cada muestra `x[n]` contra un umbral. El de
pendiente compara

```
s[n] = Σ_{i=0}^{L-1} x[n-i]  −  Σ_{i=0}^{L-1} x[n-L-G-i]
```

es decir, la suma de las últimas `L` muestras menos la suma de `L` muestras
que están `G` más atrás. Escrito como convolución, `s = h * x` con la
respuesta impulsiva de la figura 1(a): `L` coeficientes +1, `G` ceros y `L`
coeficientes −1.

![Respuesta impulsiva y en frecuencia](figuras/pendiente/01_respuesta_impulsiva.png)

*Figura 1. (a) Respuesta impulsiva con L=4, G=3. (b) Respuesta en frecuencia
para cuatro configuraciones, normalizada por L.*

Dos propiedades se leen directamente de la figura:

- **Los coeficientes suman cero**, así que una continua da `s = 0`. En
  frecuencia es el cero en `f = 0` de la figura 1(b). El filtro es un
  **pasabanda**, no un pasabajos: rechaza la línea de base y sus derivas lentas,
  y deja pasar la banda donde vive el flanco del pulso.
- **`L` promedia.** La diferencia de 4 muestras (`L=1, G=3`, curva más clara)
  deja pasar casi todo el ruido de alta frecuencia. Al subir `L` el lóbulo
  principal se angosta y baja de frecuencia, y el ruido a la salida crece solo
  como `√(2L)` mientras la señal crece como `L` (§5).

## 2. El trapecio como superposición de copias del mismo pulso

Knoll construye las formas conformadas sumando copias retardadas y escaladas
del mismo pulso. El trapezoidal rápido admite exactamente esa lectura, y para
un escalón de entrada (la salida de un preamplificador de carga, o el flanco de
cualquier pulso rápido) la cuenta se hace a ojo:

![Superposición](figuras/pendiente/02_superposicion_escalon.png)

*Figura 2. El trapecio de un escalón, L=4, G=3.*

1. **(a)** Al escalón `x[n]` se le resta una copia retardada `L+G` muestras.
2. **(b)** Lo que queda, `d[n] = x[n] − x[n−(L+G)]`, es un rectángulo de
   `L+G` muestras. La continua ya desapareció: lejos del escalón, la señal y su
   copia se cancelan.
3. **(c)** Se toman `L` copias de ese rectángulo, cada una retardada una
   muestra más que la anterior.
4. **(d)** Apiladas forman el **trapecio**:
   - sube durante `L` muestras, porque entra una copia por muestra;
   - se queda en `L·A` durante `G+1` muestras, mientras están todas;
   - baja durante `L` muestras, a medida que van saliendo.

   Los puntos negros son `s[n]` calculado por el modelo del RTL, y coinciden
   con la pila.

De ahí salen las tres respuestas que hay que tener en la cabeza:

| Entrada | `s` |
|---|---|
| continua | 0 |
| escalón de alto `A`, más rápido que `L+G` | trapecio de alto `L·A`, subida `L`, techo `G+1` |
| rampa de `m` cuentas por muestra | `L·(L+G)·m` |

La última es la que da el nombre de "pendiente": sobre una rampa, `s` es la
pendiente escalada por `L·(L+G)`. Sobre un flanco rápido, `s` es la amplitud
escalada por `L`.

## 3. Cómo lo calcula el hardware

Sumar `L` copias por muestra costaría `2L` sumas. El RTL usa la forma
recursiva, que reordena la misma cuenta:

```
s[n] = s[n-1] + (x[n] − x[n−L]) − (x[n−L−G] − x[n−2L−G])
                \_______________________________________/
                               d[n], el incremento
```

![Recursión](figuras/pendiente/03_recursion_rtl.png)

*Figura 3. La misma síntesis con cuatro copias y un acumulador.*

- **(a)** Entran al sumador cuatro copias del escalón con signo, `+ − − +`:
  la entrada y las tres tomas de las líneas de retardo.
- **(b)** Su suma es el incremento `d[n]`: `+1` durante `L` muestras, cero
  durante `G` y `−1` durante `L`. Es la derivada del trapecio.
- **(c)** El acumulador integra `d[n]` y devuelve el trapecio de la figura 2.

![Diagrama de bloques](figuras/pendiente/04_bloques_rtl.png)

*Figura 4. El datapath de `mt_slope_trig`.*

| Bloque | En el RTL |
|---|---|
| `z^{-L}`, `z^{-G}`, `z^{-L}` | tres líneas de retardo en cascada (`sr_l1`, `sr_g`, `sr_l2`), una toma dinámica cada una, inferidas en SRL. Con `G = 0` la del medio se puentea |
| Σ de las tomas | etapa `p2_d`: `(x − x_a) − (x_b − x_c)` |
| Σ con `z⁻¹` | el acumulador `s` |
| `s ≥ thr`, `s ≤ −thr` | Schmitt simétrico. Cada salida re-arma al volver más allá de `thr−hyst` y da un pulso de un ciclo: `p` y `n` |

Tres detalles de implementación que no están en el dibujo:

- **Exactitud.** Todo es entero y la suma de `d` es exactamente cero, así que
  el acumulador vuelve a 0 después de cada pulso. No hay deriva numérica.
- **Historia en cero.** Las líneas de retardo no tienen reset. Un contador de
  llenado hace que una toma más vieja que el último re-arranque lea 0, así que
  `s` es el filtro aplicado sobre una señal que valía 0 antes del arranque.
- **Arranque silencioso.** Ese arranque desde cero es un escalón falso (se ve
  en `t ≈ 0` de la figura 5b). Por eso, mientras no entraron `2L+G` muestras,
  el Schmitt queda en "disparado" y no sale ningún pulso.

## 4. Sobre pulsos de detector

Las figuras 5 y 6 usan pulsos de doble exponencial muestreados a 125 MS/s:
subida de 20 ns, cola de 1.14 µs y ruido σ = 3 cuentas (el medido es 2.8).
Los parámetros son `L = 8`, `G = 4`, con el umbral de pendiente puesto para que
un pulso de 100 cuentas llegue justo. El disparo de nivel usa umbral 100 e
histéresis 40.

### Línea de base

![Línea de base](figuras/pendiente/05_linea_base.png)

*Figura 5. El mismo tren sobre dos líneas de base separadas 50 cuentas.*

El disparo de nivel (a) compara contra un umbral **absoluto**: al bajar la base
50 cuentas, el pulso de 130 se pierde, y el umbral efectivo sobre la amplitud
del pulso se corrió 50 cuentas. En la pendiente (b) las dos curvas son la misma
y los disparos caen en las mismas muestras: el umbral efectivo queda en 100
cuentas sobre la base, esté donde esté. Es la propiedad que importa para este
MCA, donde la deriva es el límite que manda
([`limites_resolucion_y_deriva.md`](../mca/limites_resolucion_y_deriva.md)).

### Apilamiento

![Apilamiento](figuras/pendiente/06_apilamiento.png)

*Figura 6. Tres pulsos apilados, y la fracción de pares resueltos contra la
separación.*

El disparo de nivel (a) dispara una sola vez: el segundo y el tercer pulso
llegan con la señal todavía arriba del re-armado. La pendiente (b) responde a
la **subida** de cada uno y dispara tres veces.

El panel (c) lo cuantifica con pares de pulsos iguales:
- la pendiente resuelve el par a partir de unas `2L+G` muestras (≈ 160 ns),
  lo que tarda `s` en volver a bajar del re-armado;
- el nivel recién lo resuelve cuando la cola del primer pulso bajó del
  re-armado, `τ·ln(A/(thr−hyst)) ≈ 3.2 µs`.

Esta es la base de la inspección de apilamiento de los procesadores digitales,
y la que no tiene el `cnt_pileup` actual
([`parametros_de_merito.md`](../mca/parametros_de_merito.md)).

En la cola, `s` es **negativo** y proporcional a la pendiente de la caída,
`L·(L+G)·A/τ`. Si se usa el canal `n`, su umbral tiene que estar por encima de
lo que da la cola del pulso más grande que se espera.

## 5. Elección de L y G

![Elección de L](figuras/pendiente/07_eleccion_L.png)

*Figura 7. Ruido, relación señal/ruido y latencia contra L, con G = 4.*

- **(a)** El ruido de `s` es `σ·√(2L)`, porque `s` suma `2L` muestras de ruido
  independientes.
- **(b)** Para pulsos con cola larga, el pulso es un escalón en la escala de
  `L`: la señal crece como `L` y la relación señal/ruido como `√L`, en todo el
  rango de `L ≤ 16`. Una subida más lenta (100 ns) pierde pico cuando `L+G` es
  comparable con la subida.
- **(c)** El precio es la latencia: `s` tarda unas `L` muestras en llegar a su
  pico, de 16 ns con `L = 1` a 80–100 ns con `L = 16`, más 40 ns de pipeline.

Regla práctica:
- **`L`**: el más grande que tolere la latencia del uso. Para coincidencias
  conviene corto; para detectar pulsos chicos sobre ruido, largo.
- **`G`**: del orden del tiempo de subida del pulso, para que la ventana vieja
  no vea todavía el flanco. Con `G` mayor, `s` se vuelve más sensible a rampas
  lentas (`L·(L+G)·m`).
- **Umbral**: con `slope_pico(L, G, escalon=A_min) // 2` desde la API, varios
  `σ·√(2L)` arriba del ruido.

## Bibliografía

| Ref | Para qué |
|---|---|
| **G. F. Knoll**, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010, caps. 16–17 | formas conformadas como superposición de pulsos; discriminadores |
| **V. T. Jordanov, G. F. Knoll**, *Digital synthesis of pulse shapes in real time for high resolution radiation spectroscopy*, Nucl. Instrum. Methods A **345** (1994) 337 | el trapezoidal recursivo de §3 |
| **V. T. Jordanov, G. F. Knoll, A. C. Huber, J. A. Pantazis**, *Digital techniques for real-time pulse shaping in radiation measurements*, Nucl. Instrum. Methods A **353** (1994) 261–264 | algoritmos recursivos en tiempo real |
| **W. K. Warburton, M. Momayezi, B. Hubbard-Nelson, W. Skulski**, *Digital pulse processing: new possibilities in nuclear spectroscopy*, Appl. Radiat. Isot. **53** (2000) 913–920 | filtro rápido para disparo y apilamiento, filtro lento para energía |

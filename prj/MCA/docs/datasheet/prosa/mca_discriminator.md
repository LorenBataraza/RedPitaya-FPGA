<!-- Prosa a mano del datasheet de `mca_discriminator`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_mca_discriminator.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Decide si un evento **entra o no entra** al histograma, mirando
**una** feature del bus de evento contra un intervalo. No mira muestras: mira
el evento ya cerrado, con todas sus características calculadas, y su veredicto
alcanza al evento completo.

Antes esto eran dos líneas sueltas dentro de la FSM del extractor (`amp_ok`):
una condición, feature **fija** —la amplitud— e intervalo siempre interno. Acá
es un bloque con selector, y el intervalo puede ser **interno** `[min, max]` o
su complemento.

**Va después de los divisores, y ahí está todo el punto.** Ponerlo antes
costaría nada y serviría para la mitad: las features de **forma** no existen
hasta que el divisor termina, y son justamente las que importan. Medido por
Monte-Carlo sobre el espectro de una línea a 100 kcps
(`software/monte-carlo/`):

| Corte | Qué rechaza | Efecto sobre el continuo bajo el fotopico |
|---|---|---|
| por **ancho** (`Pico/Q_total`) | **99.1 %** de los apilados, sin perder un solo evento limpio | 32.4 % → **0.8 %** |
| por `Q_cola/Q_total`, modo histéresis | 29.6 % | — |
| por `Q_cola/Q_total`, modo compuerta | **exactamente nada** | — |

El precio de estar después del divisor es que todo evento paga su latencia
antes de poder ser rechazado: `DIV_W` ciclos = **128 ns** contra una ventana de
3.07 µs, el **4 %**.

> **El corte hay que calibrarlo contra la amplitud, y con un pulser
> deslizante.** `Pico/Q_total` **no** es constante: en modo histéresis la
> ventana cierra cuando la cola cruza el umbral, o sea que su largo crece con
> el logaritmo de la amplitud y el cociente deriva **~21 %** de punta a punta
> del rango. Un umbral fijo cortaría los pulsos limpios chicos y dejaría pasar
> los apilados grandes. Y la calibración **no** se hace con el espectro fuente:
> con una línea monoenergética el lugar geométrico queda definido en un puñado
> de canales, y el corte terminaría rechazando por caer fuera del rango
> calibrado en vez de por tener la forma mal — un corte en amplitud disfrazado
> de corte en forma, que da un resultado espectacular y falso.

**Intervalo vacío.** Con `min > max` el conjunto interno es vacío por
definición, así que `interno` rechaza **todo** y `externo` acepta todo. No es
un caso de error: es la respuesta correcta a lo que se pidió, y está fijado por
un test para que nadie lo «arregle» después.

Un detalle de implementación que ya mordió una vez: la selección de feature es
un *part-select* indexado y **no** una función. Dentro de un `assign` continuo
una función no queda sensible a lo que lee del alcance exterior, y el mux se
quedaría clavado en el valor de reset. Pasó en `mca_top`.

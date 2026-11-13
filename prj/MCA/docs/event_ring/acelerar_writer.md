# Acelerar el writer

El writer era el cuello de botella del ring. Este documento registra el cambio que se
aplicó, la opción A, y lo que costaría ir más lejos, la opción B, que sigue siendo un
prototipo.

- **A está aplicada** en `event_slot_writer.sv`: duplica el techo y no cuesta recursos.
  Está verificada en simulación y en el bitstream del ring del 2026-11-08; **no se
  probó en la placa**.
- **B no está aplicada.** Subiría el techo otro 65 % con 1024 muestras y bajaría a la
  mitad el tiempo muerto de la captura, pero toca tres módulos y sus testbenches.
- **Ninguna sube lo sostenido por red** con 1024 muestras: ahí limita el Ethernet.

## Dónde se iba el tiempo

Había dos causas, en dos bloques:

1. **El writer armaba cada palabra en 9 ciclos.** `W_DATA` era una cadena `if / else if`:
   en cada ciclo pedía o recibía, no las dos cosas. Alternaba dos pedidos, dos
   recepciones y un ciclo para emitir, aunque el stage puede dar una muestra por ciclo.
   **Esto es lo que resolvió A.**
2. **La captura serializa.** Saca los dos canales de a una muestra de 16 b por ciclo,
   así que una ventana de W muestras tarda 2·W ciclos. Por eso el stage es de 16 b y por
   eso el rezago crece, que es lo que obliga a `PRE_AW = 11`. **Esto sigue igual.**

## A: lecturas continuas en el writer (aplicada)

`W_DATA` pide una muestra por ciclo y arma una palabra cada 4. El mecanismo y la regla
de la contrapresión están en
[`logica_de_captura_y_axi.md`](logica_de_captura_y_axi.md) §4.2. No cambian el formato
del slot, los registros, el software, la captura ni el stage.

**Un error del prototipo que se corrigió al aplicarlo.** Como `W_DATA` ahora sale un
ciclo después de la última palabra, una ventana que entra justa en el slot, como 1014
muestras en 4 KB, levantaba `err_slot_ovf` sin motivo. Los datos salían bien, pero el
error quedaba marcado. La señal `hay_mas` distingue ahora "falta algo de este evento" de
"ya salió todo".

**Lo que se agregó a la verificación:**

- `tb_event_slot_writer` comprueba el ritmo de 4 ciclos, la ventana justa, y 20 eventos
  no múltiplos de 4 con contrapresión fuerte.
- `tb_event_ring_ventana` comprueba 1014 muestras en 4 KB.
- Se corrigió el `fork` de la escena 3 de `tb_event_slot_writer`, que seguía moviendo
  `wr_rdy` en las escenas siguientes.
- Fallan como corresponde con cada una de estas variantes: el writer anterior, el
  prototipo, y cinco mutaciones del RTL nuevo (sin la regla de contrapresión, relleno
  sin esperar la salida, sin `hay_mas` en la guarda de error, saliendo con muestras en
  camino, y `acc` en el orden equivocado).

## B: 32 b en toda la cadena (no aplicada)

La captura dejaría de serializar y sacaría `{ch1, ch0}` por ciclo, el stage pasaría a
2048 palabras de 32 b (los mismos bits), y el writer armaría una palabra de 64 b cada 2
ciclos, con un registro extra para la contrapresión. El formato del slot no cambia, así
que el software tampoco. Parche, sobre el RTL actual:
[`prototipo_b.patch`](figuras/tiempos/prototipo_b/prototipo_b.patch).

B tiene un efecto más: el rezago queda fijo en `pre`, así que el pre-buffer vuelve a
`PRE_AW = 9`. A cambio, `pre` queda limitado a 511, y pasarse no se ve en la rampa: `pre`
se trunca, la ventana sale continua y queda corrida.

## Resultados

Simulación del RTL con AXI ideal y créditos de sobra, y síntesis fuera de contexto con
Vivado 2021.2:

| | antes de A | hoy (A) | B |
|---|---|---|---|
| LUT | 1093 | 1091 | 1180 |
| FF | 1030 | 1012 | 1036 |
| bloques de BRAM | 5.5 | 5.5 | 4 |
| holgura sin caminos de geometría, después de síntesis | +0.336 ns | +0.393 ns | +0.357 ns |

Ciclos por evento, captura / writer, y el techo que dan:

| ventana | slot | antes de A | hoy (A) | B |
|---|---|---|---|---|
| 32 | 256 B | 66 / 165: 758 k/s | 66 / 88: 1420 k/s | 34 / 56: 2232 k/s |
| 128 | 1 KB | 258 / 645: 194 k/s | 258 / 328: 381 k/s | 130 / 200: 625 k/s |
| 1014 | 4 KB | 2030 / 4573: 27 k/s | 2030 / 2041: 61 k/s | 1016 / 1027: 122 k/s |
| 1024 | 8 KB | 2050 / 5125: 24 k/s | 2050 / 2568: 49 k/s | 1026 / 1544: 81 k/s |

Eventos guardados con un tren de Poisson (k/s):

| ventana | tasa | antes de A | hoy (A) | B |
|---|---|---|---|---|
| 1024 | 10 kcps | 8.7 | 8.8 | 9.3 |
| 1024 | 30 kcps | 18.1 | 20.7 | 24.3 |
| 1024 | 100 kcps | 24.0 | 38.2 | 54.4 |
| 1024 | 1 Mcps | 24.4 | 48.3 | 80.1 |
| 128 | 100 kcps | 79.8 | 79.8 | 87.8 |
| 128 | 1 Mcps | 191 | 317 | 477 |
| 32 | 1 Mcps | 633 | 644 | 761 |

Hasta 30 kcps con 1024 muestras, A ayudó poco: lo que manda es el tiempo muerto de la
captura, que solo bajaría con B. Con A, `DROP_FULL` desapareció o quedó chico (como mucho
15 %, con 1024 muestras a 1 Mcps) y manda `DROP_BUSY`: la captura pasó a ser el límite,
salvo donde el relleno del slot todavía mantiene al writer por detrás.

## Lo que no arregla

Acelerar el writer no sube lo que se puede sostener aguas abajo. Con 1024 muestras son
4136 B útiles por evento, y copiar del ring cuesta el slot entero, con relleno:

| etapa | medido | límite con 1024 muestras |
|---|---|---|
| tarjeta SD | 12.4 MB/s | ~3 k/s |
| Ethernet, TCP | 90–110 MB/s | ~24 k/s |
| PS copiando slots de 8 KB | ~220 MB/s | ~27 k/s |
| PS copiando slots de 4 KB (1014 muestras) | ~220 MB/s | ~54 k/s |
| **writer de hoy** | | **49 k/s** (61 k/s con 1014 muestras) |

Con ventanas largas, lo sostenido queda limitado por la red y el PS. Falta además lo que
el PS haga con cada evento en Python, que no está medido con ventanas largas.

Lo que el writer más rápido sí compra:

- **Menos pérdida a tasa moderada:** a 30 kcps y 1024 muestras guarda 68 % de los
  eventos, contra 59 % antes. B llegaría a 80 %.
- **Ráfagas más densas.** El ring de 32 MB guarda 4096 eventos de 1024 muestras, y se
  llena a la tasa del writer. Sirve para tomar una ráfaga corta a alta tasa y drenarla
  después.
- **Ventanas cortas a tasa alta**, si el PS reduce los datos antes de sacarlos.

## Riesgos y lo que falta medir

- **AXI y DDR en la placa.** La simulación usa AXI ideal. Con 1024 muestras y slots de
  8 KB, el writer de hoy escribe hasta 400 MB/s, contra 200 MB/s antes, y B llegaría a
  660 MB/s, compitiendo con el PS por la misma DDR. El puerto HP llega a 1 GB/s; el resto
  no se midió.
- **Timing.** Es después de síntesis. Falta ruteo, y el bitstream ya está muy justo.
- **B.** Pasa los dos testbenches de integración, salvo el chequeo de que el writer no da
  abasto, que dejaría de cumplirse. Los de unidad de captura, stage y writer asumen 16 b y
  no se corrieron: habría que adaptarlos. Su writer está escrito para `N_CH = 2`.

## Recomendación

- **B, solo si hace falta bajar el tiempo muerto** con ventanas largas a más de unos
  10 kcps, o pasar de ~50 k/s con 1024 muestras.
- **Para sacar ventanas largas por red, conviene usar 1014 muestras con slots de 4 KB:**
  casi el mismo dato, con la mitad de DDR y de copia.

## Cómo se rehace

La receta está en la cabecera de
[`figuras/tiempos/tb_ring_medir.sv`](figuras/tiempos/tb_ring_medir.sv). Para B, aplicar
el parche sobre una copia de `modulos/event_ring/rtl/` y correr el mismo TB con
`-gPRE_AW=9 -gDATA_AW=11 -gPALABRA=1`. Los resultados están en `figuras/tiempos/`: los
del RTL actual en la carpeta, y los otros en `antes_de_A/`, `prototipo_b/` y
`stage_8192/`.

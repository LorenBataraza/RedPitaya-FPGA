# Figuras: la arquitectura de software de la API

Dieciséis figuras sobre **cómo está construido el software de la API**, repartidas en
cuatro documentos:

- [`../arquitectura_software.md`](../arquitectura_software.md): la vista del software
  como software (niveles, concurrencia, filesystem, tipos);
- [`../libmca.md`](../libmca.md): la biblioteca en C y su binding;
- [`../adquisicion_de_eventos.md`](../adquisicion_de_eventos.md): las fuentes, los
  hilos, el pool y la sesión;
- [`../diseno_de_clases.md`](../diseno_de_clases.md): la red, y el índice de todos los
  diagramas de clases (§3).

Son TikZ, con el estilo común de los panoramas
([`../../figuras/estilo_tikz.tex`](../../figuras/estilo_tikz.tex)), más
[`clases_estilo.tex`](clases_estilo.tex) para la notación de los diagramas de clases:
PDF para la tesis y SVG para los markdown, con fondo blanco siempre.

```bash
cd prj/MCA/docs/API/figuras
for f in niveles hilos secuencia_bitstream escritura_corrida esquema_evento \
         clases_bloque clases_libmca clases_lotes clases_binding clases_red \
         clases_fuentes maquinas_estados corrida_mca hilos_captura pool_batches \
         clases_sesion; do
  pdflatex $f.tex && pdftocairo -svg $f.pdf $f.svg
done
rm -f *.aux *.log
```

Son **esquemas de la estructura del código**, no datos medidos: salen de leer
[`software/libmca/`](../../../software/libmca/), [`software/API/`](../../../software/API/)
y [`software/app/`](../../../software/app/). El único número que aparece es los
12.4 MB/s de la microSD, medido en
[`../../movimiento_de_datos.md`](../../movimiento_de_datos.md). Si cambia el código,
hay que volver a pasar las figuras por las coordenadas a mano: no hay extracción
automática.

## Las figuras

**La arquitectura** ([`arquitectura_software.md`](../arquitectura_software.md)):

| Figura | Qué muestra | Dónde |
|---|---|---|
| [`niveles.svg`](niveles.svg) ([`.tex`](niveles.tex)) | Los **seis niveles** de software sobre los registros de la PL, en la máquina donde corre cada uno (PL, PS, PC), y las fronteras físicas: el bus AXI (GP0 a los registros, HP0 del `event_ring` a la DDR) y la red. Los niveles 1 a 4 de los seis bloques son una columna en C (`libmca/`), con el binding de Python al lado y `ctypes` entre los dos | §1 |
| [`hilos.svg`](hilos.svg) ([`.tex`](hilos.tex)) | Los **tres sistemas de concurrencia**, uno por banda: el pipeline (colas), el servidor (un lock) y la GUI (señales de Qt) | §2 |
| [`secuencia_bitstream.svg`](secuencia_bitstream.svg) ([`.tex`](secuencia_bitstream.tex)) | Lo que la API **lee** del filesystem, en el orden en que lo lee: la recarga de la PL, con la ruta que toca cada paso | §3 |
| [`escritura_corrida.svg`](escritura_corrida.svg) ([`.tex`](escritura_corrida.tex)) | Lo que la API **escribe** cuando mide: el `.tmp` + `os.replace` de los dos escritores y el camino físico de un `write()` | §3 |
| [`esquema_evento.svg`](esquema_evento.svg) ([`.tex`](esquema_evento.tex)) | El esquema del evento **armado en runtime**: quién declara cada columna y el `EventBatch` que resulta | §4 |

**libmca** ([`libmca.md`](../libmca.md)):

| Figura | Qué muestra | Dónde |
|---|---|---|
| [`clases_bloque.svg`](clases_bloque.svg) ([`.tex`](clases_bloque.tex)) | **La forma de un bloque**, dibujada una sola vez: el handle genérico con `mca_bloque` como primer miembro, los códigos y las tablas comunes, el bus con el backend `devmem_bus`, el único que toca la PL, y `mca_mem`, la DDR del ring | §1 y §2 |
| [`clases_libmca.svg`](clases_libmca.svg) ([`.tex`](clases_libmca.tex)) | **Los seis handles** (`mca_h`, `integration_h`, `multitrigger_h`, `osciloscope_h`, `osciloscope_ring_h`, `gen_pulsos_h`) con lo que distingue a cada uno, y `gen_disparos`, el motor de los generadores | §3 |
| [`clases_lotes.svg`](clases_lotes.svg) ([`.tex`](clases_lotes.tex)) | **Los dos lazos por lote**: `osciloscope_leer_lote` y `osciloscope_ring_leer_lote`, los handles que reciben, sus structs de configuración, estado, columnas y resultado, `Lector` y `LectorRing`, y el `EventBatch` donde escriben | §4 |
| [`clases_binding.svg`](clases_binding.svg) ([`.tex`](clases_binding.tex)) | **El binding de Python**: las funciones con `@_api` y su despacho a libmca, a `ref_py` o a la red; `_libmca.py`; los handles de cada bloque y el shim `MultiTriggerScope` | §5 |

**La adquisición de eventos** ([`adquisicion_de_eventos.md`](../adquisicion_de_eventos.md)):

| Figura | Qué muestra | Dónde |
|---|---|---|
| [`clases_fuentes.svg`](clases_fuentes.svg) ([`.tex`](clases_fuentes.tex)) | La interfaz **`EventSource`**, por lote, quién llama cada parte, y sus dos implementaciones con el lazo de C de cada una | §1 |
| [`maquinas_estados.svg`](maquinas_estados.svg) ([`.tex`](maquinas_estados.tex)) | **Una corrida del osciloscopio**, en tres partes lado a lado: (a) el lazo del hilo lector, igual con las dos fuentes; lo que hace `read_batch` adentro (b) con el ring, por bloque de slots, y (c) con la BRAM, por evento, con el re-armado | §2 |
| [`corrida_mca.svg`](corrida_mca.svg) ([`.tex`](corrida_mca.tex)) | **Una corrida del MCA**, lineal: el hardware acumula entre el start y el stop | §2 |
| [`hilos_captura.svg`](hilos_captura.svg) ([`.tex`](hilos_captura.tex)) | **Los hilos de la captura en el tiempo**: principal, lector y escritor, con lo que corre en Python (con el GIL), en C y en el `write()` (sin él), y los batches por las colas | §3 |
| [`pool_batches.svg`](pool_batches.svg) ([`.tex`](pool_batches.tex)) | **El pool**: los `EventBatch` que circulan entre el lector, `full_q`, el escritor y `free_q`, y lo que pasa sin batch libre | §4 |
| [`clases_sesion.svg`](clases_sesion.svg) ([`.tex`](clases_sesion.tex)) | **`AcquisitionSession`** y lo que compone: `ReaderThread`, `ChunkWriter`, el pool de `EventBatch` y las dos colas; los `Annotator` y lo que queda en `run_dir/`. La fuente aparece sólo como la interfaz | §5 |

**La red** ([`diseno_de_clases.md`](../diseno_de_clases.md)):

| Figura | Qué muestra | Dónde |
|---|---|---|
| [`clases_red.svg`](clases_red.svg) ([`.tex`](clases_red.tex)) | `MCARemote`, el proxy de la op `call`, que hereda de `MCA` sin abrir libmca; `Channel` y la trama; `ServidorMCA` y la lista blanca | §4 |

---

## Lo que los diagramas de clases no dibujan

- **Los sustitutos de prueba** (`FakeMCA`, `FakeOsc`, `FakeMultiTrigger`,
  `FakeMtRegion`, `FakeSource`) y los backends de C por callbacks y por fichero. No son
  parte de la API que usa un programa; están en
  [`../diseno_de_clases.md`](../diseno_de_clases.md) §5.1. Por lo mismo, el camino por
  evento del lector, que sólo usa `FakeSource`, no aparece.
- **Lo que ya dibujó otra figura.** Lo común a todos los bloques va una sola vez, en
  `clases_bloque`. Los métodos de los handles de Python son las funciones de libmca:
  van una sola vez, en `clases_libmca`. La sesión ve la fuente sólo como la interfaz
  `EventSource`; las implementaciones van en `clases_fuentes`. Lo que hace cada lazo por
  evento va en `maquinas_estados`, no en `clases_lotes` ni en `hilos_captura`.

Dos convenciones de notación:

- **Herencia.** Si la base está en la figura, la herencia es el triángulo hueco. Si no
  está (`threading.Thread`), va entre paréntesis en el nombre. En C, «hereda» quiere
  decir que el struct base va como primer miembro.
- **Hilos.** Naranja quiere decir que la clase **es** un hilo (hereda de
  `threading.Thread`). Los subtítulos no nombran en qué hilo corre cada cosa: eso está
  en `hilos` y en `hilos_captura`.

## Las figuras van sin prosa adentro

Lo que llevan son **nombres de módulo, de clase, de función y de ruta**, o sea,
identificadores que el lector va a buscar en el código. Las razones, las mediciones y
las advertencias van una sola vez, en el documento. En las figuras de libmca, de la
adquisición, de los niveles y de los hilos, la leyenda dice sólo los colores y la
notación; el epígrafe está en `<figura>.txt`, al lado del `.tex`, y en cursiva debajo de
la imagen en el documento que la incluye. Es la misma regla que
[`docs/TOP/figuras/`](../../TOP/figuras/) y que [`docs/mca/figuras/`](../../mca/figuras/).

Por esa regla se rehicieron. Las versiones anteriores las generaba
`figuras_arquitectura_software.py`: cuatro SVG oscuros con párrafos dentro de las cajas,
y cada uno contaba dos o tres cosas a la vez. Las dos más cargadas quedaron partidas:
el filesystem ahora son dos figuras, una por lo que lee y otra por lo que escribe, y lo
mismo los tipos y la ejecución. Con libmca entera en C se partió también la capa de C
(la forma común, los bloques, los lazos) y se juntaron los handles de Python en una
sola figura del binding.

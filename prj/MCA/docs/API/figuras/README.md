# Figuras: la arquitectura de software de la API

Once figuras sobre **cómo está construido el software de la API**. Las seis
primeras las usa [`../arquitectura_software.md`](../arquitectura_software.md);
las cinco `clases_*` son los diagramas de clases, nivel por nivel, y las usa
[`../diseno_de_clases.md`](../diseno_de_clases.md). Son TikZ, con el
estilo común de los panoramas
([`../../figuras/estilo_tikz.tex`](../../figuras/estilo_tikz.tex)), más
[`clases_estilo.tex`](clases_estilo.tex) para la notación de los diagramas de
clases: PDF para la tesis y SVG para los markdown, con fondo blanco siempre.

```bash
cd prj/MCA/docs/API/figuras
for f in niveles hilos secuencia_bitstream escritura_corrida esquema_evento maquinas_estados \
         clases_libmca clases_mca clases_scope clases_fuentes clases_sesion; do
  pdflatex $f.tex && pdftocairo -svg $f.pdf $f.svg
done
rm -f *.aux *.log
```

Son **esquemas de la estructura del código**, no datos medidos: salen de leer
[`software/API/`](../../../software/API/) y [`software/app/`](../../../software/app/).
El único número que aparece es los 12.4 MB/s de la microSD, medido en
[`../../movimiento_de_datos.md`](../../movimiento_de_datos.md). Si cambia el
código, hay que volver a pasar las figuras por las coordenadas a mano: no hay
extracción automática.

| Figura | Qué muestra | Dónde está embebida |
|---|---|---|
| [`niveles.svg`](niveles.svg) ([`.tex`](niveles.tex)) | Los **seis niveles** de software sobre los registros de la PL, como jerarquía de dependencias, en la máquina donde corre cada uno (PL, PS, PC), y las dos fronteras físicas: el bus AXI y la red. Los niveles 1 a 4 del MCA son una columna en C (`libmca/`), con el binding de Python al lado y `ctypes` entre los dos. El camino remoto es `MCARemote`, un proxy en la PC: cada función de la API viaja entera por la op `call` y el servidor la corre sobre el binding | §1 |
| [`hilos.svg`](hilos.svg) ([`.tex`](hilos.tex)) | Los **tres sistemas de concurrencia**, uno por banda: el pipeline (colas), el servidor (un lock) y la GUI (señales de Qt) | §2 |
| [`secuencia_bitstream.svg`](secuencia_bitstream.svg) ([`.tex`](secuencia_bitstream.tex)) | Lo que la API **lee** del filesystem, en el orden en que lo lee: la recarga de la PL, con la ruta que toca cada paso | §3 Lo que lee |
| [`escritura_corrida.svg`](escritura_corrida.svg) ([`.tex`](escritura_corrida.tex)) | Lo que la API **escribe** cuando mide: el `.tmp` + `os.replace` de los dos escritores y el camino físico de un `write()` | §3 Lo que escribe |
| [`esquema_evento.svg`](esquema_evento.svg) ([`.tex`](esquema_evento.tex)) | El esquema del evento **armado en runtime**: quién declara cada columna y el `EventBatch` que resulta | §4 El esquema |
| [`maquinas_estados.svg`](maquinas_estados.svg) ([`.tex`](maquinas_estados.tex)) | Dos subfiguras: **(a)** el lazo de `EventSource`, con el tiempo muerto marcado, y **(b)** el flujo lineal del MCA | §4 Las dos máquinas |
| [`clases_libmca.svg`](clases_libmca.svg) ([`.tex`](clases_libmca.tex)) | La **capa de C** del MCA: `mca_h` con todas sus funciones agrupadas, los tipos que cruzan la interfaz (`mca_config_t`, `mca_counters_t`, `MCA_FIELDS`), y el bus `mca_bus` con el backend `devmem_bus`, el único que toca la PL | [`diseno_de_clases.md`](../diseno_de_clases.md) §3 |
| [`clases_mca.svg`](clases_mca.svg) ([`.tex`](clases_mca.tex)) | El **binding de Python** y la red: `MCA`, que guarda el `mca_h*` (sus métodos no se repiten: son los de C); las funciones `mca_*` con el despacho de `@_api` a libmca, a `ref_py` o a la red; `MCARemote`, el proxy de la op `call`, que hereda de `MCA` sin abrir libmca, y `ServidorMCA` | [`diseno_de_clases.md`](../diseno_de_clases.md) §4 y §8 |
| [`clases_scope.svg`](clases_scope.svg) ([`.tex`](clases_scope.tex)) | El resto de los handles: `Osciloscope`, el shim `MultiTriggerScope`, `MultiTrigger`, `MtRegion` e `Integration` | [`diseno_de_clases.md`](../diseno_de_clases.md) §5 |
| [`clases_fuentes.svg`](clases_fuentes.svg) ([`.tex`](clases_fuentes.tex)) | La interfaz **`EventSource`**, quién llama cada método, y sus dos implementaciones sobre la placa con de dónde lee cada una | [`diseno_de_clases.md`](../diseno_de_clases.md) §6 |
| [`clases_sesion.svg`](clases_sesion.svg) ([`.tex`](clases_sesion.tex)) | **`AcquisitionSession`**, la sesión del osciloscopio, y lo que compone: `ReaderThread`, `ChunkWriter`, el pool de `EventBatch` y las dos colas; los `Annotator` y lo que queda en `run_dir/`. La fuente aparece sólo como la interfaz | [`diseno_de_clases.md`](../diseno_de_clases.md) §7 |

---

## Lo que los diagramas de clases no dibujan

- **Los sustitutos de prueba** (`FakeMCA`, `FakeOsc`, `FakeMultiTrigger`,
  `FakeMtRegion`, `FakeSource`) y el backend de C por callbacks. No son parte
  de la API que usa un programa; están en
  [`../diseno_de_clases.md`](../diseno_de_clases.md) §9.1.
- **Lo que ya dibujó otra figura.** Los métodos de `MCA` son las funciones de
  libmca: van una sola vez, en `clases_libmca`. La sesión ve la fuente sólo
  como la interfaz `EventSource`; las implementaciones van en `clases_fuentes`.

Dos convenciones de notación:

- **Herencia.** Si la base está en la figura, la herencia es el triángulo
  hueco. Si no está (`threading.Thread`), va entre paréntesis en el nombre.
- **Hilos.** Naranja quiere decir que la clase **es** un hilo (hereda de
  `threading.Thread`). Los subtítulos no nombran en qué hilo corre cada cosa:
  eso está en `hilos`.

## Las figuras van sin prosa adentro

Lo que llevan son **nombres de módulo, de clase, de función y de ruta**, o sea,
identificadores que el lector va a buscar en el código. Las razones, las
mediciones y las advertencias van una sola vez, en
[`arquitectura_software.md`](../arquitectura_software.md). Es la misma regla
que [`docs/TOP/figuras/`](../../TOP/figuras/) y que
[`docs/mca/figuras/`](../../mca/figuras/).

Por esa regla se rehicieron. Las versiones anteriores las generaba
`figuras_arquitectura_software.py`: cuatro SVG oscuros con párrafos dentro de
las cajas, y cada uno contaba dos o tres cosas a la vez. Las dos más cargadas
quedaron partidas: el filesystem ahora son dos figuras, una por lo que lee y
otra por lo que escribe, y lo mismo los tipos y la ejecución. El aviso del
multitrigger en el slot 1, las mediciones del pipeline y las trampas de orden
salieron de los dibujos: ya estaban en el texto.

# Figuras: la arquitectura de software de la API

Diez figuras sobre **cómo está construido el software de la API**. Las seis
primeras las usa [`../arquitectura_software.md`](../arquitectura_software.md);
las cuatro `clases_*` son los diagramas de clases de los niveles 4 y 6. Son TikZ, con el
estilo común de los panoramas
([`../../figuras/estilo_tikz.tex`](../../figuras/estilo_tikz.tex)), más
[`clases_estilo.tex`](clases_estilo.tex) para la notación de los diagramas de
clases: PDF para la tesis y SVG para los markdown, con fondo blanco siempre.

```bash
cd prj/MCA/docs/API/figuras
for f in niveles hilos secuencia_bitstream escritura_corrida esquema_evento maquinas_estados \
         clases_mca clases_scope clases_fuentes clases_sesion; do
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
| [`niveles.svg`](niveles.svg) ([`.tex`](niveles.tex)) | Los **siete niveles**, en la máquina donde corre cada uno (PL, PS, PC), y las dos fronteras físicas: el bus AXI y la red. El camino remoto entra a la placa por el nivel 7 y vuelve a la pila por el 4 | §1 |
| [`hilos.svg`](hilos.svg) ([`.tex`](hilos.tex)) | Los **tres sistemas de concurrencia**, uno por banda: el pipeline (colas), el servidor (un lock) y la GUI (señales de Qt) | §2 |
| [`secuencia_bitstream.svg`](secuencia_bitstream.svg) ([`.tex`](secuencia_bitstream.tex)) | Lo que la API **lee** del filesystem, en el orden en que lo lee: la recarga de la PL, con la ruta que toca cada paso | §3 Lo que lee |
| [`escritura_corrida.svg`](escritura_corrida.svg) ([`.tex`](escritura_corrida.tex)) | Lo que la API **escribe** cuando mide: el `.tmp` + `os.replace` de los dos escritores y el camino físico de un `write()` | §3 Lo que escribe |
| [`esquema_evento.svg`](esquema_evento.svg) ([`.tex`](esquema_evento.tex)) | El esquema del evento **armado en runtime**: quién declara cada columna y el `EventBatch` que resulta | §4 El esquema |
| [`maquinas_estados.svg`](maquinas_estados.svg) ([`.tex`](maquinas_estados.tex)) | Dos subfiguras: **(a)** el lazo de `EventSource`, con el tiempo muerto marcado, y **(b)** el flujo lineal del MCA | §4 Las dos máquinas |
| [`clases_mca.svg`](clases_mca.svg) ([`.tex`](clases_mca.tex)) | **`MCA`** y sus dos subclases, `MCARemote` y `FakeMCA`: atributos, métodos y qué redefine cada una. A la izquierda, quién usa el handle: las funciones `mca_*` y `ServidorMCA` | todavía no |
| [`clases_scope.svg`](clases_scope.svg) ([`.tex`](clases_scope.tex)) | El resto de los handles: `Osciloscope`, el shim `MultiTriggerScope`, `MultiTrigger`, `MtRegion`, `Integration` y los sustitutos `FakeOsc` y `FakeMultiTrigger` | todavía no |
| [`clases_fuentes.svg`](clases_fuentes.svg) ([`.tex`](clases_fuentes.tex)) | La interfaz **`EventSource`**, quién llama cada método, y sus tres implementaciones con de dónde lee cada una | todavía no |
| [`clases_sesion.svg`](clases_sesion.svg) ([`.tex`](clases_sesion.tex)) | **`AcquisitionSession`** y lo que compone: `ReaderThread`, `ChunkWriter`, el pool de `EventBatch` y las dos colas; los `Annotator` y lo que queda en `run_dir/` | todavía no |

---

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

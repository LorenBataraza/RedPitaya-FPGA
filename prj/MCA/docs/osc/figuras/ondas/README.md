# Figuras: ondas del módulo OSC

Tres diagramas de tiempo. Los dos primeros salen del VCD de
[`tb_osc_filter`](../../../../modulos/osc/sim/tb_osc_filter.sv), que es un
testbench de **equivalencia**: corre `osc_filter` y `osc_filter_ref` —el filtro
original del repo— lado a lado con el mismo estímulo y cuenta las discrepancias
ciclo a ciclo. Por eso las figuras dibujan las dos salidas superpuestas: lo que
se ve es la prueba de que el rediseño no cambió la respuesta.

| Figura | Archivo | Qué muestra | Datos | Origen |
|---|---|---|---|---|
| Respuesta al impulso del ecualizador | [`osc_filter_impulso.svg`](osc_filter_impulso.svg) | coeficientes de reset (la cadena es transparente), osc_filter vs osc_filter_ref | simulación | `tb_osc_filter`, caso de coeficientes de reset |
| Compensación polo-cero del ecualizador | [`osc_filter_polocero.svg`](osc_filter_polocero.svg) | compensacion polo-cero (aa=25000): la cola que compensa el preamplificador | simulación | `tb_osc_filter`, caso de compensacion polo-cero |
| Flujo de adquisición del osciloscopio | [`osc_cfg_adquisicion.svg`](osc_cfg_adquisicion.svg) | osc_cfg | esquema | esquema (sin VCD: `osc_cfg` no tiene testbench) |

Los epígrafes —con los números medidos— están en
[`epigrafes.txt`](epigrafes.txt), que escribe el mismo script para que no
puedan desincronizarse de los dibujos. El visor
[`ondas_osc.html`](ondas_osc.html) muestra las 3 con sus notas y
no necesita nada instalado.

## Regenerar

```bash
cd prj/MCA
python3 docs/osc/figuras/ondas/ondas_osc.py          # con los FST versionados

# regenerar los FST desde cero (una vez, con Questa):
make -C modulos/osc/work vcd TB=tb_osc_filter VCD_ADD="/tb_osc_filter/*"
python3 docs/osc/figuras/ondas/ondas_osc.py --recortar \
        modulos/osc/work/waves/tb_osc_filter.vcd
```

## Cómo se hacen

Las ondas salen de un **VCD de verdad** de los testbenches del módulo, no de un
esquema dibujado a mano, y los tiempos —latencias, cuántos ciclos dura una
ventana, cuántos tarda un ack— los **mide el script sobre el VCD** y los
escribe en el epígrafe. Por eso no pueden desincronizarse del RTL: si cambia
una latencia, cambia el número del epígrafe sin que nadie lo toque.

La ventana de cada figura se ubica por **condiciones sobre las señales** (el
cruce de un umbral, el juego de coeficientes que define la escena, una racha de
incrementos), nunca por un tiempo fijo. Si el testbench agrega una escena
antes, las figuras siguen saliendo donde corresponde.

Lo genérico —leer el VCD/FST, muestrearlo en una grilla de ciclos, armar el
WaveJSON, renderizar y escribir los epígrafes— está en
[`docs/figuras/ondas.py`](../../../figuras/ondas.py), compartido con los demás
scripts de ondas y con los del protocolo del bus.

**Una columna es un ciclo de reloj.** Las figuras del bus de sistema
([`docs/TOP/figuras/bus_sistema/`](../../../TOP/figuras/bus_sistema/)) usan
medio ciclo, porque ahí hay dos relojes asíncronos y la fase importa; acá hay
un solo dominio y lo que importa es la secuencia de muestras.

## Qué se versiona

| Archivo | Para qué |
|---|---|
| `*.json` | el WaveJSON: es la fuente, pesa poco y permite rehacer el SVG sin tener el renderer |
| `*.svg` | la figura que embebe el datasheet |
| `*.fst` | las ondas recortadas a la ventana que se dibuja |
| `epigrafes.txt` | los epígrafes con los números medidos; lo escribe el script |
| `ondas.json` | el manifiesto que lee `datasheet.py` para armar §1.6 |

Los FST van **recortados a la ventana**: el VCD completo de `tb_osc_filter` son
23 MB (y 1.5 MB de FST) porque Questa escribe los vectores bit por bit;
recortado a lo que se dibuja queda en unos kB y las figuras se regeneran en un
clon limpio **sin Questa**.

## Renderer

El `.svg` lo hace `wavedrom-cli`. Si no está instalado, el script igual escribe
el WaveJSON y el visor HTML, que dibuja desde el CDN y no necesita nada:

```bash
npm i -g wavedrom-cli          # o --render cli, que lo baja con npx (pide red)
pip install --user wavedrom    # alternativa, sólo SVG
```

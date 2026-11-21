# Figuras: ondas del módulo Multitrigger

Tres diagramas de tiempo, de los VCD de `tb_trigger_shield` y
`tb_mt_trig_src`. La secuencia de uso (el contrato PS ↔ módulo) no es una
figura de ondas: es un diagrama de secuencia,
[`../secuencia/mt_secuencia.svg`](../secuencia/mt_secuencia.svg), y va en la
§1.3 del datasheet.

La primera junta las **tres formas del veto** en un solo dibujo, separadas por
el hueco de WaveDrom (`|`): son tres ventanas distintas del mismo testbench y el
hueco dice explícitamente que entre una y otra se salteó tiempo. Pegarlas sin el
hueco daría a entender que una sigue a la otra.

| Figura | Archivo | Qué muestra | Datos | Origen |
|---|---|---|---|---|
| Veto en Multitrigger | [`mt_veto_tres_formas.svg`](mt_veto_tres_formas.svg) | nivel / nivel con cola / ventana por flanco | simulación | `tb_trigger_shield`, escenas 4, 5 y 6 |
| Holdoff y re-arm del escudo | [`mt_holdoff_rearm.svg`](mt_holdoff_rearm.svg) | el escudo cuenta y al expirar limpia el canal de destino | simulación | `tb_trigger_shield`, escena 2 |
| Disparo single-shot | [`mt_trig_src_enganche.svg`](mt_trig_src_enganche.svg) | el flanco dispara, engancha el disable y la mascara se auto-limpia | simulación | `tb_mt_trig_src`, escena 1 |

Los epígrafes —con los números medidos— están en
[`epigrafes.txt`](epigrafes.txt), que escribe el mismo script para que no
puedan desincronizarse de los dibujos. El visor
[`ondas_mt.html`](ondas_mt.html) muestra las 3 con sus notas y
no necesita nada instalado.

## Regenerar

```bash
cd prj/MCA
python3 docs/mt/figuras/ondas/ondas_mt.py

# regenerar los FST desde cero (una vez, con Questa):
for tb in tb_trigger_shield tb_mt_trig_src; do
  make -C modulos/mt/work vcd TB=$tb VCD_ADD="/$tb/*"
  vcd2fst modulos/mt/work/waves/$tb.vcd \
          docs/mt/figuras/ondas/$tb.fst
done
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

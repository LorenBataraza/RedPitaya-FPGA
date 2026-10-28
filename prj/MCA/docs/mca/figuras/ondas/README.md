# Figuras: ondas del módulo MCA

Cinco diagramas de tiempo. Cuatro salen de los VCD de
`tb_mca_pulse_feature`, `tb_mca_hist` y `tb_mca_top`; el quinto es un esquema
de la secuencia de uso.

| Figura | Archivo | Qué muestra | Datos | Origen |
|---|---|---|---|---|
| Vida de un pulso en el MCA | [`mca_pulso_vida.svg`](mca_pulso_vida.svg) | cruce de umbral, ventana, carga acumulada y evento | simulación | `tb_mca_pulse_feature`, escena 1 (pulso rectangular) |
| Apilamiento de pulsos | [`mca_apilamiento.svg`](mca_apilamiento.svg) | la ventana llega a maxlen: el pulso se cuenta pero NO se acepta | simulación | `tb_mca_pulse_feature`, escena 5 (apilamiento) |
| Lectura-modificación-escritura del histograma | [`mca_hist_rmw.svg`](mca_hist_rmw.svg) | la cuenta no se pierde aunque los eventos lleguen pegados | simulación | `tb_mca_hist`, escena 3 (forwarding) |
| Borrado del histograma sin bloquear el bus | [`mca_ack_borrado.svg`](mca_ack_borrado.svg) | el barrido de borrado dura miles de ciclos y el bus no se entera | simulación | `tb_mca_top`, escena 5 (lectura durante el borrado) |
| Flujo de uso del MCA | [`mca_flujo.svg`](mca_flujo.svg) | mca_top | esquema | esquema (sin VCD) |

Los epígrafes —con los números medidos— están en
[`epigrafes.txt`](epigrafes.txt), que escribe el mismo script para que no
puedan desincronizarse de los dibujos. El visor
[`ondas_mca.html`](ondas_mca.html) muestra las 5 con sus notas y
no necesita nada instalado.

## Regenerar

```bash
cd prj/MCA
python3 docs/mca/figuras/ondas/ondas_mca.py          # con los FST versionados

# regenerar los FST desde cero (una vez, con Questa):
for tb in tb_mca_pulse_feature tb_mca_hist tb_mca_top; do
  make -C modulos/mca/work vcd TB=$tb VCD_ADD="/$tb/*"
done
python3 docs/mca/figuras/ondas/ondas_mca.py --recortar
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

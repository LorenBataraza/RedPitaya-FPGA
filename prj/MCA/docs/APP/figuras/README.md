# Figuras: el protocolo de red

Dos figuras sobre **la trama** del protocolo entre `mca_server.py` y sus clientes. Las
usa [`../protocolo.md`](../protocolo.md), en "La trama".

Son TikZ, con el estilo común de los panoramas
([`../../figuras/estilo_tikz.tex`](../../figuras/estilo_tikz.tex)): PDF para la tesis y
SVG para los markdown, con fondo blanco siempre.

```bash
cd prj/MCA/docs/APP/figuras
for f in trama trama_flujo; do
  pdflatex $f.tex && pdftocairo -svg $f.pdf $f.svg
done
rm -f *.aux *.log
```

| Figura | Qué muestra |
|---|---|
| [`trama.svg`](trama.svg) ([`.tex`](trama.tex)) | **Los mensajes, byte a byte**: la cabecera JSON, el `\n` y el payload, con mensajes reales de la op `call`: una función sin arreglo, una con arreglo y un error |
| [`trama_flujo.svg`](trama_flujo.svg) ([`.tex`](trama_flujo.tex)) | **Por qué hace falta `Channel`**: el flujo TCP sin límites, dónde corta cada `recv()` y dónde corta `Channel`, y lo que queda en su buffer |

Salen de leer [`software/API/mca_net.py`](../../../software/API/mca_net.py),
[`software/API/mca_remote.py`](../../../software/API/mca_remote.py) y
[`software/app/mca_server.py`](../../../software/app/mca_server.py). Si cambia la trama,
hay que rehacerlas a mano.

Como en las demás carpetas de figuras, adentro van sólo identificadores y valores; el
epígrafe está en `<figura>.txt` y en cursiva debajo de la imagen en el documento.

## Las capturas de la GUI

En [`capturas/`](capturas/) hay una PNG por pestaña de `mcamon`. Las saca
[`capturas_gui.py`](capturas_gui.py), sin pantalla y sin placa: levanta
`mca_server.py --fake` en local, conecta la GUI, acumula unos segundos y guarda cada
pestaña tal como queda. Los datos son los del servidor simulado: un fotopico gaussiano
a ~1 kev/s, dos poblaciones en el mapa 2D y pulsos sintéticos en «Pulses». Por eso la
barra superior dice `simulated`.

```bash
cd prj/MCA/docs/APP/figuras
python3 capturas_gui.py                       # 1500x950, en capturas/
python3 capturas_gui.py --tam 1280x800 --segundos 15
```

| Captura | Pestaña |
|---|---|
| [`mcamon_spectrum.png`](capturas/mcamon_spectrum.png) | **Spectrum**: el histograma 1D, los contadores, el tiempo muerto y los picos detectados |
| [`mcamon_2d_map_psd.png`](capturas/mcamon_2d_map_psd.png) | **2D map (PSD)**: amplitud × forma, y la FOM |
| [`mcamon_mca_settings.png`](capturas/mcamon_mca_settings.png) | **MCA settings**: la franja del MCA por etapas y sus registros |
| [`mcamon_pulses.png`](capturas/mcamon_pulses.png) | **Pulses**: la traza del osciloscopio y la tasa en el tiempo |
| [`mcamon_osc_settings.png`](capturas/mcamon_osc_settings.png) | **OSC settings**: el osciloscopio arriba, el ring abajo |
| [`mcamon_multitrigger.png`](capturas/mcamon_multitrigger.png) | **Multitrigger**: fuentes, máscaras OR, evento y shield |
| [`mcamon_generator.png`](capturas/mcamon_generator.png) | **Generator**: el generador de pulsos por etapas y el lazo digital |
| [`mcamon_calibration.png`](capturas/mcamon_calibration.png) | **Calibration**: el canal medido con el falso (una fila en Origin) y la base del MCA |
| [`mcamon_messages.png`](capturas/mcamon_messages.png) | **Messages**: el registro de la sesión |

La pestaña **Integration** no sale: el servidor simulado no tiene el bloque de
integración, y la GUI sólo la muestra cuando el bitstream lo trae.

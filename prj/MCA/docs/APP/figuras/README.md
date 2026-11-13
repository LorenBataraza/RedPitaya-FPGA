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

# Figuras del generador de pulsos

En TikZ, con el estilo común ([`../../figuras/estilo_tikz.tex`](../../figuras/estilo_tikz.tex));
el `.pdf` va a la tesis y el `.svg` a los documentos. El epígrafe de cada una está en su
`.txt` y, en cursiva, debajo de la imagen en el doc.

| Fuente | Qué muestra | Dónde está embebida |
|---|---|---|
| [`panorama_gen_pulsos.tex`](panorama_gen_pulsos.tex) | `gen_pulsos` por funciones, coloreado por función y con los símbolos de la ecuación de §3 ($t_k$, $i_k$, $A_k$, $h$ con $\tau_d$ y $\tau_r$, $B$, $r$): el motor (bloque), la amplitud con sus símbolos (xorshift32, cuenta, mux, tabla), la forma y la salida como bloques (su detalle es el datapath), el banco de registros y el bus | [`generador_pulsos.md`](../generador_pulsos.md) §3 |
| [`panorama_gen_disparos.tex`](panorama_gen_disparos.tex) | El motor de disparos que comparten `gen_pulsos` y `gen_eventos`, con un símbolo por operación: el arranque, el período, el xorshift32 y el comparador, la espera, la decisión (un mux), la salida, la cuenta y el fin | [`generador_pulsos.md`](../generador_pulsos.md) §3; enlazada desde [`event_ring/generador.md`](../../event_ring/generador.md) |
| [`datapath_gen_pulsos.tex`](datapath_gen_pulsos.tex) | La forma, la salida y el ruido registro por registro, con un símbolo por operación, los anchos y el ciclo (g − 1 a g + 5) en que el pulso está en cada registro | [`generador_pulsos.md`](../generador_pulsos.md) §3 |

Los símbolos (`oper`, `opxor`, `desp`, `satur`, `puerta y`, `puerta o`, `cte`) están en el
estilo común: una operación que tiene símbolo se dibuja con el símbolo, y no se nombra el
tipo de celda con que se sintetiza.

Para regenerar:

```bash
for f in panorama_gen_pulsos panorama_gen_disparos datapath_gen_pulsos; do
  pdflatex $f.tex && pdftocairo -svg $f.pdf $f.svg
done
rm -f *.aux *.log
```

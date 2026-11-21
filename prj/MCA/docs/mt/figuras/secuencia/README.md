# Figuras: secuencia de programación del módulo MT

El contrato entre el PS y el multitrigger, como diagrama de secuencia: qué
escribe y qué lee el software, en qué orden y qué estado del módulo ve en cada
paso. Qué pasa si no se respeta el orden va en el epígrafe, no en la figura.
Sólo aparecen el PS y el módulo; las fuentes entran y el disparo sale como
flechas desde y hacia el borde, sin actor. La captura que espera el disparo es
de otro módulo: el orden entre su arm y la máscara va en el epígrafe.

| Figura | Archivo | Fuente | Página |
|---|---|---|---|
| Un disparo, visto desde el PS | [`mt_secuencia.svg`](mt_secuencia.svg) | [`mt_secuencia.tex`](mt_secuencia.tex) | [`datasheet_mt_top.md`](../../../datasheet/datasheet_mt_top.md) §1.3 |

El título, el epígrafe y a qué páginas va cada figura están en
[`secuencia.json`](secuencia.json), que lee `modulos/mk/datasheet.py`. Se
escribe a mano, como las figuras: no hay nada que medir, lo que fijan es el
orden.

Las convenciones (líneas de vida, colores de flecha, franjas de estado) y sus
macros están en
[`docs/figuras/estilo_tikz.tex`](../../../figuras/estilo_tikz.tex), sección
«secuencias».

## Regenerar

```bash
cd docs/mt/figuras/secuencia
pdflatex mt_secuencia.tex
pdftocairo -svg mt_secuencia.pdf mt_secuencia.svg
make -C ../../../../modulos/mt/work datasheet
```

# Figuras: secuencia de programación del módulo OSC

El contrato entre el PS y el módulo, como diagrama de secuencia: qué escribe y
qué lee el software, en qué orden y qué estado del módulo ve en cada paso. Qué
pasa si no se respeta el orden va en el epígrafe, no en la figura. Sólo
aparecen el PS y el módulo; lo que llega de otro módulo (el trigger) entra como
una flecha desde el borde.

| Figura | Archivo | Fuente | Página |
|---|---|---|---|
| Una captura, vista desde el PS | [`osc_secuencia.svg`](osc_secuencia.svg) | [`osc_secuencia.tex`](osc_secuencia.tex) | [`datasheet_osc_cfg.md`](../../../datasheet/datasheet_osc_cfg.md) §1.3 |

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
cd docs/osc/figuras/secuencia
pdflatex osc_secuencia.tex
pdftocairo -svg osc_secuencia.pdf osc_secuencia.svg
make -C ../../../../modulos/osc/work datasheet
```

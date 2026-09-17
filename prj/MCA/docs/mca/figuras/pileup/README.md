# Figuras: apilamiento

Figuras para [`../../apilamiento.md`](../../apilamiento.md). Las genera
[`figuras_pileup.py`](figuras_pileup.py), con la misma convención que el resto
de [`figuras/`](../): sin texto adentro, paleta y rcParams de
[`figuras_resolucion.py`](../figuras_resolucion.py).

```bash
cd prj/MCA/docs/mca/figuras/pileup
python3 figuras_pileup.py
```

| Figura | Qué muestra | Datos |
|---|---|---|
| [`01_cola_undershoot.png`](01_cola_undershoot.png) | Apilamiento de cola (Knoll fig. 17.17). Arriba: el primer pulso deja una **cola positiva** y el segundo se mide de más — el pico gana una cola a la derecha. Abajo: el mismo pulso tras una diferenciación CR sin polo-cero deja **undershoot** y el segundo se mide de menos — la cola va a la izquierda. El espectro de la derecha no es un dibujo: es la distribución de la altura del segundo pulso con instante de llegada uniforme, convolucionada con la resolución del pico | esquema |

## Epígrafe

**Figura 1.** Apilamiento de cola. Izquierda: señal en el tiempo; un pulso de
amplitud 1 seguido, antes de que vuelva a la línea de base, por otro de amplitud
0,62 (trazo continuo: la señal medida; trazo discontinuo: el primer pulso solo).
La flecha roja marca el residuo del primer pulso en el instante en que llega el
segundo; la naranja, la altura que el MCA mide para el segundo, que es la suya
más ese residuo. Derecha: espectro dN/dH de esa altura cuando el segundo pulso
llega en un instante al azar (uniforme entre 2,5 y 14 unidades de tiempo después
del primero) y el pico tiene resolución gaussiana σ = 0,02. La línea punteada
es la altura verdadera del segundo pulso; el rayado, el exceso respecto del pico
limpio. Arriba, con la forma del estímulo de la campaña —subida suave, cola
exponencial— la cola del espectro va hacia alturas mayores. Abajo, el mismo
pulso pasado por un CR sin cancelación polo-cero tiene undershoot y la cola del
espectro va hacia alturas menores. Las unidades de tiempo son arbitrarias: el
esquema muestra el mecanismo, no las constantes del sistema.

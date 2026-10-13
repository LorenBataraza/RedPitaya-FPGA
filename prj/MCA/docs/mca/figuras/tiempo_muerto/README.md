# Figuras: tiempo muerto, el modelo

Figuras para la sección "El modelo, en unidades de τ" de
[`../../tiempo_muerto.md`](../../tiempo_muerto.md). Las genera
[`figuras_tiempo_muerto.py`](figuras_tiempo_muerto.py), con la misma convención
que el resto de [`figuras/`](../): sin texto adentro, paleta y rcParams de
[`figuras_resolucion.py`](../figuras_resolucion.py). Son **teóricas**: no
entra ningún `.npz`, y los ejes van en unidades de τ para que la misma curva
sirva al lector de Python (τ ≈ 250 µs) y al MCA (τ ≈ 2.9 µs).

```bash
cd prj/MCA/docs/mca/figuras/tiempo_muerto
python3 figuras_tiempo_muerto.py     # además imprime las tablas que cita el doc
```

| Figura | Qué muestra | Datos |
|---|---|---|
| [`01_tasas_adimensionales.png`](01_tasas_adimensionales.png) | `m·τ` contra `n·τ` para los tres modelos K=1 —periódico (dientes de sierra), Poisson no paralizable, paralizable— y la fracción perdida contra ρ en log. Donde los modelos se separan es a ρ chico | teórico |
| [`02_integral_exponencial.png`](02_integral_exponencial.png) | Un tren Poisson con sus ventanas muertas; la densidad exponencial de `Δt` con el **área entre 0 y τ** sombreada; y lo que da esa área, `1 − e^{−ρ}`, contra `ρ/(1+ρ)` y `ρ`. El paralizable es exactamente el área; el no paralizable coincide a primer orden | teórico |
| [`03_cola_K.png`](03_cola_K.png) | Poisson con `K` lugares en el sistema (`K=1` = sin cola): la fracción perdida cae un orden en ρ por cada lugar de cola, y la fracción de tiempo ocupado **sube** con `K`. Cadena embebida de M/D/1/K, no simulación | teórico |
| [`04_periodico.png`](04_periodico.png) | Cuatro trenes periódicos con distinto `T_prod/T_cons` y cuáles arribos se pierden; la escalera `m·τ = ρ/⌈ρ⌉` con τ fijo y con dispersión σ/τ = 3 % y 10 %, junto a Poisson | teórico |

## Epígrafes

**Figura 1.** Tasa registrada contra tasa incidente, ambas multiplicadas por el
tiempo muerto τ, para un servidor sin cola (K=1). (a) Escala lineal. Punteado:
sin pérdidas, m = n. Azul: arribos periódicos, m·τ = ρ/⌈ρ⌉, sin pérdida hasta
ρ = 1 y en dientes de sierra después; en cada entero se registra uno de cada k
arribos. Naranja: arribos Poisson con tiempo muerto no paralizable,
m·τ = ρ/(1+ρ), que tiende a 1 sin alcanzarlo. Verde: paralizable, ρ·e^{−ρ},
con máximo 1/e en ρ = 1. La curva de Poisson pasa por el fondo de cada diente
del periódico: en ρ = k ambas valen k/(k+1). (b) La fracción perdida 1 − m/n
de las mismas curvas, con ρ logarítmico: el periódico da cero hasta ρ = 1; los
otros dos dan ≈ ρ desde el origen.

**Figura 2.** De dónde sale la pérdida con arribos Poisson. (a) Un tren de
arribos Poisson con ρ = 0,5, en unidades de τ. Cada arribo registrado (azul)
abre una ventana muerta de largo τ (gris); los arribos que caen adentro (rojo)
se pierden y no la extienden. (b) Densidad del intervalo entre arribos,
τ·n·e^{−n·Δt}, para ρ = 0,2, 0,5 y 1, con el área entre 0 y τ sombreada. Esa
área, 1 − e^{−ρ}, es la probabilidad de que el próximo arribo caiga dentro de
la ventana; es no nula para todo ρ porque la exponencial tiene su máximo en
Δt = 0. (c) Fracción perdida contra ρ: el área (verde, punto-raya) es exacta
para el modelo paralizable; para el no paralizable la pérdida es ρ/(1+ρ)
(naranja), porque los perdidos no reabren la ventana y lo que cuenta es su
número esperado, ∫₀^τ n·dt = ρ. Las dos coinciden con ρ (punteado) a primer
orden.

**Figura 3.** Arribos Poisson, servicio fijo τ y K lugares en el sistema
contando al que se atiende; K = 1 es sin cola. Resuelto con la cadena de Markov
embebida en las partidas de M/D/1/K. (a) Fracción perdida contra ρ para
K = 1, 2, 3, 5, 10 y K = ∞ (discontinua). Con K = 1 basta un arribo dentro de
una ventana para perderlo y la pérdida es ≈ ρ; con K lugares hace falta una
ráfaga de K en un mismo servicio, ≈ ρ^K/K!. Con K = ∞ la pérdida es
exactamente cero hasta ρ = 1. Por encima de ρ = 1 todas convergen a 1 − 1/ρ.
(b) Fracción de tiempo ocupado m·τ para los mismos K: sube con K, porque el
servidor atiende más. La cola no reduce el tiempo ocupado; hace que estar
ocupado deje de implicar perder. Con K = 1 los dos paneles coinciden en
ρ/(1+ρ).

**Figura 4.** Productor periódico de período T_prod y consumidor que tarda
T_cons = τ por evento, sin cola. (a) Cuatro trenes en unidades de τ, con
T_prod/T_cons = 2, 1,25, 0,8 y 0,4 (ρ = 0,5, 0,8, 1,25 y 2,5). Azul: arribos
registrados; gris: ventana muerta; rojo: arribos perdidos. Con T_prod ≥ T_cons
no se pierde ninguno; con 0,8 se pierde uno de cada dos y con 0,4 dos de cada
tres. (b) m·τ contra n·τ = T_cons/T_prod. Azul grueso: τ fijo,
m·τ = ρ/⌈ρ⌉; los puntos negros son los cuatro trenes de (a). Azules finos: τ
con dispersión gaussiana σ/τ = 3 % y 10 %, m = n/E[⌈τ/T⌉]; el diente se
redondea sólo cerca de cada entero, con ancho ± (σ/τ)·ρ, así que los dientes
altos se borran antes que los bajos. Naranja: Poisson, para comparar. (c) La
fracción perdida de las mismas curvas.

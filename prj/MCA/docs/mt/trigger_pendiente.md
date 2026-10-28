# Disparo por pendiente (trapezoidal rápido)

**RTL:** [`mt_slope_trig.sv`](../../modulos/mt/rtl/mt_slope_trig.sv), instanciado
por canal en [`mt_top.sv`](../../modulos/mt/rtl/mt_top.sv) al
lado de `rp_adc_trig`.
**Registros:** `SLOPE_CFG` / `SLOPE_THR` / `SLOPE_HYST` de la región del
multitrigger ([`register_map_mt.md`](register_map_mt.md)).
**Fuentes de la máscara OR:** bits 17–24 (`BIT_SLOPE_P0..P3`, `BIT_SLOPE_N0..N3`).
**Cómo funciona el filtro, con figuras:**
[`procesamiento_pendiente.md`](procesamiento_pendiente.md).

---

## 1. Qué disparos usan los MCA

| Esquema | Qué compara contra el umbral | A favor | En contra | Dónde está acá |
|---|---|---|---|---|
| **Nivel (leading edge)** con histéresis | la muestra `x` | trivial, latencia mínima | *walk* (el instante depende de la amplitud); el umbral efectivo se mueve con la **línea de base** | `rp_adc_trig` (`BIT_ADC_*`) y el Schmitt de `mca_pulse_feature` |
| **Pendiente: diferencia de k muestras** | `x[n] − x[n−k]` | rechaza la continua | amplifica el ruido de alta frecuencia | `mt_slope_trig` con `L=1`, `G=k−1` |
| **Pendiente: trapezoidal rápido** | `Σ_L x[n−i] − Σ_L x[n−L−G−i]` | rechaza la continua **y** promedia ruido; es la rama rápida de los procesadores digitales de pulsos | latencia ≈ L muestras | **`mt_slope_trig`** (`BIT_SLOPE_*`) |
| **RC-CR² / cruce por cero** | segunda derivada; dispara en el cruce | buen *timing* | más registros y más lógica; sensible al ruido | — |
| **CFD digital** (fracción constante) | `f·x[n] − x[n−D]`, cruce por cero | instante sin *walk* | es un método de *timing*, no de detección: igual necesita un *arming* por umbral | — |
| **Ventana de tiempo de subida** | tiempo entre dos niveles | selecciona por forma | dos umbrales y un contador por canal | — |

Los procesadores digitales comerciales (XIA, Amptek, el DPP-PHA de CAEN)
disparan con un **filtro rápido de pendiente** y miden la energía con un
filtro lento. El filtro rápido es un trapezoidal corto, que es lo que hace
`mt_slope_trig`.

## 2. Por qué conviene en este MCA

1. **Rechaza la continua.** Los coeficientes suman cero, así que un offset o
   una deriva lenta no mueven el umbral efectivo. En el disparo de nivel sí lo
   mueven, y la deriva es el límite real del instrumento
   ([`limites_resolucion_y_deriva.md`](../mca/limites_resolucion_y_deriva.md)).
2. **El umbral es sobre la subida, no sobre el valor absoluto.** Un pulso que
   llega montado sobre la cola del anterior genera una pendiente nueva aunque la
   señal nunca haya bajado del umbral de nivel. Esa es la base de la inspección
   de apilamiento de los DPP, y es justo lo que el `cnt_pileup` actual no
   detecta ([`parametros_de_merito.md`](../mca/parametros_de_merito.md)).

## 3. Qué mide `s`

```
s[n] = Σ_{i=0}^{L-1} x[n-i]  −  Σ_{i=0}^{L-1} x[n-L-G-i]
```

| Entrada | `s` |
|---|---|
| continua | 0 |
| escalón de alto `A` (más rápido que `L+G`) | trapecio de alto **`L·A`**, subida `L`, techo `G+1` muestras |
| rampa de `m` cuentas/muestra | **`L·(L+G)·m`** |
| ruido blanco `σ` | `σ_s = σ·√(2L)` |

Para un escalón, la relación señal/ruido de `s` crece como `√L`. `G` no cambia
el ruido, pero sí la sensibilidad a rampas: un `G` grande hace que el filtro
vea flancos lentos como escalones. Elegir el umbral:

```python
from API.multitrigger import slope_pico
thr = slope_pico(L, G, escalon=A_min) // 2      # mitad del pico del pulso más chico
# y que quede varios σ_s arriba del ruido: thr >> σ·sqrt(2L)
```

## 4. Cómo está hecho

- **Recursivo y exacto en enteros:**
  `s[n] = s[n−1] + (x[n] − x[n−L]) − (x[n−L−G] − x[n−2L−G])`. No acumula
  error.
- **Tres líneas de retardo en cascada** (`L`, `G`, `L`), cada una con una toma
  dinámica, inferidas en SRL. La primera versión, una sola línea de 63 muestras
  con tres tomas, salía en flip-flops y muxes, unas 3–5 veces más cara (ver §6).
- **Re-arranque.** Las líneas no tienen reset. Al cambiar `L` o `G`, con
  `en=0` o con el reset, el filtro se vacía (`s=0`) y un contador de llenado
  hace que las tomas más viejas que el re-arranque lean 0. Así `s` queda
  exactamente igual al filtro aplicado sobre historia en cero.
- **Arranque silencioso.** Mientras la ventana (`2L+G` muestras) no está
  llena, el Schmitt queda en "disparado" y no sale ningún pulso. El primer
  disparo exige re-armar antes (`s < thr−hyst`). Por eso habilitarlo sobre una
  señal con offset no dispara, aunque el arranque desde cero sea un escalón
  falso.
- **Schmitt simétrico**, igual que `rp_adc_trig`: `p` dispara con `s ≥ thr` y
  re-arma con `s < thr−hyst`; `n` dispara con `s ≤ −thr` y re-arma con
  `s > −thr+hyst`. Con `hyst ≥ thr` no re-arma nunca en `s=0`.
- **Avanza solo con `adc_dv`**, así que sirve sobre cualquier tap de
  `ROUTE_MTRG`: el nativo decimado o los de 125 MSPS.
- **Latencia:** 5 ciclos de pipeline, más lo que tarde `s` en cruzar `thr`
  (del orden de `L` muestras para un escalón).

## 5. Uso

```python
from API.multitrigger import (MtRegion, MultiTrigger, multitrigger_arm,
                              BIT_SLOPE_P0, slope_pico)

mt3 = MtRegion.open()                       # slot 3; Integration.base('mtrg') si es otro top
mt3.set_slope(0, L=8, G=4, thr=slope_pico(8, 4, escalon=200)//2, hyst=300)
multitrigger_arm(osc, mt, mask_ch0=BIT_SLOPE_P0, mask_ch1=BIT_SLOPE_P0)
...
mt3.read_snapshot()                          # ['slope_p0'] si disparó por pendiente
```

- **Desde el MCA:** se usa con `cfg_trig_src = 1` (disparo externo) y hereda la
  advertencia de `mca_pulse_feature`: la ventana arranca unas muestras tarde.
  Sirve para coincidencia y para tener una base de tiempo común; para medir
  energía hace falta la línea de retardo de la Fase 3.
- **El snapshot del event ring** guarda 17 bits por slot, así que las fuentes de
  pendiente solo se ven en `SNAPSHOT` (0x018 del slot 3). Tampoco aparecen en
  `TRG_STATE`, que reporta 8 bits por canal.

## 6. Costo

Síntesis OOC (`make -C modulos/mt/work syn TOP=mt_slope_trig`), xc7z010-1 a
125 MHz, **por canal**:

| | LUT | de ellas SRL | FF | WNS |
|---|---|---|---|---|
| línea única con 3 tomas (descartada) | 907 | 0 | 1102 | +2.60 ns |
| **tres líneas en cascada** | **287** | 42 | **226** | **+2.47 ns** |

Con dos canales suma alrededor de 575 LUT, aproximadamente un 3 % del xc7z010,
sobre el 47 % que ocupa el diseño en `out/baseline_reports`.

## 7. Verificación

| Testbench | Qué verifica |
|---|---|
| [`tb_mt_slope_trig`](../../modulos/mt/sim/tb_mt_slope_trig.sv) | `s` contra un modelo de suma directa, muestra a muestra: rango completo con `L=16`, `G=31`, huecos de `dv`, `L=1`/`G=0` y saturación de `L`. Escalón → un pulso `p` y un pulso `n` con pico `L·A`. Continua y rampa lenta → nada. 20 escalones ruidosos → 20 + 20 pulsos. Cambio de `L`/`G` en caliente sin espurios. `en=0` |
| [`tb_mt_trig_src`](../../modulos/mt/sim/tb_mt_trig_src.sv) | bits 17–24 de la máscara |
| [`tb_mt_event_logic`](../../modulos/mt/sim/tb_mt_event_logic.sv) | evento conjunto y snapshot en los bits 17/22 |
| [`tb_mt_cfg`](../../modulos/mt/sim/tb_mt_cfg.sv) | `SLOPE_*`: escritura, readback, campos, sin fan-out; `CAPS[16]` |
| `test_api_osc.py` | layout de `set_slope`, validación de rangos, `slope_pico` |

**Pendiente en placa:** con el generador (`rigol_dg4162.py`, trapezoidal o
CR-RC⁴), comparar la curva S de `BIT_ADC_P0` contra la de `BIT_SLOPE_P0`, y
verificar que al mover el offset DC el umbral efectivo de la pendiente no
cambia y el de nivel sí.

## Bibliografía

| Ref | Para qué |
|---|---|
| **V. T. Jordanov, G. F. Knoll**, *Digital synthesis of pulse shapes in real time for high resolution radiation spectroscopy*, Nucl. Instrum. Methods A **345** (1994) 337 | el trapezoidal recursivo |
| **V. T. Jordanov, G. F. Knoll, A. C. Huber, J. A. Pantazis**, *Digital techniques for real-time pulse shaping in radiation measurements*, Nucl. Instrum. Methods A **353** (1994) 261–264, doi:10.1016/0168-9002(94)91652-7 | algoritmos recursivos en tiempo real; prototipo a 50 MHz |
| **W. K. Warburton, M. Momayezi, B. Hubbard-Nelson, W. Skulski**, *Digital pulse processing: new possibilities in nuclear spectroscopy*, Appl. Radiat. Isot. **53** (2000) 913–920 | arquitectura filtro rápido (disparo, apilamiento) + filtro lento (energía) en FPGA |
| **A. Fallu-Labruyère, H. Tan, W. Hennig, W. K. Warburton**, *Time resolution studies using digital constant fraction discrimination*, Nucl. Instrum. Methods A **579** (2007) 247–251, doi:10.1016/j.nima.2007.04.048 | CFD digital por cruce por cero (la fila CFD de §1) |
| **G. F. Knoll**, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010, cap. 17 | discriminadores analógicos: leading edge, cruce por cero, CFD, ARC |
| **CAEN**, WP2081 *Digital Pulse Processing in Nuclear Physics*, y el manual del DPP-PHA | el "Trigger and Timing Filter" RC-CR² |

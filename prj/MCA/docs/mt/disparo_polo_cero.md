# Disparo con polo-cero (`mt_pz_trig`)

Es la fuente de disparo del banco de trapecios del MCA. Va por canal, al lado del
disparo de nivel (`rp_adc_trig`) y del de pendiente (`mt_slope_trig`), y entra
en los bits 25..28 de `OR_MASK`. Está en el RTL y en el bitstream desde el
2026-11-03, y se midió en la placa el 2026-11-05.

```
tap MTRG ─► mca_trap (k, m, M, sh) ─► Schmitt (thr, thr − hyst) ─► pz_p ─► OR_MASK[25 + ch]
```

## Por qué otra fuente

El disparo por pendiente ([`trigger_pendiente.md`](trigger_pendiente.md))
compara s = Σ_L x − Σ_L x[n−L−G] contra un umbral. Como no cancela el polo de la
cola, tiene dos puntos ciegos que el banco de trapecios no tolera
([`../mca/pruebas_banco_trapecios.md`](../mca/pruebas_banco_trapecios.md) §4):

- **Funde pares a menos de ~2L + G muestras.** Con L = 8 y G = 4, dos pulsos a
  menos de ~20 muestras dan un solo disparo.
- **No ve un pulso chico en la cola de uno grande.** Sobre la cola, s es
  negativo durante cientos de muestras: uno de 300 después de uno de 8000
  recién dispara a ~150.

Además, su instante corre de 7 a 13 ciclos con la amplitud.

El polo-cero cambia lo que se compara: la salida de un trapecio de
Jordanov-Knoll **con** cancelación del polo. Cada pulso exponencial sale como un
trapecio que vuelve a cero a las 2k + m muestras, apoyado en cero aunque haya una
cola debajo. Con k = 2 y m = 1:

| | pendiente (L = 8, G = 4) | polo-cero, simulado | polo-cero, en la placa |
|---|---|---|---|
| dos disparos para 1 → 0.6, desde | 21 muestras (placa: 24) | **7–8** | **10** |
| uno de 0.04 en la cola, desde | 152 (placa: 400) | **7–8** | **9** |
| latencia hasta `trig_i`, A = 8000 → 100 | 7 → 14 ciclos | 12 → 14 | — |
| falsos sin señal, umbral 50 | — | ninguno en 22.8 M muestras | **ninguno en 37 G** |

*La simulación usa una subida de 1.2 muestras, sin sobrepaso (`tb_banco_disparo.sv` y
`tb_mt_pz_trig.sv`). En la placa, la más rápida sin doble disparo ronda 1.5–1.6; con 2.6–3.1,
separa desde 13. Las tablas están en
[`pruebas_banco_trapecios.md`](../mca/pruebas_banco_trapecios.md) §6.*

## Cómo funciona

- **El trapecio es `mca_trap`**, el mismo del MCA (`modulos/comun/rtl/`). Usa
  líneas de 32 muestras en LUT (`RAM_STYLE = "distributed"`, `DAW = 5`), así que
  k + m ≤ 31. Es bit a bit la recursión entera d → p → s del MCA, sobre la
  muestra cruda del tap: no resta la base.
- **La continua no se cancela del todo.** Para una entrada constante D, la
  salida se asienta en 16·k·l·D >> sh: es l/(1 + M) de lo que da un pulso de alto
  D, unas 80 veces menos. Con la base de la placa (~5 cuentas) no se nota. Con
  500 cuentas de offset, el umbral efectivo corre ~6 cuentas. Con más de ~+1880,
  el Schmitt (umbral 50, re-armado 25) ya no re-arma.
- **Re-arranque.** La configuración se registra dos veces. Un cambio de k, m o
  M, `en = 0` o el reset le pulsan `clr` al trapecio, como en la pendiente.
- **Arranque.** Desde el `clr` el trapecio ve la continua del tap como un
  escalón: con 500 cuentas sube a ~3900. Por eso el Schmitt queda "disparado"
  sin flanco hasta k + l + 12 muestras después, y el primer pulso pide re-armar
  antes.
- **Schmitt, solo positivo.** Dispara con y ≥ thr, re-arma con y < thr − hyst,
  y da un pulso de un ciclo. thr y hyst van en unidades de la salida.
- **Latencia.** Son 10 ciclos desde la muestra del cruce hasta `pz_p_o`: los 8
  de `mca_trap`, el Schmitt y el flanco. `mt_trig_src` suma uno más. En el peor
  caso, A = 100, llega a 14 hasta `trig_i`, igual que la pendiente: el
  `cfg_pre_dly` = 16 de la placa sirve para las dos (`tb_mca_mt_latencia`).

## Cómo se configura

Los registros están en [`register_map_mt.md`](register_map_mt.md): `PZ_CFG`,
`PZ_MQ`, `PZ_THR` y `PZ_HYST` (+4·ch), con `CAPS[17]`. Desde Python:

```python
from API.multitrigger import multitrigger_armar_mca, pz_ganancia
multitrigger_armar_mca(osc, mtr, ch=0, fuente='pz', mq=mq_del_mca)
```

- **`mq` es el mismo M·16 del MCA**, el que sale de ajustar la cola en la placa
  (etapa `trapecio` de `test_mca2_placa.py`). Con un M errado la salida deja una
  cola chica; con una forma tan corta casi no pesa.
- **El umbral va en cuentas de amplitud**: 50 para disparar y 25 para re-armar.
  `pz_ganancia(k, m, mq, sh)` las pasa a unidades de la salida. Es la altura de
  la meseta por cuenta para un pulso con la subida de la cadena: 7.07 con el M
  nominal, ~10 % menos que la ideal 16·k·(1 + M)/2^sh, porque con m = 1 la
  meseta es de una muestra. Con el M nominal queda en 353/177.
- **k y m van por registro** para un detector más lento. Con 8–16 muestras de
  subida, k = 2 no llega a la altura del pulso, y los de 100–150 cuentas no
  disparan.

## Un flanco con sobrepaso dispara dos veces

La forma es tan corta que sigue lo que viene después del flanco. Con 1 ns de subida la
entrada del Rigol sobrepasa ~8 % y rebota: la salida cae por debajo del re-armado y vuelve a
cruzar el umbral 6 muestras después. Da 1.65 disparos por pulso desde ~1500 cuentas, y a
1 Mcps baja los buenos de 665 a 565 k/s. Con 3 ns o más da 1.000 hasta 7600 cuentas.

El holdoff del shield lo tapa sin tocar el RTL: `dur` ≥ 5 deja un disparo por pulso, y con 6
la separación de pares sigue en 10. Con una subida limpia cuesta 3 % de buenos a 1 Mcps, así
que `multitrigger_armar_mca` no lo pone: conviene si `cross` da más que los pulsos.

```python
multitrigger_armar_mca(osc, mtr, ch=0, fuente='pz', mq=mq)
mtr.set_shield(src=1 << 0, dst=1 << 0, dur=6)     # después de armar, que lo deja en 0
```

## Lo que cuesta

OOC de `mt_top` a 125 MHz: WNS +1.46 ns. Cada canal cuesta 457 LUT (360 son del
`mca_trap`), 380 FF y 1 DSP, sin BRAM.

## Cómo se verificó

| Testbench | Qué verifica |
|---|---|
| [`tb_mt_pz_trig`](../../modulos/mt/sim/tb_mt_pz_trig.sv) | Contra modelos escritos aparte: el trapecio bit a bit y el Schmitt en cada ciclo (248 903), con decimación y con cambios de forma a mitad de la corrida. El arranque sin falsos con −1000 a +1800 de continua. 564 de 564 pulsos aislados con un disparo cada uno. Los pares desde 7. |
| [`tb_mt_cfg`](../../modulos/mt/sim/tb_mt_cfg.sv), [`tb_mt_trig_src`](../../modulos/mt/sim/tb_mt_trig_src.sv), [`tb_mt_event_logic`](../../modulos/mt/sim/tb_mt_event_logic.sv), [`tb_mt_top`](../../modulos/mt/sim/tb_mt_top.sv) | Los registros, los bits 25..28 de la máscara, el snapshot de 29 bits, y el disparo por registro de punta a punta. |
| [`tb_banco_disparo.sv`](../mca/figuras/trapecio/tb_banco_disparo.sv) | Da los mismos disparos que el modelo con el que se validó el banco, en 3600 pulsos y 6320 pares, un ciclo más tarde. |
| [`tb_banco_e2e.sv`](../mca/figuras/trapecio/tb_banco_e2e.sv) | Con el MCA y el banco, sobre un tren de Poisson: los disparos son los del modelo en el 99.97 % (los otros, corridos una muestra por el umbral en flotante del modelo). |

**Relacionados →** [`trigger_pendiente.md`](trigger_pendiente.md) (la otra
fuente), [`../mca/pruebas_banco_trapecios.md`](../mca/pruebas_banco_trapecios.md)
(por qué y con qué números) y
[`../mca/separacion_trapezoidal.md`](../mca/separacion_trapezoidal.md) (cómo
separa un trapecio).

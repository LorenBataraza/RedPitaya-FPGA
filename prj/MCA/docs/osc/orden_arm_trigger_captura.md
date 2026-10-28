# Orden arm-vs-fuente de trigger — decisión de diseño y guía de captura

Este documento explica **por qué hay que armar la `bram_sm` antes de habilitar
la OR-mask de trigger**, la FSM de captura involucrada, y da una guía práctica
del orden de comandos con snippets.

> La anatomía completa de la cadena de adquisición original —la FSM de
> `rp_bram_sm` señal por señal, el buffer, el camino a DDR— está en
> [`sistema_adquisicion_original.md`](sistema_adquisicion_original.md).

---

## Parte 1 — Decisión de diseño

### El síntoma

Una captura disparada por **flanco de ADC** nunca congelaba el buffer:
`adc_wp_trig = 0`, `adc_trg_rd = 0`, y la FSM quedaba armada para siempre. En
cambio el **SW trigger** funcionaba perfecto. Registros medidos en HW con la
señal viva (Rigol 100 kHz en IN1):

Los offsets están dados en el mapa **actual**: el multitrigger tiene slot propio
(`0x4030_0000`) desde el refactor de registros. La medición original se tomó con
el mapa viejo, donde estos registros vivían en el slot 1 como `0x218`/`0x21C`.

```
slot1 0x000 (adc_state) = 0x0101  -> adc_we=1 (armada), adc_trg_rd=0 (NUNCA disparó)
slot3 0x018 (snapshot)  = 0x0002  -> adc_p0 (el flanco SÍ se detectó)
slot3 0x01C (dis+wekp)  = 0x0000  -> adc_trg_dis limpio (el shield lo limpió)
slot1 0x01C (wp_trig)   = 0       -> la FSM no registró ningún trigger
```

`adc_trg_rd = 0` con `snapshot = adc_p0` es la firma del bug: **el evento de
trigger ocurrió, pero fuera de la ventana en que la `bram_sm` podía registrarlo**.

### Dos señales independientes

La causa raíz es confundir dos señales que son **independientes**:

1. **`set_trig_src` (OR-mask, `0x4030_0040`/`0x044`)** — qué fuentes de trigger
   están *vivas*. Vive en [`multitrigger_trig_src.sv`](../../rtl/mine/multitrigger/multitrigger_trig_src.sv).
2. **`adc_arm_do` / `adc_we` (reg `0x00` bit0)** — la FSM de captura
   ([`rp_bram_sm.v`](../../../../rtl/classic/rp_bram_sm.v)) está *armada y
   escribiendo al buffer*.

La lógica de trigger reacciona a los flancos **apenas se carga la máscara** — no
espera a que la `bram_sm` esté armada. Y la `bram_sm` solo registra el trigger si
ya estaba armada cuando llega el pulso.

### El comportamiento de `multitrigger_trig_src` (idéntico al stock `rp_trig_src`)

Al disparar (`adc_trig`), en modo **single-shot** (`adc_we_keep=0`):

- **Auto-clear** de la máscara:
  [`multitrigger_trig_src.sv:67`](../../rtl/mine/multitrigger/multitrigger_trig_src.sv#L67) —
  `set_trig_src <= 0`. Es de un solo tiro.
- **Trigger-protect**:
  [`:73`](../../rtl/mine/multitrigger/multitrigger_trig_src.sv#L73) — `adc_trg_dis <= 1`. Bloquea
  la máscara hasta que se limpie (`0x94` o el `trigger_shield`).

En modo **continuo** (`adc_we_keep=1`) la máscara **no** se auto-limpia (la
condición de la línea 67 tiene `!adc_we_keep_i`); solo se engancha `adc_trg_dis`.

### La FSM de la `bram` (`rp_bram_sm`)

La FSM de captura registra el trigger **solo mientras está armada**:

- `adc_wp_trig_o <= adc_wp_o` cuando `adc_trig_i && !adc_dly_do`
  ([`rp_bram_sm.v:91`](../../../../rtl/classic/rp_bram_sm.v#L91)). Guarda el
  puntero de escritura en el momento del trigger (referencia pre/post).
- `adc_trg_rd <= 1` en el flanco de `adc_trig_i`
  ([`:107`](../../../../rtl/classic/rp_bram_sm.v#L107)); se **borra con
  `adc_arm_do` o `adc_rst_do`** ([`:109`](../../../../rtl/classic/rp_bram_sm.v#L109)).
- Tras el trigger cuenta `set_dly` muestras post-trigger y **detiene la escritura**
  (`adc_we <= 0`, [`:67`](../../../../rtl/classic/rp_bram_sm.v#L67)): eso es lo
  que **congela** el buffer para leerlo coherente.

### El race, paso a paso

El notebook hacía `set_or_mask()` **antes** del arm:

1. `set_or_mask(ALL)` → `set_trig_src` vivo. Las fuentes de flanco de ADC quedan
   activas.
2. *(pasan µs — es otra escritura al bus)*.
3. `w32(0x00, arm)` → recién ahí se arma la `bram_sm`.

Con una señal viva (flanco cada 10 µs) casi siempre entra un **flanco pre-arm**
entre 1 y 3. Ese flanco:

- dispara `adc_trig` → engancha `adc_trg_dis=1` y **auto-limpia `set_trig_src=0`**
  (single-shot);
- la `bram_sm` **todavía no está armada** → no guarda `wp_trig`, y el `adc_trg_rd`
  que se prende lo borra el `adc_arm_do` del paso 3.

Resultado: la `bram_sm` queda armada con la máscara ya en 0 (y el protect
enganchado) → **espera un trigger que no puede llegar**. Deadlock. El
`trigger_shield` limpia `adc_trg_dis`, pero ya es tarde: la máscara está en 0.

**Por qué el SW trigger es inmune:** la fuente SW (`adc_trig_sw`) es *pasiva* —
solo se activa con el pulso `0x04`, que se escribe *después* del arm. No hay
disparo pre-arm.

### La decisión

El RTL es **correcto** (idéntico al stock `rp_trig_src`), así que **no se
modifica el RTL**. Se adopta la **convención de RedPitaya**: armar (`rp_AcqStart`)
**antes** de habilitar la fuente de trigger (`rp_AcqSetTriggerSrc`). El fix es de
software (reordenar), inmediato y sin re-síntesis.

Se descartó endurecer el RTL (gatear el auto-clear/protect con una señal
"armado") para no divergir del stock ni pagar un loop de síntesis en Vivado; la
convención de orden lo resuelve limpio.

### Qué hace (y qué no) el arm/trigger/freeze

Un buffer grande **no** reemplaza este mecanismo:

- **Congelar para leer coherente**: sin el freeze single-shot, leer 16k muestras
  por el bus mientras el ADC escribe a 125 MS/s da una **lectura rota** (el
  artefacto de "pulsos de distinta altura"). El buffer grande no lo arregla.
- **Referenciar el evento**: `wp_trig` marca dónde ocurrió el trigger.
- **Trigger-protect**: que un segundo trigger no pise `wp_trig` antes de leerlo.

Donde el buffer grande **sí** ayuda: en **modo continuo (`we_keep=1`)** podés
streamear sin congelar, y como la máscara no se auto-limpia, ese modo es **más
robusto al orden** (aún así conviene respetar arm→fuente).

### Verificación

- **Simulación (QuestaSim):** [`../sim/`](../../sim/) — `tb_trig_capture` reproduce
  el deadlock (máscara-antes-de-arm) y valida la captura (arm-antes-de-máscara).
  Correr con `cd prj/MCA/sim && make`.
- **HW:** con el orden corregido, `first_capture` da `capturo=True`, `wp_trig!=0`
  y pulsos de altura uniforme; la validación A/B/C da `PASS`.

---

## Parte 2 — Guía de orden de comandos

### La regla

> **Armar la `bram_sm` (slot 1, reg `0x00`) ANTES de habilitar la OR-mask
> (slot 3, `0x040`/`0x044`).** Igual que `rp_AcqStart` antes de
> `rp_AcqSetTriggerSrc`.

En [`API/multitrigger.py`](../../software/API/multitrigger.py) esto ya está
resuelto dentro de `multitrigger_arm(osc, mt, ...)`, que arma y después llama a
`set_or_mask`. Si armás "a mano" por escritura directa, respetá el orden.

> La función recibe **los dos handles** porque la secuencia cruza los dos
> bloques: histéresis (`0x20`/`0x24`) y arm (`0x00`) son del osciloscopio (slot 1),
> shield (`0x010`) y máscara OR (`0x040`/`0x044`) son del multitrigger (slot 3). Así la
> dependencia está en la firma en vez de escondida dentro de una clase.
>
> **El orden está congelado por un test.**
> [`API/tests/test_compat_api.py`](../../software/API/tests/test_compat_api.py) guarda la
> secuencia ordenada de escrituras de esta función y la compara en cada corrida,
> sobre un mmap falso: reordenarla falla en la PC en segundos, con un diff que
> señala las líneas movidas, en vez de fallar en la placa y sólo con señal viva.

### Snippet 1 — captura single-shot por flanco de ADC (recomendado)

```python
from multitrigger_utils import MultiTriggerScope, BIT_ADC_P0, decode_snap

sc = MultiTriggerScope.open()
sc.verify_bitstream(raise_on_fail=True)          # confirmar el diseño cargado

# arma (slot1 0x00) + habilita la mascara (slot3 0x040) EN ESE ORDEN:
sc.arm_for_adc_trigger(mask_ch0=BIT_ADC_P0, mask_ch1=BIT_ADC_P0,
                       thr=0.5, hyst=0.02, delay=N_BUF // 2,
                       we_keep_both=False, auto_rearm=False)   # single-shot

# esperar la captura por wp_trig (mas confiable que rp_AcqGetBufferFillState
# cuando se arma por escritura directa)
import time
for _ in range(1000):
    if sc.r32(0x1C) != 0:            # wp_trig latcheo -> capturo
        break
    time.sleep(0.001)
assert sc.r32(0x1C) != 0, 'no capturo: revisar senal / dis_we @slot3 0x01C'

d1, d2 = sc.read_buffers()
sc.disarm()
```

> `delay` nunca 0: `set_dly=0` es un caso degenerado del `rp_bram_sm` (la FSM lo
> trata como delay completo e ignora el trigger). Usar `delay>=1`
> (`arm_for_adc_trigger` lo maneja con `set_raw_delay`).

### Snippet 2 — multi-evento continuo (`we_keep=1` + shield)

```python
# modo continuo: la mascara NO se auto-limpia; el trigger_shield re-arma solo.
sc.arm_for_adc_trigger(mask_ch0=BIT_ADC_P0, mask_ch1=BIT_ADC_P0,
                       thr=0.5, hyst=0.02,
                       we_keep_both=True, auto_rearm=True)     # continuo + shield

# detectar triggers nuevos por cambios de wp_trig (@0x1C)
wp_prev = sc.r32(0x1C)
for _ in range(N):
    while sc.r32(0x1C) == wp_prev:
        pass
    wp_prev = sc.r32(0x1C)
    # ... procesar evento ...
sc.disarm()
```

### Snippet 3 — captura forzada por SW (independiente de la señal)

```python
# el SW trigger es inmune al orden (adc_trig_sw es pasivo hasta el pulso 0x04).
d1, d2, snap = sc.acq_capture_sw(thr=0.5)     # arma, pulsa 0x04, espera fill
print('disparo:', decode_snap(snap))
```

### Si armás por escritura directa (sin `arm_for_adc_trigger`)

```python
sc.acq_base(thr=0.5, delay=1)      # reset + clear(0x94) + dec/thr/dly
sc.w32(0x00, 0x0000_0101)          # 1) ARMAR primero (single-shot ch0+ch1)
sc.set_or_mask(OR_MASK_ALL)        # 2) recien ahora habilitar la mascara
# ... esperar wp_trig / leer buffer ...
```

### Anti-patrón (NO hacer)

```python
sc.set_or_mask(OR_MASK_ALL)        # mascara viva ANTES de armar  <-- RACE
sc.w32(0x00, 0x0000_0101)          # un flanco pre-arm gasta la mascara -> deadlock
```

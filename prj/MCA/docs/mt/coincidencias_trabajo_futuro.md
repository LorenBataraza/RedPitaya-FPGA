# Coincidencias y anticoincidencias — análisis y diseño (trabajo futuro)

> **Estado:** no implementado. Este documento deja el análisis y un diseño
> concreto para retomarlo cuando se defina el montaje experimental. **Sin al
> menos dos señales físicas independientes** (dos detectores, o un detector y
> un blindaje activo) **la función no tiene uso**, así que no se bajó a RTL.

**RTL relacionado:** [`mt_trig_src.sv`](../../modulos/mt/rtl/mt_trig_src.sv) ·
[`trigger_shield.sv`](../../modulos/mt/rtl/trigger_shield.sv) ·
[`mt_event_logic.v`](../../modulos/mt/rtl/mt_event_logic.v) ·
[`mt_cfg.sv`](../../modulos/mt/rtl/mt_cfg.sv) ·
[`mca_pulse_feature.sv`](../../modulos/mca/rtl/mca_pulse_feature.sv)

---

## 1. Qué es y para qué se usa

Una **coincidencia** acepta un evento solo si varias fuentes de disparo se
activan dentro de una ventana de tiempo W, que se llama *tiempo de resolución*.
Una **anticoincidencia** acepta un evento de una fuente de referencia solo si
**otra** fuente (el veto) *no* se activó dentro de esa ventana. La forma
general es la coincidencia **mayoritaria M de N**: el evento se acepta si al
menos M de las N fuentes seleccionadas dispararon dentro de W. Con M=1 es un
OR, y con M=N es una coincidencia total.

En espectroscopía con MCA, los usos típicos son estos:

| uso | lógica | qué se gana |
|---|---|---|
| supresión Compton | detector principal **y no** blindaje (BGO/NaI) | se rechazan los fotones que escapan tras dispersar: baja el continuo Compton |
| espectros γ-γ / β-γ en coincidencia | detector A **y** detector B | se aíslan cascadas de un núcleo dado y se suprime el fondo |
| rechazo de muones cósmicos | detector **y no** paleta de veto | se saca el fondo cósmico |
| telescopio / trayectoria | A **y** B **y** C | se selecciona una dirección de incidencia |

En un montaje de **un solo detector** no hay con qué coincidir.

> **Fuente de esta clasificación.** Sale del conocimiento general de electrónica
> nuclear: las unidades de coincidencia NIM con entradas de veto y lógica
> mayoritaria, y la lógica de trigger de los sistemas digitales. Antes de citarla en
> la tesis hay que contrastarla con bibliografía, por ejemplo G. F. Knoll,
> *Radiation Detection and Measurement*, en los capítulos de electrónica de
> pulsos y de coincidencias.

## 2. Qué hay hoy en el `mt` y qué falta

El multitrigger ya combina disparos de dos maneras, pero ninguna sirve para esto:

- **OR por canal** ([`mt_trig_src.sv`](../../modulos/mt/rtl/mt_trig_src.sv)). Es
  una máscara de 25 fuentes (bits 0–24, con 25–31 reservados) donde cualquiera
  dispara. Las fuentes se combinan en `trigger_event = |adc_trig`
  ([`mt_event_logic.v:139`](../../modulos/mt/rtl/mt_event_logic.v#L139)).
- **Escudo** ([`trigger_shield.sv`](../../modulos/mt/rtl/trigger_shield.sv)).
  Una fuente arranca **un** contador global de `dur` ciclos, que inhibe y
  después re-arma canales de destino y da un **nivel** de veto al MCA. Ese veto
  solo impide *abrir* un pulso: no rechaza un pulso ya abierto cuyo veto llega
  después.

Ninguno puede expresar "A **y** B dentro de W" ni "A **sin** B dentro de W".

### Por qué no conviene un "modo coincidencia" dentro del escudo

| | escudo | coincidencia |
|---|---|---|
| estado | **un** contador global | **un estirador por fuente** |
| salida | control: re-arm por canal y nivel de veto | un **evento** nuevo, es decir, una fuente de disparo |
| quién la consume | `mt_trig_src` (disable) y el MCA (veto) | la máscara OR, como cualquier otra fuente |

Meterlos en un mismo bloque con un `case (mode)` daría ramas que no comparten
ni el estado ni las salidas. La propuesta es un **módulo hermano**,
`mt_coinc.sv`, instanciado al lado de `i_shield` y alimentado con el mismo
vector de fuentes. El escudo queda como está.

## 3. Diseño propuesto

### Registros (slot 3, a partir de `0x090`, hoy libre)

| Offset | Campo | Significado |
|---|---|---|
| `0x090` | `COINC_REQ` | máscara de fuentes **requeridas** |
| `0x094` | `COINC_ANTI` | máscara de fuentes **prohibidas** (veto) |
| `0x098` | `COINC_CFG` `{M, W}` | mayoría M y ventana W en ciclos de `adc_clk` (8 ns) |

Las fuentes serían las mismas que ya ve el escudo: los disparos por canal
(`adc_trig_p/n` y `slope_p/n`) y la entrada externa (`ext_p`, `ext_n`,
`ext_lvl`).

### Regla, sin modos

```
evento = popcount(estirado & COINC_REQ) >= M   &&   !(estirado_anti & COINC_ANTI)
```

| caso | `REQ` | `ANTI` | `M` |
|---|---|---|---|
| coincidencia total A·B·C | A,B,C | — | 3 |
| mayoría 2 de 3 | A,B,C | — | 2 |
| anticoincidencia (Compton) | principal | blindaje | 1 |
| combinada: A·B y no C | A,B | C | 2 |

Una anticoincidencia **pura** ("que no haya pasado nada") no produce ningún
evento: siempre hace falta una referencia en `REQ` que diga *cuándo* mirar.

### Salida

El evento sale como **bit 25** de la máscara OR de `mt_trig_src`. Es el mismo
patrón con el que `mt_slope_trig` agregó los bits 17–24. También queda en el
bit 25 del snapshot. Así la coincidencia dispara la captura del scope y del
`event_ring` sin tocar `rp_bram_sm`.

## 4. Las dos decisiones de tiempo

Estas decisiones no cambian el costo, pero sí el comportamiento.

**¿Cuándo sale el evento?**

- **Al cumplirse.** El evento sale cuando llega el último pulso requerido. Es la
  coincidencia por solapamiento clásica: cada entrada se estira a W y la salida
  aparece cuando los pulsos estirados empiezan a solaparse. La latencia varía
  entre 0 y W según el orden de llegada, así que la posición del trigger dentro
  del buffer **baila** hasta W muestras.
- **A latencia fija.** El evento sale siempre W ciclos después del primer pulso,
  como un *strobe* retardado. El trigger cae siempre en la misma posición, y el
  pretrigger (`set_dly`, o la ventana *pre* del `event_ring`) solo tiene que
  cubrir W.

**La anticoincidencia tiene que mirar hacia adelante.** Si el blindaje dispara
50 ns *después* del pulso principal, el evento igual se debe rechazar. Por eso el
veredicto sale a W del pulso de referencia, y el veto se estira 2W para cubrir
[t−W, t+W]. Con la opción de latencia fija esto sale gratis. Con la opción
"al cumplirse" la anticoincidencia solo ve hacia atrás.

Para la captura, la opción de **latencia fija** es la más razonable.

## 5. Costo estimado

El hardware es un estirador (un contador de W bits) por fuente, un popcount, un
comparador y tres registros. Con ~10 fuentes y W de 10 bits, el orden es de
**~100 FF y ~150–200 LUT**, frente a los 17.6 k LUT del Z7010.

> Es una **estimación**, no una medición: hay que confirmarla con
> `make -C modulos/mt/work syn` (OOC) una vez escrito el RTL.

## 6. Lo caro: usarlo para el MCA

El caso de uso más común con MCA es filtrar el espectro: solo eventos en
coincidencia, o supresión Compton. Para eso **no** sirve conectar la coincidencia
como trigger externo del MCA (`cfg_trig_src = 1`). Ese camino ya llega tarde y
trunca el pulso, como documenta
[`mca_pulse_feature.sv:71-80`](../../modulos/mca/rtl/mca_pulse_feature.sv#L71-L80),
y la latencia W lo empeora.

Lo correcto es que el MCA siga abriendo con su propio Schmitt y que la
coincidencia actúe como **compuerta al confirmar el evento**: aceptar o rechazar
cuando el pulso cierra, con W menor que la ventana de integración. Eso toca
`mca_pulse_feature` / `mca_top` y es la parte de verdadero trabajo.

## 7. Camino recomendado cuando haya montaje

1. **Primero offline.** El `event_ring` ya graba ventanas multicanal con su
   posición temporal. Con eso se puede hacer la coincidencia en software,
   barriendo W, y ver si el espectro mejora antes de gastar en hardware.
2. **Medir las accidentales.** Para dos fuentes independientes de tasas R1 y
   R2, la tasa de coincidencias casuales es aproximadamente

   ```
   R_acc ≈ 2 · W · R1 · R2
   ```

   Barrer W y verificar la pendiente es una buena validación, y también una
   figura para el capítulo.
3. **Solo si rinde, bajarlo a hardware:**
   1. `modulos/mt/rtl/mt_coinc.sv`: estiradores, popcount ≥ M, veto, latencia
      fija W, salida de 1 ciclo y contadores de debug (`n_coinc`, `n_anti`).
   2. `mt_event_logic.v`: instanciarlo junto a `i_shield` y cablear la salida a
      `trg_src_bits[25]` y al snapshot.
   3. `mt_cfg.sv`: registros `0x090`–`0x098` con su lectura.
   4. `modulos/mt/sim/tb_mt_coinc.sv`, con el estilo de `tb_trigger_shield.sv`.
      Casos: A·B dentro y fuera de W, M de N, veto antes y después de la
      referencia, W=0.
   5. Docs: este mapa de registros, la prosa del datasheet y una figura de
      ondas (con [`ondas.py`](../figuras/ondas.py)).
   6. API: `coinc_configure(req, anti, M, W)` en
      [`multitrigger.py`](../../software/API/multitrigger.py).
   7. Fase aparte: la compuerta de confirmación en el MCA (§6).

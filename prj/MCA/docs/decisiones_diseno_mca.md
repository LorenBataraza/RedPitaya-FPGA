# Decisiones de diseño del Analizador Multicanal (MCA)

Documento de por qué el MCA quedó como quedó. El **qué** está en
[`register_map_mca.md`](register_map_mca.md) (mapa de registros) y en el RTL;
acá va el **por qué**, incluidas las alternativas que se descartaron y las que
se probaron y fallaron.

Estado: bitstream `prj/MCA/out/mca_red_pitaya.bit` construido y simulado;
**sin validar en hardware todavía**.

---

## 1. Motivación

El scope multitrigger ya detectaba pulsos y congelaba ventanas en BRAM, pero
**todo el análisis era offline en NumPy** (`pulses_from_buffer`,
`pulse_metrics`). Eso ata la tasa de eventos al costo de leer 16384 muestras por
evento a través del bus de registros, que además cruza un CDC por acceso.

El MCA mueve la estadística al FPGA: el ARM lee **espectros ya formados** en vez
de formas de onda. Acumula dos indicadores:

1. **Espectro 1D de amplitud de pulso** — el MCA clásico.
2. **Mapa 2D amplitud × factor de forma** (PSD = `Q_cola / Q_total`) — para
   discriminación por forma de pulso.

---

## 2. Qué parámetros hay que caracterizar en un MCA

Esta tabla es la que determinó qué contadores expone el hardware. Sin ellos, la
mitad de las mediciones no se puede hacer.

### Eje de amplitud

| Parámetro | Qué es | Cómo se mide |
|---|---|---|
| **Ganancia de conversión** | Canales por volt (o por keV). | Barrido de amplitud; ajuste lineal del centroide. |
| **No linealidad integral (INL)** | Desviación del centroide respecto de la recta ideal, en % de fondo de escala. Buenos MCA: <±0.05% FS. | Residuo del ajuste lineal. |
| **No linealidad diferencial (DNL)** | Variación del *ancho* de canal. Un canal más ancho acumula más cuentas y deforma los picos. Spec típica <±1%. | *Sliding pulser*: amplitud uniformemente aleatoria, que debería llenar todos los canales por igual. |
| **Offset de cero** | Canal donde cae energía cero. | Extrapolación del ajuste. |
| **Deriva** | Corrimiento del centroide con tiempo y temperatura. | Adquisiciones repetidas durante horas. |

> La DNL del *binning digital* es exactamente cero por construcción: el bin es un
> desplazamiento a la derecha de un entero, así que todos los canales tienen
> idéntico ancho. Lo que la medición de DNL caracteriza es el **ADC y el
> estimador de amplitud**, que es justamente lo interesante.

### Resolución

| Parámetro | Qué es |
|---|---|
| **Contribución de ruido electrónico** | El FWHM del pico de un pulser ideal *es* el ensanchamiento que agrega la cadena. Se resta en cuadratura del FWHM total para separar detector de electrónica. |
| **Ensanchamiento por jitter de muestreo** | Ver §5. Se mide comparando los dos estimadores de amplitud sobre el mismo estímulo. |

### Comportamiento con la tasa

| Parámetro | Registro que lo habilita |
|---|---|
| Tiempo muerto por evento | `deadtime` / `cnt_total` |
| Modelo (paralizable vs no paralizable) | curva `cnt_accepted` vs tasa incidente |
| Curva de throughput | ídem |
| Resolución par-pulso | `cnt_pileup` + barrido del gap |
| Exactitud del live time | `livetime` vs `realtime` |
| Corrimiento del pico con la tasa | centroide vs frecuencia |

### Umbral

| Parámetro | Qué es |
|---|---|
| **LLD y piso de ruido** | Umbral mínimo utilizable sin disparar con ruido. |
| **Curva S de eficiencia** | Fracción detectada vs amplitud; el 50% define el umbral efectivo. |

### Discriminación por forma

| Parámetro | Qué es |
|---|---|
| **Figure of Merit** | `FOM = \|c₁ − c₂\| / (FWHM₁ + FWHM₂)` sobre la proyección del eje de forma. FOM > 1.27 es buena separación. |
| **FOM vs energía** | La separación se degrada a baja amplitud; se calcula por rebanadas del eje de amplitud. |

**Consecuencia de diseño:** el hardware expone `cnt_total`, `cnt_accepted`,
`cnt_rej_amp`, `cnt_rej_psd`, `cnt_pileup`, `cnt_dropped` y tres relojes de
64 bits (`realtime`, `livetime`, `deadtime`).

---

## 3. Dónde conectarlo: bus de sistema, slot 7

**Decisión: slot 7 del bus personalizado, base `0x4070_0000`.**

No había alternativa real:

- **`M_AXI_GP0` *es* ese bus** (`red_pitaya_ps.sv:404-416` → `axi4_slave` →
  `ps_sys` → el interconnect de 8 slots). No es un puerto libre.
- **`M_AXI_GP1` ya lo consume el XADC** dentro del block design
  (`prj/MCA/ip/systemZ10.tcl:849-850`, mapeado en `0x83C0_0000`) y ni siquiera
  sale al top level.
- **Los 4 puertos AXI-HP están tomados**: HP0/HP1 por el scope, HP2/HP3 por el
  ASG.

El interconnect decodifica `bus.addr[22:20]`
(`rtl/sys_bus_interconnect.sv:50-51`) → 8 slots de 1 MB desde `0x4000_0000`. Los
slots 6 y 7 estaban libres (`sys_bus_stub`).

**Por qué el 7 y no el 6:** el stub del slot 6 vive dentro de un
`` `ifdef Z20_G2 / `else `` (`red_pitaya_top.sv:705-751`), así que el MCA
desaparecería silenciosamente en esa variante. El del slot 7 es una línea
incondicional. Además el XDC ya trae las 32 restricciones CDC de
`for_bus[0..7]`, así que el slot 7 queda constrained sin tocar nada.

**Latencia:** cada acceso cruza `sys_bus_cdc` (~8-12 ciclos ida y vuelta). Es la
misma penalidad que paga el scope hoy, y una conexión GP directa no sería más
rápida. Irrelevante acá: leer un espectro una vez por segundo no es cuello de
botella — a diferencia de leer 16k muestras por evento, que era el problema
original.

---

## 4. Presupuesto de memoria

**Unidad de cuenta:** un RAMB36 son 36 Kb configurables como 1024×36, o sea
**1024 bins de 32 bits = 4 KB**. Toda la aritmética de dimensionamiento sale de
ahí.

**Ancho de contador: 32 bits.** A 100 kcps concentrados en un pico, saturar un
bin lleva ~12 horas. Con 18 bits serían 44 minutos: no vale la pena ahorrar.
Los contadores **saturan**, no envuelven.

### Configuración instanciada

| Motor | Parámetros | Bins | RAMB36 |
|---|---|---|---|
| Espectro 1D | `H_AW = 14` | 16384 | 16 |
| Amplitud × forma | `H2_AW = 7`, `PSD_AW = 6` | 128 × 64 | 8 |
| | | **Total MCA** | **24** |

Utilización final del bitstream: **40/60 RAMB36 (67%)**, 33% LUT, 58% slices.

### Justificación de los tamaños

- **16384 canales en el 1D**: sólo se justifica con el estimador de integral
  (§5). Con la muestra de pico, el ruido de una sola muestra hace que todo lo
  que pase de ~4096 canales sea sobremuestrear ruido.
- **64 bins en el eje de forma**: un gráfico PSD sirve para **separar
  poblaciones**, no para resolver. 64 bins dan 1.56% de resolución en
  `Q_cola/Q_total`, contra separaciones típicas del 10-20%.
- **128 bins de amplitud en el 2D**: grueso a propósito. Con `H2_AW = 12` el
  mapa sería 2^18 bins = **256 RAMB36**, imposible. El detalle en amplitud vive
  en el espectro 1D; el eje del 2D es un rebineado configurable
  (`cfg_h2_shift`).

### Lo que liberó espacio

Sacar el ASG del top del MCA liberó ~17 RAMB36 (dos tablas de onda de 16384×14b
más los FIFOs). Sin eso, los dos indicadores no entraban juntos y habría hecho
falta elegir uno.

**Si 40/60 llegara a ser poco**, sacar el ASG además libera HP2/HP3, con lo que
acumular en DDR por AXI-HP pasa a ser viable. Es un motor DMA aparte y quedó
fuera de alcance, pero la puerta está abierta.

---

## 5. El estimador de amplitud — la decisión más importante

**Más bins no dan más precisión por sí solos.** Lo que la da es cómo se estima
la amplitud, y por eso el registro `cfg_amp_src` existe.

- **Muestra de pico** (`cfg_amp_src = 0`): la amplitud sale de *una* muestra, o
  sea arrastra el ruido completo del ADC. Peor: el muestreo casi nunca cae en el
  máximo verdadero, y esa subestimación variable **ensancha el fotopico** por
  razones puramente instrumentales. A 125 MSPS con subida de 100 ns hay ~12
  muestras en el flanco y el error es chico; con subida de 20 ns hay 2.5 y es
  severo.
- **Integral de carga** (`cfg_amp_src = 1`, `Q_total >> cfg_q_shift`): el ruido
  blanco promedia como σ/√N y desaparece el jitter de muestreo. Es lo que hace
  cualquier MCA digital serio. Con N = 256 muestras, `Q_total` tiene ~21 bits
  significativos: **ahí sí** los 16384 canales están justificados.

Poder alternar entre los dos **en el mismo bitstream** no es un lujo: *es* el
experimento que mide la contribución de jitter de muestreo
(`compare_estimators()` en `testbench_mca.py` lo barre contra el tiempo de
subida).

> **Fuera de alcance, pero es el paso siguiente natural:** el conformado
> trapezoidal (Jordanov-Knoll) es el estándar real para espectroscopía de alta
> resolución — corrige el déficit balístico y el corrimiento de línea de base a
> alta tasa. Conviene medir primero cuánto rinde la integral simple.

---

## 6. Arquitectura RTL

Cuatro módulos en [`prj/MCA/rtl/mine/mca/`](../rtl/mine/mca/), todos en el
dominio `adc_clk`. El cruce a `clk_fpga_0` lo hace `sys_bus_cdc` por slot, así
que no hay CDC propio.

### `mca_hist.sv` — motor de histograma genérico

Una sola implementación, instanciada N veces. Memoria inferida **simple dual
port**: puerto A sólo escritura, puerto B sólo lectura.

**Por qué no un read-modify-write de 3 estados** (como el `axis_histogram.v` de
pavel-demin que estaba en el repo): un puerto de BRAM tiene UNA dirección por
ciclo, así que no puede leer `addr(n)` y escribir `addr(n-2)` a la vez. Con la
lectura en el puerto B y la escritura en el A se consigue **1 incremento por
ciclo**; el de 3 estados acepta 1 evento cada 3 y obligaría a decimar un futuro
mapa de persistencia.

**Forwarding de 2 etapas**: el evento que lee en el ciclo *m* tiene su dato en
*m+1* y escribe en *m+2*. Un evento a la misma dirección en *m+1* o *m+2* leería
un valor viejo, así que hay que puentear la escritura en vuelo (distancia 1) y
la del ciclo anterior (distancia 2). A distancia ≥3 la memoria ya está
actualizada.

**El barrido de borrado usa sólo el puerto de escritura**, así que el de lectura
queda vivo durante todo el barrido. Es un requisito duro: un barrido de 16384
bins son 131 µs, ~500 veces el timeout de 32 ciclos de `rtl/axi4_slave.sv:193`.
Si frenara el ack, el bus se colgaría.

### `mca_pulse_feature.sv` — segmentador y extractor

Emite **un registro de evento coherente** `{amp, psd}` por pulso. Que salga de
un único registro es lo que garantiza que el espectro 1D y el mapa 2D cuenten
exactamente los mismos pulsos.

- **Línea de base**: seguidor IIR `bl_acc += x − (bl_acc >> k)` con acumulador
  ancho. Con la forma ingenua `bl += (x−bl)>>k` el incremento se cuantiza a cero
  cuando `|x−bl| < 2^k` y el seguidor se congela. Se congela durante el pulso
  **y durante `cfg_bl_holdoff` muestras después**: si se descongelara al cruzar
  la histéresis hacia abajo, agarraría el undershoot de la cola y arrastraría la
  base hacia el lado equivocado.
- **Segmentación**: Schmitt igual que `rp_adc_trig.v`, para que los umbrales del
  MCA y del scope sean comparables.
- **Pico con comparación estricta (`>`)**: en un techo plano con ruido gana la
  *primera* ocurrencia. Con `>=` el instante de pico se correría hasta el final
  de la meseta.
- **Apilamiento**: si la ventana llega a `cfg_maxlen`, el evento se cuenta en
  `cnt_pileup` pero **no** se histogramea — su integral y su pico están
  contaminados por el segundo pulso.
- **Cargas**: cada muestra se satura a ≥ 0 antes de acumular. Sin eso, una cola
  con undershoot resta de `Q_total` mientras `Q_cola` sigue sumando, y se llega
  a `Q_cola > Q_total`, que rompe la premisa del divisor.

### `mca_div_restore.sv` — el divisor del factor de forma

Calcula `q = floor(Q_cola · 2^PSD_AW / Q_total)`.

**El truco**: como `Q_cola < Q_total`, arrancando con `rem = Q_cola` y haciendo
`rem = 2·rem; if (rem >= Q_total) { rem -= Q_total; q |= 1; }` se obtiene un bit
de cociente por iteración. Hacen falta **exactamente `PSD_AW` iteraciones sin
importar el ancho de los operandos**, y no hace falta normalizar previamente.
Con `PSD_AW = 6` son 6 ciclos y **cero DSP**.

Latencia **fija** de `PSD_AW` ciclos incluso en los casos de error: es
deliberado, hace predecible el tiempo muerto por evento (uno de los parámetros
a caracterizar).

Tres casos borde que rompen si no se tratan, y que el testbench barre
exhaustivamente (32640 combinaciones):

| Caso | Sin la guarda | Con la guarda |
|---|---|---|
| `Q_total == 0` | `rem >= 0` siempre true → cociente todo unos → **todos esos eventos al bin superior** | `err_o`, evento rechazado y contado |
| `Q_cola == Q_total` | cociente `2^PSD_AW`, no entra en `PSD_AW` bits y **envuelve a 0** → evento al extremo *opuesto* del eje | satura a `2^PSD_AW − 1` |
| `Q_cola == 0` | — | `q = 0`, resultado válido |

### `mca_top.sv` — esclavo de bus

Instanciación condicional por parámetro (`EN_HIST_H`, `EN_HIST_H_PSD`), con la
rama `else` alimentando `32'h0` al mux de lectura. El RTL deja lugar para dos
motores más que quedaron apagados por defecto: **amplitud × tiempo de subida** y
**mapa de persistencia** (amplitud × tiempo dentro del pulso). Agregarlos es
cambiar un parámetro, no reescribir.

---

## 7. El idioma del esclavo de bus (y el bug que evita)

**Ack de latencia fija a los 4 ciclos para *cualquier* dirección**, desde un
shift register incondicional. **No existe ninguna ruta de ack por motor.**

Esto es deliberado y no cosmético. Un esclavo que no hace ack **no produce sólo
una lectura mala: deja el CDC del slot desincronizado** — `reg_done` sólo avanza
con `bus_m.ack`, así que sin ack el handshake queda trabado y ese slot no acepta
más transacciones. Al ARM lo rescata el timeout de 32 ciclos de
`rtl/axi4_slave.sv:193`, pero la lectura devuelve un valor sin sentido y sin
ninguna indicación de error. El mecanismo completo está en
[`bus_sistema_redpitaya.md`](bus_sistema_redpitaya.md) §7.1.

El scope tiene un bug latente exactamente de esa clase: ata
`bram_ack[2]/[3] = 0` para los canales no construidos
(`rp_scope_multitrigger_com.sv:572-573`) y `multitrigger_rp_scope_cfg.sv:506-507`
lo usa como ack de las aperturas de los canales 2 y 3. Cualquier lectura en
`0x4013_0000`–`0x4014_FFFF` dispara el escenario. No está activo hoy sólo porque
el driver mapea `SCOPE_SIZE = 0x30000` y nunca llega ahí.

En el MCA, un motor apagado por parámetro simplemente devuelve 0 en su apertura;
no hay forma de colgar el bus.

`tb_mca_top.sv` es la regresión contra eso: un BFM que imita a `sys_bus_cdc`
(sostiene `wen`/`ren` hasta el ack) y **falla el test si el ack no llega en ≤20
ciclos**, barriendo registros, huecos, aperturas, offsets fuera de rango,
motores apagados y direcciones no mapeadas — con dos DUT de parámetros
distintos.

Otras dos cosas que impone el entorno:

- **Estrobo de escritura de un ciclo.** `sys_bus_cdc` sostiene `wen` hasta el
  ack (~5 ciclos); sin estrobo, cada transacción ejecutaría el `case` 5 veces y
  `clear` quedaría activo 5 ciclos en vez de uno.
- **`sys_rdata` tiene que ser un registro plano.** El XDC trae un
  `set_false_path` sobre `inst_sys_bus_cdc/reg_rdata*`, pero `sys_bus_cdc.sv` no
  tiene ese registro (hace un `assign`), así que la restricción **no engancha
  nada** y el cruce de datos de lectura se timea de verdad, con 0.94 ns de
  margen. Nada de lógica combinacional ancha ahí.

---

## 8. El ecualizador `osc_filter`: qué se intentó y por qué se abandonó

Ésta es la parte que más tiempo llevó y la que más vale documentar.

### El problema

El diseño **ya no cerraba timing antes de tocar nada**: WNS −1.820 ns, 221
endpoints en falla. De ésos, **137 (62%) estaban en las dos instancias de
`osc_filter`, y se llevaban toda la severidad** (−1.820 y −1.672 ns; el resto no
pasaba de −0.2 ns).

El camino crítico es el lazo IIR (`osc_filter.v:129-141`):

```
aa_mult = r3_reg_dsp1 * coeff_aa;
r3_sum  = (r2_reg <<< 23) + (r3_reg_dsp2 <<< 25) - aa_mult;
r3_reg_dsp1 <= r3_sum >>> 25;
```

Registro → multiplicador DSP → suma de 48 bits → vuelta al registro, **todo en
un ciclo**: 15 niveles de lógica (12 CARRY4 + 1 DSP), **9.421 ns contra 8 ns de
período**, con el 70% del retardo en lógica y sólo 30% en ruteo.

### El malentendido que hubo que aclarar

La señal **no** "pasa de largo" el filtro cuando no está configurado. Son dos
cosas distintas:

1. `set_filt_byp` (registro 0x98) **resetea a `4'h0`**
   (`multitrigger_rp_scope_cfg.sv:317`): por defecto `adc_dec_in = adc_filtered`,
   o sea los datos **sí** atraviesan el filtro.
2. La respuesta unitaria con los coeficientes por defecto es un **resultado
   matemático, no un bypass**: con `bb=0` la primera etapa queda como derivador
   y con `aa=0` la segunda como integrador, y se cancelan. Pero la señal recorre
   físicamente todas las etapas en cada muestra.

Y los endpoints en falla dentro del filtro **no son sólo los del `aa_mult`**:
incluyen `r5_reg_*` (el registro de **salida**) y `pp_mult_*`, que están activos
con cualquier configuración porque `kk = 0xFFFFFF ≠ 0`. O sea que **aplica
siempre**.

### Los dos intentos de rediseño, y por qué fallaron

Ambos verificados **bit a bit** contra una copia congelada del original
(`prj/MCA/sim/osc_filter_ref.v` + `tb_osc_filter.sv`, 10 casos: coeficientes por
defecto, extremos de `aa`/`pp`/`kk`, todos al máximo, 12 juegos aleatorios).

| Intento | Idea | Resultado |
|---|---|---|
| Original | — | −1.820 ns / 221 endpoints |
| **1** | Identidad `(y<<<25) − y·aa ≡ y·(2^25 − aa)`, para dejar un solo `P = C + A·B` | **−3.514 ns**: el coeficiente pasa a 27 bits, el multiplicador de 23×27 no entra en un DSP48E1 y Vivado lo parte en **dos DSP en cascada dentro del lazo**, más lento que la cadena de acarreo que eliminaba |
| **2** | Reasociar: `p = (r2<<<23) − aa_mult` en el DSP y `+ (y<<<25)` en fabric | **−1.957 ns**: sigue quedando un sumador en el lazo |

También se probó un `set_multicycle_path` con re-implementación completa:
−1.820 → −1.160. **No sirve**: el lazo es genuinamente de un ciclo y no se puede
relajar; el registro de coeficiente aparecía como origen sólo por atribución.

**Conclusión: es una limitación estructural, no de codificación.** Un IIR de un
polo con coeficiente general necesita multiplicación + suma en un ciclo, y a
125 MHz en un `-1` eso es marginal por diseño.

### La decisión

**El MCA no instancia el filtro.** Parámetro `EN_FILT` en
`rp_scope_multitrigger_com`, con **default 1** para que el bitstream del scope
no cambie de comportamiento; el top del MCA lo pone en 0.

Motivos:

- Elimina los 137 endpoints severos del build del MCA y libera DSP.
- Para espectroscopía el ecualizador de respuesta del ADC no hace falta.
- Con los coeficientes de reset era pass-through de todos modos.
- **Cero riesgo sobre el diseño que ya funciona**: un rediseño con desenrollado
  del lazo (look-ahead) sí cerraría, pero cambia el redondeo, y con un polo en
  ~0.996 (Q≈250, prácticamente un integrador) los errores de redondeo **se
  acumulan** en vez de promediarse. Validar eso exige medir la respuesta en
  frecuencia en la placa.

**Queda pendiente**: el bitstream del scope sigue con su WNS de −1.820 ns
preexistente. Mitigación gratis mientras tanto: escribir `0x98 = 0x3` hace que
el mux tome la señal pre-filtro, con lo que nadie consume la salida del filtro.

---

## 9. Cómo se construye

`red_pitaya_vivado_Z10.tcl` lo usan **los 18 proyectos de `prj/`** y es un
archivo de upstream que sigue recibiendo cambios, así que **no se toca**. En su
lugar hay una copia, [`red_pitaya_vivado_Z10_mca.tcl`](../../../red_pitaya_vivado_Z10_mca.tcl),
con **cinco diferencias** de una línea:

| # | Cambio | Por qué |
|---|---|---|
| 1 | `synth_design -top mca_red_pitaya_top` | el top nuevo |
| 2-3 | `write_bitstream` → `mca_red_pitaya.bit` / `.bin` | que no pise los artefactos del scope |
| 4 | `write_sysdef -bitfile/-file` → `mca_red_pitaya.*` | el original referencia el `.bit` **por nombre**: sin este cambio apunta a un archivo inexistente |
| 5 | `add_files` de `sdc/red_pitaya_mca.xdc` | restricciones propias del MCA |

```bash
vivado -nojournal -mode batch -source red_pitaya_vivado_Z10_mca.tcl -tclargs MCA
```

**No hace falta regenerar FSBL ni device tree**: ambos salen de la configuración
del PS7 (`ip/systemZ10.tcl`), que es la misma en los dos tops.

El encabezado de la copia documenta de qué commit salió, para que
re-sincronizar ante un cambio de upstream sea mecánico.

### El top del MCA

[`mca_red_pitaya_top.sv`](../rtl/mine/mca_red_pitaya_top.sv) es una copia de
`red_pitaya_top.sv` con cuatro diferencias: `mca_top` en el slot 7, `i_scope`
con `EN_FILT(0)`, y **sin ASG (slot 2) ni PID (slot 3)**.

Conserva a propósito la lista de puertos y los nombres de instancia `i_ams` y
`sys_bus_interconnect`, **porque el XDC engancha por esos nombres**
(`sdc/red_pitaya.xdc:1` para el LOC del XADC, y las 32 restricciones CDC de
`for_bus[0..7]`).

Lo que se pierde al sacar el ASG: las salidas del DAC quedan mudas y desaparece
`trig_asg_out`, o sea las fuentes de disparo `BIT_ASG_P`/`BIT_ASG_N` del OR-mask
del scope. Con el estímulo migrado al Rigol DG4162 por USB, no molesta.

---

## 10. Bugs encontrados por los testbenches

Cuatro de diseño, todos corregidos. Se documentan porque son la justificación de
haber escrito los testbenches antes de sintetizar.

1. **La línea de base absorbía la primera muestra de cada pulso.** `st` todavía
   vale `S_IDLE` en el flanco en que se abre el pulso, así que el IIR se comía la
   muestra del flanco de subida. A tasa alta eso arrastra la base hacia arriba de
   forma sistemática y **corre el centroide de todo el espectro**.
2. **El re-armado Schmitt sólo ocurría en `S_IDLE`.** Si la señal volvía a la
   base durante los 6 ciclos del divisor y subía otra vez, el pulso se perdía
   **en silencio**, sin contarse ni siquiera en `cnt_lost_busy`.
3. **Abría a mitad del pulso siguiente** tras liberarse el divisor, midiendo una
   amplitud truncada que habría metido una **cola espuria de baja energía** en el
   espectro. Ahora se desarma si la señal cruza el umbral mientras el módulo está
   ocupado: se pierde el pulso entero pero se cuenta, que es un tiempo muerto
   medible y corregible.
4. **En `mca_hist`, el dato de lectura vivía un solo ciclo.** El puerto B vuelve
   a la dirección del pipeline de incremento apenas baja `rd_i`, y como el ack
   llega 4 ciclos después, **toda lectura devolvía el bin del último evento** en
   vez del pedido. El espectro entero se habría leído como un valor repetido.
   Se corrigió con un enable en el registro de salida.

Además, dos errores de *test* que vale la pena recordar: el BFM no esperaba a
que bajara el `ack` de la transacción anterior (muestreaba datos viejos), y el
estímulo inicial no armaba el Schmitt antes del primer pulso.

---

## 11. Evolución del timing

| Etapa | WNS | Endpoints |
|---|---|---|
| `red_pitaya_top` (referencia, con ASG y filtro) | −1.874 ns | 650 |
| MCA inicial | −0.674 | 266 |
| + línea de base y desplazador registrados | −0.313 | 106 |
| + multicycle en los registros de config | −0.260 | 60 |
| + registro de entrada en `mca_top` | **−0.114** | **14** |

De los 14 finales: **6 en `ps/system_i`** (el `axi_protocol_converter` del block
design de Xilinx, preexistente, peor −0.114) y **8 en `i_mca/i_feat`** (peor
−0.057 ns, 0.7% del período). **El peor camino del diseño ya no es del MCA.**

Dos aprendizajes concretos:

- El registro de entrada de `mca_top` fue el cambio de mayor impacto: cortaba el
  camino que venía desde el registro de salida de la calibración del scope y
  atravesaba el mux de canal, el decimador y toda la lógica de umbral. 34 de 60
  endpoints.
- **El parser de XDC de Vivado no soporta `if`**
  (`CRITICAL WARNING [Designutils 20-1307]`). Una guarda condicional anula la
  restricción **en silencio**: la primera versión de `red_pitaya_mca.xdc` no hizo
  nada y el timing no se movió.

### Sobre la restricción multicycle

Los registros de configuración del MCA los escribe el software y cambian a lo
sumo una vez por adquisición. El caso que la motiva es `cfg_q_shift`: alimenta un
barrel shifter de 32 bits seguido de los comparadores de la ventana de amplitud
y la lógica de control — 91 de 106 endpoints nacían ahí.

Es **legítima** acá, a diferencia del caso de `osc_filter`: allá el registro de
coeficiente aparecía como origen pero el camino real era el lazo **recursivo**
del IIR (que sí necesita cerrar en un ciclo). Acá el camino es genuinamente
cuasi-estático.

Única consecuencia: reconfigurar **en medio** de una adquisición puede dar
valores mezclados durante ~4 ciclos. `mca_utils.MCA.configure()` escribe con
`run = 0` y después arranca, así que no se da.

---

## 12. Software

Misma separación que ya existía entre `multitrigger_utils.py` (driver) y
`testbench_multitrigger.py` (mediciones):

- [`mca_utils.py`](../software/mca_utils.py) — `class MCA` (mmap de `/dev/mem`,
  `identify()`, `configure()`, `acquire()`) más helpers de análisis **puros**
  (`gauss_fit_peak`, `energy_calibration`, `dnl`, `fom`, `deadtime_fit`). Los
  helpers no tocan hardware a propósito: se validan contra `.npz` guardados, sin
  la placa. Están verificados contra datos sintéticos de parámetros conocidos.
- [`testbench_mca.py`](../software/testbench_mca.py) — nueve tests, uno por fila
  de la tabla de §2, con CLI y graficado.
- `rigol_dg4162.py` — se le agregó soporte de **forma de onda arbitraria**, sin
  el cual no se puede sintetizar un pulso de detector realista, ni las dos
  poblaciones con colas distintas que hacen falta para medir la FOM, ni el
  sliding pulser de la DNL. **Sigue la guía de programación de la serie DG4000
  pero no se pudo probar contra el instrumento**: usar con `check_errors=True`
  la primera vez.

Dos detalles heredados del driver del scope que hay que respetar:

- **Escrituras por asignación de slice, no `struct.pack_into`.** `pack_into`
  hace un `memset` previo que sobre memoria de dispositivo sale como stores de a
  byte; el esclavo AXI no los reconoce y el puente GP0 tira un *external abort* →
  SIGBUS.
- **Los contadores de 64 bits se leen palabra baja primero**: leer `lo` congela
  `hi` en un registro sombra del RTL. Al revés la lectura se parte.

---

## 13. Lo que queda abierto

1. **Validación en hardware.** Nada de esto se probó en la placa. Orden
   sugerido: verificar el magic → `single_peak` → `cross_check` (si el conteo
   cuadra con la tasa del generador, el camino de datos completo está validado).
2. **El soporte ARB del Rigol** no está probado contra el instrumento.
3. **El timing del bitstream del scope** sigue en −1.820 ns, con el filtro como
   causa. El MCA no lo arregla ni lo empeora de forma significativa.
4. **El build del scope no quedó bit-idéntico**: envolver `osc_filter` en un
   `generate if` agrega un nivel de jerarquía y con `-flatten_hierarchy none`
   eso mueve los límites de optimización (+22 LUT, WNS de −1.820 a −1.874).
   Funcionalmente idéntico.
5. **Conformado trapezoidal** como estimador de amplitud (§5).
6. **Los dos motores apagados**: amplitud × tiempo de subida, y mapa de
   persistencia. El RTL ya los contempla.
7. **Acumulación en DDR** por AXI-HP si 40/60 RAMB36 llegara a quedar corto.

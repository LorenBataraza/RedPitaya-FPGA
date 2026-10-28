# La plataforma: la familia Red Pitaya y lo que este proyecto usa de ella

Qué hay en una Red Pitaya, en qué se diferencian los modelos entre sí, y
—con mucho más detalle— qué partes de la placa toca el MCA y cómo. Es el
documento para leer antes de preguntarse "¿esto anda en la otra placa?" o
"¿por qué el ADC entrega esto?".

Está en dos mitades:

- **§1–§3** son la familia: tabla comparativa, la arquitectura común (Zynq,
  front-end, relojes, conectores, procesador, **las tres fronteras del SoC**),
  **el software que da el proyecto original de
  Red Pitaya** (§2.12) y cómo el repo nombra cada variante.
- **§4–§7** es **este proyecto**: la STEMlab 125-14 del banco, elemento por
  elemento, con los números del bitstream `Z10_2CH`, **el software que
  escribimos nosotros** (§4.8) y lo que habría que cambiar para llevarlo a otra
  placa.

El software está dividido en esas dos secciones a propósito: **§2.12 es lo que
viene de fábrica, §4.8 es lo que pusimos**, con la lista de qué tomamos y qué
descartamos de lo primero.

Los números de la familia salen de la documentación oficial (enlaces en §8); los
del proyecto salen del RTL, del XDC y de los reportes de Vivado que están en el
repo, y cada uno lleva su referencia. Si un número de acá no coincide con el
archivo al que apunta, el que manda es el archivo.

Documentos hermanos, para no duplicar:

| Documento | Qué contiene |
|---|---|
| [`movimiento_de_datos.md`](movimiento_de_datos.md) | el overlay sobre este diagrama: qué mueve, cuánta CPU cuesta y cuánto ajuste lleva cada conexión |
| [`adc_ltc2145.md`](adc_ltc2145.md) | el ADC solo, parámetro por parámetro, y los límites fijos que le pone al MCA |
| [`pinout_zynq.md`](pinout_zynq.md) | las 400 bolas del Zynq: qué es cada una y cuál usa la placa, pin por pin |
| [`TOP/bus_sistema_redpitaya.md`](TOP/bus_sistema_redpitaya.md) | el bus de registros GP0 → `sys_bus`, en detalle |
| [`TOP/register_map_top.md`](TOP/register_map_top.md) | el mapa de los 8 slots |
| [`puesta_en_marcha.md`](puesta_en_marcha.md) | el montaje del banco y el orden de arranque |
| [`mca/fuentes_de_jitter.md`](mca/fuentes_de_jitter.md) | el reloj y el ADC vistos desde la resolución temporal |
| [`ruido_del_sistema.md`](ruido_del_sistema.md) | cuánto ruido pone el front-end de §2.1, medido, y qué lo baja |
| [`mca/limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md) | qué limita al MCA en la práctica (y no es la placa) |

---

## 1. La familia

Todas las Red Pitaya son la misma idea: un **Zynq-7000** (ARM dual-core +
FPGA en el mismo chip), un ADC rápido de dos o cuatro canales cableado a la
FPGA, un DAC rápido, Ethernet y Linux en una microSD. Lo que cambia entre
modelos es el tamaño de la FPGA, el ADC, la RAM y los conectores.

### 1.1 Generación original (Gen 1)

| | STEMlab 125-10 | **STEMlab 125-14** | STEMlab 125-14 Z7020 | STEMlab 125-14 4-Input | SDRlab 122-16 | SIGNALlab 250-12 |
|---|---|---|---|---|---|---|
| SoC | Zynq 7010 | **Zynq 7010** | Zynq 7020 | Zynq 7020 | Zynq 7020 | Zynq 7020 (grado -3) |
| RAM DDR3 | 256 MB | **512 MB** | 512 MB | 512 MB | 512 MB | 1 GB |
| ADC | 2 × 10 bit | **2 × 14 bit** | 2 × 14 bit | **4 × 14 bit** | 2 × 16 bit | 2 × 12 bit |
| Tasa ADC | 125 MS/s | **125 MS/s** | 125 MS/s | 125 MS/s | 122.88 MS/s | 250 MS/s |
| Ancho de banda | DC–50 MHz | **DC–60 MHz** | DC–60 MHz | DC–60 MHz | 300 kHz–550 MHz (AC) | DC–60 MHz |
| Rango de entrada | ±1 V / ±20 V | **±1 V / ±20 V** | ±1 V / ±20 V | ±1 V / ±20 V | 0.5 Vpp (50 Ω) | ±1 V / ±20 V |
| DAC | 2 × 10 bit | **2 × 14 bit** | 2 × 14 bit | — | 2 × 14 bit | 2 × 14 bit |
| Tasa DAC | 125 MS/s | **125 MS/s** | 125 MS/s | — | 122.88 MS/s | 250 MS/s |
| GPIO (E1) | 16 | **16** | 22 | 22 | 22 | 19 |
| Ethernet | 1 Gbit | **1 Gbit** | 1 Gbit | 1 Gbit | 1 Gbit | 1 Gbit |
| USB | USB-A 2.0 | **USB-A 2.0** | USB-A 2.0 | USB-A 2.0 | USB-A 2.0 | 2 × USB-A 2.0 |
| Alimentación | 5 V, 1.5 A | **5 V, 2 A** | 5 V, 2 A | 5 V, 2 A | 5 V, 2 A | 24 V, 0.5 A |
| Temperatura | 0–55 °C | **0–55 °C** | 0–55 °C | 0–55 °C | 0–55 °C | 0–55 °C |

La columna en negrita es **la placa del banco** (§4). La 125-10 está
discontinuada; la 125-14 es la placa de referencia de toda la familia y la que
el repo upstream trata como caso base (`Z10`).

Tres diferencias que importan para un MCA y que la tabla esconde:

- **La SDRlab 122-16 está acoplada en AC** (300 kHz de corte inferior). Un
  pulso de detector con cola de decenas de µs sale diferenciado; el MCA tal como
  está —que integra carga en una ventana— no sirve ahí sin rehacer el
  acondicionamiento.
- **La 4-Input no tiene DAC.** Para este proyecto no importa (el ASG está
  eliminado del build, §4.4), pero el top es otro
  ([`rtl/red_pitaya_top_4ADC.sv`](../rtl/red_pitaya_top_4ADC.sv)).
- **La 250-12 tiene otro árbol de RTL** (`rtl_250/`, `ip_250/`, `sdc_250/`,
  `dts_250/` en la raíz): el ADC de 250 MS/s cambia la interfaz, y el Zynq es
  grado de velocidad -3 (`xc7z020clg400-3`).

### 1.2 Generación 2 (Gen 2)

Desde 2025 la 125-14 se vende en tres variantes nuevas. Mismo ADC/DAC, misma
tasa, pero front-end rediseñado, USB-C y —en la Pro Z7020— un tercer conector.

| | STEMlab 125-14 Gen 2 | STEMlab 125-14 Pro Gen 2 | STEMlab 125-14 Pro Z7020 Gen 2 |
|---|---|---|---|
| SoC | Zynq 7010 | Zynq 7010 | Zynq 7020 |
| RAM | 512 MB | 512 MB | 1 GB |
| ADC / DAC | 2 × 14 bit, 125 MS/s, DC–60 MHz | ídem | ídem |
| ADC | LTC2145-14 | LTC2145-14 | LTC2145-14 |
| DAC | AD9767 | AD9767 | AD9767 |
| E1 | 16 GPIO (8 pares) | 16 GPIO | **22 GPIO (11 pares)** |
| E2 | 4 ADC lentos, 4 DAC lentos, SPI/UART/I2C | ídem | ídem + **entrada de reloj ADC externo** (LVDS) |
| E3 | — | QSPI/eMMC externos, watchdog, control de alimentación | ídem + **8 pares LVDS a 2.5 V** |
| Sincronización | S1/S2 por USB-C (no estándar), hasta 500 Mb/s | ídem | ídem |
| USB | USB-C 2.0 (alimentación + consola) | USB-C 2.0 | USB-C 2.0 |
| Alimentación | 5 V, 3 A | 5 V, 3 A | 5 V, 3 A |
| Jitter de salida DAC | 20 ps rms @ 40 MHz | ídem | ídem |
| Dimensiones | 106.8 × 60.0 × 17.9 mm | ídem | ídem |

> **Falta en esta tabla**: en junio de 2025 Red Pitaya sacó con Texas
> Instruments dos placas más, la **STEMlab 125-14 TI** (ADC3664) y la **STEMlab
> 65-16 TI** (ADC3663), que cambian de proveedor de ADC y de tipo de interfaz
> (SLVDS serie en vez de CMOS paralelo) y son la variante `Z20_LL` del repo (§3).
> El censo completo de conversores por placa, con lo que cada uno cambiaría para
> el MCA, está en [`adc_ltc2145.md`](adc_ltc2145.md) §9.

Para el MCA lo relevante de la Gen 2 es (a) el **reloj de ADC externo** de la
Pro Z7020, que ataca directamente el límite que hoy ata la resolución del
instrumento —la deriva del oscilador, ver
[`mca/limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md)—, y
(b) que el repo ya la contempla como variante `Z20_G2` (§3), con una salvedad
en el mapa de slots (§4.3).

### 1.3 Los dos Zynq

El "7010 contra 7020" es la diferencia de fondo entre modelos: mismo ARM,
cuatro veces más FPGA.

| Recurso de la PL   | XC7Z010     | XC7Z020      | ×    |
| ------------------ | ----------- | ------------ | ---- |
| Celdas lógicas     | 28 k        | 85 k         | 3.0  |
| LUT6               | 17 600      | 53 200       | 3.0  |
| Flip-flops         | 35 200      | 106 400      | 3.0  |
| Block RAM (RAMB36) | 60 (2.1 Mb) | 140 (4.9 Mb) | 2.3  |
| DSP48E1            | 80          | 220          | 2.75 |
| PLL / MMCM         | 2 / 2       | 4 / 4        | 2    |

La otra diferencia, la que explica que la misma PCB acepte los dos chips, está en
el encapsulado: en `CLG400` el **7010 tiene 100 bolas de I/O del PL y el 7020
tiene 125**, y las 25 de diferencia son exactamente las que el 7010 deja sin
conectar — el banco 13, que en el 7010 está alimentado pero vacío. Ahí viven las
6 líneas extra de E1 (`DWE = 11` contra 8). El mapa de las 400 bolas, con lo que
usa esta placa, está en [`pinout_zynq.md`](pinout_zynq.md) — y dice dos cosas
más: **de las 100 del 7010 el diseño usa 99**, y la única libre (`R17`) es de
**1.8 V**, porque cae en el banco 34.

En los dos el PS es el mismo: **2 × ARM Cortex-A9 @ 667 MHz** (grado -1, el
núcleo en detalle en §2.6), NEON,
512 KB de L2, 256 KB de OCM, controlador DDR3 de 16 bit, Gigabit Ethernet,
USB 2.0 OTG, SD, QSPI, 2 × UART, 2 × I2C, 2 × SPI, 2 × CAN. El encapsulado es
el mismo (`CLG400`), por eso la placa cambia de chip sin cambiar de PCB.

El build del MCA está en **45.6 % de las LUT y 41.7 % de la BRAM de un 7010**
(§4.7). Pasar a un 7020 no es cuestión de espacio; es cuestión de qué se quiere
agregar (más instancias de MCA, ring en DDR, 4 canales).

---

## 2. Arquitectura común

Lo que sigue es la 125-14, que es la base. Las diferencias por modelo están
marcadas.

### 2.1 Front-end de adquisición

```
  IN1 ──┬─ jumper LV/HV ─ 1 MΩ ‖ 10 pF ─ atenuador ─ driver ─┐
        │                                                    │  LTC2145-14
  IN2 ──┴─ (ídem) ───────────────────────────────────────────┤  2 ch, 14 bit
                                                             │  125 MS/s
   oscilador 125 MHz ────────────────────────────────────────┤
                                                             │
                                  16 líneas LVCMOS18 / canal ▼
                                  + reloj diferencial        PL (Zynq)
```

|                          | Valor                                                                                         | Fuente                                                                                                                        |
| ------------------------ | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| ADC                      | Analog Devices (ex-Linear) **LTC2145-14**: dual, 14 bit, 125 MS/s, salida paralela CMOS 1.8 V | doc oficial; XDC (`LVCMOS18`)                                                                                                 |
| Rango a fondo de escala  | **±1 V** (jumper LV) o **±20 V** (jumper HV), por canal, DC                                   | doc oficial                                                                                                                   |
| Máximo absoluto          | ±6 V (LV) / ±30 V (HV)                                                                        | doc oficial                                                                                                                   |
| Impedancia de entrada    | 1 MΩ ‖ 10 pF                                                                                  | doc oficial                                                                                                                   |
| Ancho de banda           | DC–60 MHz (la doc vieja decía 50 MHz)                                                         | doc oficial                                                                                                                   |
| Resolución               | 2 V / 16384 = **122 µV por código en LV** ⇒ ≈ 8192 códigos por volt                           | derivado                                                                                                                      |
| SNR / jitter de apertura | **73.1 dBFS** · **0.08 ps rms** (⇒ 1.28 cuentas rms de ruido propio)                          | hoja de datos; desarrollado en [`adc_ltc2145.md`](adc_ltc2145.md) §3 y [`mca/fuentes_de_jitter.md`](mca/fuentes_de_jitter.md) |
| Codificación             | offset binary de **pendiente negativa**: el top la convierte a complemento a 2                | [`mca_red_pitaya_top.sv`](../rtl/mine/tops/mca_red_pitaya_top.sv), bloque *ADC IO*                                            |

Dos detalles de la interfaz que el RTL hereda de la placa:

- **Cada canal entra por 16 pines aunque el ADC tenga 14 bits.** Los dos bits
  bajos están reservados para la 122-16 (16 bit). El top toma
  `adc_dat_i[ch][15 -: ADW]` con `ADW = 14` en la 125-14 y `16` bajo
  `` `ifdef Z20_122 ``.
- **La pendiente es negativa**: un voltaje mayor da un código menor. Por eso el
  top hace `{raw[13], ~raw[12:0]}`: invierte los 13 bits bajos y deja el signo,
  lo que en un solo paso pasa de offset-binary-negativo a complemento a 2. Todo
  lo que está aguas abajo (scope, multitrigger, MCA) ve **signed 14 bit** —un
  entero, no un punto fijo: la escala a volts vive en el software. La
  derivación de esa línea, su tabla de verdad y el LSB que regala están en
  [`adc_ltc2145.md`](adc_ltc2145.md) §2.3.

El conversor en detalle —todos sus parámetros, y los límites fijos que le pone
al eje de amplitud, al eje de tiempo y al caudal de datos— está en
[`adc_ltc2145.md`](adc_ltc2145.md).

El ADC también recibe de la PL un `adc_cdcs_o` (*clock duty cycle stabilizer*,
fijo en 1) y hay una salida de reloj opcional `adc_clk_o` que en la 125-14 no
alimenta nada (el reloj va del oscilador al ADC y de ahí a la FPGA).

### 2.2 Front-end de generación

| | Valor | Fuente |
|---|---|---|
| DAC | Analog Devices **AD9767**: dual, 14 bit, 125 MS/s | doc oficial |
| Salida | ±1 V sobre 50 Ω (±2 V en alta impedancia), DC–60 MHz | doc oficial |
| Interfaz | **un solo bus de 14 bits entrelazado** para los dos canales (`dac_dat_o`), con `dac_sel_o` y `dac_wrt_o` al doble de la tasa | XDC + ODDRs del top |
| Nivel lógico | LVCMOS33 | XDC |

El entrelazado explica los relojes `dac_clk_1x` / `2x` / `2p` de §2.4: los datos
cambian a 125 MHz con canal A en un flanco y B en el otro (ODDR sobre
`dac_clk_1x`), la escritura se estroba a 250 MHz y el reloj hacia el DAC va
desfasado −45° para centrar el muestreo.

En este proyecto el DAC **está físicamente cableado pero no genera nada**
(§4.4).

### 2.3 Analógico lento: XADC y PWM

El Zynq trae un **XADC** de 12 bit, 1 MS/s, que la placa usa para dos cosas:

- **4 entradas analógicas lentas en E2** (AI0–AI3), vía divisores resistivos.
  La doc actual las especifica 0–7 V; la doc histórica de la Gen 1 decía
  0–3.5 V. 100 kS/s efectivos por canal. En el block design son los pares
  `VAUX0/1/8/9` más `VP/VN`
  ([`ip/systemZ10.tcl`](../ip/systemZ10.tcl), IP `xadc_wiz`, secuenciador
  apagado) y en el top los puertos `vinp_i[4:0]` / `vinn_i[4:0]`.
- **Telemetría interna**: temperatura del die, VCCINT, VCCAUX. Linux los expone
  por IIO gracias al overlay [`dts/pl_patch.dtsi`](../dts/pl_patch.dtsi)
  (`xlnx,axi-xadc`, canales 0, 1, 2, 9, 10). Es la temperatura que se usa en
  [`mca/sesion_placa_deriva.md`](mca/sesion_placa_deriva.md) para correlacionar
  la deriva del centroide.

Las **4 salidas analógicas lentas** (AO0–AO3, 0–1.8 V) no son DAC: son
**PWM/PDM** de la PL (`dac_pwm_o[3:0]`, LVCMOS18, pines T10/T11/P15/U13)
filtradas con RC en la placa. Las genera `red_pitaya_pdm` a partir de 4
registros de 8 bits en `red_pitaya_ams` (slot 4). Alrededor de 3.2 MS/s de
tasa de actualización según la doc.

### 2.4 Relojes

Hay **un solo oscilador de 125 MHz** en la placa y todo cuelga de él:

```
  XO 125 MHz ──► LTC2145 (muestreo) ──► adc_clk_i[1:0]  (DIFF_HSTL_I_18, pines U18/U19)
                                            │
                                         IBUFDS
                                            │
                                    PLLE2_ADV  (red_pitaya_pll.sv: ×8 / ÷n, VCO 1 GHz)
                                            │
        ┌──────────┬──────────┬─────────────┼──────────────┬────────────┐
     adc_clk   dac_clk_1x  dac_clk_2x   dac_clk_2p     ser_clk      pdm_clk
     125 MHz    125 MHz     250 MHz     250 MHz −45°   250 MHz      250 MHz
```

y por otro lado el PS genera **cuatro relojes de fábrica** desde su propia PLL
(configurados en `ip/systemZ10.tcl`, `PCW_FPGA*_PERIPHERAL_FREQMHZ`):

| `fclk[n]` | Frecuencia | Quién lo usa |
|---|---|---|
| 0 | **125 MHz** | el bus de registros (`ps_sys`), `red_pitaya_hk`, reset global `frstn[0]` |
| 1 | 250 MHz | puertos HP1 (declarado; sin uso en el MCA) |
| 2 | 50 MHz | — |
| 3 | 200 MHz | el subsistema del XADC: `M_AXI_GP1` → `xadc_wiz`, dentro del block design (§2.10.1). Es el camino de 7 ps de slack del que habla el script de build |

Consecuencia importante: **`adc_clk` y `fclk[0]` tienen la misma frecuencia
nominal pero son asincrónicos** (distinto oscilador, distinta PLL). Todo cruce
entre el bus de registros y el datapath pasa por un `sys_bus_cdc`
([`TOP/bus_sistema_redpitaya.md`](TOP/bus_sistema_redpitaya.md) §3). Y **el
reloj de muestreo es el reloj del datapath**: scope, multitrigger y MCA corren
a `adc_clk`, un ciclo = una muestra = 8 ns. Eso simplifica todo el RTL de
adquisición y es lo que hace que la deriva del XO se traduzca directamente en
deriva de tiempos del MCA.

Restricciones de reloj relevantes ([`sdc/red_pitaya.xdc`](../../../sdc/red_pitaya.xdc)):

```
create_clock -period 8.000 -name adc_clk [get_ports adc_clk_i[1]]
set_input_delay -clock adc_clk 3.400 [get_ports adc_dat_i[*][*]]
create_clock -period 4.000 -name rx_clk [get_ports daisy_p_i[1]]
```

El reset del datapath (`adc_rstn`) se libera 64 ciclos después de que la PLL
engancha (`RST_MAX = 64` en el top); si la PLL pierde el lock, todo el datapath
se resetea. El bit `pll_locked` es legible desde el slot 6
(`integration_cfg`).

### 2.5 Conectores de expansión
**E1 — digital** (2 × 13 pines, paso 2.54 mm, 3.3 V):

| Señal           | Puerto del top  | Pines Zynq (125-14)                    | Función alternativa                                                                      |
| --------------- | --------------- | -------------------------------------- | ---------------------------------------------------------------------------------------- |
| DIO0_P … DIO7_P | `exp_p_io[7:0]` | G17, H16, J18, K17, L14, L16, K16, M14 | `DIO0_P` = **trigger externo** (`trig_ext`) · `DIO6_P`/`DIO7_P` = CAN1/CAN0 RX           |
| DIO0_N … DIO7_N | `exp_n_io[7:0]` | G18, H17, H18, K18, L15, L17, J16, M15 | `DIO0_N` = **salida de trigger** (si `daisy_mode[1]`) · `DIO6_N`/`DIO7_N` = CAN1/CAN0 TX |
| +3.3 V × 2      | —               | —                                      | 0.5 A cada una                                                                           |

La dirección de cada línea la fija `red_pitaya_hk` (slot 0, registro `0x10`); en
reset todas son **entrada**. En la 7020 (`DWE = 11`) hay 22 líneas
(`DIO0..10`); en la 7010 (`DWE = 8`), 16.

El XDC les pone, además del estándar, dos propiedades del buffer de salida
([`sdc/red_pitaya.xdc`](../../../sdc/red_pitaya.xdc) líneas 141–144):

| Propiedad             | Qué es                                                                                         | Por qué ese valor                                                                                                                                                                                                                 |
| --------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `IOSTANDARD LVCMOS33` | niveles CMOS de 3.3 V (banco 35, alimentado a 3.3 V): `0` ≲ 0.8 V, `1` ≳ 2.0 V                 | es la tensión del conector; **ojo: una señal de 5 V daña el pin**                                                                                                                                                                 |
| `DRIVE 8`             | corriente nominal del driver: **8 mA por pin** manteniendo los niveles lógicos                 | suficiente para atacar la entrada de otro instrumento con unos pocos pF de cable sin degradar el flanco. Es un valor del medio del rango que admite LVCMOS33 (4/8/12/16 mA): los LEDs van a `DRIVE 4` y el PWM de E2 a `DRIVE 12` |
| `SLEW FAST`           | tiempo de transición del flanco: el más rápido que permite el banco (la alternativa es `SLOW`) | E1 es el conector de trigger y de daisy chain: lo que importa es el **jitter de propagación**, no el ruido                                                                                                                        |

Las dos sólo tienen efecto cuando la línea está configurada como **salida**; en
reset, con todo en entrada, son irrelevantes. Y `FAST` tiene su precio: flancos
más abruptos significan más `di/dt`, más overshoot y más acoplamiento a los
pines vecinos del mismo banco, así que un cable largo colgado de E1 y sin
terminar muestra ringing. Para este proyecto el compromiso es el correcto —la
única línea que se usa es el veto/trigger de `DIO0` (§4.6)— pero si alguna vez
se saca por E1 una señal lenta o de control, conviene bajarla a `SLEW SLOW`.

**E2 — analógico lento y comunicaciones** (2 × 13 pines, paso 2.54 mm, 3.3 V):

| Grupo                      | Señales              | De dónde salen                                                                                                                            | Nivel / rango                                                   | Estado en el MCA                          |
| -------------------------- | -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------- |
| Entradas analógicas lentas | AI0–AI3              | **XADC** del Zynq, pares `VAUX0/1/8/9` → `vinp_i[3:0]`/`vinn_i[3:0]` (pines B19/A20, C20/B20, E17/D18, E18/E19), vía divisores resistivos | 0–7 V (la doc vieja decía 0–3.5 V), 12 bit, ~100 kS/s por canal | leídas desde Linux, no desde la PL (§2.3) |
| Salidas analógicas lentas  | AO0–AO3              | **PL**: `dac_pwm_o[3:0]` (`red_pitaya_pdm` ← `red_pitaya_ams`, slot 4) + filtro RC en la placa                                            | 0–1.8 V, LVCMOS18, `DRIVE 12`, ~3.2 MS/s de actualización       | instanciado, sin uso                      |
| SPI                        | MOSI, MISO, SCK, CS  | **SPI0 del PS por EMIO**: atraviesa la PL (aparece en el block design)                                                                    | 3.3 V                                                           | sin uso                                   |
| UART                       | TX, RX               | **UART1 del PS por MIO 8–9**: no pasa por la PL                                                                                           | 3.3 V                                                           | sin uso                                   |
| I2C                        | SDA, SCL             | **I2C0 del PS por MIO 50–51**: no pasa por la PL, y es el mismo bus de la EEPROM de calibración                                           | 3.3 V                                                           | sin uso (la EEPROM tampoco se lee, §2.8)  |
| Alimentación               | +5 V, +3.3 V, −3.4 V | rieles de la placa                                                                                                                        | según la doc oficial: 500 mA en +5 V y +3.3 V, 50 mA en −3.4 V  | —                                         |

La distinción MIO/EMIO importa para la portabilidad: lo que sale por **MIO**
(UART, I2C) es un periférico del PS cableado a pines dedicados y funciona
aunque la PL esté vacía; lo que sale por **EMIO** (SPI0) sólo existe si el
bitstream lo rutea, y por eso aparece en `ip/systemZ10.tcl`. **Este proyecto no
usa nada de E2** por la PL: el único consumidor es Linux leyendo la temperatura
del die por IIO.

El top declara un quinto par de entradas analógicas (`vinp_i[4]`/`vinn_i[4]`,
pines K9/L10, el `VP/VN` dedicado del XADC) que no corresponde a ninguna de las
AI0–AI3 del conector.

**S1 / S2 — daisy chain**: en la Gen 1 son conectores **SATA** (sólo el
conector; no es SATA), dos pares diferenciales por sentido a `DIFF_HSTL_I_18`,
hasta 500 Mb/s. Sirven para encadenar placas compartiendo reloj y trigger. En
el RTL es `red_pitaya_daisy` (slot 5) con los puertos `daisy_p/n_o[1:0]` y
`daisy_p/n_i[1:0]`; la línea `[1]` es la capaz de reloj. En la Gen 2 el
conector es USB-C, con detección de orientación y de link
(`s1_orient_i`, `s1_link_i` en el top bajo `` `ifdef Z20_G2 ``).

**E3 (sólo Gen 2 Pro)**: 8 pares LVDS de 2.5 V, QSPI/eMMC para boot externo,
señales de apagado y watchdog, I2C. En el top bajo `Z20_G2` aparecen
`exp_e3p/n_o[3:0]` y `exp_e3p/n_i[3:0]`, y ocupa el **slot 6** del bus
(`i_serlines_add`).

**LEDs**: 8, `led_o[7:0]`, LVCMOS33 en F16/F17/G15/H15/K14/G14/J15/J14,
manejados por `red_pitaya_hk`. Los usa la placa para el "heartbeat" del OS y
este proyecto para señalizar estado del bitstream.

### 2.6 El procesador de aplicación: los dos Cortex-A9

El Cortex-A9 es el procesador de aplicación del PS: sobre él corre Linux y,
dentro de Linux, el código que configura el MCA y lee los histogramas. **No
participa de la adquisición** — eso ocurre entero en la PL — pero sí de todo lo
demás: configuración, lectura, almacenamiento y presentación.

- **Dos núcleos a 667 MHz**, grado de velocidad −1, el del XC7Z010 de la placa
  (§1.3). Es un diseño de 2007 y se nota: es un procesador de aplicación
  modesto, no un acelerador.

- **Superescalar de dos vías, con ejecución fuera de orden.** *Dos vías*
  significa que puede arrancar hasta dos instrucciones por ciclo; *fuera de
  orden*, que si una queda esperando a memoria puede adelantar a la siguiente, y
  el renombre de registros se encarga de que el resultado sea idéntico al del
  orden del programa. El techo teórico son entonces 2 × 667 MHz ≈ 1.3 × 10⁹
  instrucciones por segundo y por núcleo, un techo que el código real casi nunca
  roza.

- **Pipeline de 8 etapas** (hasta 11 según la instrucción). El *pipeline* es en
  cuántos pasos se parte la ejecución de una instrucción para que varias puedan
  solaparse. Ese número importa sobre todo cuando un salto se predice mal: hay
  que descartar todo lo que ya entró al pipeline, así que la penalización es del
  orden de su profundidad. El Cortex-A8 que lo precedió tenía 13 etapas; con 8,
  equivocarse sale más barato.

- **Predicción dinámica de saltos**, que es la contracara de lo anterior: buffer
  de destinos, historia global y pila de retorno. Es lo que mantiene el pipeline
  lleno.

- **Cachés**: 32 KB de L1 de instrucciones y 32 KB de L1 de datos por núcleo, y
  **512 KB de L2 compartida** entre los dos. La coherencia entre las L1 de datos
  la mantiene la SCU (ver abajo). A esto se suman **256 KB de OCM**, memoria en
  el chip sin caché de por medio.

- **Juego de instrucciones ARMv7-A**: A32 (32 bit) y Thumb-2 (mezcla de 16 y 32
  bit, más compacta), con **VFPv3** para punto flotante y **NEON** para SIMD de
  enteros y de `float32` — NEON no hace `float64`, que queda para la VFP. Es la
  razón por la que conviene que el procesamiento numérico pesado quede en `numpy`
  y no en lazos de Python: `numpy` usa esas unidades, el intérprete no.

- **Extensiones de seguridad TrustZone**, que duplican el estado del procesador
  en un mundo seguro y uno no seguro. En la Red Pitaya todo corre en el mundo no
  seguro; quedan sin usar.

- **Direcciones de 32 bits**, es decir un espacio de 2³² = 4 GB. De ahí viene la
  rigidez del mapa de memoria del Zynq: la DDR, la OCM, los periféricos del PS y
  las ventanas hacia la PL tienen que convivir dentro de esos 4 GB, y por eso los
  ocho slots de la PL son de 1 MB cada uno a partir de `0x4000_0000` (§4.3).

- **2.5 DMIPS/MHz por núcleo.** DMIPS es el puntaje de Dhrystone, un programa de
  prueba sintético, normalizado por frecuencia de reloj para poder comparar
  arquitecturas sin que el reloj ensucie la comparación. A 667 MHz son ~1 670
  DMIPS por núcleo, ~3 340 en total. Conviene leerlo como orden de magnitud y
  nada más — ver el cierre de esta sección.

#### La SCU, y qué garantiza (y qué no)

La **SCU** (*Snoop Control Unit*) mantiene coherentes las cachés L1 de datos de
los dos núcleos, es decir, garantiza que cada dirección de memoria tenga un
único valor vigente. Para lograrlo guarda una **copia duplicada de los tags** de
las dos L1: sabe en todo momento qué líneas tiene cada núcleo, y así puede
husmear (*snooping*) sólo al que corresponde en vez de interrogar a los dos en
cada acceso.

**Qué son esos tags.** Un *tag* es la parte alta de la dirección que la caché
guarda junto a cada línea para saber **qué** dirección está realmente ahí. Con
los números del A9 —L1 de datos de 32 KB, asociativa de 4 vías, líneas de 32
bytes— hay 1024 líneas repartidas en 256 conjuntos, y la dirección física se
parte así:

```
  31                          13 12        5 4         0
 ┌──────────────────────────────┬───────────┬───────────┐
 │        tag  (19 bits)        │ set (8 b) │ offset (5)│
 └──────────────────────────────┴───────────┴───────────┘
   lo que se guarda              elige el     byte dentro
   y se compara                  conjunto     de la línea
```

Los 8 bits del medio dicen en qué conjunto puede estar la línea; los 5 de abajo,
qué byte de los 32. Los 19 de arriba no se deducen de la posición, así que hay
que guardarlos: ése es el tag. Buscar una dirección es ir al conjunto que indica
el índice y comparar el tag contra las 4 vías.

Cada entrada del tag RAM lleva **el tag, el bit de válido y el estado MESI** de
esa línea, y lo que la SCU duplica es exactamente eso para las dos L1 de datos:
1024 entradas por núcleo de ~22 bits, unos **2.8 KB por núcleo** — nada al lado
de los 32 KB de datos que describen. Con eso resuelve sola los tres casos
posibles de un fallo de caché:

- **el otro núcleo no tiene la línea**: va a la L2 o a la DDR sin molestarlo —
  ni un ciclo de su pipeline, ni consumo en su tag RAM;
- **la tiene limpia**: puede pedir la transferencia directa de caché a caché;
- **la tiene sucia**: fuerza la transferencia o la escritura antes de entregar el
  dato.

El precio es mantener el duplicado sincronizado: cada relleno y cada desalojo de
una L1 tiene que actualizarlo, y por eso la SCU está físicamente **entre** las
dos L1 y la L2, no al costado.

Un detalle con consecuencias: **la L1 de datos del A9 es PIPT** (indexada y
etiquetada con la dirección *física*), así que la traducción de la MMU ocurre
**antes** de la comparación del tag. Es lo que hace que el husmeo funcione entre
núcleos sin problemas de *aliasing* de direcciones virtuales, y lo que permite
comparar directamente contra estos tags un acceso que entra por el ACP, que
lleva direcciones físicas. La L1 de instrucciones es VIPT y **no es coherente**:
no hay tags de ella en la SCU.

El mecanismo **no es una exclusión mutua**: varias cachés pueden tener la misma
línea a la vez mientras sólo la lean, en estado compartido y sin costo
adicional. El conflicto aparece con la escritura, donde el núcleo que escribe
tiene que adquirir la línea en exclusiva e invalidar las copias de los demás. Lo
que decide cada transición es una máquina de estados por línea, de la familia
**MESI** (*Modified / Exclusive / Shared / Invalid*) y sus variantes — la SCU del
Cortex-A9 admite además pasar una línea sucia directamente de una caché a la
otra, sin escribirla a memoria.

Vale separar qué garantiza de qué no, porque es una confusión frecuente:

| | Qué asegura | Con qué |
|---|---|---|
| **Coherencia** | que no haya dos valores distintos para la misma dirección | la SCU, en hardware y de forma transparente |
| **Atomicidad** | que un leer-modificar-escribir no se intercale con otro | `LDREX`/`STREX` y el *exclusive monitor*, explícitos |
| **Orden** | en qué orden ve un núcleo las escrituras del otro | barreras `DMB`/`DSB`, explícitas: ARMv7-A es de **orden débil** |

Que la coherencia no alcance para lo segundo se ve en el caso más simple:
`contador++` no es una instrucción sino un `LDR`, un `ADD` y un `STR`. Los dos
núcleos pueden leer 5 —valor perfectamente coherente, ninguno leyó nada viejo—,
los dos calcular 6 y los dos escribir 6. Se perdió un incremento, con la SCU
funcionando impecablemente.

Lo que sí hace la coherencia es **costar caro cuando se la ejercita seguido**.
Una variable que los dos núcleos escriben hace que su línea de caché migre de
uno al otro en cada acceso (*cache line ping-pong*): un acierto en L1 cuesta un
par de ciclos, una línea en disputa decenas. La variante traicionera es el
**falso compartimiento**, donde las variables son distintas pero caen en la
misma línea y se pelean igual. Como el husmeo se aplica sólo a la memoria
marcada como *Shareable*, es la tabla de traducción de la MMU la que decide si
el mecanismo se activa para una región dada.

El **ACP** (*Accelerator Coherency Port*) no es un protocolo de coherencia sino
un **puerto**: una interfaz esclava AXI de 64 bits que entra a la SCU, de modo
que los accesos de un master de la PL se husmean contra las L1 y la L2 en vez de
ir directo a la DDR. Es coherencia **en un solo sentido** —la PL ve lo que el
CPU tiene sucio en caché, el CPU no ve nada de la PL— y en la Red Pitaya el
puerto no está cableado (§2.10.1).

Para este proyecto nada de esto está en el camino crítico: el software es un
proceso de Python, los dos núcleos no se pelean por ninguna estructura
compartida, y el único cliente real de la SCU sería el ACP.

#### La MMU, y por qué existe

Ningún programa direcciona la memoria directamente: toda dirección que usa es
**virtual**, y la MMU (*Memory Management Unit*) la traduce, página por página, a
la dirección **física** que finalmente sale al bus. Existe por tres razones:

1. **Aislamiento.** Cada proceso tiene su propio mapa y literalmente no puede
   nombrar la memoria de otro. Un puntero salvaje mata a su proceso y a nadie
   más.
2. **Libertad de ubicación.** El sistema operativo puede entregar una región
   virtual contigua armada con páginas físicas dispersas, y reubicarlas después
   sin que el programa se entere.
3. **Atributos por página.** Además de la dirección, cada entrada lleva los
   permisos (acceso: lectura/escritura/ejecución, y modo: usuario/privilegiado) y el **tipo de memoria**: si el acceso puede cachearse, agruparse en un buffer o
   reordenarse (`Normal`) o no (`Device`, `Strongly-ordered`).

La tercera es la que importa acá. Cuando el código abre `/dev/mem` y hace `mmap`
de `0x4000_0000`, lo que pide es exactamente eso: **que la MMU inserte en su
tabla una entrada que apunte a la ventana de la PL y la marque como no
cacheable**. A partir de ahí, un `self._mem[off:off+4]` es una carga ordinaria
que termina en el bus AXI. La MMU no es un detalle del sistema operativo en este
proyecto: es el mecanismo por el cual el proceso llega a tocar la FPGA. El
detalle del tipo de memoria y de lo que pasa cuando el acceso no respeta lo que
el esclavo acepta está en
[`TOP/bus_sistema_redpitaya.md`](TOP/bus_sistema_redpitaya.md) §7 y en
[`patrones_memoria_hw.md`](patrones_memoria_hw.md).

La tabla de traducción vive en la DDR, y recorrerla en cada acceso sería
carísimo, así que la MMU guarda las traducciones recientes en el **TLB**
(*Translation Lookaside Buffer*), en dos niveles: uno pequeño junto a cada caché
L1 y uno unificado detrás. Las páginas van de 4 KB a 16 MB — cuanto más grandes,
menos entradas se gastan para cubrir la misma extensión.

#### Qué significa todo esto para el MCA

Nada de lo anterior es el límite del sistema. La lectura del espectro desde
Python cuesta **~6.7 µs por palabra**, que a 667 MHz son unos **4 500 ciclos
para mover 32 bits** — tres órdenes de magnitud por debajo de lo que la
arquitectura permite, y unas 28 veces más que los ~0.235 µs que tarda el acceso
AXI en sí. El cuello de botella nunca fue el procesador: es el intérprete. Las
opciones para arreglarlo, con sus tiempos estimados, están en
[`TOP/bus_sistema_redpitaya.md`](TOP/bus_sistema_redpitaya.md) §10.1.

### 2.7 Interconexiones: las tres fronteras

El Zynq son **dos chips en un die**, y toda señal que entra o sale del SoC cruza
una de **tres fronteras**, cada una con su propia física y sus propios límites:

| Frontera | Por dónde pasa | Qué la limita | Dónde |
|---|---|---|---|
| **PS ↔ Externo** | los 54 pines **MIO** y los pines dedicados del PS (DDR, QSPI, USB, reloj, resets) | está fijada en silicio: el periférico y el pin ya vienen apareados. Funciona **aunque la PL esté vacía** | §2.8 |
| **PL ↔ Externo** | los pines de I/O de la FPGA (**SelectIO**) y las entradas analógicas del XADC | la elige el diseño, pero la acotan el encapsulado y el banco: cuántos pines hay y a qué tensión | §2.9 |
| **PS ↔ PL** | un conjunto **fijo y finito** de interfaces internas: AXI, relojes, interrupciones, EMIO | no hay forma de inventar un camino nuevo: sólo elegir entre los que existen | §2.10 |

Y un cuarto caso que no es una frontera sino la composición de dos: **EMIO**, un
periférico del PS que cruza a la PL y sale por un pin de la FPGA
(PS → PL → Externo). Es el que más confunde y el que decide la portabilidad
(§2.10.5).

El inventario de todo eso es la figura 10.1 de la UG585 (*Zynq-7000 AP SoC
interfaces, signals and pins*), y las dos sub-secciones que siguen la recorren
entera —primero grupo por grupo, después instanciada en esta placa— diciendo,
para cada cosa, **qué existe en el 7010, qué cablea la Red Pitaya y qué usa el
build del MCA**.

Todo lo que se afirma de acá hasta el final de §2.10 sale de
[`ip/systemZ10.tcl`](../ip/systemZ10.tcl) (la configuración del PS7 y el block
design), de [`rtl/red_pitaya_ps.sv`](../rtl/red_pitaya_ps.sv) (el envoltorio) y
del [`out/post_imp_io.rpt`](../out/post_imp_io.rpt) del build.

#### 2.7.1 El inventario, grupo por grupo

La última columna de cada fila remite a la frontera que la trata en detalle.

| Grupo en la figura                                                                                  | Qué es                                                                           | En la 125-14                                                                                     | En el build MCA                                                                |
| --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| **PS signals and interfaces**<br>(DDR, NAND/NOR/SRAM, `Ps_CLK`/`POR_RST_N`/`SRST_N`, Quad-SPI, USB) | pines **dedicados del PS**: no tocan la PL ni consumen I/O de la FPGA            | DDR3 512 MB, QSPI de boot, USB host, cristal y resets del PS. NAND/NOR: no existe en la placa    | transparente: es el `FIXED_IO` + `DDR` del top (§2.8)                          |
| **MIO pins, EMIO signals, JTAG**                                                                    | los 54 pines MIO del PS, y la opción de sacar un periférico **por la PL** (EMIO) | GigE, SD, UART, I2C, SPI1, USB por MIO; GPIO, SPI0, CAN y TTC0 por EMIO                          | EMIO GPIO y CAN (§2.10.5); el resto, por MIO (§2.8)                             |
| **AXI interfaces**<br>2× `M_AXI_GP`, 2× `S_AXI_GP`, 4× `S_AXI_HP`, 1× `S_AXI_ACP`                   | los puertos de memoria entre PS y PL                                             | GP0 → registros · GP1 → XADC · HP0–HP3 → DDR · GP esclavos y ACP sin cablear                     | GP0 todo el tiempo; HP0/HP1 construidos y apagados (§2.10.1)                    |
| **Misc. PL signals**<br>(AXI idle, DMA req/ack, FCLKs, FTMD/FTMT trace, IRQ/event/standby)          | señales sueltas, no de memoria                                                   | sólo FCLK/FCLK_RESET e `IRQ_F2P`                                                                 | 4 relojes + reset global; una sola interrupción, y no es del proyecto (§2.10.4) |
| **PL signals**<br>(User SelectIO, XADC, MGT)                                                        | lo que la PL expone por sí misma                                                 | SelectIO: ADC, DAC, E1, LEDs, daisy · XADC: entradas lentas · **MGT: no existe en el 7010/7020** | todo el datapath (§2.9)                                                      |
| **PS/PL power pins**                                                                                | alimentación separada de cada mitad, y por banco de I/O en la PL                 | banco 34 a **1.8 V**, banco 35 a **3.3 V**                                                       | fija qué estándar puede usar cada pin (§2.9)                                 |

#### 2.7.2 El mapa completo de la 125-14

La figura de la UG585, instanciada para esta placa y este build. Entre
paréntesis, lo que el MCA no usa:

```
        ┌──────────────── PS ────────────────┐        ┌─────────────── PL ───────────────┐
 DDR3   │                                    │        │                                  │
 512MB ═╡ controlador DDR  ◄══════════════════════════╡ S_AXI_HP0/HP1 ◄── axi_master     │
        │                                    │  64 b  │   (cableados, apagados §4.5)     │
 QSPI ──┤ MIO 1-6                            │        │ (S_AXI_HP2/HP3 en cero)          │
 µSD ───┤ MIO 40-47                          │        │                                  │
 GigE ──┤ MIO 16-27  ─┐                      │        │                                  │
 USB ───┤ MIO 28-39   ├ pines dedicados      │        │                                  │
 UART ──┤ MIO 14-15   │ del PS               │        │                                  │
 I2C ───┤ MIO 50-51  ─┘ (EEPROM de calib.)   │        │                                  │
        │                                    │  32 b  │                                  │
        │  2× Cortex-A9 ── M_AXI_GP0 ════════════════►╡ axi4_slave ─► sys_bus ─► 8 slots │
        │     667 MHz                        │ 125MHz │        (§4.3: hk, osc, mtrg,     │
        │               ── M_AXI_GP1 ════════╪════╗   │         top, MCA)                │
        │                                    │200MHz  │                                  │
        │               ── FCLK_CLK0..3 ─────┼───────►╡ 125 / 250 / 50 / 200 MHz         │
        │               ── FCLK_RESET0_N ────┼───────►╡ reset global de la PL            │
        │               ◄── IRQ_F2P ─────────┼───╗    │                                  │
        │               ── EMIO GPIO[23:8] ◄─┼───╪───╡ exp_p_in / exp_n_in (sólo lectura)│
        │               ── EMIO CAN0/1 ──────┼───╪───►╡ exp_*[7:6]                       │
        │  (S_AXI_GP0, ACP, DMA, trace: sin  │   ║ ╚══╡ xadc_wiz ◄── Vaux0/1/8/9, Vp_Vn  │
        │   cablear)                         │   ╚════╡ (IRQ del XADC)                   │
        └────────────────────────────────────┘        │                                  │
                                                      │ SelectIO banco 34 (1.8 V):       │
                                                      │   ADC 2×16 b, reloj dif., PWM,   │
                                                      │   daisy LVDS (sin MGT)           │
                                                      │ SelectIO banco 35 (3.3 V):       │
                                                      │   DAC 14 b, E1, LEDs             │
                                                      └──────────────────────────────────┘
```

### 2.8 Frontera PS ↔ Externo: los pines dedicados del PS

Es la frontera **rígida**: cada periférico del PS tiene asignado de antemano a
qué pines puede salir, el ruteo lo hace el PS y no la PL, y por eso **nada de
esta tabla consume I/O de la FPGA ni depende del bitstream**. Una placa con la
PL vacía igual arranca, levanta la red y da consola — que es exactamente la
situación en la que uno se encuentra cuando el bitstream todavía no cargó.

| Periférico | Salida | Para qué |
|---|---|---|
| DDR3 | pines dedicados (ni MIO ni PL) | 1 × **MT41J256M16** (4 Gb, ×16) = 512 MB, `DDR_RAM_HIGHADDR 0x1FFF_FFFF` |
| QSPI | MIO 1–6 | flash de boot (`boot.bin` alternativo) |
| SD0 | MIO 40–45 (+CD 46, WP 47) | microSD: **es el disco del sistema** |
| Ethernet 0 | MIO 16–27, MDIO 52–53 | RGMII, 1 Gbit |
| USB 0 | MIO 28–39 (ULPI), reset MIO 48 | host USB-A |
| UART 0 | MIO 14–15 | **consola serie** (micro-USB en la placa, 115200 8N1) |
| UART 1 | MIO 8–9 | E2 |
| I2C 0 | MIO 50–51 | **EEPROM de calibración** y E2 |
| SPI 1 | MIO 10–15 | — |

Los periféricos del PS que **no** salen por acá —GPIO, CAN, SPI0, TTC0— salen
atravesando la PL, y están en §2.10.5.

JTAG queda del lado del PS. En uso normal **la PL no se programa por JTAG**
sino desde Linux (§2.11), lo que explica que no haya conector JTAG a la vista.

La **EEPROM de calibración** que cuelga del I2C0 guarda ganancia y offset de
cada canal de ADC y DAC, en LV y HV; el formato está en
[`doc/calibregs.adoc`](../../../doc/calibregs.adoc). El MCA no la lee: calibra
su propio eje de canales contra el generador
([`resultados_validacion_hw.md`](resultados_validacion_hw.md)).

### 2.9 Frontera PL ↔ Externo: lo que la FPGA expone por su cuenta

Es la frontera **flexible y acotada**: qué señal sale por qué pin lo decide el
diseño, pero el encapsulado fija cuántos pines hay —100 en el 7010 de esta
placa, de los que el build usa 99 (§1.3)— y el banco fija a qué tensión. El
inventario pin por pin está en [`pinout_zynq.md`](pinout_zynq.md).

**User SelectIO** — los pines de la FPGA, repartidos en dos bancos con
tensiones distintas, que es lo que fija qué estándar puede usar cada señal
(verificado en [`out/post_imp_io.rpt`](../out/post_imp_io.rpt)):

| Banco | Tensión | Señales | Estándar |
|---|---|---|---|
| **34** | **1.8 V** | datos del ADC · reloj del ADC · PWM de E2 · daisy S1/S2 | `LVCMOS18`, `DIFF_HSTL_I_18` |
| **35** | **3.3 V** | datos del DAC · **E1 completo** · LEDs · entradas del XADC | `LVCMOS33` |

De ahí sale, sin misterio, por qué E1 es de 3.3 V y el bus del ADC de 1.8 V:
no es una elección del RTL, es la alimentación del banco.

**XADC** — en la figura aparece como recurso de la PL, y en este diseño lo es
literalmente: **no se usa la interfaz XADC del PS**, sino una instancia de
`xadc_wiz` **dentro del block design**, esclava AXI-Lite de GP1 (§2.10.1), con
sus cinco pares analógicos (`Vaux0/1/8/9` + `Vp_Vn`) saliendo a los pines
`vinp_i`/`vinn_i`. Su interrupción es la única `IRQ_F2P` del diseño.

> **Una restricción colgada.** [`prj/MCA/sdc/red_pitaya.xdc:1`](../sdc/red_pitaya.xdc#L1)
> dice `set_property LOC XADC_X0Y0 [get_cells i_ams/XADC_inst]`, pero
> `red_pitaya_ams` hoy es **sólo la configuración del PWM**: no instancia
> ningún XADC. El build lo avisa (`WARNING [Vivado 12-180] No cells matched` +
> `CRITICAL WARNING [Common 17-55]`, líneas 3838–3839 de
> [`out/build_Z10_2CH.log`](../out/build_Z10_2CH.log)) y sigue de largo. No
> tiene consecuencia —hay un solo sitio XADC en el chip y el `xadc_wiz` cae
> ahí igual—, pero conviene saber que **el comentario de cabecera del top, que
> dice que el XDC engancha `i_ams` por nombre, está desactualizado en esa
> línea**: las que sí enganchan son las 32 de los CDC de `for_bus[0..7]`.

**MGT (transceptores multi-gigabit)** — la nota al pie de la figura es la
clave: existen **sólo en 7z030, 7z045 y 7z100**. El 7010 y el 7020 **no
tienen**. Por eso la daisy chain de la Red Pitaya, aunque entre por un
conector SATA (Gen 1) o USB-C (Gen 2), **no es un enlace serie de verdad**:
son pares LVDS por SelectIO común (`DIFF_HSTL_I_18`), serializados a mano en
la lógica, con un `create_clock -period 4.000` sobre `daisy_p_i[1]` y un techo
práctico de 500 Mb/s. Cualquier plan que necesite un enlace serie rápido entre
placas choca con esto y no se arregla con RTL.

### 2.10 Frontera PS ↔ PL: lo que cruza dentro del die

Es la frontera que **no tiene pines**: todo pasa por interfaces internas al
chip, y el catálogo es cerrado. Hay cuatro clases, y la Red Pitaya usa tres:

- **puertos AXI**, para registros y para datos (§2.10.1 a §2.10.3);
- **relojes, resets e interrupciones** sueltos (§2.10.4);
- **EMIO**, que saca un periférico del PS a través de la PL (§2.10.5);
- y **DMA del PS, trace y ACP**, que existen en el silicio y quedan sin cablear.

#### 2.10.1 Las interfaces AXI

Son cinco clases de puerto y la placa usa tres. El detalle importa porque
**cada una tiene un ancho y una latencia distintos**, y ahí se decide qué
puede ir rápido y qué no:

| Puerto             | Sentido       | Ancho      | Reloj                                                  | Dónde va                                                                                                             | Uso en el MCA                                                                  |
| ------------------ | ------------- | ---------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| **`M_AXI_GP0`**    | PS → PL       | 32 bit     | `fclk[0]` 125 MHz                                      | sale del block design al top → `axi4_slave` → `sys_bus`. Ventana `0x4000_0000`, rango 1 GB                           | **todo el control y toda la lectura de espectros** (§4.3)                      |
| **`M_AXI_GP1`**    | PS → PL       | 32 bit     | `fclk[3]` **200 MHz**                                  | **no sale del block design**: `axi_register_slice` → `axi_protocol_converter` → `xadc_wiz`, en `0x83C0_0000` (64 KB) | indirecto: es por donde Linux lee el XADC                                      |
| `S_AXI_GP0`        | PL → PS       | 32 bit     | —                                                      | habilitado en el PS7, **sólo con el reloj conectado**: no hay puerto de interfaz en el block design                  | sin uso                                                                        |
| **`S_AXI_HP0..3`** | PL → DDR/OCM  | **64 bit** | HP0/HP1 a `adc_clk`, HP2/HP3 a `dac_axi_clk` (250 MHz) | `axi_master` del top → ventana `0x0000_0000` + 512 MB (`HP*_DDR_LOWOCM`), `ID_WIDTH 4`                               | HP0/HP1 cableados al scope y **apagados por registro** (§4.5); HP2/HP3 en cero |
| `S_AXI_ACP`        | PL → SCU      | 64 bit     | —                                                      | **entra a la SCU, no a la interconexión de memoria**: los accesos se husmearían contra las L1 y la L2 (§2.6). No habilitado | sin uso                                                                        |

#### 2.10.2 Qué puede mover cada puerto

La tabla de arriba dice **dónde está cableado** cada puerto; ésta dice **qué
rinde**. Las dos primeras columnas son del SoC (no dependen de la placa); la de
"techo real" es lo que queda después de la implementación concreta de
Red Pitaya, y ahí es donde aparecen las sorpresas.

|                          | `M_AXI_GP`                                                                                           | `S_AXI_GP`                                  | `S_AXI_HP`                                                 | `S_AXI_ACP`                                                        |
| ------------------------ | ---------------------------------------------------------------------------------------------------- | ------------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------ |
| **Ancho de bus**         | 32 bit                                                                                               | 32 bit                                      | **64 bit** (configurable 32/64)                            | 64 bit                                                             |
| **Reloj máximo**         | 150 MHz (lo fija la PL)                                                                              | 150 MHz                                     | 150 MHz                                                    | 150 MHz                                                            |
| **Techo teórico**        | 32 b × 150 MHz = **600 MB/s**                                                                        | 600 MB/s                                    | 64 b × 150 MHz = **1200 MB/s** por puerto                  | 1200 MB/s                                                          |
| **Reloj en esta placa**  | GP0: **125 MHz** · GP1: 200 MHz                                                                      | —                                           | HP0/1: **125 MHz** · HP2/3: 250 MHz                        | —                                                                  |
| **Techo con ese reloj**  | 500 MB/s                                                                                             | —                                           | **1 GB/s** por puerto                                      | —                                                                  |
| **Techo real medido**    | **17 MB/s** desde C · **1.7 MB/s** desde Python                                                      | —                                           | **1 GB/s** (el cuello pasa a ser la DDR y el consumidor)   | —                                                                  |
| **Transferencia mínima** | 1 palabra de 32 bit                                                                                  | 32 bit                                      | 1 *beat* de 64 bit; ráfaga útil de **16 beats = 128 B**    | 64 bit, línea de caché de 32 B                                     |
| **Ráfagas**              | las admite AXI, **pero el esclavo de Red Pitaya no** (ver abajo)                                     | sí                                          | **sí**, hasta 16 beats, con FIFO de lectura y de escritura | sí                                                                 |
| **Latencia de acceso**   | **96 ns** de ida y vuelta en la PL (12 ciclos) · **235 ns** vistos desde C · **2.3 µs** desde Python | —                                           | ~100 ns de arranque, amortizados en la ráfaga              | la más baja de las cuatro si pega en caché                         |
| **Determinismo**         | alto en la PL, **nulo desde Linux**                                                                  | —                                           | alto; compite por la DDR                                   | depende del estado de la caché                                     |
| **Caso de uso típico**   | **registros de control y estado**; lecturas chicas y esporádicas                                     | que la PL acceda a periféricos del PS u OCM | **volcado masivo a DDR**: captura de ADC, video, DMA       | acelerador que comparte estructuras con el CPU sin invalidar caché |
| **En este proyecto**     | todo el control + los 32 kB del espectro                                                             | sin uso                                     | el `event_ring` (ruta C)                                   | sin uso                                                            |

Las cuatro cosas que esa tabla explica:

- **El factor 30 entre el techo teórico de GP0 y el real no es del puerto AXI:
  es del esclavo.** El `sys_bus` de Red Pitaya admite **una sola transacción en
  vuelo, sin ráfagas**, y cada acceso paga un cruce de dominio de reloj
  completo: 96 ns medidos en el RTL
  ([`TOP/bus_sistema_redpitaya.md`](TOP/bus_sistema_redpitaya.md) §5). Leer
  16 k muestras son 16 k transacciones. Por eso el techo práctico es 17 MB/s
  desde C y no 500.
- **Pedirle una ráfaga a GP0 no es lento: reinicia la placa.** Un `memcpy`,
  un slice grande del `mmap` o un `np.frombuffer().copy()` sobre esa región
  emiten accesos anchos o en ráfaga, el esclavo los rechaza, y el *external
  abort* resultante **no da SIGBUS en esta placa: reinicia el sistema**
  (verificado — [`patrones_memoria_hw.md`](patrones_memoria_hw.md)). La lectura
  del espectro es palabra por palabra por obligación, no por descuido.
- **HP es el único puerto con FIFOs y ráfagas hacia la DDR**, y por eso es la
  única palanca de orden de magnitud. Su techo de 1 GB/s no es el límite real:
  la DDR3 de la placa (16 bit a 533 MHz) da ~2.1 GB/s de pico teórico y ~1.4
  GB/s prácticos **compartidos entre los cuatro puertos HP y los dos ARM**.
- **ACP sería el puerto correcto para transferencias chicas y frecuentes**
  —es coherente con L1/L2, así que no hay que invalidar caché— pero Red Pitaya
  no lo cablea. Y la coherencia va **en un solo sentido**: la PL ve la caché del
  CPU, no al revés (§2.6).

#### 2.10.3 Los parámetros que no son constantes

Vale la pena separar **qué número se puede poner en una hoja de datos y qué
número hay que medir cada vez**, porque la mitad de las discusiones sobre
rendimiento nacen de tratar a los segundos como si fueran los primeros:

| Magnitud | ¿Fija? | Qué la mueve |
|---|---|---|
| Ancho de bus, transferencia mínima | **fija** | es silicio |
| Latencia de GP0 **dentro de la PL** (96 ns) | **fija** | el handshake no mira la dirección: el `ack` sale en un número fijo de ciclos |
| Latencia de GP0 **vista desde Linux** | **variable** | planificador, fallos de página, el GIL de CPython (stalls medidos de **5.3 ms**), y si hay otro proceso tocando `/dev/mem` |
| Throughput de HP | **casi fija**, con piso | compite con los ARM por la DDR; el refresco de la DDR3 también se lleva su parte |
| Throughput de la microSD | **variable** | 12.4 MB/s medidos, pero la escritura sostenida cae con la tarjeta llena y con el FTL |
| **Throughput por red** | **el más variable de todos** | 90–110 MB/s con TCP crudo, 60–90 con NFS, 20–40 con SSHFS (AES por software). Y además depende del *tamaño del lote*: con `sync` por evento se pierde la mitad del ancho de banda en round-trips |

De ahí la regla que atraviesa todo el diseño del software: **lo que cruza una
frontera lenta se manda en lotes grandes y pocos**, y lo que necesita ser
determinista se queda del lado de la PL. Los números medidos de cada tramo, con
su procedencia, están en
[`movimiento_de_datos.md`](movimiento_de_datos.md) §1 y §9.

> **Una rareza heredada que conviene tener en el radar.** `M_AXI_GP1` corre a
> `fclk[3]` = **200 MHz**, por encima de los 150 MHz que se citan como máximo
> de los puertos AXI del PS. El build cierra timing —apenas: es el camino de
> 7 ps del `phys_opt_design` condicional— y la placa funciona, pero el margen
> es ése. Viene del block design de upstream y **no está verificado contra la
> DS190**; si alguna vez hay que tocar el PS7, bajar GP1 a `fclk[0]` es el
> cambio obvio.

#### 2.10.4 Señales sueltas PS → PL

De todo el grupo *Misc. PL signals* de la figura, la Red Pitaya usa dos cosas:

| Señal                      | Estado                               | Detalle                                                                                                                                                                                                  |
| -------------------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`FCLK_CLK0..3`**         | **usadas**                           | los cuatro relojes de §2.4. `fclk[0]` es el del bus; `fclk[3]` (200 MHz) es el del subsistema XADC                                                                                                       |
| **`FCLK_RESET0..3_N`**     | **usadas**                           | `frstn[0]` es el **reset global de todo el diseño de la PL**: lo emite el PS, así que un `reboot` del ARM resetea la PL sin recargar el bitstream. `FCLK_RESET3_N` alimenta el `proc_sys_reset` del XADC |
| **`IRQ_F2P`**              | **usada, pero no por este proyecto** | la única interrupción PL→PS es `xadc/ip2intc_irpt`. **Ningún módulo del MCA interrumpe**: todo es *polling* desde Linux por GP0                                                                          |
| DMA req/ack                | sin habilitar                        | el DMAC del PS no se usa; los volcados a DDR los hace un master propio en la PL                                                                                                                          |
| FTMD trace / FTMT triggers | sin habilitar                        | depuración con trace: no se usa                                                                                                                                                                          |
| AXI idle, event, standby   | sin habilitar                        | —                                                                                                                                                                                                        |

Que **no haya interrupciones del datapath** es una decisión que se paga en el
software: el lazo de adquisición pregunta en vez de ser avisado, y eso fija un
piso de latencia por el round-trip de `/dev/mem`. Para el MCA no es un problema
(el FPGA acumula y el ARM lee cuando quiere); para el scope multitrigger sí, y
es parte del tiempo muerto medido.

#### 2.10.5 MIO contra EMIO: el periférico que cruza dos fronteras

Es la distinción que más confunde y la que decide la portabilidad: un
periférico del PS puede salir por sus **pines dedicados (MIO)**, y entonces
funciona *aunque la PL esté vacía* (§2.8), o puede **atravesar la PL (EMIO)** y
salir por un pin cualquiera de la FPGA, y entonces **sólo existe si el
bitstream lo rutea**.

| Periférico | Salida | Para qué |
|---|---|---|
| **GPIO** | **EMIO, 24 bits** | las líneas de E1 (ver abajo) |
| **CAN 0/1** | **EMIO** → E1 | `exp_*[7:6]`, habilitadas por `can_on` de `red_pitaya_hk` |
| SPI 0 | EMIO | **terminado en el envoltorio**: entradas a `1'b0`, salidas al aire ([`red_pitaya_ps.sv:515`](../rtl/red_pitaya_ps.sv#L515)). Existe en el PS, no llega a ningún pin |
| TTC0 | EMIO | habilitado en el PS7, sin puerto en el block design: se queda adentro |

El **GPIO por EMIO** merece el detalle, porque es la vía por la que Linux ve
el conector E1. Son `3 × DWE = 24` bits (`set ::gpio_width 24` en el script de
build), y el top conecta sólo la mitad:

```systemverilog
assign gpio.i[2*GDW-1:  GDW] = exp_p_in[GDW-1:0];   // bits 15:8  <- DIO0_P..DIO7_P
assign gpio.i[3*GDW-1:2*GDW] = exp_n_in[GDW-1:0];   // bits 23:16 <- DIO0_N..DIO7_N
assign trig_ext = gpio.i[GDW] & ~(daisy_mode[0] & daisy_trig);  // bit 8 = DIO0_P
```

`gpio.o` y `gpio.t` **no se usan**, y los bits `[7:0]` de la entrada quedan sin
asignar. O sea: **Linux puede leer los pines de E1 por el GPIO del kernel,
pero no puede manejarlos desde ahí**; para sacar un nivel hay que escribir los
registros de `red_pitaya_hk` (slot 0). Y el trigger externo no es un camino
aparte: es el mismo bit 8 de ese banco EMIO.

### 2.11 Arranque, sistema operativo y carga de la PL

1. **BootROM → FSBL** desde la microSD (o QSPI). El FSBL sale de la
   configuración del PS7 (`hsi`, `red_pitaya_hsi_fsbl.tcl`); no depende del
   diseño de la PL, por eso el MCA no lo regenera.
2. **U-Boot → Linux**. Red Pitaya OS es un Ubuntu ARM con kernel Xilinx. El
   banco corre **RP OS 2.00, kernel 5.15-xilinx, Python 3.10**; con el sistema
   arriba quedan **~461 MB** libres de los 512.
3. **La PL se carga en caliente** con el FPGA manager de Linux
   (`/sys/class/fpga_manager/fpga0`, herramienta `fpgautil`). Acepta el
   formato de `bootgen` (`.bit.bin`), **no** el `.bit` de Vivado; el script de
   build del MCA hace la conversión en línea
   ([`red_pitaya_vivado_Z10_mca.tcl`](../../../red_pitaya_vivado_Z10_mca.tcl)).
   El device tree de la PL va como overlay ([`dts/fpga.dtso`](../dts/fpga.dtso)).
4. El acceso a registros desde Linux es **`/dev/mem` + `mmap`** sobre
   `0x4000_0000`. No hay driver de kernel propio.

### 2.12 El software que da el proyecto original de Red Pitaya

La plataforma no es sólo la PCB. La microSD viene con un stack completo, y
**buena parte del valor de elegir una Red Pitaya sobre una placa Zynq pelada
está acá**: no hay que escribir FSBL, ni device tree, ni driver, ni servidor
web.

Esta sección es **sólo el inventario de lo que viene de fábrica**. Qué tomamos
de cada cosa, qué descartamos y qué escribimos nosotros está en §4.8; acá la
columna «MCA» sólo adelanta el veredicto con un símbolo.

Y va dividido en dos, porque «lo que da la plataforma» son en realidad dos
cosas muy distintas: **(A) lo que sale de un Linux estándar** —que estaría en
cualquier Zynq bien configurado— y **(B) lo que es propio de Red Pitaya** —que
sólo existe en esta plataforma—. La diferencia no es académica: **es
exactamente la lista de lo que habría que reescribir para dejar la familia Red
Pitaya** (§5).

Son cuatro capas. A la derecha, de dónde sale cada una: **[std]** es Linux
estándar o software upstream, **[RP]** es propio de Red Pitaya. El MCA entra
por la capa más baja y se saltea casi todo lo de arriba:

```
  apps web (nginx) · marketplace    JupyterLab    scpi-server (:5000)
       └────────────────┬───────────────┴────────────────┘        [RP]
                        │
     librp (C) ─────────┴── binding `import rp` ── rp_overlay     [RP]
                        │
   herramientas de shell:  fpgautil · monitor · calib         [Xilinx/RP]
  ───────────────── Linux (kernel 5.15-xilinx) ─────────────────
   /dev/mem · fpga_manager · fpga_bridge · IIO · reserved-memory  [std]
   systemd · ssh · rsync · Python 3.10 + NumPy                    [std]
  ──────────────────── PL (el bitstream) ────────────────────
                        ▲
                 el MCA entra por acá: mmap sobre 0x4000_0000
```

Leyenda de la última columna de las dos tablas que siguen: **✓** lo usamos ·
**~** lo usamos en parte · **✗** existe y no lo usamos. El por qué de cada
veredicto está en §4.8.

#### A. Lo que sale de un Linux estándar

Nada de esto es invención de Red Pitaya: son subsistemas del kernel y paquetes
de distribución que estarían en **cualquier Zynq con un Ubuntu y un device tree
correcto**. Lo que aporta la plataforma acá no es la facilidad en sí, es que
**ya viene configurada y arranca**: el kernel con los drivers del Zynq
compilados, el device tree de esta placa y la distro armada.

| Facilidad | Qué nos da | Quién la provee | MCA |
|---|---|---|---|
| **`/dev/mem` + `mmap`** | el único camino a los registros de la PL, sin escribir un driver | kernel (mainline) | ✓ |
| **`fpga_manager` + `fpga_bridge`** (sysfs) | recargar la PL en caliente y bajar/subir los puentes AXI, sin JTAG ni reinicio | subsistema mainline + el driver del Zynq | ✓ |
| **IIO** | temperatura del die y AI0–AI3 como archivos, sin tocar la PL | subsistema y driver `xadc` mainline — **pero el nodo del XADC lo pone el device tree de la placa** (§2.3) | ✓ |
| **`reserved-memory`** del device tree | el mecanismo estándar para apartar DDR fuera del alcance de Linux | binding estándar de DT — **las regiones concretas son de Red Pitaya** (ver tabla B) | ✓ |
| **Ubuntu ARM + Python 3.10 + NumPy** | un entorno de trabajo completo en la placa, sin compilar nada | distribución | ✓ |
| **`systemd`, ssh, rsync** | servicios que arrancan solos y despliegue por red (`make placa-sync`) | distribución | ✓ |
| **Consola serie** por el micro-USB | entrar a la placa cuando la red no levanta (115200 8N1) | kernel + `getty` | ✓ |
| **nginx** | el servidor web que sirve la interfaz | paquete estándar — **lo que corre encima es de Red Pitaya** (tabla B) | ✗ |
| **JupyterLab** | editar y correr Python **en la placa**, con gráficos | proyecto upstream; Red Pitaya lo empaqueta, lo arranca y le da `/home/jupyter` | ✓ |

La consecuencia práctica de esta mitad: **lo que el MCA usa del software de la
placa es casi todo de acá**, y por eso el proyecto es portable a cualquier Zynq
con Linux. Nada de `/dev/mem`, `fpga_manager` ni IIO depende de que la placa sea
una Red Pitaya.

#### B. Lo que es propio de Red Pitaya

Acá sí: software que existe sólo en esta plataforma, y que si la placa fuera
otra habría que escribir.

| Facilidad | Qué nos da | Fuente | MCA |
|---|---|---|---|
| **La imagen RP OS 2.00 que arranca sola** | FSBL generado para este PS7, U-Boot, kernel 5.15-xilinx y el device tree de **esta** placa, todo armado. Es el ítem más valioso de la lista y el que más trabajo ahorra | la placa (§2.11) | ✓ |
| **`librp`** (librería C) | maneja el bitstream de fábrica —adquisición, trigger, generador— por offsets fijos en `0x4010_0000` | [`osc/register_map_osc.md`](osc/register_map_osc.md) | ✓ |
| **Binding Python (`import rp`)** (`/opt/redpitaya/lib/python`) | toda `librp` desde Python, sin escribir una línea de C | ídem | ✓ |
| **`rp_overlay`** | cargar los overlays de fábrica (`v0.94`, `mercury`, …) desde Python | [`guardado_mariana.py`](../software/campanas/guardado_mariana.py) | ~ |
| **API de *deep memory* (`rp_AcqAxi*`)** | capturar a DDR por los puertos HP desde la librería, sin RTL propio | doc oficial | ✗ |
| **Las regiones de DDR ya reservadas** | `buffer@1000000` (2 MB, para la *deep memory*) y `labuf@a000000` (32 MB, del analizador lógico), en el device tree de fábrica | [`hw_ring_plumbing.py`](../software/API/tests/placa/hw_ring_plumbing.py) | ✓ |
| **`fpgautil`** (`/opt/redpitaya/bin/`) | programa la PL y aplica el overlay de device tree en un comando | [`API/fpga.py`](../software/API/fpga.py) | ✓ |
| **`monitor`** (`/opt/redpitaya/bin/`) | leer/escribir un registro de la PL desde la shell, y con `-f` el **modelo de placa grabado en la EEPROM** | ídem | ~ |
| **EEPROM de calibración + `calib`** | ganancia y offset de fábrica por canal, en LV y HV, ya medidos y grabados | §2.8; doc oficial | ✗ |
| **`scpi-server`** (TCP 5000) | manejar la placa como un instrumento de banco desde MATLAB, LabVIEW o Python | doc oficial | ✗ |
| **Las aplicaciones web + el *marketplace*** | osciloscopio + generador, analizador de espectro, analizador lógico, medidor LCR, Bode, streaming, y la tienda para instalar más | doc oficial | ✗ |
| **El árbol `RedPitaya-FPGA`** (este repo) | el top, el XDC con los 400 pines, el block design del PS7, la PLL, el `sys_bus` y sus 8 slots, el overlay `fpga.dtso` | §3, [`TOP/bus_sistema_redpitaya.md`](TOP/bus_sistema_redpitaya.md) | ✓ |

> **Ojo con `fpgautil`**: la herramienta es de Xilinx, no de Red Pitaya; lo
> propio de la plataforma es que **viene instalada y en `/opt/redpitaya/bin/`**
> (y que un shell no interactivo no la tiene en el `PATH`, de ahí el *fallback*
> absoluto de [`API/fpga.py`](../software/API/fpga.py)).

Y **lo que la plataforma no trae**, porque marca el límite de lo que nos
regalan: el módulo `usbtmc` del kernel, y cualquier noción de espectro,
histograma o tiempo muerto. Todo eso lo pusimos nosotros (§4.8).

#### `librp` es la pieza que condiciona el RTL

De todo el stack, la que más pesa en las decisiones de diseño es `librp`,
porque es una librería **C y cerrada**: lee y escribe **offsets fijos** del
slot 1. Eso tiene dos consecuencias que no se ven desde el software:

1. **El mapa de registros del scope no se puede mover.** Mudar los registros
   rompería las 111 llamadas de golpe, sin posibilidad de parche del lado
   Python. Por eso el slot 1 mantiene una **ventana de compatibilidad legacy**
   (`0x000`–`0xFFF`) además del mapa canónico, al precio de 100–200 LUT y
   gobernada por el parámetro `EN_LEGACY_MAP` —el único lugar a tocar cuando el
   software esté migrado—. El detalle está en
   [`osc/register_map_osc.md`](osc/register_map_osc.md).
2. **Su comodidad cuesta tiempo muerto.** Cada llamada a `rp_AcqGetDataPosV`
   trae ~35 µs fijos **dentro de la librería**, y el ciclo por evento completo
   desde Python queda en ~253 µs ⇒ techo de **3.7 kev/s**. El mismo ciclo en C,
   leyendo la BRAM directo y salteando `librp`, baja a 19.2 µs ⇒ **~52 kev/s**
   (×14). Los números y el reparto están en
   [`API/arquitectura_adquisicion_software.md`](API/arquitectura_adquisicion_software.md)
   Partes 4 y 5. Es parte de por qué la estadística se mudó al FPGA (§6).

> ⚠️ **Y una regla que vale para todo el stack**: al bus de la PL sólo se le
> hacen **loads/stores de 32 bits alineados, uno por vez**. Ni `memcpy`, ni
> NEON, ni nada que agrupe accesos: el esclavo no los reconoce, la transacción
> cuelga el core y **se reinicia la placa**.

---

## 3. Cómo nombra el repo a cada placa

El árbol es un fork de `RedPitaya-FPGA` upstream y arrastra su convención:
un script de Vivado por placa, que fija la parte y un `` `define `` que el RTL
usa para ramificar.

| Script (raíz) | Parte | Defines | Placa |
|---|---|---|---|
| `red_pitaya_vivado_Z10.tcl` | `xc7z010clg400-1` | `Z10` | STEMlab 125-10 / **125-14** |
| **`red_pitaya_vivado_Z10_mca.tcl`** | `xc7z010clg400-1` | `Z10` | **el build de este proyecto** (variante `Z10_2CH`) |
| `red_pitaya_vivado_Z20_14.tcl` | `xc7z020clg400-1` | `Z20_14 Z20_xx` | STEMlab 125-14 Z7020 |
| `red_pitaya_vivado_Z20_4.tcl` | `xc7z020clg400-1` | `Z20_4 Z20_xx` | STEMlab 125-14 4-Input |
| `red_pitaya_vivado_Z20.tcl` | `xc7z020clg400-1` | `Z20_122 Z20_xx` | SDRlab 122-16 |
| `red_pitaya_vivado_Z20_250.tcl` | `xc7z020clg400-3` | `Z20_250` | SIGNALlab 250-12 |
| `red_pitaya_vivado_Z20_G2.tcl` | `xc7z020clg400-1` | `Z20_G2 Z20_xx` | STEMlab 125-14 Pro Z7020 Gen 2 |
| `red_pitaya_vivado_Z20_ll.tcl` | `xc7z020clg400-1` | `Z20_LL` | variante *low latency* (`prj/v0.94_ll`, `sdc_ll/`) |

Qué controla cada define dentro del top:

| Define | Efecto |
|---|---|
| `Z20_122` | `ADW = 16` (ADC de 16 bit) en vez de 14 |
| `Z20_xx` | `DWE = 11`: 22 líneas en E1 en vez de 16 |
| `Z20_G2` | puertos de E3 y de orientación de S1; `i_serlines_add` en el slot 6 |
| `Z20_250` | árbol `rtl_250/` completo |

La parte se ve reflejada en el **nombre del artefacto**: el build del MCA
produce `out/mca_red_pitaya_Z10_2CH.bit.bin`, y la placa va en el nombre
porque un `.bit.bin` no la lleva adentro y cargar uno de 7010 en una 7020 deja
el FPGA manager trabado hasta reiniciar.

---

## 4. Lo que usa este proyecto: STEMlab 125-14, build `Z10_2CH`

La placa del banco es una **STEMlab 125-14 de la generación original**: Zynq
7010, 512 MB, 2 entradas de 14 bit, jumpers en **LV (±1 V)**. Lo que sigue
recorre el top [`mca_red_pitaya_top.sv`](../rtl/mine/tops/mca_red_pitaya_top.sv)
elemento por elemento y dice, para cada pieza de la placa, si el MCA la usa,
la deja instanciada sin usar, o la eliminó.

### 4.1 Resumen

| Elemento de la placa | Estado en el build MCA | Dónde |
|---|---|---|
| ADC IN1 / IN2 (LTC2145-14) | **usado**: es la señal del detector | §4.2 |
| Reloj del ADC + PLL | **usado**: `adc_clk` es el reloj de todo el datapath | §2.4 |
| M_AXI_GP0 → `sys_bus` | **usado**: todos los registros | §4.3 |
| E1 `DIO0_P` | **usado**: trigger externo / **veto del MCA** | §4.6 |
| LEDs | **usado**: `red_pitaya_hk` | slot 0 |
| XADC (temperatura, AI0–AI3) | **usado** desde Linux (IIO). La IP está en la PL y cuelga de GP1, pero ningún módulo del proyecto la lee desde el RTL | §2.3, §2.9 |
| DAC AD9767 | cableado, **salida cero** (ASG eliminado) | §4.4 |
| PWM AO0–AO3 | instanciado (`red_pitaya_ams` + `red_pitaya_pdm`), sin uso | slot 4 |
| S1/S2 daisy | instanciado (`red_pitaya_daisy`), sin uso | slot 5 |
| S_AXI_HP0/HP1 → DDR | cableado al scope, **apagado** por registro | §4.5 |
| S_AXI_HP2/HP3 | en cero | — |
| CAN0/CAN1 | instanciado en `hk`, sin uso | — |
| ASG (slot 2) y PID (slot 3 original) | **eliminados** del top | §4.4 |
| USB-A | **usado desde Linux**: el generador Rigol DG4162 se controla por USB desde la placa | [`puesta_en_marcha.md`](puesta_en_marcha.md) §0 |
| Ethernet | **usado**: ssh, rsync, servidor de la app | ídem |
| microSD | el sistema y el árbol `software/` desplegado | ídem |

### 4.2 El camino de la señal: de IN1 al MCA

```
 IN1 (LV, ±1 V) ─► LTC2145 ─► adc_dat_i[0][15:2] ─► {s, ~b[12:0]} ─► adc_dat[0]  signed 14b @ adc_clk
                                                                        │
                                             ┌──────────────────────────┼─────────────────────┐
                                             ▼                          ▼                     ▼
                                     rp_scope_mt_com    (mt_cfg)     tap → mca_dat_bus
                                     slot 1 · BRAM 2 × 8192       slot 3 · detección          │
                                     EN_FILT = 0                  y trigger_shield       mca_top  slot 7
                                                                                         hist 8192 + 128×64
```

- **Geometría del scope** (top, `SCOPE_*`): 2 canales, 14 bit, `RSZ = 13` ⇒
  **8192 muestras por canal = 65.5 µs a 125 MS/s**. Son 4 RAMB36 por canal. Se
  eligió 13 (y no 14, como el scope original) para liberar BRAM para el MCA.
- **Sin ecualizador** (`EN_FILT = 0`): el `osc_filter` de upstream compensa la
  respuesta del front-end con un IIR que no cierra timing en el 7010. La
  consecuencia es que el MCA ve la respuesta cruda del front-end analógico, que
  para pulsos de µs es plana.
- **Los taps** (`route_*_tap` desde `integration_cfg`, slot 6) eligen qué
  muestra ve cada consumidor: la cruda o una acondicionada. En reset es
  `TAP_NATIVE`, o sea el ADC directo.
- **Escala**: con el jumper en LV, 1 Vpp de pulso ≈ 8192 códigos, y el MCA lo
  mapea a **~3700–3900 canales/Vpp** en el espectro de 8192 canales según la
  ganancia de conformado (medido en [`resultados_validacion_hw.md`](resultados_validacion_hw.md)).
  El jumper HV (±20 V) reduce la resolución de amplitud 20× y no se usa.

### 4.3 El bus y el mapa de slots

`sys_bus_interconnect #(.SN(8), .SW(20))`: 8 esclavos de 1 MB a partir de
`0x4000_0000`, decodificados por `addr[22:20]`. El detalle está en
[`TOP/bus_sistema_redpitaya.md`](TOP/bus_sistema_redpitaya.md); acá sólo el
mapa del build MCA:

| Slot | Dirección | Módulo | Origen |
|---|---|---|---|
| 0 | `0x4000_0000` | `red_pitaya_hk` — LEDs, GPIO de E1, DNA | upstream |
| 1 | `0x4010_0000` | `rp_scope_mt_com` (`osc_cfg`) | propio, sobre el scope de upstream |
| 2 | `0x4020_0000` | libre (ASG eliminado; `event_ring` en el otro top) | — |
| 3 | `0x4030_0000` | `mt_cfg` (PID eliminado) | propio |
| 4 | `0x4040_0000` | `red_pitaya_ams` — PWM | upstream |
| 5 | `0x4050_0000` | `red_pitaya_daisy` | upstream |
| 6 | `0x4060_0000` | `integration_cfg` — ruteo, run/clear, `pll_locked`, geometría | propio |
| 7 | `0x4070_0000` | `mca_top` | propio |

Nota de portabilidad: en la Gen 2 (`Z20_G2`) el slot 6 lo ocupa upstream con
`i_serlines_add`; ahí `integration_cfg` tendría que mudarse (al 2, por ejemplo).

### 4.4 Lo que se quitó y por qué

El top del MCA es una copia de `red_pitaya_top.sv` con cuatro cambios, todos
documentados en su cabecera:

1. `mca_top` en el slot 7.
2. `EN_FILT(0)` en el scope (timing, ver arriba).
3. **Sin `red_pitaya_asg`**: el generador arbitrario no tiene uso en un MCA y
   pagaba ~17 RAMB36 (de 60) más los puertos HP2/HP3.
4. **Sin `red_pitaya_pid`**.

El DAC sigue cableado (ODDRs, relojes, `dac_rst`) porque el XDC y la placa lo
esperan, pero `asg_dat` y `pid_dat` son cero ⇒ **OUT1/OUT2 quedan en 0 V**. El
`digital_loop` del `hk` (ADC → DAC de prueba) sigue funcionando.

### 4.5 DDR y puertos HP: construido, apagado

`rp_scope_mt_com` conserva los `rp_axi_sm` por canal de upstream y el
top los cablea a `axi0_sys` / `axi1_sys` → `axi_master` → `S_AXI_HP0/HP1`
(64 bit, a `adc_clk`). La ruta está verificada pero **apagada por registro**
(`set_axi_en`, offsets `0x5C`/`0x7C` del scope, nunca escritos): el MCA no
necesita formas de onda en DDR porque acumula en BRAM. La discusión de cuándo
convendría encenderla está en
[`API/arquitectura_adquisicion_software.md`](API/arquitectura_adquisicion_software.md)
Parte 5. El otro top del proyecto, `event_ring_red_pitaya_top.sv`, sí usa HP0
para volcar eventos a una región reservada de DDR
([`event_ring/`](event_ring/)).

### 4.6 E1: trigger externo y veto

La única línea digital que el MCA usa es **`DIO0_P`** (pin G17, `exp_p_io[0]`,
3.3 V). Es la entrada `trig_ext` de upstream, y el multitrigger la reutiliza
como **veto del MCA** vía el `trigger_shield` (`SRC_EXT_LVL` → `DST_MCA`):
con la línea en alto, `cnt_total` se congela y `vetotime` avanza. Está en
[`puesta_en_marcha.md`](puesta_en_marcha.md) §9b y en el mapa del multitrigger.
En reset la línea es entrada (registro `0x10` de `hk`), así que no hay que
configurar dirección.

`DIO0_N` puede sacar el trigger del scope hacia afuera (`daisy_mode[1]`), útil
para disparar un osciloscopio externo.

### 4.7 Ocupación del 7010 y timing

Reporte post-route del build vigente
([`out/post_route_util.rpt`](../out/post_route_util.rpt),
[`out/post_route_timing_summary.rpt`](../out/post_route_timing_summary.rpt)):

| Recurso | Usado | Disponible (7010) | % |
|---|---|---|---|
| LUT | 8 650 (8 203 lógica + 447 memoria) | 17 600 | 49.2 |
| Flip-flops | 9 949 | 35 200 | 28.3 |
| Slices ocupados | 3 317 (2 165 SLICEL + 1 152 SLICEM) | 4 400 | 75.4 |
| Block RAM (tiles) | 25 (24 × RAMB36 + 2 × RAMB18) | 60 | 41.7 |
| DSP48E1 | 4 | 80 | 5.0 |
| IOB | 95 | 100 | 95.0 |
| BUFG | 9 | 32 | 28.1 |
| PLLE2_ADV | 1 | 2 | 50.0 |

| Timing | Valor |
|---|---|
| WNS setup | **+0.006 ns** (todas las restricciones cumplidas) |
| WHS hold | +0.033 ns |
| Endpoints | 29 332 |

> **El 75 % de slices contra el 49 % de LUT no es contradictorio**: Vivado
> reparte la lógica en más slices de los mínimos necesarios para aflojar el
> ruteo. El recurso que primero se agota en esta placa **no es la lógica sino
> el pin**: 95 de 100 IOB.

Dónde va la BRAM: 8 RAMB36 en la captura del scope (2 canales × 4), el
histograma 1D del MCA (8192 canales × contador de 32 bit = 8 RAMB36), el mapa
2D (128 × 64) y las FIFOs/CDC del bus. Los 4 DSP los infiere Vivado para
sumas y acumuladores anchos: **ni el MCA ni el multitrigger tienen
multiplicadores explícitos** (la división del PSD y el conformador se hicieron
adrede con cadenas de acarreo, ver
[`mca/decisiones_diseno_mca.md`](mca/decisiones_diseno_mca.md)); el único
bloque con multiplicadores de verdad, el ecualizador `osc_filter`, quedó fuera
del build.

El margen de 6 ps está dominado por un camino interno del PS7 (XADC a
200 MHz) que no depende del RTL; el script de build corre `phys_opt_design`
post-route sólo si ese camino cae negativo. Ese margen **se mueve entre builds**
—fue de 50 ps en una corrida anterior— porque depende de cómo caiga la
colocación del resto del diseño: es el síntoma de que el camino crítico no es
nuestro.

### 4.8 El lado del software: lo que puso este proyecto

§2.12 es el inventario de lo que da el proyecto original de Red Pitaya. Esta
sección es la otra mitad: **con qué de eso nos quedamos, qué descartamos y qué
hubo que escribir**. La arquitectura del software como pieza de software —los
siete niveles, los hilos, los tipos— está en
[`API/arquitectura_software.md`](API/arquitectura_software.md); acá sólo la
frontera con la plataforma.

#### El entorno, tal como viene

Lo heredado sin tocar, que es el piso sobre el que corre todo lo demás:

| | |
|---|---|
| OS | Red Pitaya OS 2.00 (Ubuntu ARM), kernel 5.15-xilinx |
| Python en la placa | 3.10, NumPy; `import rp` sólo para los tests que necesitan hardware |
| Acceso a la PL | `/dev/mem` + `mmap` (una región por slot); sin driver |
| Carga del bitstream | `fpgautil` → `/sys/class/fpga_manager/fpga0`, con `.bit.bin` de `bootgen` |
| Red | Ethernet 1 Gbit: `ssh pitaya`, `rsync` del árbol `software/`, servidor de la GUI |
| USB-A | host del **Rigol DG4162** (USBTMC manejado desde Python, sin `/dev/usbtmc`) |
| Consola | UART0 por el micro-USB, 115200 8N1 — para cuando la red no levanta |
| RAM útil | ~461 MB: alcanza para el servidor y NumPy; no para clonar el repo entero |

El FSBL, U-Boot y el device tree base **no se tocan**: lo único que el proyecto
le agrega al arranque es el overlay de la PL (§2.11).

#### Qué tomamos de la plataforma y qué descartamos

La columna «Origen» repite la división de §2.12: **[std]** Linux estándar,
**[RP]** propio de Red Pitaya. Leída de arriba abajo dice algo útil: **casi
todo lo que tomamos es `[std]`, y casi todo lo que descartamos es `[RP]`**.

| Pieza de fábrica (§2.12) | Origen | Decisión | Por qué |
|---|---|---|---|
| `fpga_manager` / `fpga_bridge` | [std] | **tomado** | es el único camino para recargar la PL en caliente; `API/fpga.py` lo envuelve y agrega la guarda de modelo |
| `fpgautil` | [RP] (de Xilinx, empaquetada) | **tomado** | hace el par programar-PL + aplicar-overlay en un comando; se resuelve a mano porque no está en el `PATH` de un shell no interactivo |
| `monitor` | [RP] | **tomado sólo `-f`** | leer el modelo de la EEPROM evita cargar un bitstream de otro Zynq, que deja el FPGA manager trabado. Para registros no sirve: un proceso por acceso es inviable, va `/dev/mem` |
| `librp` + binding `rp` | [RP] | **tomado para el camino de formas de onda** | `rp_AcqGetDataPosV` ya resuelve la lectura de la BRAM del scope y reescribirlo no se justificaba. El precio está asumido: la ventana legacy del slot 1 y ~35 µs por llamada (§2.12) |
| `reserved-memory` (el mecanismo) | [std] | **tomado** | es la forma estándar de apartar DDR de Linux, y el `event_ring` necesita una región que el kernel no toque |
| …las regiones concretas (`labuf`) | [RP] | **tomado prestado** | el ring escribe en `labuf@a000000` (32 MB) para no tener que tocar el device tree. **Es prestada**: si alguna vez corre el analizador lógico a la vez, se pisan; para producción corresponde un nodo propio |
| IIO (XADC) | [std] | **tomado** | la temperatura del die como archivo, sin gastar un slot ni lógica de la PL |
| JupyterLab | [std] (RP lo empaqueta) | **tomado como banco de pruebas** | editar y correr en la placa, con gráficos, es lo más rápido para un ensayo. Y es el culpable habitual del SIGBUS: ver la regla de abajo |
| `rp_overlay` | [RP] | **heredado, no adoptado** | sólo lo usa [`guardado_mariana.py`](../software/campanas/guardado_mariana.py); el código nuevo carga el bitstream por `API/fpga.py` |
| API de *deep memory* (`rp_AcqAxi*`) | [RP] | **descartado** | supone el bitstream de fábrica. El ring vuelca a DDR desde su propio RTL, por HP0 |
| EEPROM de calibración / `calib` | [RP] | **descartado** | da volts, y lo que el MCA necesita es su eje de canales, que se calibra contra el generador ([`resultados_validacion_hw.md`](resultados_validacion_hw.md)) |
| `scpi-server` | [RP] | **descartado** | la Pitaya no es el instrumento que se controla, es el instrumento. SCPI sí se usa, pero **contra el Rigol** |
| Aplicaciones web + marketplace | [RP] | **descartado** | el bitstream no es el de fábrica, así que no funcionarían igual, y ninguna sabe de histogramas. En su lugar está `mcamon` |
| nginx | [std] | **descartado** | no hay nada que servir: la GUI es PyQt5 en la PC y habla TCP, no HTTP |

Las dos excepciones a la regla son las que vale la pena recordar: **`librp` es
lo único de Red Pitaya que está en el camino de medición** —y por eso es lo que
condiciona el RTL (§2.12)—, y **`fpgautil` + `monitor` son lo único de Red
Pitaya que está en el camino de puesta en marcha**.

#### Qué escribimos nosotros

El árbol [`software/`](../software/) — **107 archivos `.py`, ~34 600 líneas**
(medido el 2026-10-10). Es todo Python salvo un archivo: el bench
[`bench_reader_c.c`](../software/API/bench/bench_reader_c.c), que existe para
medir el techo del camino GP+BRAM sin el intérprete de por medio (los 19.2 µs
por evento de §2.12) y **no forma parte del camino de medición**.

| Parte | Tamaño | Qué es | Documento |
|---|---|---|---|
| [`API/`](../software/API/) | 49 arch., ~15 650 líneas | el driver y los handles: `mmap` por slot, `w32`/`r32`, `MCA`, `Osciloscope`, `MultiTrigger`, `Integration`, `RingSource`, sus *fakes*, el análisis (picos, FWHM, DNL, FOM, tau) y el bring-up [`fpga.py`](../software/API/fpga.py) | [`API/arquitectura_software.md`](API/arquitectura_software.md), [`API/referencia_api.md`](API/referencia_api.md) |
| [`API/osciloscope_store/`](../software/API/osciloscope_store/) | (dentro de `API/`) | el pipeline de adquisición y guardado: `EventSource`, `ReaderThread`, `ChunkWriter`, `AcquisitionSession` | [`API/arquitectura_adquisicion_software.md`](API/arquitectura_adquisicion_software.md) |
| [`app/`](../software/app/) | 13 arch., ~5 550 líneas | **lo que reemplaza a las aplicaciones web**: `mca_server` en la placa + `mcamon` (PyQt5) en la PC, por **TCP 1001**, con sus seis paneles | [`APP/README.md`](APP/README.md), [`APP/protocolo.md`](APP/protocolo.md) |
| [`campanas/`](../software/campanas/) | 21 arch., ~7 550 líneas | los drivers de campaña: e2e de espectro, deriva, barridos de tasa, estímulo del Rigol, testbenches de hardware | [`resultados_validacion_hw.md`](resultados_validacion_hw.md) |
| [`monte-carlo/`](../software/monte-carlo/) | 11 arch., ~5 400 líneas | el modelo de referencia: pile-up, tiempo muerto, formas, réplica vectorizada del RTL | [`mca/apilamiento.md`](mca/apilamiento.md), [`mca/tiempo_muerto.md`](mca/tiempo_muerto.md) |
| [`mca/`](../software/mca/) | 8 arch., 127 líneas | *shims* de compatibilidad del refactor (el paquete se mudó a `API/osciloscope_store/`) | [`API/decisiones_del_refactor.md`](API/decisiones_del_refactor.md) |
| [`release/`](../software/release/) | `instalar.sh` + `LEEME.md` | el paquete instalable para quien sólo quiere usar el sistema | [`publicar_release.md`](publicar_release.md) |
| [`Makefile`](../software/Makefile) | — | los `placa-*` (deploy, carga, estado) y los `verificar-*` (29 archivos de test, la suite offline corre en la PC) | [`puesta_en_marcha.md`](puesta_en_marcha.md) |

Las dos piezas que más se parecen a «driver» son propias y están donde la
plataforma no llegaba: el **acceso de 32 bits** con sus dos reglas —escritura
por slice y lectura palabra por palabra, porque `pack_into` y `memcpy` cuelgan
el bus— y el **bring-up** de `fpga.py`, que baja los puentes AXI, reprograma,
los sube y después pregunta si el bus está vivo **desde un proceso hijo**, para
que un SIGBUS mate al hijo y no a la sesión.

#### La regla de operación que atraviesa todo

> **Un solo proceso mapeando `/dev/mem` a la vez.** No hay servicios que
> apagar (ni nginx, ni el servidor web, ni el `scpi-server`): lo que rompe son
> dos procesos mapeados a la vez, típicamente un kernel de Jupyter que hizo
> `rp_Init()` y un `mca_server` viejo. El síntoma es **SIGBUS sin traceback**,
> y si GP0 llegó a abortar una vez queda trabado hasta reiniciar la placa.
> Ver [`puesta_en_marcha.md`](puesta_en_marcha.md) §2.

Cómo se conecta todo y en qué orden está en
[`puesta_en_marcha.md`](puesta_en_marcha.md); la API en
[`API/guia_de_uso.md`](API/guia_de_uso.md).

---

## 5. Qué cambiaría en otra placa

Para cada modelo, lo que habría que tocar para correr el MCA. Ordenado de
menos a más trabajo.

| Placa | Cambios | Qué se gana |
|---|---|---|
| **STEMlab 125-14 Z7020** | otra parte (`xc7z020clg400-1`), `DWE = 11`, mismo top, mismo XDC (más los 6 pares extra de E1). Nuevo `ip/systemZ20_14.tcl` (ya está). | 3× lógica, 2.3× BRAM: **más instancias de MCA**, `RSZ = 14`, ring en DDR sin apretar |
| **125-14 Pro Gen 2 (7010)** | igual al build actual salvo el XDC de la Gen 2 (`sdc/red_pitaya_G2.xdc` ya existe) | front-end nuevo, USB-C |
| **125-14 Pro Z7020 Gen 2** | `Z20_G2`: mover `integration_cfg` del slot 6; E3 disponible | **reloj de ADC externo** (ataca la deriva), 1 GB, 22 GPIO, LVDS |
| **125-14 4-Input** | otro top sobre `red_pitaya_top_4ADC.sv`, un PS7 propio (`ip/systemZ20_4.tcl`, que en `prj/MCA/ip/` todavía no existe), otro XDC (`sdc/red_pitaya_4ADC.xdc`, ya está), `SCOPE_N_CH = 4` | 4 detectores a la vez; sin DAC (no importa) |
| **SDRlab 122-16** | `ADW = 16` y **rehacer el acondicionamiento**: acoplamiento AC a 300 kHz | 16 bit no sirven de nada con la entrada diferenciada; no recomendable |
| **SIGNALlab 250-12** | árbol `rtl_250/` completo; el MCA a 250 MHz probablemente no cierre timing sin re-pipelinear | 2× tasa: tiempos de subida más finos; 12 bit es menos resolución de amplitud |

Lo que **no** cambia en ninguna: el bus de registros y su contrato, el mapa de
slots (salvo el 6 en Gen 2), la codificación del ADC, el hecho de que el reloj
de muestreo es el reloj del datapath, y el flujo de carga por `fpga_manager`.

### Y si se sale de la familia Red Pitaya

En cualquier placa de la tabla, **todo el software de fábrica sigue estando**,
así que el lado software no es parte del problema. La pregunta interesante es
la otra: qué pasa en un Zynq que **no** sea Red Pitaya. La respuesta sale de la
división de §2.12: se conserva todo lo `[std]` —`/dev/mem`, `fpga_manager`, IIO,
`reserved-memory`, la distro— y hay que reemplazar lo `[RP]`, que para este
proyecto se reduce a tres cosas:

| Qué se pierde | Qué habría que hacer |
|---|---|
| la imagen que arranca sola (FSBL, U-Boot, kernel y device tree de la placa) | armarla: es el trabajo grande, y es el que la plataforma hoy regala |
| `librp` + el binding `rp` | reescribir el camino de lectura de formas de onda sobre `/dev/mem` — y de paso **desaparece el motivo de la ventana legacy del slot 1** (`EN_LEGACY_MAP = 0`) |
| `fpgautil` y `monitor -f` | `fpgautil` es de Xilinx y se consigue; la guarda de modelo por EEPROM hay que rehacerla contra lo que exponga la placa nueva |

Lo que **no** habría que tocar: el RTL (es Zynq-7000 genérico salvo pines y
relojes), ni la API, ni la aplicación — porque están apoyadas en la mitad
`[std]`.

---

## 6. Limitaciones de la plataforma que este proyecto ya chocó

Para no redescubrirlas:

| Limitación | Dónde se sintió | Referencia |
|---|---|---|
| **El oscilador de 125 MHz deriva con la temperatura** y no hay entrada de reloj externo en la Gen 1 | es el límite activo de la resolución del MCA (×38 sobre su tolerancia) | [`mca/limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md) |
| **El bus de registros no tiene ráfagas**: 16 k muestras = 16 k transacciones, cada una con CDC | ~683 µs de tiempo muerto por evento leyendo formas de onda; motivó mover la estadística al FPGA | [`mca/decisiones_diseno_mca.md`](mca/decisiones_diseno_mca.md) §1 |
| **Un esclavo que no responde `ack` cuelga GP0** hasta reiniciar | el refactor de registros | [`TOP/bus_sistema_redpitaya.md`](TOP/bus_sistema_redpitaya.md) §7 |
| **60 RAMB36 en el 7010** | decidió `RSZ = 13`, sacar el ASG, y el tamaño del mapa 2D | §4.4, §4.7 |
| **El IIR del ecualizador de upstream no cierra timing en el 7010** | `EN_FILT = 0` | cabecera del top |
| **Cargar el bitstream con `/dev/mem` mapeado traba GP0** | una sesión perdida; orden fijo en el arranque | [`puesta_en_marcha.md`](puesta_en_marcha.md) §2 |
| **`fpgautil` no acepta el `.bit` de Vivado** | `bootgen` en línea en el script de build | [`red_pitaya_vivado_Z10_mca.tcl`](../../../red_pitaya_vivado_Z10_mca.tcl) |
| **El kernel de la placa no trae `usbtmc`** | el Rigol se maneja por USB crudo desde Python | [`puesta_en_marcha.md`](puesta_en_marcha.md) §0 |
| **461 MB de RAM** | no se clona el repo en la placa; se sincroniza `software/` | ídem §3 |
| **`librp` es cerrada y usa offsets fijos**: el mapa del scope no se puede mover | obligó a la ventana de compatibilidad legacy del slot 1 (100–200 LUT) | §2.12, [`osc/register_map_osc.md`](osc/register_map_osc.md) |
| **~35 µs fijos por llamada dentro de `librp`** | techo de 3.7 kev/s desde Python; el mismo ciclo en C da ×14 | §2.12, [`API/arquitectura_adquisicion_software.md`](API/arquitectura_adquisicion_software.md) Parte 4 |
| **Al bus de la PL, sólo loads/stores de 32 bits alineados**: un `memcpy` cuelga el core y reinicia la placa | descartó el camino de lectura rápida desde Python | ídem |
| **Dos procesos sobre `/dev/mem` ⇒ SIGBUS sin traceback** | un kernel de Jupyter vivo alcanza para arruinar una sesión | §4.8, [`puesta_en_marcha.md`](puesta_en_marcha.md) §2 |
| **`monitor -f` sin permiso de EEPROM imprime `undefined` con código de salida 0** | hay que descartar ese valor a mano o se toma por el nombre de un modelo | [`API/fpga.py`](../software/API/fpga.py) |

---

## 7. Glosario rápido

| Término | Significado acá |
|---|---|
| **PS / PL** | *Processing System* (los ARM y sus periféricos) / *Programmable Logic* (la FPGA) del Zynq |
| **GP0 / HP0..3** | puertos AXI del PS: *General Purpose* (registros, 32 bit) / *High Performance* (a DDR, 64 bit) |
| **`sys_bus`** | el bus simple de Red Pitaya que cuelga de GP0 y se reparte en 8 slots |
| **`adc_clk`** | el reloj de 125 MHz derivado del ADC; reloj del datapath |
| **`fclk[0]`** | el reloj de 125 MHz del PS; reloj del bus de registros |
| **LV / HV** | posición de los jumpers de entrada: ±1 V / ±20 V |
| **E1 / E2 / E3** | conectores de expansión: digital / analógico lento / (Gen 2) LVDS y boot |
| **S1 / S2** | conectores de daisy chain (SATA en Gen 1, USB-C en Gen 2) |
| **MIO / EMIO** | las dos salidas posibles de un periférico del PS: pines dedicados (anda con la PL vacía) / a través de la PL (sólo existe si el bitstream lo rutea) — §2.10.5 |
| **XADC** | el ADC lento de 12 bit interno del Zynq: entradas AI0–AI3 y temperatura. Acá es una IP **en la PL** colgada de GP1, no la interfaz del PS (§2.9) |
| **MGT** | transceptores multi-gigabit: **no existen en el 7010/7020**, por eso la daisy chain es LVDS por SelectIO (§2.9) |
| **`Z10` / `Z20_*`** | los defines del repo que eligen placa (§3) |
| **`Z10_2CH`** | la variante del bitstream del MCA: 7010, dos canales |
| **RP OS** | el sistema de fábrica de la microSD: Ubuntu ARM con kernel Xilinx y todo el stack de §2.12 |
| **`librp`** | la librería C cerrada de Red Pitaya que maneja el bitstream de fábrica por offsets fijos; `import rp` es su binding Python |
| **`fpgautil` / `monitor`** | las dos herramientas de shell del RP OS que usa el proyecto: programar la PL y leer el modelo de la EEPROM |

---

## 8. Fuentes

Documentación oficial de Red Pitaya (consultada en septiembre de 2026):

- Comparativa de la generación original:
  <https://redpitaya.readthedocs.io/en/latest/developerGuide/hardware/compares/vs.html>
- STEMlab 125-14 (Gen 1):
  <https://redpitaya.readthedocs.io/en/latest/developerGuide/hardware/ORIG_GEN/125-14/top.html>
- STEMlab 125-14 Gen 2:
  <https://redpitaya.readthedocs.io/en/latest/developerGuide/hardware/GEN2/125-14_Gen2/top.html>
- STEMlab 125-14 Pro Gen 2:
  <https://redpitaya.readthedocs.io/en/latest/developerGuide/hardware/GEN2/125-14_Gen2_Pro/top.html>
- STEMlab 125-14 Pro Z7020 Gen 2:
  <https://redpitaya.readthedocs.io/en/latest/developerGuide/hardware/GEN2/125-14_Gen2_Z7020_Pro/top.html>

Del lado del software (§2.12), las aplicaciones web, el control remoto por SCPI
y las APIs de C y Python viven en la sección **"Applications and Features"** de
la misma documentación (<https://redpitaya.readthedocs.io/>); las filas de la
tabla de §2.12 que dicen "doc oficial" salen de ahí y son las que **este
proyecto no usa**, así que no están verificadas contra el banco. Todas las
demás llevan su referencia al repo.

Del repo: [`sdc/red_pitaya.xdc`](../../../sdc/red_pitaya.xdc) (pines y
relojes), [`rtl/red_pitaya_pll.sv`](../../../rtl/red_pitaya_pll.sv) (PLL),
[`ip/systemZ10.tcl`](../ip/systemZ10.tcl) (PS7 y XADC),
[`rtl/red_pitaya_ps.sv`](../rtl/red_pitaya_ps.sv) (puertos AXI),
[`rtl/mine/tops/mca_red_pitaya_top.sv`](../rtl/mine/tops/mca_red_pitaya_top.sv)
(el top), [`out/`](../out/) (reportes de Vivado: `post_imp_io.rpt` para bancos y
estándares de I/O, `build_Z10_2CH.log` para las advertencias del build).

De Xilinx/AMD: los recursos de los XC7Z010/XC7Z020 son de la hoja de datos
**DS190**; el inventario de interfaces de §2.7 —y su reparto en las tres
fronteras de §2.8 a §2.10— sigue la **figura 10.1 de
la UG585** (*Zynq-7000 SoC Technical Reference Manual*), "Zynq-7000 AP SoC
interfaces, signals and pins", contrastada contra lo que el block design
realmente conecta.

# La plataforma: la familia Red Pitaya y lo que este proyecto usa de ella

Qué hay en una Red Pitaya, en qué se diferencian los modelos entre sí, y
—con mucho más detalle— qué partes de la placa toca el MCA y cómo. Es el
documento para leer antes de preguntarse "¿esto anda en la otra placa?" o
"¿por qué el ADC entrega esto?".

Está en dos mitades:

- **§1–§3** son la familia: tabla comparativa, la arquitectura común (Zynq,
  front-end, relojes, conectores) y cómo el repo nombra cada variante.
- **§4–§7** es **este proyecto**: la STEMlab 125-14 del banco, elemento por
  elemento, con los números del bitstream `Z10_2CH` y lo que habría que cambiar
  para llevarlo a otra placa.

Los números de la familia salen de la documentación oficial (enlaces en §8); los
del proyecto salen del RTL, del XDC y de los reportes de Vivado que están en el
repo, y cada uno lleva su referencia. Si un número de acá no coincide con el
archivo al que apunta, el que manda es el archivo.

Documentos hermanos, para no duplicar:

| Documento | Qué contiene |
|---|---|
| [`movimiento_de_datos.md`](movimiento_de_datos.md) | el overlay sobre este diagrama: qué mueve, cuánta CPU cuesta y cuánto ajuste lleva cada conexión |
| [`TOP/bus_sistema_redpitaya.md`](TOP/bus_sistema_redpitaya.md) | el bus de registros GP0 → `sys_bus`, en detalle |
| [`TOP/register_map_top.md`](TOP/register_map_top.md) | el mapa de los 8 slots |
| [`puesta_en_marcha.md`](puesta_en_marcha.md) | el montaje del banco y el orden de arranque |
| [`mca/fuentes_de_jitter.md`](mca/fuentes_de_jitter.md) | el reloj y el ADC vistos desde la resolución temporal |
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

Para el MCA lo relevante de la Gen 2 es (a) el **reloj de ADC externo** de la
Pro Z7020, que ataca directamente el límite que hoy ata la resolución del
instrumento —la deriva del oscilador, ver
[`mca/limites_resolucion_y_deriva.md`](mca/limites_resolucion_y_deriva.md)—, y
(b) que el repo ya la contempla como variante `Z20_G2` (§3), con una salvedad
en el mapa de slots (§4.3).

### 1.3 Los dos Zynq

El "7010 contra 7020" es la diferencia de fondo entre modelos: mismo ARM,
cuatro veces más FPGA.

| Recurso de la PL | XC7Z010 | XC7Z020 | ×  |
|---|---|---|---|
| Celdas lógicas | 28 k | 85 k | 3.0 |
| LUT6 | 17 600 | 53 200 | 3.0 |
| Flip-flops | 35 200 | 106 400 | 3.0 |
| Block RAM (RAMB36) | 60 (2.1 Mb) | 140 (4.9 Mb) | 2.3 |
| DSP48E1 | 80 | 220 | 2.75 |
| PLL / MMCM | 2 / 2 | 4 / 4 | 2 |

En los dos el PS es el mismo: **2 × ARM Cortex-A9 @ 667 MHz** (grado -1), NEON,
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

| | Valor | Fuente |
|---|---|---|
| ADC | Analog Devices (ex-Linear) **LTC2145-14**: dual, 14 bit, 125 MS/s, salida paralela CMOS 1.8 V | doc oficial; XDC (`LVCMOS18`) |
| Rango a fondo de escala | **±1 V** (jumper LV) o **±20 V** (jumper HV), por canal, DC | doc oficial |
| Máximo absoluto | ±6 V (LV) / ±30 V (HV) | doc oficial |
| Impedancia de entrada | 1 MΩ ‖ 10 pF | doc oficial |
| Ancho de banda | DC–60 MHz (la doc vieja decía 50 MHz) | doc oficial |
| Resolución | 2 V / 16384 = **122 µV por código en LV** ⇒ ≈ 8192 códigos por volt | derivado |
| SNR / jitter de apertura | ≈ 73 dB · ≈ 0.1 ps rms | hoja de datos, citada en [`mca/fuentes_de_jitter.md`](mca/fuentes_de_jitter.md) |
| Codificación | offset binary de **pendiente negativa**: el top la convierte a complemento a 2 | [`mca_red_pitaya_top.sv`](../rtl/mine/tops/mca_red_pitaya_top.sv), bloque *ADC IO* |

Dos detalles de la interfaz que el RTL hereda de la placa:

- **Cada canal entra por 16 pines aunque el ADC tenga 14 bits.** Los dos bits
  bajos están reservados para la 122-16 (16 bit). El top toma
  `adc_dat_i[ch][15 -: ADW]` con `ADW = 14` en la 125-14 y `16` bajo
  `` `ifdef Z20_122 ``.
- **La pendiente es negativa**: un voltaje mayor da un código menor. Por eso el
  top hace `{raw[13], ~raw[12:0]}`: invierte los 13 bits bajos y deja el signo,
  lo que en un solo paso pasa de offset-binary-negativo a complemento a 2. Todo
  lo que está aguas abajo (scope, multitrigger, MCA) ve **signed 14 bit**.

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
| 3 | 200 MHz | el XADC dentro del PS7 (es el camino de 7 ps de slack del que habla el script de build) |

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

| Señal | Puerto del top | Pines Zynq (125-14) | Función alternativa |
|---|---|---|---|
| DIO0_P … DIO7_P | `exp_p_io[7:0]` | G17, H16, J18, K17, L14, L16, K16, M14 | `DIO0_P` = **trigger externo** (`trig_ext`) · `DIO6_P`/`DIO7_P` = CAN1/CAN0 RX |
| DIO0_N … DIO7_N | `exp_n_io[7:0]` | G18, H17, H18, K18, L15, L17, J16, M15 | `DIO0_N` = **salida de trigger** (si `daisy_mode[1]`) · `DIO6_N`/`DIO7_N` = CAN1/CAN0 TX |
| +3.3 V × 2 | — | — | 0.5 A cada una |

LVCMOS33, `DRIVE 8`, `SLEW FAST`. La dirección de cada línea la fija
`red_pitaya_hk` (slot 0, registro `0x10`); en reset todas son **entrada**. En
la 7020 (`DWE = 11`) hay 22 líneas (`DIO0..10`); en la 7010 (`DWE = 8`), 16.

**E2 — analógico y comunicaciones**: AI0–AI3 (XADC), AO0–AO3 (PWM), SPI, UART,
I2C, y rieles +5 V / +3.3 V / −3.4 V. UART e I2C salen por MIO del PS (no por la
PL); SPI0 va por EMIO.

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

### 2.6 El PS: periféricos y memoria

Lo que el block design ([`ip/systemZ10.tcl`](../ip/systemZ10.tcl)) le enciende
al PS7, y por dónde sale cada cosa:

| Periférico | Salida | Para qué |
|---|---|---|
| DDR3 | dedicado | 1 × **MT41J256M16** (4 Gb, x16) = 512 MB, `DDR_RAM_HIGHADDR 0x1FFF_FFFF` |
| QSPI | MIO 1–6 | flash de boot (`boot.bin` alternativo) |
| SD0 | MIO 40–45 (+CD 46, WP 47) | microSD: **es el disco del sistema** |
| Ethernet 0 | MIO 16–27, MDIO 52–53 | RGMII, 1 Gbit |
| USB 0 | MIO (ULPI) | host USB-A |
| UART 0 | MIO 14–15 | **consola serie** (micro-USB en la placa, 115200 8N1) |
| UART 1 | MIO 8–9 | E2 |
| I2C 0 | MIO 50–51 | **EEPROM de calibración** y E2 |
| SPI 1 | MIO 10–15 | — |
| SPI 0 | EMIO | E2 |
| CAN 0/1 | EMIO → E1 | vía `red_pitaya_hk` (`can_on`) |
| Interrupciones F2P | — | habilitadas (`PCW_USE_FABRIC_INTERRUPT`); sin uso en el MCA |

Y los puertos AXI entre PS y PL:

| Puerto | Rol | Reloj | Uso |
|---|---|---|---|
| **M_AXI_GP0** | PS → PL, 32 bit | `fclk[0]` 125 MHz | **el bus de registros**: `0x4000_0000`, ventana de 1 GB, 8 slots de 1 MB (§4.3) |
| M_AXI_GP1 | PS → PL | — | habilitado, sin conectar |
| **S_AXI_HP0..3** | PL → DDR, **64 bit** | HP0/1 a `adc_clk`, HP2/3 a `dac_axi_clk` | streaming a DDR: HP0/HP1 cableados al scope (apagados en el MCA, §4.5); HP2/HP3 en cero |
| S_AXI_ACP | — | — | no habilitado |

La **EEPROM de calibración** guarda ganancia y offset de cada canal de ADC y
DAC, en LV y HV; el formato está en [`doc/calibregs.adoc`](../../../doc/calibregs.adoc).
El MCA no la lee: calibra su propio eje de canales contra el generador
([`resultados_validacion_hw.md`](resultados_validacion_hw.md)).

### 2.7 Arranque, sistema operativo y carga de la PL

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
| XADC (temperatura, AI0–AI3) | **usado** desde Linux (IIO), no desde la PL | §2.3 |
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
                                     rp_scope_multitrigger_com    (multitrigger_cfg)     tap → mca_dat_bus
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
| 1 | `0x4010_0000` | `rp_scope_multitrigger_com` (`osc_cfg`) | propio, sobre el scope de upstream |
| 2 | `0x4020_0000` | libre (ASG eliminado; `event_ring` en el otro top) | — |
| 3 | `0x4030_0000` | `multitrigger_cfg` (PID eliminado) | propio |
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

`rp_scope_multitrigger_com` conserva los `rp_axi_sm` por canal de upstream y el
top los cablea a `axi0_sys` / `axi1_sys` → `axi_master` → `S_AXI_HP0/HP1`
(64 bit, a `adc_clk`). La ruta está verificada pero **apagada por registro**
(`set_axi_en`, offsets `0x5C`/`0x7C` del scope, nunca escritos): el MCA no
necesita formas de onda en DDR porque acumula en BRAM. La discusión de cuándo
convendría encenderla está en
[`multitrigger/arquitectura_adquisicion_software.md`](multitrigger/arquitectura_adquisicion_software.md)
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
| LUT | 8 033 | 17 600 | 45.6 |
| Flip-flops | 9 178 | 35 200 | 26.1 |
| Block RAM (tiles) | 25 (24 × RAMB36 + 2 × RAMB18) | 60 | 41.7 |
| DSP48E1 | 4 | 80 | 5.0 |

| Timing | Valor |
|---|---|
| WNS setup | **+0.050 ns** (todas las restricciones cumplidas) |
| WHS hold | +0.024 ns |
| Endpoints | 26 416 |

Dónde va la BRAM: 8 RAMB36 en la captura del scope (2 canales × 4), el
histograma 1D del MCA (8192 canales × contador de 32 bit = 8 RAMB36), el mapa
2D (128 × 64) y las FIFOs/CDC del bus. Los 4 DSP los infiere Vivado para
sumas y acumuladores anchos: **ni el MCA ni el multitrigger tienen
multiplicadores explícitos** (la división del PSD y el conformador se hicieron
adrede con cadenas de acarreo, ver
[`mca/decisiones_diseno_mca.md`](mca/decisiones_diseno_mca.md)); el único
bloque con multiplicadores de verdad, el ecualizador `osc_filter`, quedó fuera
del build.

El margen de 50 ps está dominado por un camino interno del PS7 (XADC a
200 MHz) que no depende del RTL; el script de build corre `phys_opt_design`
post-route sólo si ese camino cae negativo.

### 4.8 El lado del software

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
| **XADC** | el ADC lento de 12 bit interno del Zynq: entradas AI0–AI3 y temperatura |
| **`Z10` / `Z20_*`** | los defines del repo que eligen placa (§3) |
| **`Z10_2CH`** | la variante del bitstream del MCA: 7010, dos canales |

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

Del repo: [`sdc/red_pitaya.xdc`](../../../sdc/red_pitaya.xdc) (pines y
relojes), [`rtl/red_pitaya_pll.sv`](../../../rtl/red_pitaya_pll.sv) (PLL),
[`ip/systemZ10.tcl`](../ip/systemZ10.tcl) (PS7 y XADC),
[`rtl/red_pitaya_ps.sv`](../rtl/red_pitaya_ps.sv) (puertos AXI),
[`rtl/mine/tops/mca_red_pitaya_top.sv`](../rtl/mine/tops/mca_red_pitaya_top.sv)
(el top), [`out/`](../out/) (reportes de Vivado).
Los recursos de los XC7Z010/XC7Z020 son de la hoja de datos DS190 de Xilinx.

////////////////////////////////////////////////////////////////////////////////
// Red Pitaya TOP module. It connects external pins and PS part with
// other application modules.
// Authors: Matej Oblak, Iztok Jeras
// (c) Red Pitaya  http://www.redpitaya.com
////////////////////////////////////////////////////////////////////////////////

/**
 * GENERAL DESCRIPTION:
 *
 * Top module connects PS part with rest of Red Pitaya applications.  
 *
 *            #== mca_red_pitaya_top (xc7z010) ==============================================#
 *            #                                                                              #
 *            #   /-- red_pitaya_ps ---------------------------------\                       #
 *            #   |   /---------\                                    |                       #
 *     PS DDR #======>|  ZYNQ   | AXI-HP2    /--------------\        |                       #
 *     PS MIO #------>|   PS    | <----------|  axi_master  |        |                       #
 *     PS CLK #------>|  (ARM   |   64 b     |     x 4      |<-------+ axi2_sys, del ring    #
 *            #   |   | + DDRC) |            \--------------/        | (64 b; 0, 1, 3 en 0)  #
 *            #   |   |         |                                    |                       #
 *            #   |   |         | M_AXI_GP0  /--------------\        |                       #
 *            #   |   |         | ---------->|  axi4_slave  |        |                       #
 *            #   |   |         | AXI4-Lite  \--------------/        |                       #
 *            #   |   |         |                   |                |                       #
 *            #   |   \---------/                   | ps_sys (32 b)  |                       #
 *            #   \------|--------------------------|----------------/                       #
 *            #          \--> fclk[0..3], frstn[0..3]                                        #
 *            #                                     v                                        #
 *            #                          /----------------------------------\                #
 *            #                          |      sys_bus_interconnect        |                #
 *            #                          |   1 maestro  ->  8 slots de 1 MiB|                #
 *            #                          |   + CDC  fclk[0]  <->  adc_clk   |                #
 *            #                          \----------------------------------/                #
 *            #                                            | sys[0..7], addr 20 b            #
 *            #                                            +---------------------+           #
 *            #                                                                  |           #
 *            #      /------------------\                                        |           #
 *    DIO exp #<====>|    HK     slot 0 |<---------------------------------------+           #
 *        LED #<-----| led_o, dig_loop  |                                        |           #
 *            #      \------------------/                                        |           #
 *            #                                                                  |           #
 *            #      /------------------\                                        |           #
 *   XADC vin #----->|   AMS     slot 4 |<---------------------------------------+           #
 *            #      \------------------/                                        |           #
 *            #            | pdm_cfg                                             |           #
 *            #            v                                                     |           #
 *            #      /-----------\                                               |           #
 *    PWM DAC #<-----|    PDM    |                                               |           #
 *            #      \-----------/                                               |           #
 *            #                                                                  |           #
 *            #      /------------------\                                        |           #
 *    SATA RX #----->|  DAISY    slot 5 |<---------------------------------------+           #
 *    SATA TX #<-----|  par_dat   16 b  |                                        |           #
 *            #      \------------------/                                        |           #
 *            #                                                                  |           #
 *            #      (slot 2: event_ring -> HP2, y gen_pulsos)                   |           #
 *            #                                                                  |           #
 *            #      /------------------\                                        |           #
 *            #      | integration_cfg  |<---------------------------------------+           #
 *            #      |   slot 6 = TOP   |                                        |           #
 *            #      \------------------/                                        |           #
 *            #          | route_{osc,mtrg,mca}_tap/_en                          |           #
 *            #          +--------------------------------v                      |           #
 *            #      /------------\        /-----------------------------\       |           #
 *            #      |   ANALOG   |------->|  rp_scope_mt_com  |       |           #
 *        ADC #----->| ADC u -> 2c| 14 b   |   OSC  slot 1  0x4010_0000  |<------+           #
 *        DAC #<-----| DAC 2c -> u|        |   MTRG slot 3  0x4030_0000  |<------+           #
 *            #      \------------/        \-----------------------------/       |           #
 *            #            ^  asg: gen_pulsos  |      |        \--> axi0/1_sys   |           #
 *            #               (pid = 0)        |      \--> scope_trigo --> DIO0  |           #
 *            #                                | mca_{dat,val,veto}, trig        |           #
 *            #                                v                                 |           #
 *            #                      /------------------------------\            |           #
 *            #                      |   mca_top        slot 7      |<-----------+           #
 *            #                      |  hist 8192 ch + PSD 128x64   |                        #
 *            #                      \------------------------------/                        #
 *            #==============================================================================#
 *
 * La caja exterior es el modulo: lo que queda a su izquierda son pines
 * fisicos de la placa (PS DDR/MIO/CLK, ADC, DAC, XADC, DIO, SATA, LED), lo de
 * adentro es la logica que instancia este archivo.
 *
 * EL PUENTE AXI <-> BUS CUSTOM (todo dentro de red_pitaya_ps)
 *
 *   Camino de control (lento, lo maneja el ARM):
 *     M_AXI_GP0 -> axi4_slave -> ps_sys -> sys_bus_interconnect -> sys[0..7]
 *   `axi4_slave` traduce AXI4-Lite de 32 b al handshake simple del bus custom
 *   (addr/wdata/wen/ren/rdata/err/ack), y `sys_bus_interconnect` parte
 *   0x4000_0000 en 8 regiones de 1 MiB -- sys[i] vive en 0x40i0_0000 -- y
 *   cruza de fclk[0] a adc_clk. Las 32 restricciones CDC del XDC enganchan por
 *   el nombre de instancia `sys_bus_interconnect`, de ahi que no se renombre.
 *
 *   Camino de datos (rapido, sin pasar por el ARM):
 *     i_event_ring -> axi2_sys -> axi_master -> S_AXI_HP2 -> DDR
 *   `axi_master` convierte las escrituras del bus custom en bursts AXI4 de
 *   64 b contra los puertos HP del PS. Hay cuatro instancias y solo anda la
 *   de HP2. HP0/HP1 eran de la captura AXI del scope, que este top no tiene
 *   (EN_AXI = 0), y HP3 era del ASG: quedan atadas a cero.
 *
 * QUE HAY EN CADA SLOT
 *
 *   0  red_pitaya_hk        LED, digital_loop, daisy_mode, DIO
 *   1  OSC      (i_scope)   adquisicion y decimacion
 *   2  event_ring_top       0x4020_0000: ventanas de evento a la DDR, por HP2
 *      gen_pulsos           0x4021_0000: pulsos al DAC, en el lugar del ASG
 *   3  MTRG     (i_scope)   logica de disparo multitrigger
 *   4  red_pitaya_ams       PDM -> dac_pwm_o
 *   5  red_pitaya_daisy     enlace serie por SATA
 *   6  integration_cfg      ID del bitstream + ruteo del datapath
 *   7  mca_top              histograma 1D y mapa 2D
 *
 *   Los slots 1 y 3 son dos buses de la MISMA instancia: rp_scope_mt_com
 *   expone sys_osc_* y sys_mtrg_* por separado.
 *
 * NOTAS DEL DATAPATH
 *
 * En ANALOG el dato del ADC pasa de unsigned con pendiente negativa a
 * complemento a dos, y al reves en el DAC. Al DAC llega asg_dat, que ahora
 * maneja gen_pulsos (mudo mientras no se prende), y pid_dat en cero: sin PID
 * no hay lazo. El estimulo entra por el ADC desde el generador externo o, con
 * digital_loop[0], desde gen_pulsos sin pasar por el analogico.
 *
 * `i_scope` publica la muestra acondicionada (post-calibracion, pre-decimacion,
 * 125 MSPS) por mca_dat/mca_val, el veto por mca_veto y el OR de todas las
 * fuentes de disparo por scope_trigo -- que alimenta a la vez DIO0, el daisy y
 * el trig_i del MCA.
 *
 * `integration_cfg` (slot 6) no es housekeeping: identifica el bitstream, dice
 * que modulos trae y en que slot vive cada uno, y maneja el ruteo del datapath
 * via route_{osc,mtrg,mca}_tap/_en. Sus ctrl_{run,clear,srst} todavia no tienen
 * consumidor: se cablean a top_run/top_clear/top_srst y ahi terminan.
 */

// =============================================================================
// event_ring_red_pitaya_top — el MCA con el event_ring
//
// GENERADO por gen_event_ring_top.py a partir de mca_red_pitaya_top.sv: no se
// edita a mano. Difiere del top del MCA en cuatro cosas, y en ninguna otra:
//   1. event_ring_top en la mitad baja del slot 2 (0x4020_0000), donde el top
//      del MCA tiene un stub (0x4021_0000 es de gen_pulsos en los dos),
//      escribiendo a la DDR por HP2 (axi2_sys)
//   2. axi2_sys en adc_clk, no en dac_axi_clk (ver su declaracion)
//   3. i_scope con EN_AXI(0): sin la captura a DDR por AXI (rp_axi_sm), que el
//      ring reemplaza. Es lo que hace lugar al ring; ver EN_AXI en
//      rp_scope_mt_com.sv
//   4. integration_cfg con EN_RING(1)
//
// Lo construye red_pitaya_vivado_Z10_v3_event_ring.tcl
// (make bitstream-event-ring), que lo regenera antes de sintetizar.
//
// Lo que sigue es la cabecera del top del MCA, que dice en que difiere el MCA
// de red_pitaya_top.sv.
// =============================================================================
//
// Copia de red_pitaya_top.sv con cuatro diferencias, todas para el MCA:
//   1. mca_top nuevo en el slot 7 del bus (0x4070_0000)
//   2. i_scope con EN_FILT(0): sin el ecualizador osc_filter, cuyo lazo IIR
//      no cierra timing (137 de los 221 endpoints en falla, -1.820 ns)
//   3. sin red_pitaya_asg (slot 2): libera ~17 RAMB36, HP2/HP3 y logica. En
//      su lugar, gen_pulsos (0x4021_0000), que maneja asg_dat y trig_asg_out
//   4. sin red_pitaya_pid (slot 3): sin uso en este flujo
//
// Conserva a proposito la lista de puertos y los nombres de instancia i_ams y
// sys_bus_interconnect, porque el XDC engancha por esos nombres:
//   sdc/red_pitaya.xdc:1   set_property LOC XADC_X0Y0 [get_cells i_ams/...]
//   sdc/red_pitaya.xdc:25+ las 32 restricciones CDC de for_bus[0..7]
//
// red_pitaya_top.sv NO se toca: los dos bitstreams conviven.
// =============================================================================
module event_ring_red_pitaya_top #(
  // identification
  bit [0:5*32-1] GITH = '0,
  // module numbers
  parameter MNA = 2,  // number of acquisition modules
  parameter MNG = 2,  // number of generator   modules
  parameter ADW_125 = 14, // códigos para el modelo? 
  parameter ADW_122 = 16, 
  parameter DWE_Z20 = 11,
  parameter DWE_Z10 = 8,
  parameter DDW     = 14, // Data 
`ifdef Z20_122
  parameter ADW=ADW_122,
  parameter ADC_DW=ADW_122,
`else
  parameter ADW=ADW_125,
  parameter ADC_DW=ADW_125,
`endif
`ifdef Z20_xx
  parameter DWE=DWE_Z20
`else
  parameter DWE=DWE_Z10
`endif


)(
  // PS connections
  inout  logic [54-1:0] FIXED_IO_mio     ,
  inout  logic          FIXED_IO_ps_clk  ,
  inout  logic          FIXED_IO_ps_porb ,
  inout  logic          FIXED_IO_ps_srstb,
  inout  logic          FIXED_IO_ddr_vrn ,
  inout  logic          FIXED_IO_ddr_vrp ,
  // DDR
  inout  logic [15-1:0] DDR_addr   ,
  inout  logic [ 3-1:0] DDR_ba     ,
  inout  logic          DDR_cas_n  ,
  inout  logic          DDR_ck_n   ,
  inout  logic          DDR_ck_p   ,
  inout  logic          DDR_cke    ,
  inout  logic          DDR_cs_n   ,
  inout  logic [ 4-1:0] DDR_dm     ,
  inout  logic [32-1:0] DDR_dq     ,
  inout  logic [ 4-1:0] DDR_dqs_n  ,
  inout  logic [ 4-1:0] DDR_dqs_p  ,
  inout  logic          DDR_odt    ,
  inout  logic          DDR_ras_n  ,
  inout  logic          DDR_reset_n,
  inout  logic          DDR_we_n   ,

  // Red Pitaya periphery

  // ADC
  input  logic [MNA-1:0] [16-1:0] adc_dat_i,  // ADC data
  input  logic           [ 2-1:0] adc_clk_i,  // ADC clock {p,n}
  output logic           [ 2-1:0] adc_clk_o,  // optional ADC clock source (unused) [0] = p; [1] = n
  output logic                    adc_cdcs_o, // ADC clock duty cycle stabilizer
  // DAC
  output logic [ 14-1:0] dac_dat_o  ,  // DAC combined data
  output logic           dac_wrt_o  ,  // DAC write
  output logic           dac_sel_o  ,  // DAC channel select
  output logic           dac_clk_o  ,  // DAC clock
  output logic           dac_rst_o  ,  // DAC reset
  // PWM DAC
  output logic [  4-1:0] dac_pwm_o  ,  // 1-bit PWM DAC
  // XADC
  input  logic [  5-1:0] vinp_i     ,  // voltages p
  input  logic [  5-1:0] vinn_i     ,  // voltages n
  // Expansion connector
  inout  logic [DWE-1:0] exp_p_io  ,
  inout  logic [DWE-1:0] exp_n_io  ,
  // SATA connector
  output logic [  2-1:0] daisy_p_o  ,  // line 1 is clock capable
  output logic [  2-1:0] daisy_n_o  ,
  input  logic [  2-1:0] daisy_p_i  ,  // line 1 is clock capable
  input  logic [  2-1:0] daisy_n_i  ,

  `ifdef Z20_G2
  // Additional E3 connector
  output logic [  4-1:0] exp_e3p_o  ,  // line 3 is clock capable (SRCC)
  output logic [  4-1:0] exp_e3n_o  ,
  input  logic [  4-1:0] exp_e3p_i  ,  // line 3 is clock capable (MRCC)
  input  logic [  4-1:0] exp_e3n_i  ,

  input  logic           s1_orient_i ,
  input  logic           s1_link_i   ,
  `endif
  // LED
  output  logic [  8-1:0] led_o
);

////////////////////////////////////////////////////////////////////////////////
// local signals
////////////////////////////////////////////////////////////////////////////////

// GPIO input data width
localparam int unsigned GDW = DWE;
localparam RST_MAX = 64;

// -----------------------------------------------------------------------------
// Geometria del scope: UNA declaracion, dos consumidores
// -----------------------------------------------------------------------------
// `i_scope` dimensiona con esto la BRAM de captura, e `i_integration` publica
// los mismos numeros para que el software los descubra en vez de suponerlos.
// Estaban escritos como literales en los DOS lugares -- que es exactamente como
// divergio H_AW: el cambio que bajo el eje a 8192 canales toco una copia y se
// olvido de la otra, y no se noto porque nadie leia la que quedo mintiendo.
// Con una sola declaracion no hay dos numeros que puedan discrepar.
//
// RSZ = 13 son 8192 muestras por canal, 65 us a 125 MSPS. Cubre todo lo medido:
// los pulsos de la campana actual son ~250 muestras y los de la campana vieja
// ~7750, que entran con poco margen (~5%). RSZ = 12 los dejaria afuera.
// A cambio libera 4 RAMB36 por canal -- 16 en una placa de cuatro --, que es la
// BRAM con la que se pagan las instancias de MCA que faltan.
localparam int SCOPE_N_CH = 2;
localparam int SCOPE_DW   = 14;
localparam int SCOPE_RSZ  = 13;

logic [4-1:0] fclk ; //[0]-125MHz, [1]-250MHz, [2]-50MHz, [3]-200MHz
logic [4-1:0] frstn;

logic [16-1:0] par_dat;

logic          daisy_trig;
logic [ 3-1:0] daisy_mode;
logic          trig_ext;
logic          trig_output_sel;
logic          trig_asg_out;
logic [ 4-1:0] trig_ext_asg01;



// PLL signals
logic                 adc_clk_in;
logic                 pll_adc_clk;
logic                 pll_dac_clk_1x;
logic                 pll_dac_clk_2x;
logic                 pll_dac_clk_2p;
logic                 pll_ser_clk;
logic                 pll_pwm_clk;
logic                 pll_locked;
logic                 pll_locked_r;
logic                 fpll_locked_r,fpll_locked_r2,fpll_locked_r3;

logic   [16-1:0]      rst_cnt = 'h0;
logic                 rst_after_locked;
logic                 rstn_pll;

// fast serial signals
logic                 ser_clk ;
// PWM clock and reset
logic                 pwm_clk ;
logic                 pwm_rstn;

// ADC clock/reset
logic                 adc_clk;
logic                 adc_rstn;
logic                 adc_clk_daisy;
logic                 scope_trigo;

//CAN
logic                 CAN0_rx, CAN0_tx;
logic                 CAN1_rx, CAN1_tx;
logic                 can_on;


// stream bus type
localparam type SBA_T = logic signed [ADW-1:0];  // acquire
localparam type SBG_T = logic signed [ 14-1:0];  // generate

SBA_T [MNA-1:0]          adc_dat;

// DAC signals
logic                    dac_clk_1x;
logic                    dac_clk_2x;
logic                    dac_clk_2p;
logic                    dac_axi_clk;
logic                    dac_rst;
logic                    dac_axi_rstn;

logic        [14-1:0] dac_dat_a, dac_dat_b;
logic        [14-1:0] dac_a    , dac_b    ;
logic signed [15-1:0] dac_a_sum, dac_b_sum;

// ASG
SBG_T [2-1:0]            asg_dat;
// --- ruteo y control global, desde la region de TOP (slot 6) ---
// En reset valen TAP_NATIVE / enable=1: el datapath queda cableado igual que
// antes del refactor, asi que un bitstream recien cargado se comporta como el
// anterior hasta que el software escriba un ROUTE_*.
logic [2-1:0] route_osc_tap, route_mtrg_tap, route_mca_tap;
logic         route_osc_en,  route_mtrg_en,  route_mca_en;
logic         top_run, top_clear, top_srst;

logic [2*14-1:0]         mca_dat_bus;   // muestra acondicionada -> MCA
logic                    mca_veto;      // trigger_shield (dst=mca) -> MCA
logic                    trig_arm;      // multitrigger -> MCA: el disparo puede salir
logic [2-1:0]            mca_val_bus;

// PID
SBA_T [2-1:0]            pid_dat;

// configuration
logic [2-1:0]            digital_loop;

// system bus
sys_bus_if   ps_sys      (.clk (fclk[0]), .rstn (frstn[0]));
sys_bus_if   sys [8-1:0] (.clk (adc_clk), .rstn (adc_rstn)); // Define 8 system bus. Cómo se relacionan entre sí?

// GPIO interface
gpio_if #(.DW (3*GDW)) gpio ();

// AXI masters
axi_sys_if axi0_sys (.clk(adc_clk    ), .rstn(adc_rstn    ));
axi_sys_if axi1_sys (.clk(adc_clk    ), .rstn(adc_rstn    ));
// HP2 en adc_clk: lo maneja el event_ring, que vive entero en adc_clk. En
// el top del MCA cuelga de dac_axi_clk (250 MHz) porque era del ASG; dejarlo
// asi seria un cruce de dominios sin sincronizar sobre wvalid/wrdy. El build
// lo acompania con hp2_clk_freq = 125 MHz en el PS7.
axi_sys_if axi2_sys (.clk(adc_clk    ), .rstn(adc_rstn    ));
axi_sys_if axi3_sys (.clk(dac_axi_clk), .rstn(dac_axi_rstn));
////////////////////////////////////////////////////////////////////////////////
// PLL (clock and reset)
////////////////////////////////////////////////////////////////////////////////

// diferential clock input
IBUFDS i_clk (.I (adc_clk_i[1]), .IB (adc_clk_i[0]), .O (adc_clk_in));  // differential clock input

assign rstn_pll = frstn[0] & ~(!fpll_locked_r2 && fpll_locked_r3);
red_pitaya_pll pll (
  // inputs
  .clk         (adc_clk_in),  // clock
  .rstn        (rstn_pll  ),  // reset - active low
  // output clocks
  .clk_adc     (pll_adc_clk   ),  // ADC clock
  .clk_dac_1x  (pll_dac_clk_1x),  // DAC clock 125MHz
  .clk_dac_2x  (pll_dac_clk_2x),  // DAC clock 250MHz
  .clk_dac_2p  (pll_dac_clk_2p),  // DAC clock 250MHz -45DGR
  .clk_ser     (pll_ser_clk   ),  // fast serial clock
  .clk_pdm     (pll_pwm_clk   ),  // PWM clock
  // status outputs
  .pll_locked  (pll_locked    )
);

BUFG bufg_adc_clk     (.O (adc_clk    ), .I (pll_adc_clk   ));
BUFG bufg_dac_clk_1x  (.O (dac_clk_1x ), .I (pll_dac_clk_1x));
BUFG bufg_dac_clk_2x  (.O (dac_clk_2x ), .I (pll_dac_clk_2x));
BUFG bufg_dac_axi_clk (.O (dac_axi_clk), .I (pll_dac_clk_2x));

BUFG bufg_dac_clk_2p (.O (dac_clk_2p), .I (pll_dac_clk_2p));
BUFG bufg_ser_clk    (.O (ser_clk   ), .I (pll_ser_clk   ));
BUFG bufg_pwm_clk    (.O (pwm_clk   ), .I (pll_pwm_clk   ));

always @(posedge fclk[0]) begin
  fpll_locked_r   <= pll_locked;
  fpll_locked_r2  <= fpll_locked_r;
  fpll_locked_r3  <= fpll_locked_r2;
end

always @(posedge adc_clk) begin
  pll_locked_r      <= pll_locked;
  if ((pll_locked && !pll_locked_r) || rst_cnt > 0) begin // some clk cycles after rising edge of pll_locked
    if (rst_cnt < RST_MAX)
      rst_cnt <= rst_cnt + 1;
    else 
      rst_cnt <= 'h0;
  end else begin
    if (~pll_locked) begin
      rst_cnt <= 'h0;
    end
  end
end

assign rst_after_locked = |rst_cnt;
// ADC reset (active low)
always @(posedge adc_clk)
adc_rstn     <=  frstn[0] & ~rst_after_locked;

// DAC reset (active high)
always @(posedge dac_clk_1x)
dac_rst      <= ~frstn[0] |  rst_after_locked;

// DAC AXI reset (active low)
always @(posedge dac_axi_clk)
dac_axi_rstn <=  frstn[0] & ~rst_after_locked;

// PWM reset (active low)
always @(posedge pwm_clk)
pwm_rstn     <=  frstn[0] & ~rst_after_locked;

////////////////////////////////////////////////////////////////////////////////
//  Connections to PS
////////////////////////////////////////////////////////////////////////////////

red_pitaya_ps ps (
  .FIXED_IO_mio       (  FIXED_IO_mio                ),
  .FIXED_IO_ps_clk    (  FIXED_IO_ps_clk             ),
  .FIXED_IO_ps_porb   (  FIXED_IO_ps_porb            ),
  .FIXED_IO_ps_srstb  (  FIXED_IO_ps_srstb           ),
  .FIXED_IO_ddr_vrn   (  FIXED_IO_ddr_vrn            ),
  .FIXED_IO_ddr_vrp   (  FIXED_IO_ddr_vrp            ),
  // DDR
  .DDR_addr      (DDR_addr    ),
  .DDR_ba        (DDR_ba      ),
  .DDR_cas_n     (DDR_cas_n   ),
  .DDR_ck_n      (DDR_ck_n    ),
  .DDR_ck_p      (DDR_ck_p    ),
  .DDR_cke       (DDR_cke     ),
  .DDR_cs_n      (DDR_cs_n    ),
  .DDR_dm        (DDR_dm      ),
  .DDR_dq        (DDR_dq      ),
  .DDR_dqs_n     (DDR_dqs_n   ),
  .DDR_dqs_p     (DDR_dqs_p   ),
  .DDR_odt       (DDR_odt     ),
  .DDR_ras_n     (DDR_ras_n   ),
  .DDR_reset_n   (DDR_reset_n ),
  .DDR_we_n      (DDR_we_n    ),
  // system signals
  .fclk_clk_o    (fclk        ),
  .fclk_rstn_o   (frstn       ),
  // ADC analog inputs
  .vinp_i        (vinp_i      ),
  .vinn_i        (vinn_i      ),
  // CAN0
  .CAN0_rx       (CAN0_rx     ),
  .CAN0_tx       (CAN0_tx     ),
  // CAN1
  .CAN1_rx       (CAN1_rx     ),
  .CAN1_tx       (CAN1_tx     ),
  // GPIO
  .gpio          (gpio),
  // system read/write channel
  .bus           (ps_sys      ),
  // AXI masters

  .axi0_sys      (axi0_sys    ),
  .axi1_sys      (axi1_sys    ),
  .axi2_sys      (axi2_sys    ),
  .axi3_sys      (axi3_sys    )
);

////////////////////////////////////////////////////////////////////////////////
// system bus decoder & multiplexer (it breaks memory addresses into 8 regions)
////////////////////////////////////////////////////////////////////////////////

sys_bus_interconnect #(
  .SN (8),
  .SW (20)
) sys_bus_interconnect (
  .pll_locked_i(pll_locked),
  .bus_m (ps_sys),
  .bus_s (sys)
);


`ifndef SCOPE_ONLY

assign daisy_trig = |par_dat;
assign trig_ext   = gpio.i[GDW] & ~(daisy_mode[0] & daisy_trig);
////////////////////////////////////////////////////////////////////////////////
// Analog mixed signals (PDM analog outputs)
////////////////////////////////////////////////////////////////////////////////

logic [4-1:0] [8-1:0] pdm_cfg;

red_pitaya_ams i_ams (
  // power test
  .clk_i           (adc_clk ),  // clock
  .rstn_i          (adc_rstn),  // reset - active low
  // PWM configuration
  .dac_a_o         (pdm_cfg[0]),
  .dac_b_o         (pdm_cfg[1]),
  .dac_c_o         (pdm_cfg[2]),
  .dac_d_o         (pdm_cfg[3]),
  // System bus
  .sys_addr        (sys[4].addr ),
  .sys_wdata       (sys[4].wdata),
  .sys_wen         (sys[4].wen  ),
  .sys_ren         (sys[4].ren  ),
  .sys_rdata       (sys[4].rdata),
  .sys_err         (sys[4].err  ),
  .sys_ack         (sys[4].ack  )
);

red_pitaya_pdm pdm (
  // system signals
  .clk   (adc_clk ),
  .rstn  (adc_rstn),
  // configuration
  .cfg   (pdm_cfg),
  .ena      (1'b1),
  .rng      (8'd255),
  // PWM outputs
  .pdm (dac_pwm_o)
);

////////////////////////////////////////////////////////////////////////////////
// ADC IO
////////////////////////////////////////////////////////////////////////////////

ODDR i_adc_clk_p ( .Q(adc_clk_o[0]), .D1(1'b1), .D2(1'b0), .C(adc_clk_daisy), .CE(1'b1), .R(1'b0), .S(1'b0));
ODDR i_adc_clk_n ( .Q(adc_clk_o[1]), .D1(1'b0), .D2(1'b1), .C(adc_clk_daisy), .CE(1'b1), .R(1'b0), .S(1'b0));

assign adc_cdcs_o = 1'b1 ;

logic [2-1:0] [ADW-1:0] adc_dat_raw;

// IO block registers should be used here
// lowest 2 bits reserved for 16bit ADC
//
// El dato crudo se registra solo, para que el flop entre en el IOB (IOB TRUE en
// sdc/red_pitaya.xdc): la captura queda pegada al pad, con la misma demora en
// todos los bits. Antes el primer flop era el del mux de digital_loop, y entraba
// en el IOB solo porque dac_a era constante (sin ASG). Con gen_pulsos manejando
// dac_a el mux es real y Vivado dejaba el flop en la fabrica (Place 30-722):
// timeado por el set_input_delay de 3.4 ns, pero con la demora del ruteo.
// Cuesta un ciclo del ADC a adc_dat; el lazo digital sigue en uno.
always @(posedge adc_clk) begin
  adc_dat_raw[0] <= adc_dat_i[0][16-1 -: ADW];
  adc_dat_raw[1] <= adc_dat_i[1][16-1 -: ADW];
end

// transform into 2's complement (negative slope)
always @(posedge adc_clk) begin
  adc_dat[0] <= digital_loop[0] ? dac_a : {adc_dat_raw[0][ADW-1], ~adc_dat_raw[0][ADW-2:0]};
  adc_dat[1] <= digital_loop[0] ? dac_b : {adc_dat_raw[1][ADW-1], ~adc_dat_raw[1][ADW-2:0]};
end
//always @(posedge adc_clk) begin
  //adc_dat[0] <= digital_loop[0] ? dac_a : adc_dat_raw[0];
  //adc_dat[1] <= digital_loop[0] ? dac_b : adc_dat_raw[1];
//end

////////////////////////////////////////////////////////////////////////////////
// DAC IO
////////////////////////////////////////////////////////////////////////////////

// Sumation of ASG and PID signal perform saturation before sending to DAC 
assign dac_a_sum = asg_dat[0] + pid_dat[0];
assign dac_b_sum = asg_dat[1] + pid_dat[1];

// saturation
assign dac_a = (^dac_a_sum[15-1:15-2]) ? {dac_a_sum[15-1], {13{~dac_a_sum[15-1]}}} : dac_a_sum[14-1:0];
assign dac_b = (^dac_b_sum[15-1:15-2]) ? {dac_b_sum[15-1], {13{~dac_b_sum[15-1]}}} : dac_b_sum[14-1:0];

// output registers + signed to unsigned (also to negative slope)
always @(posedge dac_clk_1x)
begin // Loopback is for demonstration only. We avoid constraining for timing optimizations.
  dac_dat_a <= digital_loop[1] ? {adc_dat[0][ADW-1], ~adc_dat[0][ADW-2 -: 13]} : {dac_a[14-1], ~dac_a[14-2:0]};
  dac_dat_b <= digital_loop[1] ? {adc_dat[1][ADW-1], ~adc_dat[1][ADW-2 -: 13]} : {dac_b[14-1], ~dac_b[14-2:0]};
end

// DDR outputs
ODDR oddr_dac_clk          (.Q(dac_clk_o), .D1(1'b0     ), .D2(1'b1     ), .C(dac_clk_2p), .CE(1'b1), .R(1'b0   ), .S(1'b0));
ODDR oddr_dac_wrt          (.Q(dac_wrt_o), .D1(1'b0     ), .D2(1'b1     ), .C(dac_clk_2x), .CE(1'b1), .R(1'b0   ), .S(1'b0));
ODDR oddr_dac_sel          (.Q(dac_sel_o), .D1(1'b1     ), .D2(1'b0     ), .C(dac_clk_1x), .CE(1'b1), .R(dac_rst), .S(1'b0));
ODDR oddr_dac_rst          (.Q(dac_rst_o), .D1(dac_rst  ), .D2(dac_rst  ), .C(dac_clk_1x), .CE(1'b1), .R(1'b0   ), .S(1'b0));
ODDR oddr_dac_dat [14-1:0] (.Q(dac_dat_o), .D1(dac_dat_b), .D2(dac_dat_a), .C(dac_clk_1x), .CE(1'b1), .R(dac_rst), .S(1'b0));

////////////////////////////////////////////////////////////////////////////////
//  House Keeping
////////////////////////////////////////////////////////////////////////////////

logic [DWE-1: 0] exp_p_in ,  exp_n_in ;
logic [DWE-1: 0] exp_p_out,  exp_n_out;
logic [DWE-1: 0] exp_p_dir,  exp_n_dir;
logic [DWE-1: 0] exp_p_otr,  exp_n_otr;
logic [DWE-1: 0] exp_p_dtr,  exp_n_dtr;
logic [DWE-1: 0] exp_p_alt,  exp_n_alt;
logic [DWE-1: 0] exp_p_altr, exp_n_altr;
logic [DWE-1: 0] exp_p_altd, exp_n_altd;

// hk tiene bus 0
red_pitaya_hk #(.DWE(DWE)) i_hk (
  // system signals
  .clk_i           (adc_clk    ),  // clock
  .rstn_i          (adc_rstn   ),  // reset - active low
  .fclk_i          (fclk[0]    ),  // clock
  .frstn_i         (frstn[0]   ),  // reset - active low

  // LED
  .led_o           (  led_o    ),  // LED output
  // global configuration
  .digital_loop    (digital_loop),
  .daisy_mode_o    (daisy_mode),
  // Expansion connector
  .exp_p_dat_i     (exp_p_in ),  // input data
  .exp_p_dat_o     (exp_p_out),  // output data
  .exp_p_dir_o     (exp_p_dir),  // 1-output enable
  .exp_n_dat_i     (exp_n_in ),
  .exp_n_dat_o     (exp_n_out),
  .exp_n_dir_o     (exp_n_dir),
  .can_on_o        (can_on   ),
   // System bus
  .sys_addr        (sys[0].addr ),
  .sys_wdata       (sys[0].wdata),
  .sys_wen         (sys[0].wen  ),
  .sys_ren         (sys[0].ren  ),
  .sys_rdata       (sys[0].rdata),
  .sys_err         (sys[0].err  ),
  .sys_ack         (sys[0].ack  )
);


////////////////////////////////////////////////////////////////////////////////
// LED
////////////////////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////////////////////////
// GPIO
////////////////////////////////////////////////////////////////////////////////

assign trig_output_sel = daisy_mode[2] ? trig_asg_out : scope_trigo;

assign exp_p_alt  = {DWE{1'b0}};
assign exp_n_alt  = {{DWE-8{1'b0}},  can_on,  can_on, 5'h0, daisy_mode[1]  };

assign exp_p_altr = {DWE{1'b0}};
assign exp_n_altr = {{DWE-8{1'b0}}, CAN0_tx, CAN1_tx, 5'h0, trig_output_sel};

assign exp_p_altd = {DWE{1'b0}};
assign exp_n_altd = {{DWE-8{1'b0}},   1'b1,   1'b1, 5'h0, 1'b1};

genvar GM;
generate
for(GM = 0 ; GM < DWE ; GM = GM + 1) begin : gpios
  assign exp_p_otr[GM] = exp_p_alt[GM] ? exp_p_altr[GM] : exp_p_out[GM];
  assign exp_n_otr[GM] = exp_n_alt[GM] ? exp_n_altr[GM] : exp_n_out[GM];

  assign exp_p_dtr[GM] = exp_p_alt[GM] ? exp_p_altd[GM] : exp_p_dir[GM];
  assign exp_n_dtr[GM] = exp_n_alt[GM] ? exp_n_altd[GM] : exp_n_dir[GM];
end
endgenerate

IOBUF i_iobufp [DWE-1:0] (.O(exp_p_in), .IO(exp_p_io), .I(exp_p_otr), .T(~exp_p_dtr) );
IOBUF i_iobufn [DWE-1:0] (.O(exp_n_in), .IO(exp_n_io), .I(exp_n_otr), .T(~exp_n_dtr) );

assign gpio.i[2*GDW-1:  GDW] = exp_p_in[GDW-1:0];
assign gpio.i[3*GDW-1:2*GDW] = exp_n_in[GDW-1:0];

assign CAN0_rx = can_on & exp_p_in[7];
assign CAN1_rx = can_on & exp_p_in[6];

////////////////////////////////////////////////////////////////////////////////
// oscilloscope
////////////////////////////////////////////////////////////////////////////////

wire [ 4-1:0] trig_ch_0_1;                // Que es esto
wire [ 4-1:0] trig_ch_2_3 = 4'h0;        // Que es esto
wire [16-1:0] trg_state_ch_0_1;          // Que es esto
wire [16-1:0] trg_state_ch_2_3 = 16'h0;
wire [16-1:0] adc_state_ch_0_1;
wire [16-1:0] adc_state_ch_2_3 = 16'h0;
wire [16-1:0] axi_state_ch_0_1;
wire [16-1:0] axi_state_ch_2_3 = 16'h0;

// El evento conjunto hacia el event_ring, y su snapshot.
wire        ring_trig;
wire [16:0] ring_snap;

// Defino con la misma interface que el scope original

rp_scope_mt_com#(
  .CHN(0),
  .N_CH(SCOPE_N_CH),
  .DW(SCOPE_DW),
  .RSZ(SCOPE_RSZ),
  .EN_FILT(0),                // sin ecualizador: ver la cabecera
  .EN_AXI(0)) i_scope (       // sin captura AXI: la reemplaza el ring
  // ADC
  .adc_dat_i     ({adc_dat[1], adc_dat[0]}  ),
  .adc_clk_i     ({2{adc_clk}}  ),  // clock
  .adc_rstn_i    ({2{adc_rstn}} ),  // reset - active low

  // Muestra acondicionada hacia el MCA (post-calib, pre-decimacion, 125 MSPS)
  .mca_dat_o     (mca_dat_bus ),
  .mca_val_o     (mca_val_bus ),

  .trig_ext_i    (trig_ext    ),  // external trigger
  .trig_asg_i    (trig_asg_out),  // ASG trigger
  .trig_ch_o     (trig_ch_0_1 ),  // output trigger to ADC for other 2 channels
  .trig_ch_i     (trig_ch_2_3 ),  // input ADC trigger from other 2 channels
  .trig_ext_asg_o(trig_ext_asg01),
  .trig_ext_asg_i(trig_ext_asg01),
  .daisy_trig_o  (scope_trigo ),
  .mca_veto_o    (mca_veto    ),  // veto externo hacia el MCA
  .event_trig_o  (ring_trig   ),  // evento conjunto hacia el event_ring
  .event_snap_o  (ring_snap   ),
  .trig_arm_o    (trig_arm    ),  // re-armado del disparo hacia el MCA

  .adc_state_o   (adc_state_ch_0_1),
  .adc_state_i   (adc_state_ch_2_3),
  .axi_state_o   (axi_state_ch_0_1),
  .axi_state_i   (axi_state_ch_2_3),
  .trg_state_o   (trg_state_ch_0_1),
  .trg_state_i   (trg_state_ch_2_3),

  // AXI0 master                 // AXI1 master
  .axi_waddr_o  ({axi1_sys.waddr,  axi0_sys.waddr} ),
  .axi_wdata_o  ({axi1_sys.wdata,  axi0_sys.wdata} ),
  .axi_wsel_o   ({axi1_sys.wsel,   axi0_sys.wsel}  ),
  .axi_wvalid_o ({axi1_sys.wvalid, axi0_sys.wvalid}),
  .axi_wlen_o   ({axi1_sys.wlen,   axi0_sys.wlen}  ),
  .axi_wfixed_o ({axi1_sys.wfixed, axi0_sys.wfixed}),
  .axi_werr_i   ({axi1_sys.werr,   axi0_sys.werr}  ),
  .axi_wrdy_i   ({axi1_sys.wrdy,   axi0_sys.wrdy}  ),
  // Ruteo del datapath, desde la region de TOP (slot 6)
  .route_osc_tap_i (route_osc_tap ), .route_osc_en_i (route_osc_en ),
  .route_mtrg_tap_i(route_mtrg_tap), .route_mtrg_en_i(route_mtrg_en),
  .route_mca_tap_i (route_mca_tap ), .route_mca_en_i (route_mca_en ),

  // System bus del OSC — slot 1, 0x4010_0000
  .sys_osc_addr  (sys[1].addr ),
  .sys_osc_wdata (sys[1].wdata),
  .sys_osc_wen   (sys[1].wen  ),
  .sys_osc_ren   (sys[1].ren  ),
  .sys_osc_rdata (sys[1].rdata),
  .sys_osc_err   (sys[1].err  ),
  .sys_osc_ack   (sys[1].ack  ),

  // System bus del MULTITRIGGER — slot 3, 0x4030_0000
  .sys_mtrg_addr (sys[3].addr ),
  .sys_mtrg_wdata(sys[3].wdata),
  .sys_mtrg_wen  (sys[3].wen  ),
  .sys_mtrg_ren  (sys[3].ren  ),
  .sys_mtrg_rdata(sys[3].rdata),
  .sys_mtrg_err  (sys[3].err  ),
  .sys_mtrg_ack  (sys[3].ack  )
);

// (bloque rp_scope_com clásico eliminado; se usa i_scope multitrigger)


////////////////////////////////////////////////////////////////////////////////
//  DAC arbitrary signal generator
////////////////////////////////////////////////////////////////////////////////


// --- ASG ELIMINADO, GENERADOR DE PULSOS EN SU LUGAR ----------------------
// Un MCA no necesita generador arbitrario, y sacarlo libera ~17 RAMB36 (dos
// tablas de onda de 16384x14b mas los FIFOs), los puertos HP2/HP3 y bastante
// logica. En su lugar va gen_pulsos: pulsos de preamplificador con disparos
// periodicos o de Poisson y amplitudes de una tabla, para probar el
// multitrigger y el MCA sin el Rigol, con un estimulo que el software conoce
// bit a bit (docs/gen_eventos/generador_pulsos.md). Toma lo que era del ASG:
//   - asg_dat, la entrada del DAC. Con digital_loop[0] (HK 0x4000_000C) vuelve
//     por adc_dat y todo el datapath ve los pulsos; si no, salen por OUT1/2.
//   - trig_asg_out, la fuente ASG del OR_MASK del multitrigger (bits 11 y 12).
//     Pasa por el antirrebote de rp_ext_trig, que comparte su largo con el
//     disparo externo: para el generador, en 0.
//   - el slot 2, que reparte con el event_ring (sys_bus_split): 0x4020_0000
//     es del ring (i_event_ring, mas abajo) y
//     0x4021_0000 del generador.
// Como el ASG, corre en adc_clk. Apagado (CTRL.en = 0, el reset), asg_dat y
// trig_asg_out quedan en cero, como antes.
sys_bus_if sys2_ring (.clk (adc_clk), .rstn (adc_rstn));   // 0x4020_0000
sys_bus_if sys2_pul  (.clk (adc_clk), .rstn (adc_rstn));   // 0x4021_0000

sys_bus_split #(.SEL_B (4'h1)) i_slot2 (
  .s_addr  (sys[2].addr    ), .s_wdata (sys[2].wdata   ),
  .s_wen   (sys[2].wen     ), .s_ren   (sys[2].ren     ),
  .s_rdata (sys[2].rdata   ), .s_err   (sys[2].err     ), .s_ack (sys[2].ack   ),
  .a_addr  (sys2_ring.addr ), .a_wdata (sys2_ring.wdata),
  .a_wen   (sys2_ring.wen  ), .a_ren   (sys2_ring.ren  ),
  .a_rdata (sys2_ring.rdata), .a_err   (sys2_ring.err  ), .a_ack (sys2_ring.ack),
  .b_addr  (sys2_pul.addr  ), .b_wdata (sys2_pul.wdata ),
  .b_wen   (sys2_pul.wen   ), .b_ren   (sys2_pul.ren   ),
  .b_rdata (sys2_pul.rdata ), .b_err   (sys2_pul.err   ), .b_ack (sys2_pul.ack )
);

// --- SLOT 2: event_ring (en el top del MCA, un stub) ---------------------
// Base 0x4020_0000: la parte del slot 2 que no es de gen_pulsos (ver
// sys_bus_split, arriba). Toma el puerto HP2 que dejo libre el ASG. Las
// muestras son mca_dat_bus, las mismas que consume el MCA: post-calibracion y
// PRE-decimacion. El trigger es el evento conjunto del multitrigger, el mismo
// que llega a rp_bram_sm y, como scope_trigo, al MCA: el ring no agrega una
// fuente de disparo, agrega un camino de salida.
event_ring_top #(
  .DW      (14),
  .N_CH    (2),
  .PRE_AW  (11),   // 2048 palabras: ventanas de hasta 1024 muestras por canal
  .S_AW    (11),
  .DATA_AW (12),   // stage: 4096 muestras (~2 RAMB36)
  .E       (4)
) i_event_ring (
  .adc_clk_i    (adc_clk          ),
  .adc_rstn_i   (adc_rstn         ),

  .dat_i        (mca_dat_bus      ),
  .dv_i         (mca_val_bus[0]   ),
  .trig_i       (ring_trig        ),
  .snapshot_i   (ring_snap        ),

  .axi_waddr_o  (axi2_sys.waddr   ),
  .axi_wdata_o  (axi2_sys.wdata   ),
  .axi_wsel_o   (axi2_sys.wsel    ),
  .axi_wsize_o  (axi2_sys.wsize   ),
  .axi_wvalid_o (axi2_sys.wvalid  ),
  .axi_wlen_o   (axi2_sys.wlen    ),
  .axi_wfixed_o (axi2_sys.wfixed  ),
  .axi_werr_i   (axi2_sys.werr    ),
  .axi_wrdy_i   (axi2_sys.wrdy    ),

  .sys_addr     (sys2_ring.addr   ),
  .sys_wdata    (sys2_ring.wdata  ),
  .sys_wen      (sys2_ring.wen    ),
  .sys_ren      (sys2_ring.ren    ),
  .sys_rdata    (sys2_ring.rdata  ),
  .sys_err      (sys2_ring.err    ),
  .sys_ack      (sys2_ring.ack    )
);

gen_pulsos #(.DW (14)) i_gen_pulsos (
  .clk_i     (adc_clk          ),
  .rstn_i    (adc_rstn         ),
  .dat_a_o   (asg_dat[0]       ),
  .dat_b_o   (asg_dat[1]       ),
  .trig_o    (trig_asg_out     ),
  .sys_addr  (sys2_pul.addr    ),
  .sys_wdata (sys2_pul.wdata   ),
  .sys_wen   (sys2_pul.wen     ),
  .sys_ren   (sys2_pul.ren     ),
  .sys_rdata (sys2_pul.rdata   ),
  .sys_err   (sys2_pul.err     ),
  .sys_ack   (sys2_pul.ack     )
);

// HP3 era del ASG: se ata para que su axi_master quede inactivo. Las
// escrituras de HP2 son del ring; sus lecturas no se usan.
assign axi3_sys.waddr = '0;
assign axi3_sys.wdata = '0;
assign axi3_sys.wsel  = '0;
assign axi3_sys.wlen  = '0;
assign axi3_sys.wsize = '0;
assign axi3_sys.wfixed= 1'b0;
assign axi3_sys.wvalid= 1'b0;
assign axi2_sys.raddr = '0;  assign axi3_sys.raddr = '0;
assign axi2_sys.rsel  = '0;  assign axi3_sys.rsel  = '0;
assign axi2_sys.rlen  = '0;  assign axi3_sys.rlen  = '0;
assign axi2_sys.rsize = '0;  assign axi3_sys.rsize = '0;
assign axi2_sys.rfixed= 1'b0; assign axi3_sys.rfixed= 1'b0;
assign axi2_sys.rvalid= 1'b0; assign axi3_sys.rvalid= 1'b0;
assign axi2_sys.rrdys = 1'b0; assign axi3_sys.rrdys = 1'b0;

////////////////////////////////////////////////////////////////////////////////
//  MIMO PID controller
////////////////////////////////////////////////////////////////////////////////

// --- PID ELIMINADO -------------------------------------------------------
// Sin uso en este flujo; libera slices y DSP para el MCA.
//
// El slot 3 que dejaba libre ahora lo ocupa la region de MULTITRIGGER
// (0x4030_0000). Se cablea dentro de i_scope, junto al bus del OSC.

assign pid_dat[0] = '0;
assign pid_dat[1] = '0;

////////////////////////////////////////////////////////////////////////////////
// Daisy test code
////////////////////////////////////////////////////////////////////////////////

wire daisy_rx_rdy ;
wire dly_clk = fclk[3]; // 200MHz clock from PS - used for IDELAY (optionaly)
wire [16-1:0] par_dati = daisy_mode[0] ? {16{trig_output_sel}} : 16'h1234;
wire          par_dvi  = daisy_mode[0] ? 1'b0 : daisy_rx_rdy;

red_pitaya_daisy i_daisy (
   // SATA connector
  .daisy_p_o       (  daisy_p_o                  ),  // line 1 is clock capable
  .daisy_n_o       (  daisy_n_o                  ),
  .daisy_p_i       (  daisy_p_i                  ),  // line 1 is clock capable
  .daisy_n_i       (  daisy_n_i                  ),
   // Data
  .ser_clk_i       (  ser_clk                    ),  // high speed serial
  .dly_clk_i       (  dly_clk                    ),  // delay clock
   // TX
  .par_clk_i       (  adc_clk                    ),  // data paralel clock
  .par_rstn_i      (  adc_rstn                   ),  // reset - active low
  .par_rdy_o       (  daisy_rx_rdy               ),
  .par_dv_i        (  par_dvi                    ),
  .par_dat_i       (  par_dati                   ),
   // RX
  .par_clk_o       ( adc_clk_daisy               ),
  .par_rstn_o      (                             ),
  .par_dv_o        (                             ),
  .par_dat_o       ( par_dat                     ),

  .sync_mode_i     (  daisy_mode[0]              ),
  .debug_o         (/*led_o*/                    ),
   // System bus
  .sys_clk_i       (  adc_clk                    ),  // clock
  .sys_rstn_i      (  adc_rstn                   ),  // reset - active low
  .sys_addr_i      (  sys[5].addr                ),
  .sys_sel_i       (                             ),
  .sys_wdata_i     (  sys[5].wdata               ),
  .sys_wen_i       (  sys[5].wen                 ),
  .sys_ren_i       (  sys[5].ren                 ),
  .sys_rdata_o     (  sys[5].rdata               ),
  .sys_err_o       (  sys[5].err                 ),
  .sys_ack_o       (  sys[5].ack                 )
);

  `ifdef Z20_G2
  // DIO11 is TX clock
  // DIO12 is RX clock
  // exp_e3x_o={DIO11, DIO13, DIO15, DIO17}
  // exp_e3x_i={DIO12, DIO14, DIO16, DIO18}
red_pitaya_daisy  #(
  .IO_STD("LVDS_25"),
  .N_DATS(3)
) i_serlines_add
(
   // SATA connector
  .daisy_p_o       (  exp_e3p_o                  ),  // line 3 is clock capable (SRCC)
  .daisy_n_o       (  exp_e3n_o                  ),
  .daisy_p_i       (  exp_e3p_i                  ),  // line 3 is clock capable (MRCC)
  .daisy_n_i       (  exp_e3n_i                  ),
   // Data
  .ser_clk_i       (  ser_clk                    ),  // high speed serial
  .dly_clk_i       (  dly_clk                    ),  // delay clock
   // TX
  .par_clk_i       (  adc_clk                    ),  // data paralel clock
  .par_rstn_i      (  adc_rstn                   ),  // reset - active low
  //.par_rdy_o       (  daisy_rx_rdy               ),
  //.par_dv_i        (  par_dvi                    ),
  //.par_dat_i       (  par_dati                   ),
   // RX
  //.par_clk_o       ( adc_clk_daisy               ),
  //.par_rstn_o      (                             ),
  //.par_dv_o        (                             ),
  //.par_dat_o       ( par_dat                     ),

  .sync_mode_i     (  1'b0                       ),
  //.debug_o         (/*led_o*/                    ),
   // System bus
  .sys_clk_i       (  adc_clk                    ),  // clock
  .sys_rstn_i      (  adc_rstn                   ),  // reset - active low
  .sys_addr_i      (  sys[6].addr                ),
  .sys_sel_i       (                             ),
  .sys_wdata_i     (  sys[6].wdata               ),
  .sys_wen_i       (  sys[6].wen                 ),
  .sys_ren_i       (  sys[6].ren                 ),
  .sys_rdata_o     (  sys[6].rdata               ),
  .sys_err_o       (  sys[6].err                 ),
  .sys_ack_o       (  sys[6].ack                 )
);
  `else
////////////////////////////////////////////////////////////////////////////////
//  Region de TOP (integracion) — slot 6, base 0x4060_0000
//
//  Identifica el bitstream, describe que modulos trae y en que slot vive cada
//  uno, y rutea el datapath entre ellos. No es housekeeping: red_pitaya_hk
//  (slot 0) es el modulo de Red Pitaya y sigue donde estaba.
//
//  OJO CON EL SLOT 6: en Z20_G2 lo ocupa i_serlines_add (la rama `ifdef` de
//  arriba). Este top se sintetiza para xc7z010 con `define Z10, asi que esa
//  rama nunca se toma; si alguna vez se compilara para Z20_G2 habria que mover
//  la region de TOP a otro slot.
////////////////////////////////////////////////////////////////////////////////
integration_cfg #(
  .MAGIC    (32'h494E5447),           // "INTG"
  .VERSION  (32'h0001_0000),
  .GITH     (GITH),
  // que hay en ESTE bitstream: sin ASG ni PID (eliminados mas arriba),
  // con el event_ring en el slot 2
  .EN_OSC(1), .EN_MTRG(1), .EN_MCA(1), .EN_RING(1), .EN_ASG(0), .EN_PID(0),
  .SLOT_OSC(1), .SLOT_RING(2), .SLOT_MTRG(3), .SLOT_TOP(6), .SLOT_MCA(7),
  // el generador de pulsos, en 0x1_0000 del slot 2 (sys_bus_split)
  .EN_PULSOS(1), .SLOT_PULSOS(2),
  // parametros con los que se instanciaron los bloques, para que el software
  // los descubra en vez de hardcodearlos
  .N_CH(SCOPE_N_CH), .DW(SCOPE_DW), .RSZ(SCOPE_RSZ), .EN_FILT(0),
  // OJO: ESTA ES UNA SEGUNDA COPIA de la geometria del MCA, que el propio MCA
  // ya publica en su registro WIDTHS (0x008). Tienen que coincidir con los
  // parametros de `i_mca` de mas abajo, y ya divergieron una vez: el commit que
  // bajo el eje de 16384 a 8192 canales cambio `i_mca` y se olvido de esta.
  // Nada del software leia esta copia, asi que la mentira paso inadvertida.
  //
  // La fuente de verdad es WIDTHS del MCA, no esto. Si alguna vez se toca H_AW,
  // se tocan LOS DOS lugares -- o mejor, se saca de aca: la geometria del
  // histograma es del MCA, mientras que N_CH/DW/RSZ/EN_FILT si son del sistema
  // y ningun bloque suelto los conoce.
  .H_AW(13), .H2_AW(7), .PSD_AW(6)
) i_integration (
  .adc_clk_i  (adc_clk ),
  .adc_rstn_i (adc_rstn),

  .route_osc_tap_o (route_osc_tap ), .route_osc_en_o (route_osc_en ),
  .route_mtrg_tap_o(route_mtrg_tap), .route_mtrg_en_o(route_mtrg_en),
  .route_mca_tap_o (route_mca_tap ), .route_mca_en_o (route_mca_en ),
  .route_ring_tap_o(              ), .route_ring_en_o(             ),

  .ctrl_run_o  (top_run  ),
  .ctrl_clear_o(top_clear),
  .ctrl_srst_o (top_srst ),

  .pll_locked_i(pll_locked),

  .sys_addr   (sys[6].addr ),
  .sys_wdata  (sys[6].wdata),
  .sys_wen    (sys[6].wen  ),
  .sys_ren    (sys[6].ren  ),
  .sys_rdata  (sys[6].rdata),
  .sys_err    (sys[6].err  ),
  .sys_ack    (sys[6].ack  )
);
  `endif
////////////////////////////////////////////////////////////////////////////////
//  Analizador Multicanal (MCA) — slot 7, base 0x4070_0000
////////////////////////////////////////////////////////////////////////////////
mca_top #(
  .DW            (14),
  // 8192 canales (13 bits), no 16384. La resolucion medida da 9.2-10.3 bits
  // efectivos (FS/FWHM = 592-1298), asi que el criterio de 4-10 canales por FWHM
  // justifica 3800-9500 canales: 16384 estaba por encima del rango util y los 4
  // bits de mas no compraban nada medible. Libera 8 RAMB36 de 16, que es lo que
  // habilita un segundo MCA. Ver docs/mca/limites_resolucion_y_deriva.md §2.
  .EN_HIST_H     (1), .H_AW (13),        // espectro 1D: 8192 canales
  .EN_HIST_H_PSD (1), .H2_AW(7), .PSD_AW(6),  // mapa 2D: 128 x 64
  // 3 ranuras y 3 formas (64/48, 32/24, 8/8), no 4 y 4: libera ~1230 LUT y
  // ~980 FF (OOC) en un bitstream que estaba al 99.86 % de los slices. El golden
  // model sobre el tren de Poisson capturado en la placa da 647 buenos/s a 1 Mcps,
  // contra 650 con 4 y 4, e igual a 300 kcps. La forma que se va es la 16/12: sus
  // pulsos pasan a la 8/8, que cuenta igual con un 40 % mas de ruido. La 8/8 no
  // se puede sacar (-20 % a 1 Mcps). Ver docs/mca/pruebas_banco_trapecios.md §7.
  .N_ACC         (3), .N_FORMAS (3)
) i_mca (
  .adc_clk_i   (adc_clk     ),
  .adc_rstn_i  (adc_rstn    ),
  .mca_dat_i   (mca_dat_bus ),
  .mca_val_i   (mca_val_bus ),
  .veto_i      (mca_veto    ),
  // Nivel del multitrigger: algun canal puede disparar. Con 0 el tiempo va a
  // t_rearm (el disparo esperando re-armar), no a livetime.
  .trig_arm_i  (trig_arm    ),
  // FASE 2: apertura de ventana por trigger externo. La fuente es
  // `scope_trigo`, como en el top del MCA — que es el MISMO
  // `event_signal` del multitrigger que le llega al ring por event_trig_o
  // (mt_event_logic ata trigger_event_o y daisy_trig_o a la misma
  // senal), o sea el OR de todas las fuentes de disparo del scope.
  //
  // El MCA lo toma por FLANCO internamente, asi que compartirlo con
  // trig_output_sel no cambia nada: es un fanout de lectura.
  //
  // No cambia nada por si solo: con cfg_trig_src = 0 (el default) no se mira.
  .trig_i      (scope_trigo ),
  // System bus
  .sys_addr    (sys[7].addr ),
  .sys_wdata   (sys[7].wdata),
  .sys_wen     (sys[7].wen  ),
  .sys_ren     (sys[7].ren  ),
  .sys_rdata   (sys[7].rdata),
  .sys_err     (sys[7].err  ),
  .sys_ack     (sys[7].ack  )
);

`else
IOBUF i_iobuf (.O(trig_ext), .IO(exp_p_io[0]), .I(1'b0), .T(1'b1) );

logic [2-1:0] [ADW-1:0] adc_dat_raw;

always @(posedge adc_clk) begin
  adc_dat_raw[0] <= adc_dat_i[0][16-1 -: ADW];
  adc_dat_raw[1] <= adc_dat_i[1][16-1 -: ADW];

  adc_dat[0] <= {adc_dat_raw[0][ADW-1], ~adc_dat_raw[0][ADW-2:0]};
  adc_dat[1] <= {adc_dat_raw[1][ADW-1], ~adc_dat_raw[1][ADW-2:0]};
end

//red_pitaya_hk #(.DWE(DWE)) i_hk (
  //// system signals
  //.clk_i           (adc_clk    ),  // clock
  //.rstn_i          (adc_rstn   ),  // reset - active low
  //.fclk_i          (fclk[0]    ),  // clock
  //.frstn_i         (frstn[0]   ),  // reset - active low
  ////// LED
  ////.led_o           (  led_o     ),  // LED output
  ////// global configuration
  ////.digital_loop    (digital_loop),
  ////.daisy_mode_o    (daisy_mode),
  ////// Expansion connector
  //// .exp_p_dat_i     (exp_p_in ),  // input data
  //// .exp_p_dat_o     (exp_p_out),  // output data
  //// .exp_p_dir_o     (exp_p_dir),  // 1-output enable
  //// .exp_n_dat_i     (exp_n_in ),
  //// .exp_n_dat_o     (exp_n_out),
  //// .exp_n_dir_o     (exp_n_dir),
  //// .can_on_o        (can_on   ),
  ////// System bus
  //.sys_addr        (sys[0].addr ),
  //.sys_wdata       (sys[0].wdata),
  //.sys_wen         (sys[0].wen  ),
  //.sys_ren         (sys[0].ren  ),
  //.sys_rdata       (sys[0].rdata),
  //.sys_err         (sys[0].err  ),
  //.sys_ack         (sys[0].ack  )
//);

//red_pitaya_scope i_scope (
  //// ADC
  //.adc_a_i       (adc_dat[0]  ),  // CH 1
  //.adc_b_i       (adc_dat[1]  ),  // CH 2
  //.adc_clk_i     (adc_clk     ),  // clock
  //.adc_rstn_i    (adc_rstn    ),  // reset - active low
  //.trig_ext_i    (trig_ext    ),  // external trigger
  //.trig_asg_i    (1'b0        ),  // ASG trigger
  //.trig_ext_asg_o(trig_ext_asg01),
  //.trig_ext_asg_i(trig_ext_asg01),
  ////.daisy_trig_o  (scope_trigo ),
  //// AXI0 master                 // AXI1 master
  //.axi0_waddr_o  (axi0_sys.waddr ),  .axi1_waddr_o  (axi1_sys.waddr ),
  //.axi0_wdata_o  (axi0_sys.wdata ),  .axi1_wdata_o  (axi1_sys.wdata ),
  //.axi0_wsel_o   (axi0_sys.wsel  ),  .axi1_wsel_o   (axi1_sys.wsel  ),
  //.axi0_wvalid_o (axi0_sys.wvalid),  .axi1_wvalid_o (axi1_sys.wvalid),
  //.axi0_wlen_o   (axi0_sys.wlen  ),  .axi1_wlen_o   (axi1_sys.wlen  ),
  //.axi0_wfixed_o (axi0_sys.wfixed),  .axi1_wfixed_o (axi1_sys.wfixed),
  //.axi0_werr_i   (axi0_sys.werr  ),  .axi1_werr_i   (axi1_sys.werr  ),
  //.axi0_wrdy_i   (axi0_sys.wrdy  ),  .axi1_wrdy_i   (axi1_sys.wrdy  ),
  //// System bus
  //.sys_addr      (sys[1].addr ),
  //.sys_wdata     (sys[1].wdata),
  //.sys_wen       (sys[1].wen  ),
  //.sys_ren       (sys[1].ren  ),
  //.sys_rdata     (sys[1].rdata),
  //.sys_err       (sys[1].err  ),
  //.sys_ack       (sys[1].ack  )
//);

assign dac_dat_a = 14'h0;
assign dac_dat_b = 14'h0;

// DDR outputs
ODDR oddr_dac_clk          (.Q(dac_clk_o), .D1(1'b0     ), .D2(1'b1     ), .C(dac_clk_2p), .CE(1'b1), .R(1'b0   ), .S(1'b0));
ODDR oddr_dac_wrt          (.Q(dac_wrt_o), .D1(1'b0     ), .D2(1'b1     ), .C(dac_clk_2x), .CE(1'b1), .R(1'b0   ), .S(1'b0));
ODDR oddr_dac_sel          (.Q(dac_sel_o), .D1(1'b1     ), .D2(1'b0     ), .C(dac_clk_1x), .CE(1'b1), .R(dac_rst), .S(1'b0));
ODDR oddr_dac_rst          (.Q(dac_rst_o), .D1(dac_rst  ), .D2(dac_rst  ), .C(dac_clk_1x), .CE(1'b1), .R(1'b0   ), .S(1'b0));
ODDR oddr_dac_dat [14-1:0] (.Q(dac_dat_o), .D1(dac_dat_b), .D2(dac_dat_a), .C(dac_clk_1x), .CE(1'b1), .R(dac_rst), .S(1'b0));

ODDR i_adc_clk_p ( .Q(adc_clk_o[0]), .D1(1'b1), .D2(1'b0), .C(1'b0), .CE(1'b1), .R(1'b0), .S(1'b0));
ODDR i_adc_clk_n ( .Q(adc_clk_o[1]), .D1(1'b0), .D2(1'b1), .C(1'b0), .CE(1'b1), .R(1'b0), .S(1'b0));

logic rxs_clk, rxs_dat;
IBUFDS #(.IOSTANDARD ("DIFF_HSTL_I_18")) i_IBUFGDS_clk
(
  .I  ( daisy_p_i[1]  ),
  .IB ( daisy_n_i[1]  ),
  .O  ( rxs_clk     )
);

IBUFDS #(.DIFF_TERM ("FALSE"), .IOSTANDARD ("DIFF_HSTL_I_18")) i_IBUFDS_dat
(
  .I  ( daisy_p_i[0]  ),
  .IB ( daisy_n_i[0]  ),
  .O  ( rxs_dat       )
);

OBUFDS #(.IOSTANDARD ("DIFF_HSTL_I_18"), .SLEW ("FAST")) i_OBUF_clk
(
  .O  ( daisy_p_o[1]  ),
  .OB ( daisy_n_o[1]  ),
  .I  ( 1'b0       )
);

OBUFDS #(.IOSTANDARD ("DIFF_HSTL_I_18"), .SLEW ("FAST")) i_OBUF_dat
(
  .O  ( daisy_p_o[0]  ),
  .OB ( daisy_n_o[0]  ),
  .I  ( 1'b0          )
);


assign adc_cdcs_o = 1'b1 ;
assign dac_pwm_o  = 1'b0;
generate
for (genvar i=2; i<7; i++) begin: for_sys2
  sys_bus_stub sys_bus_stub_2_5 (sys[i]);
end: for_sys2
endgenerate

`endif
endmodule: event_ring_red_pitaya_top

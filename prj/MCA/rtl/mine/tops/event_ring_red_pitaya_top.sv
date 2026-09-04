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
 *                   /-------\      
 *   PS DDR <------> |  PS   |      AXI <-> custom bus
 *   PS MIO <------> |   /   | <------------+
 *   PS CLK -------> |  ARM  |              |
 *                   \-------/              |
 *                                          |
 *                            /-------\     |
 *                         -> | SCOPE | <---+
 *                         |  \-------/     |
 *                         |                |
 *            /--------\   |   /-----\      |
 *   ADC ---> |        | --+-> |     |      |
 *            | ANALOG |       | PID | <----+
 *   DAC <--- |        | <---- |     |      |
 *            \--------/   ^   \-----/      |
 *                         |                |
 *                         |  /-------\     |
 *                         -- |  ASG  | <---+ 
 *                            \-------/     |
 *                                          |
 *             /--------\                   |
 *    RX ----> |        |                   |
 *   SATA      | DAISY  | <-----------------+
 *    TX <---- |        | 
 *             \--------/ 
 *               |    |
 *               |    |
 *               (FREE)
 *
 * Inside analog module, ADC data is translated from unsigned neg-slope into
 * two's complement. Similar is done on DAC data.
 *
 * Scope module stores data from ADC into RAM, arbitrary signal generator (ASG)
 * sends data from RAM to DAC. MIMO PID uses ADC ADC as input and DAC as its output.
 *
 * Daisy chain connects with other boards with fast serial link. Data which is
 * send and received is at the moment undefined. This is left for the user.
 */

// =============================================================================
// mca_red_pitaya_top — top del Analizador Multicanal (MCA)
//
// Copia de red_pitaya_top.sv con cuatro diferencias, todas para el MCA:
//   1. mca_top nuevo en el slot 7 del bus (0x4070_0000)
//   2. i_scope con EN_FILT(0): sin el ecualizador osc_filter, cuyo lazo IIR
//      no cierra timing (137 de los 221 endpoints en falla, -1.820 ns)
//   3. sin red_pitaya_asg (slot 2): libera ~17 RAMB36, HP2/HP3 y logica
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
logic [2*14-1:0]         mca_dat_bus;   // muestra acondicionada -> MCA
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
// HP2 pasa a adc_clk (125 MHz) porque ahora lo maneja el event_ring, que vive
// entero en adc_clk. Antes colgaba de dac_axi_clk (250 MHz) porque era del ASG;
// dejarlo asi seria un cruce de dominios sin sincronizar sobre wvalid/wrdy, o
// sea datos corruptos sin ningun sintoma visible. El ASG ya no existe, asi que
// HP2 es de uso exclusivo del ring. Coherente con axi0/axi1, que ya usan adc_clk.
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

assign adc_dat_raw[0] = adc_dat_i[0][16-1 -: ADW];
assign adc_dat_raw[1] = adc_dat_i[1][16-1 -: ADW];

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

// --- event_ring (Fase 1) -------------------------------------------------
// Se cuelga del MISMO trigger conjunto que ya alimenta a rp_bram_sm: el ring
// no agrega una fuente de disparo, agrega un camino de salida.
wire        ring_trig;
wire [16:0] ring_snap;

// Defino con la misma interface que el scope original

rp_scope_multitrigger_com#(
  .CHN(0),
  .N_CH(2),
  .DW(14),
  .RSZ(14),
  .EN_FILT(0)) i_scope (      // sin ecualizador: ver la cabecera
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

  // evento conjunto hacia el event_ring
  .event_trig_o  (ring_trig       ),
  .event_snap_o  (ring_snap       ),

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
  // System bus
  // Ruteo del datapath, desde la region de TOP
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


// --- ASG ELIMINADO -------------------------------------------------------
// Un MCA no necesita generador arbitrario, y sacarlo libera ~17 RAMB36 (dos
// tablas de onda de 16384x14b mas los FIFOs), los puertos HP2/HP3 y bastante
// logica. El estimulo de las pruebas viene del Rigol DG4162 por USB.
// Consecuencias: las salidas del DAC quedan mudas y desaparece trig_asg_out,
// o sea las fuentes de disparo BIT_ASG_P/BIT_ASG_N del OR-mask del scope.
// --- SLOT 2: event_ring (antes el stub del ASG) --------------------------
// Base 0x4020_0000. Toma el slot y el puerto HP que dejo libres el ASG, asi
// que no le saca nada al scope (HP0/HP1) ni al MCA (slot 7).
//
// Las muestras son mca_dat_bus: post-calibracion y PRE-decimacion, las mismas
// que consume el MCA. La decimacion del scope vive aguas abajo y no llega
// hasta aca; si mas adelante se quiere decimar el ring, hay que sacar el
// dv decimado de rp_scope_multitrigger_com igual que se saco event_trig_o.
event_ring_top #(
  .DW      (14),
  .N_CH    (2),
  .PRE_AW  (9),    // 512 muestras de pre-trigger
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

  .sys_addr     (sys[2].addr      ),
  .sys_wdata    (sys[2].wdata     ),
  .sys_wen      (sys[2].wen       ),
  .sys_ren      (sys[2].ren       ),
  .sys_rdata    (sys[2].rdata     ),
  .sys_err      (sys[2].err       ),
  .sys_ack      (sys[2].ack       )
);

assign asg_dat[0]   = '0;
assign asg_dat[1]   = '0;
assign trig_asg_out = 1'b0;

// Los puertos AXI-HP del ASG se atan para que su axi_master quede inactivo.
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
// El slot 3 lo ocupa ahora la region de MULTITRIGGER (0x4030_0000),
// cableada dentro de i_scope junto al bus del OSC.

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
//  Mismo mapa de slots que mca_red_pitaya_top, mas el event_ring en el 2.
////////////////////////////////////////////////////////////////////////////////
integration_cfg #(
  .MAGIC    (32'h494E5447),           // "INTG"
  .VERSION  (32'h0001_0000),
  .GITH     (GITH),
  .EN_OSC(1), .EN_MTRG(1), .EN_MCA(1), .EN_RING(1), .EN_ASG(0), .EN_PID(0),
  .SLOT_OSC(1), .SLOT_RING(2), .SLOT_MTRG(3), .SLOT_TOP(6), .SLOT_MCA(7),
  .N_CH(2), .DW(14), .RSZ(14), .EN_FILT(0),
  .H_AW(14), .H2_AW(7), .PSD_AW(6)
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
  .EN_HIST_H_PSD (1), .H2_AW(7), .PSD_AW(6)  // mapa 2D: 128 x 64
) i_mca (
  .adc_clk_i   (adc_clk     ),
  .adc_rstn_i  (adc_rstn    ),
  .mca_dat_i   (mca_dat_bus ),
  .mca_val_i   (mca_val_bus ),
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

`timescale 1ns/1ps
//=============================================================================
// gen_pulsos — generador de pulsos de preamplificador, en el lugar del ASG.
//
// Para probar el multitrigger y el MCA sin el Rigol, con un estimulo que el
// software conoce bit a bit. Escribe en asg_dat (la entrada del DAC que el ASG
// de Red Pitaya dejo libre) y en trig_asg_out (la fuente ASG del OR_MASK del
// multitrigger). Con eso, sin tocar nada mas del top:
//
//   digital_loop[0] = 1 (HK 0x4000_000C): adc_dat toma el DAC en vez del ADC,
//     y el osciloscopio, el multitrigger, el MCA y el ring ven los pulsos
//     generados, bit a bit. La placa se compara contra la replica del MCA.
//   digital_loop[0] = 0: los pulsos salen por OUT1/OUT2. Con un cable a IN1 es
//     un estimulo analogico, con el ruido del ADC de verdad.
//
// CADA PULSO es un impulso de amplitud A que pasa por dos polos enteros:
//
//   caida   y1 <- trunc0(y1 * DECAE / 2^16) + A * 2^F       (un DSP48)
//   subida  y2 <- y2 + ((y1 - y2) >>> SUBIDA)
//   salida  sat14( trunc0(y2 / 2^F) + BASE + ruido )
//
// con F = 8 bits de fraccion. La caida es la exponencial del preamplificador:
// tau = -1 / ln(DECAE / 2^16) muestras, y la constante del polo-cero que la
// cancela es M = DECAE / (2^16 - DECAE) (Mq = 16 M en el trapecio). Con
// SUBIDA = 0 no hay polo de subida y el pico es exactamente A. Como todo es
// lineal, el apilamiento sale exacto y sin limite de solapamiento.
//
// Los dos redondeos llevan a cero: trunc0 (hacia cero) en la caida hace que y1
// llegue a 0 exacto, y y2 lo sigue sin pasarse (el corrimiento por piso nunca
// sobrepasa a y1). Entre pulsos la salida vuelve exacto a BASE + ruido.
//
// LOS DISPAROS los decide gen_disparos.sv, el mismo motor del generador del
// ring: periodicos, o un Poisson discreto con tiempo muerto DT_MIN. trig_o es
// el pulso que sale; su primera muestra aparece en dat 5 ciclos despues (con
// SUBIDA = 0): el impulso registrado, y1, y2, el redondeo y la suma.
//
// LA AMPLITUD sale de una tabla de 1024 entradas (14 bits con signo) que carga
// el PS. Con CTRL.amp_aleat, cada pulso toma la entrada de los 10 bits altos de
// un xorshift32 propio: con la tabla armada por CDF inversa, cualquier espectro.
// Sin el bit, las toma en orden, de 0 a AMP_N - 1, y vuelve a empezar.
//
// EL RUIDO, si se prende, es la suma de los cuatro bytes de otro xorshift32,
// menos 510 (Irwin-Hall de 4: casi gaussiano, sigma 147.8), corrida RUIDO.sh
// bits: sigma = 147.8 / 2^sh cuentas. Uno nuevo por ciclo.
//
// DETERMINISTA. Todo el estado (los disparos, los dos xorshift, la tabla en
// orden, los polos, el ruido) se reinicia al prender CTRL.en, y los tres
// xorshift salen de una sola SEMILLA (los de la amplitud y el ruido, de
// SEMILLA ^ una constante, impar). El modelo
// (modelos/python_model/gen_pulsos_model.py) predice cada muestra.
//
// Registros (sys_addr[15:0]; el top lo pone en 0x4021_0000, en el slot 2):
//   0x0000 RW CTRL     [0] en  [1] aleatorio  [2] amp_aleat  [3] out1  [4] out2
//   0x0004 RW PERIODO  ciclos entre disparos, modo periodico (>= 2)
//   0x0008 RW UMBRAL   probabilidad por ciclo * 2^32, modo aleatorio
//   0x000C RW DT_MIN   ciclos minimos entre disparos, modo aleatorio (>= 2; 16 bits)
//   0x0010 RW N        cuantos pulsos; 0 = sin fin
//   0x0014 RW SEMILLA  de los tres xorshift; 0 usa 0x2545F491
//   0x0018 R  GEN_CNT  pulsos que salieron desde el arranque
//   0x001C R  ESTADO   [0] generando  [1] llego a N  [2] desborde de y1
//   0x0020 R  MAGIC    "PUL1"
//   0x0024 RW DECAE    16 bits, el factor de caida por muestra * 2^16
//   0x0028 RW SUBIDA   [2:0] el polo de subida: tau ~ 2^SUBIDA muestras; 0 = sin
//   0x002C RW AMP_N    [9:0] entradas en uso en orden; 0 = 1024
//   0x0030 RW BASE     14 bits con signo, sumado a la salida
//   0x0034 RW RUIDO    [3:0] sh  [8] prendido
//   0x1000 RW TABLA    + 4 i, i = 0..1023: la amplitud i, 14 bits con signo
//
// El ESTADO.desborde es pegajoso hasta el proximo arranque: y1 tiene 25 bits
// (16 enteros, 8 veces el fondo de escala) y el apilamiento lo puede pasar con
// tasas y constantes de tiempo absurdas. Si se prende, la traza no sirve.
//=============================================================================
module gen_pulsos #(
  parameter integer DW     = 14,
  parameter integer TAB_AW = 10
)(
  input                      clk_i,
  input                      rstn_i,

  output     [DW-1:0]        dat_a_o,   // hacia asg_dat[0] (OUT1)
  output     [DW-1:0]        dat_b_o,   // hacia asg_dat[1] (OUT2)
  output                     trig_o,    // hacia trig_asg_out

  // bus de sistema
  input      [32-1:0]        sys_addr,
  input      [32-1:0]        sys_wdata,
  input                      sys_wen,
  input                      sys_ren,
  output reg [32-1:0]        sys_rdata,
  output reg                 sys_err,
  output reg                 sys_ack
);

localparam [31:0] MAGIC     = 32'h5055_4C31;   // "PUL1"
localparam [31:0] SEMILLA_0 = 32'h2545_F491;
localparam [31:0] K_AMP     = 32'h9E37_79B9;   // la semilla de la amplitud: SEMILLA ^ K_AMP
localparam [31:0] K_RUIDO   = 32'h7F4A_7C15;   // la del ruido: SEMILLA ^ K_RUIDO
localparam integer F  = 8;                     // bits de fraccion de los polos
localparam integer YW = 25;                    // ancho de y1 e y2: el puerto A del DSP48E1
localparam integer SW = YW - F;                // y2 / 2^F
localparam signed [DW-1:0] DMAX = {1'b0, {(DW-1){1'b1}}};
localparam signed [DW-1:0] DMIN = {1'b1, {(DW-1){1'b0}}};

//-----------------------------------------------------------------------------
// Registros
//-----------------------------------------------------------------------------
reg               cfg_en, cfg_aleat, cfg_amp_aleat, cfg_out1, cfg_out2;
reg        [31:0] cfg_periodo, cfg_umbral, cfg_n, cfg_semilla;
reg        [15:0] cfg_dt_min, cfg_decae;
reg        [ 2:0] cfg_subida;
reg  [TAB_AW-1:0] cfg_amp_n;
reg signed [DW-1:0] cfg_base;
reg        [ 3:0] cfg_ruido_sh;
reg               cfg_ruido_en;

wire        sel_tab = (sys_addr[15:12] == 4'h1);
wire        sel_reg = (sys_addr[15:12] == 4'h0);
wire [7:0]  a       = sys_addr[7:0];

always @(posedge clk_i) begin
  if (!rstn_i) begin
    cfg_en        <= 1'b0;
    cfg_aleat     <= 1'b0;
    cfg_amp_aleat <= 1'b0;
    cfg_out1      <= 1'b0;
    cfg_out2      <= 1'b0;
    cfg_periodo   <= 32'd1000;
    cfg_umbral    <= 32'd0;
    cfg_dt_min    <= 16'd2;
    cfg_n         <= 32'd0;
    cfg_semilla   <= 32'd0;
    cfg_decae     <= 16'd65280;          // M = 255, tau = 255.5 muestras (2 us)
    cfg_subida    <= 3'd0;
    cfg_amp_n     <= {TAB_AW{1'b0}};     // 1024
    cfg_base      <= {DW{1'b0}};
    cfg_ruido_sh  <= 4'd0;
    cfg_ruido_en  <= 1'b0;
  end else if (sys_wen && sel_reg) begin
    case (a)
      8'h00: {cfg_out2, cfg_out1, cfg_amp_aleat, cfg_aleat, cfg_en} <= sys_wdata[4:0];
      8'h04: cfg_periodo  <= sys_wdata;
      8'h08: cfg_umbral   <= sys_wdata;
      8'h0C: cfg_dt_min   <= sys_wdata[15:0];
      8'h10: cfg_n        <= sys_wdata;
      8'h14: cfg_semilla  <= sys_wdata;
      8'h24: cfg_decae    <= sys_wdata[15:0];
      8'h28: cfg_subida   <= sys_wdata[2:0];
      8'h2C: cfg_amp_n    <= sys_wdata[TAB_AW-1:0];
      8'h30: cfg_base     <= sys_wdata[DW-1:0];
      8'h34: {cfg_ruido_en, cfg_ruido_sh} <= {sys_wdata[8], sys_wdata[3:0]};
      default: ;
    endcase
  end
end

//-----------------------------------------------------------------------------
// Los disparos: el motor compartido con gen_eventos (gen_disparos.sv)
//-----------------------------------------------------------------------------
wire        arranque, disp_c, pulso, hecho, activo;
wire [31:0] gen_cnt;

gen_disparos u_disp (
  .clk_i      (clk_i),       .rstn_i    (rstn_i),
  .en_i       (cfg_en),      .run_i     (1'b1),
  .aleat_i    (cfg_aleat),   .periodo_i (cfg_periodo), .umbral_i (cfg_umbral),
  .dt_min_i   (cfg_dt_min),  .n_i       (cfg_n),       .semilla_i(cfg_semilla),
  .arranque_o (arranque),    .disp_o    (disp_c),      .pulso_o  (pulso),
  .cnt_o      (gen_cnt),     .activo_o  (activo),      .hecho_o  (hecho),
  .hold_o     (),            .trig_gen_o()
);

assign trig_o = pulso;

//-----------------------------------------------------------------------------
// Los dos xorshift propios: la amplitud (un paso por pulso) y el ruido (uno
// por ciclo). Sus semillas salen de SEMILLA, asi una sola fija todo.
//-----------------------------------------------------------------------------
function automatic [31:0] xorshift32(input [31:0] v);
  reg [31:0] t;
  begin
    t = v ^ (v << 13);
    t = t ^ (t >> 17);
    xorshift32 = t ^ (t << 5);
  end
endfunction

wire [31:0] sem0     = (cfg_semilla == 32'd0) ? SEMILLA_0 : cfg_semilla;
// Impares: asi nunca son 0 (el xorshift no sale del 0), sin un comparador.
wire [31:0] sem_amp  = (sem0 ^ K_AMP)   | 32'd1;
wire [31:0] sem_rui  = (sem0 ^ K_RUIDO) | 32'd1;

reg  [31:0]       ra, rr;          // xorshift de la amplitud y del ruido
reg  [TAB_AW-1:0] idx;             // la entrada que sigue, en orden

wire [TAB_AW-1:0] idx_c  = cfg_amp_aleat ? ra[31 -: TAB_AW] : idx;
wire [TAB_AW-1:0] amp_m1 = cfg_amp_n - 1'b1;     // 0 - 1 = 1023: AMP_N = 0 son 1024

always @(posedge clk_i) begin
  if (!rstn_i || arranque) begin
    ra  <= sem_amp;
    rr  <= sem_rui;
    idx <= {TAB_AW{1'b0}};
  end else begin
    if (disp_c) begin
      ra  <= xorshift32(ra);
      idx <= (idx == amp_m1) ? {TAB_AW{1'b0}} : idx + 1'b1;
    end
    if (cfg_en) rr <= xorshift32(rr);
  end
end

//-----------------------------------------------------------------------------
// La tabla de amplitudes: un RAMB18 de doble puerto. A es del PS, B del
// generador, que lee en el ciclo de la decision y tiene la amplitud en el
// ciclo en que sale el pulso.
//-----------------------------------------------------------------------------
(* ram_style = "block" *) reg [DW-1:0] tabla [0:(1<<TAB_AW)-1];
reg [DW-1:0] tab_a_q, tab_b_q;

// En cero, como queda la BRAM al cargar el bitstream
integer i_t;
initial for (i_t = 0; i_t < (1 << TAB_AW); i_t = i_t + 1) tabla[i_t] = {DW{1'b0}};

always @(posedge clk_i) begin
  if (sys_wen && sel_tab) tabla[sys_addr[TAB_AW+1:2]] <= sys_wdata[DW-1:0];
  tab_a_q <= tabla[sys_addr[TAB_AW+1:2]];
end

always @(posedge clk_i)
  tab_b_q <= tabla[idx_c];

//-----------------------------------------------------------------------------
// Los polos
//-----------------------------------------------------------------------------
reg  signed [YW-1:0] y1, y2;
reg  signed [SW-1:0] s;            // trunc0(y2 / 2^F)
reg         [9:0]    nsum;         // la suma de los 4 bytes del xorshift del ruido
reg  signed [10:0]   nz;           // el ruido de este ciclo
reg  signed [DW-1:0] dat;
reg                  desborde;

// El impulso, registrado: la BRAM no queda en el camino del DSP. Entra a y1 el
// ciclo despues del pulso.
reg  signed [DW-1:0]  imp;
always @(posedge clk_i)
  if (!rstn_i || arranque) imp <= {DW{1'b0}};
  else                     imp <= pulso ? $signed(tab_b_q) : {DW{1'b0}};

// La caida, en un DSP48: p = y1 * DECAE + (A << (16 + F)) + redondeo. El
// redondeo hacia cero es sumar 2^16 - 1 cuando y1 es negativo (el producto
// tiene el signo de y1, porque DECAE es positivo).
// El impulso y el redondeo no se pisan (el impulso empieza en el bit 16 + F),
// asi que la entrada C es una concatenacion, sin sumador.
wire signed [47:0]    prod = y1 * $signed({1'b0, cfg_decae});
wire signed [47:0]    c_in = {{(48-DW-16-F){imp[DW-1]}}, imp, {F{1'b0}}, {16{y1[YW-1]}}};
wire signed [47:0]    p    = prod + c_in;
wire                  ovf  = (p[16+YW] != p[16+YW-1]);

// La subida: un polo con corrimiento por piso, que nunca pasa a y1
wire signed [YW:0]    e    = y1 - y2;
wire signed [YW:0]    de   = e >>> cfg_subida;

// La salida: y2 / 2^F hacia cero, mas la base y el ruido, saturado
wire signed [SW-1:0]  s_c  = (y2 + (y2[YW-1] ? $signed(YW'((1 << F) - 1)) : $signed(YW'(0)))) >>> F;
wire        [9:0]     nsum_c = rr[7:0] + rr[15:8] + rr[23:16] + rr[31:24];
wire signed [10:0]    nz_c   = ($signed({1'b0, nsum}) - 11'sd510) >>> cfg_ruido_sh;
wire signed [SW+1:0]  suma = s + cfg_base + nz;

always @(posedge clk_i) begin
  if (!rstn_i || arranque) begin
    y1       <= {YW{1'b0}};
    y2       <= {YW{1'b0}};
    s        <= {SW{1'b0}};
    nsum     <= 10'd510;                 // ruido 0 en la primera muestra
    nz       <= 11'sd0;
    dat      <= {DW{1'b0}};
    desborde <= 1'b0;
  end else if (cfg_en) begin
    y1  <= p[16 +: YW];
    y2  <= y2 + de[YW-1:0];
    s    <= s_c;
    nsum <= nsum_c;
    nz   <= cfg_ruido_en ? nz_c : 11'sd0;
    dat <= (suma > $signed({{(SW+2-DW){1'b0}}, DMAX})) ? DMAX :
           (suma < $signed({{(SW+2-DW){1'b1}}, DMIN})) ? DMIN : suma[DW-1:0];
    if (ovf) desborde <= 1'b1;
  end else begin
    dat <= {DW{1'b0}};
  end
end

assign dat_a_o = cfg_out1 ? dat : {DW{1'b0}};
assign dat_b_o = cfg_out2 ? dat : {DW{1'b0}};

//-----------------------------------------------------------------------------
// Lectura y ack (latencia fija, como gen_eventos: la tabla llega a tiempo)
//-----------------------------------------------------------------------------
always @(posedge clk_i) begin
  sys_err <= 1'b0;
  if (sel_tab)
    sys_rdata <= {{(32-DW){tab_a_q[DW-1]}}, tab_a_q};
  else if (sel_reg)
    case (a)
      8'h00:   sys_rdata <= {27'h0, cfg_out2, cfg_out1, cfg_amp_aleat, cfg_aleat, cfg_en};
      8'h04:   sys_rdata <= cfg_periodo;
      8'h08:   sys_rdata <= cfg_umbral;
      8'h0C:   sys_rdata <= {16'h0, cfg_dt_min};
      8'h10:   sys_rdata <= cfg_n;
      8'h14:   sys_rdata <= cfg_semilla;
      8'h18:   sys_rdata <= gen_cnt;
      8'h1C:   sys_rdata <= {29'h0, desborde, hecho, activo};
      8'h20:   sys_rdata <= MAGIC;
      8'h24:   sys_rdata <= {16'h0, cfg_decae};
      8'h28:   sys_rdata <= {29'h0, cfg_subida};
      8'h2C:   sys_rdata <= {{(32-TAB_AW){1'b0}}, cfg_amp_n};
      8'h30:   sys_rdata <= {{(32-DW){cfg_base[DW-1]}}, cfg_base};
      8'h34:   sys_rdata <= {23'h0, cfg_ruido_en, 4'h0, cfg_ruido_sh};
      default: sys_rdata <= 32'h0;
    endcase
  else
    sys_rdata <= 32'h0;
end

reg [2:0] ack_sr;
always @(posedge clk_i) begin
  if (!rstn_i) begin ack_sr <= 3'h0; sys_ack <= 1'b0; end
  else begin
    ack_sr  <= {ack_sr[1:0], (sys_wen || sys_ren)};
    sys_ack <= ack_sr[1];
  end
end

endmodule

`timescale 1ns/1ps
//=============================================================================
// mca_top — analizador multicanal: esclavo del bus de sistema (slot 7)
//
// Base 0x4070_0000. Todo en el dominio adc_clk; el cruce a fclk[0] lo hace
// sys_bus_cdc por slot, así que acá no hace falta CDC.
//
// ACK DE LATENCIA FIJA — es lo más importante de este módulo.
//
// Un esclavo que no hace ack NO produce sólo una lectura mala: deja el CDC del
// slot DESINCRONIZADO. En sys_bus_cdc.sv, reg_done sólo avanza con bus_m.ack,
// así que sin ack queda reg_do != reg_done para siempre, el strobe de lectura
// pegado en alto, y del lado controlador ctrl_do ya no puede togglear: ese slot
// no acepta más transacciones. Al ARM lo rescata el timeout de 32 ciclos de
// rtl/axi4_slave.sv:193, que fabrica un ack por su cuenta, pero la transacción
// devuelve un valor sin sentido y SIN indicación de error.
//
// El scope tiene ese bug latente: ata bram_ack[2]/[3] = 0 para los canales no
// construidos (rp_scope_mt_com.sv:572-573) y
// mt_rp_scope_cfg.sv:506-507 lo usa como ack de las aperturas 3 y 4.
//
// Acá el ack sale de un shift register incondicional: NO existe ninguna ruta de
// ack por motor, así que un motor apagado por parámetro no puede colgar el bus.
// Su apertura simplemente devuelve 0. Ver docs/TOP/bus_sistema_redpitaya.md §7.1.
//
// CONTADORES DE 64 BITS. Leer lo y después hi puede partirse: a 125 MHz el
// contador avanza entre las dos lecturas. Leer la palabra BAJA congela la
// ALTA en un registro sombra, que es lo que devuelve la dirección alta.
//=============================================================================

module mca_top #(
  parameter integer DW      = 14,
  // --- espectro 1D de amplitud ---
  parameter integer EN_HIST_H     = 1,
  parameter integer H_AW          = 14,   // 16384 canales
  // --- mapa 2D amplitud x factor de forma ---
  parameter integer EN_HIST_H_PSD = 1,
  parameter integer H2_AW         = 7,    // 128 bins de amplitud
  parameter integer PSD_AW        = 6,    // 64 bins de forma
  // --- varios ---
  parameter integer AMP_W  = 16,
  parameter integer QW     = 32,
  parameter integer LEN_W  = 16,
  parameter integer DIV_W  = 16,   // bits de cociente de los divisores de forma
  parameter integer NFEAT  = 16,   // ranuras del bus de features
  // Ranuras de medicion: juegos de acumuladores que pueden medir a la vez. El
  // registro cfg_n_acc elige cuantas se usan (1..N_ACC); con 1 es la
  // arquitectura de una ventana con publicacion bloqueante.
  parameter integer N_ACC  = 4,
  // Conformado trapezoidal (mca_trap): el BANCO de formas de F_TRAP. Con 0 no
  // se instancia ninguna, F_TRAP vale cero y CAPS bit 2 lo dice; con 1 es el
  // trapecio unico; con mas, cada ranura elige la forma al publicar (F_FORMA).
  // El registro 0x134 dice cuantas hay y cuantas se usan.
  parameter integer N_FORMAS = 4
)(
  input                    adc_clk_i   ,
  input                    adc_rstn_i  ,

  // --- muestras de los dos canales (post-calib/filtro, pre-decimación) ---
  input      [2*DW-1:0]    mca_dat_i   ,
  input      [2-1:0]       mca_val_i   ,

  // --- veto externo (nivel), del trigger_shield del multitrigger ---
  // Mientras vale 1 no se abren pulsos, el pulso en curso termina normal y el
  // reloj de tiempo vivo se detiene: el tiempo va a `vetotime`. Atar a 0 si
  // el top no lo usa.
  input                    veto_i      ,

  // --- trigger externo: el UNICO que abre ventanas (se toma por FLANCO) ---
  // Viene del trigger_event del multitrigger, ya en adc_clk, asi que no hace
  // falta CDC. Llega con la latencia del disparo por pendiente: la compensa la
  // linea de retardo de muestras (cfg_pre_dly). Atado a 0, el MCA no abre nunca.
  input                    trig_i      ,

  // --- estado del disparo (nivel), del multitrigger ---
  // 1 = algun canal del multitrigger puede disparar ya. Con 0 el disparo esta
  // esperando re-armar (el Schmitt no bajo de thr - hyst), y un pulso que llegue
  // no genera flanco: el MCA no lo ve, asi que lo unico medible es el TIEMPO, que
  // va a t_rearm en vez de a livetime. Atar a 1 si el top no lo tiene (es el
  // comportamiento de antes).
  input                    trig_arm_i  ,

  // --- bus de sistema ---
  input      [32-1:0]      sys_addr    ,
  input      [32-1:0]      sys_wdata   ,
  input                    sys_wen     ,
  input                    sys_ren     ,
  output reg [32-1:0]      sys_rdata   ,
  output reg               sys_err     ,
  output reg               sys_ack
);

// "MCA2": el mapa de las ranuras. Cambio de proposito respecto de "MCA1": se
// fueron el Schmitt interno, la histeresis, el re-armado y el modo de
// publicacion, y el software tiene que poder darse cuenta.
localparam [31:0] MAGIC = 32'h4D434132;   // "MCA2"

//=============================================================================
// Registros de configuración
//=============================================================================
reg              cfg_run;
reg              cfg_chan;                // 0 = IN1, 1 = IN2
reg signed [DW-1:0] cfg_baseline;
reg              cfg_bl_auto;
reg        [3:0] cfg_bl_k;
reg [LEN_W-1:0]  cfg_bl_holdoff;
reg [LEN_W-1:0]  cfg_gate_short;
reg [LEN_W-1:0]  cfg_gate_long;
reg [AMP_W-1:0]  cfg_amp_min;
reg [AMP_W-1:0]  cfg_amp_max;
reg              cfg_amp_src;
reg [4:0]        cfg_q_shift;

// Las ranuras y la linea de retardo
localparam integer NA_W  = 3;      // bits de cfg_n_acc
localparam integer DLY_W = 7;      // bits de cfg_pre_dly (0..127 ciclos)
reg [NA_W-1:0]   cfg_n_acc;        // ranuras habilitadas, 1..N_ACC
reg [DLY_W-1:0]  cfg_pre_dly;      // retardo de la muestra respecto de trig_i

// El banco de trapecios. Por forma f: k y m (en muestras); off y lw ubican la
// ventana sobre la meseta (desde la apertura, en muestras del trapecio); sh
// escala F_TRAP; antes y despues son los umbrales de dt_prev y dt_next con los
// que la ranura la elige. M, la constante polo-cero en punto fijo con 4 bits
// fraccionarios, es comun. La forma 0 es la del trapecio unico de antes: sus
// registros se leen y escriben tambien en 0x128 y 0x130.
localparam integer TDAW = 10;      // lineas de retardo de 1024 muestras
localparam integer TMW  = 20;      // M hasta 65535.9375 muestras
localparam integer TRAP_LAT = 8;   // la de mca_trap: solo para trap_ok
localparam integer NF   = (N_FORMAS < 1) ? 1 : N_FORMAS;
reg [TDAW-1:0]   cfg_trap_k  [0:NF-1];
reg [TDAW-1:0]   cfg_trap_m  [0:NF-1];
reg [LEN_W-1:0]  cfg_trap_off[0:NF-1];
reg [2:0]        cfg_trap_lw [0:NF-1];
reg [5:0]        cfg_trap_sh [0:NF-1];
reg [LEN_W-1:0]  cfg_trap_antes  [0:NF-1];
reg [LEN_W-1:0]  cfg_trap_despues[0:NF-1];
reg [TMW-1:0]    cfg_trap_mq;
reg [2:0]        cfg_n_formas;     // formas que se usan, 1..N_FORMAS

// DEPRECADOS. Se siguen decodificando —se escriben y se leen— para que el
// software viejo no vea errores, pero YA NO AFECTAN AL DATAPATH: el eje pasó de
// `amp >> h_shift` a "feature normalizada, los AW bits altos de la ventana de
// zoom". Se conservan en vez de borrarse porque hay datos guardados con ese
// metadato; la conversión canal->volts vive en counts_to_volts(h_aw=...).
reg [4:0]        cfg_h_shift;      // sin efecto: lo subsume cfg_zoom_1d
reg [4:0]        cfg_h2_shift;     // sin efecto: lo subsume cfg_zoom_2dx

// Que feature alimenta cada eje. Los indices son los localparam F_* de
// mca_pulse_feature: un solo espacio de numeracion para los tres ejes.
reg [3:0]        cfg_sel_1d, cfg_sel_2dx, cfg_sel_2dy;
// Zoom por eje: {k[15:8], z[3:0]}. z=0 es fondo de escala, o sea el
// comportamiento historico.
reg [3:0]        cfg_z_1d,  cfg_z_2dx,  cfg_z_2dy;
reg [7:0]        cfg_k_1d,  cfg_k_2dx,  cfg_k_2dy;
reg [16-1:0]     cfg_dec;
reg              cfg_keep_full;   // 1 = seguir contando con el histograma lleno
// Discriminador: una condicion sobre una feature elegida.
reg              cfg_discr_en, cfg_discr_out;
reg [3:0]        cfg_discr_sel;
reg [AMP_W-1:0]  cfg_discr_min, cfg_discr_max;
reg [31:0]       cnt_rej_discr;

// Pulsos de un ciclo generados por escritura
reg              clr_pulse;               // borra histogramas y contadores
reg              trap_wr;                 // se escribio la forma del trapecio

wire sys_en = sys_wen | sys_ren;

//=============================================================================
// Decimación propia del MCA (independiente del set_dec del scope)
//=============================================================================
wire [DW-1:0] dat_sel = cfg_chan ? mca_dat_i[2*DW-1:DW] : mca_dat_i[DW-1:0];
wire          val_sel = cfg_chan ? mca_val_i[1]         : mca_val_i[0];

reg [16-1:0] dec_cnt;
wire         dec_pass = (cfg_dec <= 16'd1) || (dec_cnt >= (cfg_dec - 16'd1));
wire         dat_val  = val_sel && dec_pass;

always @(posedge adc_clk_i)
  if (!adc_rstn_i)      dec_cnt <= 16'd0;
  else if (val_sel)     dec_cnt <= dec_pass ? 16'd0 : (dec_cnt + 16'd1);

// Registro de entrada. Corta el camino que venia desde el registro de salida
// de la calibracion del scope (i_calib_ch/calib_dat_o) y atravesaba el mux de
// canal, el decimador y toda la logica de umbral del extractor: eran 34 de los
// 60 endpoints en falla del build. El MCA no tiene relacion temporal con nada
// mas, asi que un ciclo de latencia extra es gratis.
reg [DW-1:0] dat_q;
reg          val_q;
always @(posedge adc_clk_i)
  if (!adc_rstn_i) begin
    dat_q <= {DW{1'b0}};
    val_q <= 1'b0;
  end else begin
    dat_q <= dat_sel;
    val_q <= dat_val;
  end

//=============================================================================
// Linea de retardo de muestras
//=============================================================================
// El trigger externo llega TARDE respecto de la muestra que lo causo (el
// disparo por pendiente necesita del orden de L muestras para cruzar su
// umbral). Retrasando la muestra, la ventana abre en el pie del pulso. Ver
// mca_delay.sv. Latencia: cfg_pre_dly + 1 ciclos.
wire [DW-1:0] dat_d;
wire          val_d;

mca_delay #(.W(DW+1), .DLW(DLY_W)) i_dly (
  .clk_i(adc_clk_i), .dat_i({val_q, dat_q}), .dly_i(cfg_pre_dly),
  .dat_o({val_d, dat_d})
);

//=============================================================================
// Extractor de características
//=============================================================================
wire                ev_valid;
wire [AMP_W-1:0]    ev_amp;
wire [PSD_AW-1:0]   ev_psd;
wire                ev_psd_ok;
wire signed [DW-1:0] baseline_now;
wire                bl_stale, feat_busy;
wire [31:0]         c_total, c_acc, c_rej_amp, c_rej_psd, c_pileup, c_lost;
wire [QW-1:0]       last_qtot, last_qtail;

// Casilleros de tiempo muerto y atribucion de arribos (ver "Relojes").
localparam integer OC_W = $clog2(N_ACC + 1);
wire                dt_win, dt_div, puede_abrir, arribo;
wire [OC_W-1:0]     n_ocup;
wire [31:0]         c_cross, c_open, c_lost_active, c_lost_veto;
wire [31:0]         c_win, c_trig;
wire [OC_W-1:0]     pub_occ, pub_occ_max;
wire [15:0]         last_win_id;

wire [NFEAT*AMP_W-1:0] ev_feat;

// La forma efectiva de cada trapecio, registrada: k >= 1 (con k = 0 la linea
// de retardo leeria la direccion que escribe) y l = k + m satura en 2^TDAW - 1,
// lo mas largo que entra en la BRAM. Cambiar cualquier forma o M, o el clear
// del MCA, reinicia el estado de todos (ver "Por que enteros exactos" en
// mca_trap.sv). Todo va aplanado hacia mca_pulse_feature.
reg  [NF*TDAW-1:0]  trap_k_v, trap_l_v;
reg  [NF-1:0]       trap_ok;
reg                 trap_clr;
wire [NF*6-1:0]     trap_sh_v;
wire [NF*LEN_W-1:0] trap_off_v, trap_antes_v, trap_despues_v;
wire [NF*3-1:0]     trap_lw_v;

genvar gf;
generate for (gf = 0; gf < NF; gf = gf + 1) begin : g_forma_cfg
  wire [TDAW:0] kl = {1'b0, (cfg_trap_k[gf] == {TDAW{1'b0}}) ? {{(TDAW-1){1'b0}}, 1'b1}
                                                             : cfg_trap_k[gf]} + {1'b0, cfg_trap_m[gf]};
  // La ventana de la meseta tiene que terminar antes de que cierre la
  // compuerta; si no, ninguna ranura la completa y esa forma no se publica.
  // Se lee en el bit 31 de FORMA_MED (y de 0x130 la de la forma 0).
  wire [LEN_W+1:0] fin = {2'b0, cfg_trap_off[gf]} + TRAP_LAT
                       + ({{(LEN_W+1){1'b0}}, 1'b1} << cfg_trap_lw[gf]);
  always @(posedge adc_clk_i)
    if (!adc_rstn_i) begin
      trap_k_v[gf*TDAW +: TDAW] <= {{(TDAW-1){1'b0}}, 1'b1};
      trap_l_v[gf*TDAW +: TDAW] <= {{(TDAW-1){1'b0}}, 1'b1};
      trap_ok[gf] <= 1'b0;
    end else begin
      trap_k_v[gf*TDAW +: TDAW] <= (cfg_trap_k[gf] == {TDAW{1'b0}}) ? {{(TDAW-1){1'b0}}, 1'b1}
                                                                    : cfg_trap_k[gf];
      trap_l_v[gf*TDAW +: TDAW] <= kl[TDAW] ? {TDAW{1'b1}} : kl[TDAW-1:0];
      trap_ok[gf] <= (fin <= {2'b0, cfg_gate_long});
    end
  assign trap_sh_v     [gf*6     +: 6]     = cfg_trap_sh[gf];
  assign trap_off_v    [gf*LEN_W +: LEN_W] = cfg_trap_off[gf];
  assign trap_lw_v     [gf*3     +: 3]     = cfg_trap_lw[gf];
  assign trap_antes_v  [gf*LEN_W +: LEN_W] = cfg_trap_antes[gf];
  assign trap_despues_v[gf*LEN_W +: LEN_W] = cfg_trap_despues[gf];
end endgenerate

always @(posedge adc_clk_i)
  if (!adc_rstn_i) trap_clr <= 1'b1;
  else             trap_clr <= clr_pulse || trap_wr;

// Los umbrales de despues tienen que entrar en la compuerta: F_DTNEXT solo ve
// los disparos de adentro de la ventana, y uno a dt >= gate_long no se ve. Si
// despues[f] > gate_long, un vecino entre los dos no la descartaria. Se lee en
// el bit 31 de 0x134, para las formas que se usan.
wire [2:0] nf_hab = (cfg_n_formas == 3'd0) ? 3'd1
                  : (cfg_n_formas > NF[2:0]) ? NF[2:0] : cfg_n_formas;
reg  umbr_ok;
integer ku;
always @(posedge adc_clk_i) begin : g_umbr_ok
  reg ok;
  ok = 1'b1;
  for (ku = 0; ku < NF; ku = ku + 1)
    if ((ku < nf_hab) && (cfg_trap_despues[ku] > cfg_gate_long)) ok = 1'b0;
  umbr_ok <= ok;
end

mca_pulse_feature #(
  .DW(DW), .QW(QW), .AMP_W(AMP_W), .PSD_AW(PSD_AW), .DIV_W(DIV_W),
  .NFEAT(NFEAT), .LEN_W(LEN_W), .EN_PSD(EN_HIST_H_PSD),
  .N_ACC(N_ACC), .PUB_IDW(16), .NA_W(NA_W),
  .N_FORMAS(N_FORMAS), .TDAW(TDAW), .TMW(TMW)
) i_feat (
  .clk_i(adc_clk_i), .rstn_i(adc_rstn_i),
  .dat_i($signed(dat_d)), .val_i(val_d),
  .cfg_run_i(cfg_run), .veto_i(veto_i), .cnt_clr_i(clr_pulse),
  .cfg_baseline_i(cfg_baseline), .cfg_bl_auto_i(cfg_bl_auto),
  .cfg_bl_k_i(cfg_bl_k), .cfg_bl_holdoff_i(cfg_bl_holdoff),
  .cfg_gate_short_i(cfg_gate_short), .cfg_gate_long_i(cfg_gate_long),
  .cfg_amp_min_i(cfg_amp_min), .cfg_amp_max_i(cfg_amp_max),
  .cfg_amp_src_i(cfg_amp_src), .cfg_q_shift_i(cfg_q_shift),
  .cfg_n_acc_i(cfg_n_acc), .trig_i(trig_i),
  .trap_clr_i(trap_clr), .cfg_trap_k_i(trap_k_v), .cfg_trap_l_i(trap_l_v),
  .cfg_trap_mq_i(cfg_trap_mq), .cfg_trap_sh_i(trap_sh_v),
  .cfg_trap_off_i(trap_off_v), .cfg_trap_lw_i(trap_lw_v),
  .cfg_trap_antes_i(trap_antes_v), .cfg_trap_despues_i(trap_despues_v),
  .cfg_n_formas_i(cfg_n_formas),
  .ev_valid_o(ev_valid), .ev_amp_o(ev_amp), .ev_psd_o(ev_psd),
  .ev_psd_ok_o(ev_psd_ok), .ev_feat_o(ev_feat),
  .baseline_o(baseline_now), .baseline_stale_o(bl_stale),
  .cnt_total_o(c_total), .cnt_accepted_o(c_acc), .cnt_rej_amp_o(c_rej_amp),
  .cnt_rej_psd_o(c_rej_psd), .cnt_pileup_o(c_pileup), .cnt_lost_busy_o(c_lost),
  .last_qtot_o(last_qtot), .last_qtail_o(last_qtail),
  .busy_o(feat_busy),
  .dt_win_o(dt_win), .dt_div_o(dt_div), .puede_abrir_o(puede_abrir),
  .n_ocup_o(n_ocup), .arribo_o(arribo),
  .cnt_cross_o(c_cross), .cnt_open_o(c_open),
  .cnt_lost_active_o(c_lost_active), .cnt_lost_veto_o(c_lost_veto),
  .cnt_win_o(c_win),
  .pub_occ_o(pub_occ), .pub_occ_max_o(pub_occ_max),
  .last_win_id_o(last_win_id), .cnt_trig_o(c_trig)
);

//=============================================================================
// De feature a bin: MUX de eje + ZOOM
//
// El bus de features es INTERNO: no sale al software. El ARM sigue leyendo las
// mismas aperturas 0x10000 y 0x20000. Lo unico que cambia del lado del software
// es un registro que dice que feature alimenta cada eje.
//
// El mux 16:1 y el zoom viven DESPUES del registro ev_feat_o del extractor, o
// sea que arrancan un camino nuevo en vez de alargar el del cierre —que es el
// que esta en falla de timing (WNS -0.294 ns).
//
// La saturacion sigue siendo el contrato: un evento nunca aparece en el extremo
// opuesto del eje. Con zoom, ademas, los bins de los extremos hacen de
// indicadores de desborde de la ventana, que con la deriva medida importa (a
// z=3 un corrimiento del 6.45 % mueve el pico un 41 % del ancho de ventana).
//=============================================================================
// El mux va como part-select indexada y NO como function. Con una function en
// un assign continuo, la sensibilidad se arma con los ARGUMENTOS: `ev_feat` se
// lee del alcance exterior y no entra en la lista, asi que la salida solo se
// actualizaba al cambiar el selector y se quedaba clavada en el valor de reset.
// El sintetizador lo resolvia bien y la simulacion no: lo agarro tb_mca_top con
// las cuentas apareciendo en el canal 0.
wire [AMP_W-1:0] f_1d  = ev_feat[cfg_sel_1d  * AMP_W +: AMP_W];
wire [AMP_W-1:0] f_2dx = ev_feat[cfg_sel_2dx * AMP_W +: AMP_W];
wire [AMP_W-1:0] f_2dy = ev_feat[cfg_sel_2dy * AMP_W +: AMP_W];

// La feature de cada eje se REGISTRA antes del zoom. Con F_FORMA el bus tiene
// once features que no son cero, el mux 16:1 suma un nivel, y el camino
// ev_feat -> mux -> zoom -> bin quedo en 11 niveles: -0.345 ns en la OOC. Es
// un ciclo mas entre el evento y su escritura al histograma, y nada depende
// de cuando ocurre (ver la etapa de pipeline de abajo). El evento y su psd_ok
// viajan con la feature.
reg [AMP_W-1:0] f_1d_q, f_2dx_q, f_2dy_q;

//=============================================================================
// Discriminador. Va DESPUES de los divisores para que el selector alcance a las
// features de forma; el detalle esta en mca_discriminator.sv.
//=============================================================================
wire discr_ok;

mca_discriminator #(.FW(AMP_W), .NFEAT(NFEAT)) i_discr (
  .ev_feat_i(ev_feat), .cfg_en_i(cfg_discr_en), .cfg_sel_i(cfg_discr_sel),
  .cfg_out_i(cfg_discr_out), .cfg_min_i(cfg_discr_min),
  .cfg_max_i(cfg_discr_max), .accept_o(discr_ok)
);

// Un evento rechazado por el discriminador NO entra a ningun motor, y se cuenta
// aparte de cnt_rej_amp: son dos criterios distintos y hay que poder atribuir
// la perdida a cada uno.
wire ev_hist = ev_valid && discr_ok;

always @(posedge adc_clk_i)
  if (!adc_rstn_i || clr_pulse)   cnt_rej_discr <= 32'h0;
  else if (ev_valid && !discr_ok) cnt_rej_discr <= cnt_rej_discr + 32'h1;

wire [H_AW-1:0]  h_bin;
wire [H2_AW-1:0] h2_bin;
wire [PSD_AW-1:0] h2y_bin;

reg ev_hist_p, ev_psd_ok_p;
always @(posedge adc_clk_i)
  if (!adc_rstn_i) begin
    f_1d_q <= {AMP_W{1'b0}}; f_2dx_q <= {AMP_W{1'b0}}; f_2dy_q <= {AMP_W{1'b0}};
    ev_hist_p <= 1'b0; ev_psd_ok_p <= 1'b0;
  end else begin
    f_1d_q <= f_1d; f_2dx_q <= f_2dx; f_2dy_q <= f_2dy;
    ev_hist_p <= ev_hist; ev_psd_ok_p <= ev_psd_ok;
  end

mca_zoom #(.FW(AMP_W), .AW(H_AW))   i_zoom_1d
  (.feat_i(f_1d_q),  .z_i(cfg_z_1d),  .k_i(cfg_k_1d),  .bin_o(h_bin));
mca_zoom #(.FW(AMP_W), .AW(H2_AW))  i_zoom_2dx
  (.feat_i(f_2dx_q), .z_i(cfg_z_2dx), .k_i(cfg_k_2dx), .bin_o(h2_bin));
mca_zoom #(.FW(AMP_W), .AW(PSD_AW)) i_zoom_2dy
  (.feat_i(f_2dy_q), .z_i(cfg_z_2dy), .k_i(cfg_k_2dy), .bin_o(h2y_bin));

//-----------------------------------------------------------------------------
// ETAPA DE PIPELINE entre el zoom y los motores. Es obligatoria, y el motivo se
// midio: sin ella el camino ev_feat_o -> mem de mca_hist tiene DIEZ niveles de
// logica (mux 16:1 + barrel shifter del zoom + comparador + mux de saturacion +
// decodificacion de direccion) y la sintesis paso de WNS -0.294 ns / 49
// endpoints a -0.571 / 166, con los 166 en ESE camino.
//
// El razonamiento que fallo, por si vuelve a tentar: "el mux sale de un
// registro, asi que arranca un camino nuevo". Es cierto y es irrelevante — lo
// que importa no es de donde arranca sino cuanta logica hay HASTA el proximo
// registro, y el destino es la direccion de una BRAM.
//
// Cuesta un ciclo mas de latencia entre el evento y su escritura al histograma.
// No hay nada que dependa de cuando ocurre esa escritura, asi que es gratis.
// `inc` y las tres direcciones se registran JUNTOS: si se desalinearan, el
// evento se contaria en el bin del evento anterior.
//-----------------------------------------------------------------------------
reg [H_AW-1:0]   h_bin_q;
reg [H2_AW-1:0]  h2_bin_q;
reg [PSD_AW-1:0] h2y_bin_q;
reg              ev_hist_q, ev_psd_ok_q;

always @(posedge adc_clk_i)
  if (!adc_rstn_i) begin
    h_bin_q <= {H_AW{1'b0}}; h2_bin_q <= {H2_AW{1'b0}};
    h2y_bin_q <= {PSD_AW{1'b0}};
    ev_hist_q <= 1'b0; ev_psd_ok_q <= 1'b0;
  end else begin
    h_bin_q   <= h_bin;
    h2_bin_q  <= h2_bin;
    h2y_bin_q <= h2y_bin;
    ev_hist_q <= ev_hist_p;
    ev_psd_ok_q <= ev_psd_ok_p;
  end

//=============================================================================
// Estrobo de lectura de bus: UN ciclo. sys_bus_cdc mantiene ren alto hasta el
// ack (~4 ciclos); si se pasara directo a los motores, cada acceso robaría 4
// ciclos al pipeline de incremento en vez de 1.
//=============================================================================
reg [7:0] en_sr;
always @(posedge adc_clk_i)
  if (!adc_rstn_i) en_sr <= 8'h0;
  else             en_sr <= {en_sr[6:0], sys_en};

wire rd_stb = sys_en && !en_sr[0];

// Lo mismo para la escritura: sys_bus_cdc sostiene wen hasta el ack (~5
// ciclos), así que sin estrobo cada transacción ejecutaría el case 5 veces.
// Para los registros de config sería inocuo (es idempotente), pero clr_pulse
// quedaría alto 5 ciclos en vez de uno.
wire wr_stb = sys_wen && !en_sr[0];

//=============================================================================
// Motores de histograma
//=============================================================================
wire [31:0] hist_h_data,  hist_2d_data;
wire        hist_h_busy,  hist_2d_busy;
wire [31:0] hist_h_drop,  hist_2d_drop;
wire        hist_h_full,  hist_2d_full;
wire [31:0] hist_h_supp,  hist_2d_supp;

generate if (EN_HIST_H) begin : g_hist_h
  mca_hist #(.AW(H_AW), .CW(32)) i_hist_h (
    .clk_i(adc_clk_i), .rstn_i(adc_rstn_i),
    .inc_i(ev_hist_q), .inc_addr_i(h_bin_q),
    .clear_i(clr_pulse), .busy_o(hist_h_busy),
    .cfg_keep_i(cfg_keep_full), .full_o(hist_h_full),
    .rd_i(rd_stb && (sys_addr[19:16] == 4'h1)), .rd_addr_i(sys_addr[H_AW+1:2]),
    .rd_data_o(hist_h_data), .dropped_o(hist_h_drop),
    .suppressed_o(hist_h_supp)
  );
end else begin : g_no_hist_h
  assign hist_h_data = 32'h0;
  assign hist_h_busy = 1'b0;
  assign hist_h_drop = 32'h0;
  assign hist_h_full = 1'b0;
  assign hist_h_supp = 32'h0;
end endgenerate

generate if (EN_HIST_H_PSD) begin : g_hist_2d
  mca_hist #(.AW(H2_AW+PSD_AW), .CW(32)) i_hist_2d (
    .clk_i(adc_clk_i), .rstn_i(adc_rstn_i),
    // Sólo entran los eventos con factor de forma válido; los rechazados por
    // el divisor siguen contando en el espectro 1D pero no en el mapa 2D.
    .inc_i(ev_hist_q && ev_psd_ok_q), .inc_addr_i({h2_bin_q, h2y_bin_q}),
    .clear_i(clr_pulse), .busy_o(hist_2d_busy),
    .cfg_keep_i(cfg_keep_full), .full_o(hist_2d_full),
    .rd_i(rd_stb && (sys_addr[19:16] == 4'h2)),
    .rd_addr_i(sys_addr[H2_AW+PSD_AW+1:2]),
    .rd_data_o(hist_2d_data), .dropped_o(hist_2d_drop),
    .suppressed_o(hist_2d_supp)
  );
end else begin : g_no_hist_2d
  assign hist_2d_data = 32'h0;
  assign hist_2d_busy = 1'b0;
  assign hist_2d_drop = 32'h0;
  assign hist_2d_full = 1'b0;
  assign hist_2d_supp = 32'h0;
end endgenerate

wire clear_busy = hist_h_busy || hist_2d_busy;

//=============================================================================
// Relojes de adquisición
//=============================================================================
// TESELADO. Con cfg_run, cada ciclo de adc_clk se atribuye a EXACTAMENTE un
// casillero, y la invariante
//
//     realtime == vetotime + t_win + t_div + livetime
//
// vale en todo ciclo. Esta como assertion en sim/sva/mca_top_sva.sv; es la
// propiedad que hace que el seguimiento sea exhaustivo y no una colección de
// contadores que hay que creer.
//
// El veto tiene prioridad sobre el estado interno: la cola de una ventana que
// termina bajo veto cuenta como tiempo vetado, no muerto. Es la convencion de
// una compuerta de MCA (gate/anticoincidencia): el reloj vivo se para mientras
// la compuerta esta cerrada, sea cual sea el estado interno.
//
// Con ranuras, "muerto" es NO HAY RANURA LIBRE, y la causa lo parte en dos:
//   t_win  todas las ranuras habilitadas estan midiendo
//   t_div  ninguna libre y al menos una esperando que el publicador la tome
// Con una sola ranura son la ventana abierta y la espera de los divisores, como
// en la arquitectura de una ventana.
//
// RE-ARMADO. El disparo lo da el multitrigger, y despues de cada uno su
// Schmitt no vuelve a disparar hasta bajar de thr - hyst: en ese lapso un pulso
// no genera flanco y se pierde sin llegar a cnt_cross. t_rearm cuenta ese
// tiempo con trig_arm_i = 0, DESPUES de t_win y t_div: es el tiempo muerto que
// agrega el disparo cuando el MCA podia abrir. Asi t_win, t_div, los periodos
// muertos y la ocupacion no cambian, y livetime queda como lo que un pulso ve
// de verdad: alguna ranura libre y el disparo armado. Con arribos Poisson, la
// fraccion perdida por el disparo es t_rearm / (realtime - vetotime).
//
// deadtime_cnt (0x078) se conserva como "alguna ranura ocupada" (feat_busy).
// Con una ranura coincide con t_win + t_div; con mas, cuenta tiempo en que el
// modulo SI podia abrir, asi que no es tiempo muerto: es la ocupacion.
//
// OCUPACION. t_ocup[j] cuenta los ciclos con exactamente j ranuras ocupadas
// (j = 0..N_ACC, con run y sin veto). Es la medicion directa del modelo
// M/D/N/N: con arribos Poisson la fraccion de tiempo con j ocupadas sigue la
// distribucion de Erlang, y la de todas ocupadas es la perdida, B(N, rho).
// Invariante: la suma de los t_ocup es realtime - vetotime.
reg [63:0] realtime_cnt, livetime_cnt, deadtime_cnt, vetotime_cnt;
reg [63:0] t_win_cnt, t_div_cnt, t_rearm_cnt, t_clear_cnt;
reg [63:0] t_ocup_cnt [0:N_ACC];

// Los ciclos que suman al tiempo muerto. Es tambien el "periodo muerto" cuya
// distribucion se mide abajo, asi que la suma de todos los L da exactamente
// t_win + t_div y E[L] sale sin correcciones.
wire bloqueado = cfg_run && !veto_i && (dt_win || dt_div);

integer ko;
always @(posedge adc_clk_i) begin
  if (!adc_rstn_i || clr_pulse) begin
    realtime_cnt <= 64'h0; livetime_cnt <= 64'h0; deadtime_cnt <= 64'h0;
    vetotime_cnt <= 64'h0;
    t_win_cnt    <= 64'h0; t_div_cnt    <= 64'h0;
    t_rearm_cnt  <= 64'h0;
    t_clear_cnt  <= 64'h0;
    for (ko = 0; ko <= N_ACC; ko = ko + 1) t_ocup_cnt[ko] <= 64'h0;
  end else if (cfg_run) begin
    realtime_cnt <= realtime_cnt + 64'h1;
    if      (veto_i)   vetotime_cnt <= vetotime_cnt + 64'h1;
    else if (dt_win)   t_win_cnt    <= t_win_cnt    + 64'h1;
    else if (dt_div)   t_div_cnt    <= t_div_cnt    + 64'h1;
    else if (!trig_arm_i) t_rearm_cnt <= t_rearm_cnt + 64'h1;
    else               livetime_cnt <= livetime_cnt + 64'h1;

    if (!veto_i) t_ocup_cnt[n_ocup] <= t_ocup_cnt[n_ocup] + 64'h1;

    // Ocupacion de alguna ranura: la definicion vieja de "tiempo muerto".
    if (!veto_i && feat_busy) deadtime_cnt <= deadtime_cnt + 64'h1;

    // El barrido de borrado del histograma es tiempo en que los eventos se
    // descartan (van a cnt_dropped) pero las ranuras siguen midiendo, asi que
    // NO es un casillero del teselado: es ortogonal y va aparte.
    if (clear_busy) t_clear_cnt <= t_clear_cnt + 64'h1;
  end
end

//=============================================================================
// Distribución del período muerto
//=============================================================================
// Tres escalares sobre los periodos en que no hay ranura libre. Con una sola
// ranura cada periodo dura exactamente tau = gate_long + 18 (la ventana y la
// publicacion): sin dispersion, max_dead_len = E[L]. Con varias, un periodo
// arranca cuando se ocupa la ultima ranura libre y termina cuando se libera
// alguna, asi que su largo es variable y su distribucion es la del modelo
// M/D/N/N.
//
// cnt_dead_ext cuenta PERIODOS CON ARRIBO, no arribos: un periodo con tres
// disparos adentro cuenta UNA vez. El cociente cnt_dead_ext / cnt_dead_periods
// es la fraccion de periodos en que llego un pulso que se perdio.
//
// Un veto en medio de un bloqueo lo PARTE en dos periodos, porque `bloqueado`
// excluye el veto para que la suma de los L cierre con los relojes. Con el veto
// apagado —el caso de toda caracterizacion de tiempo muerto— no pasa nunca.
reg [31:0] dead_len;                    // largo del periodo muerto en curso
reg [31:0] max_dead_len;
reg [31:0] cnt_dead_periods, cnt_dead_ext;
reg        bloq_q;                      // para el flanco
reg        ext_visto;                   // ya se conto la extension de ESTE periodo

wire dead_len_sat = (dead_len == 32'hFFFF_FFFF);
// Un disparo durante el bloqueo es un pulso perdido (no hay donde medirlo).
// Ya no alarga el periodo: el re-armado lo hace el multitrigger, no la senal.
wire dead_ext_now = bloqueado && arribo && !ext_visto;

always @(posedge adc_clk_i) begin
  if (!adc_rstn_i || clr_pulse) begin
    dead_len <= 32'h0; max_dead_len <= 32'h0;
    cnt_dead_periods <= 32'h0; cnt_dead_ext <= 32'h0;
    bloq_q <= 1'b0; ext_visto <= 1'b0;
  end else begin
    bloq_q <= bloqueado;

    if (bloqueado) begin
      if (!bloq_q) begin                       // flanco: arranca un periodo
        dead_len         <= 32'h1;
        cnt_dead_periods <= cnt_dead_periods + 32'h1;
        ext_visto        <= 1'b0;
      end else if (!dead_len_sat) begin
        dead_len <= dead_len + 32'h1;
      end
      if (dead_ext_now) begin
        cnt_dead_ext <= cnt_dead_ext + 32'h1;
        ext_visto    <= 1'b1;
      end
    end else if (bloq_q) begin                 // se cerro: queda el maximo
      if (dead_len > max_dead_len) max_dead_len <= dead_len;
      ext_visto <= 1'b0;
    end
  end
end

//=============================================================================
// Escritura de registros
//=============================================================================
integer kr;
always @(posedge adc_clk_i) begin
  if (!adc_rstn_i) begin
    cfg_run <= 1'b0; cfg_chan <= 1'b0;
    cfg_baseline <= 0;
    cfg_bl_auto <= 1'b0; cfg_bl_k <= 4'd6; cfg_bl_holdoff <= 16'd0;
    cfg_gate_short <= 16'd32; cfg_gate_long <= 16'd384;
    cfg_amp_min <= 16'd0; cfg_amp_max <= 16'hFFFF;
    cfg_amp_src <= 1'b0; cfg_q_shift <= 5'd0;
    cfg_h_shift <= 5'd0; cfg_h2_shift <= 5'd0;
    // Defaults = comportamiento historico: eje 1D con la amplitud de PICO
    // (§5 del doc de diseno), eje X del 2D tambien amplitud, eje Y el factor de
    // forma, y zoom en cero (fondo de escala) en los tres.
    cfg_sel_1d <= 4'd0; cfg_sel_2dx <= 4'd0; cfg_sel_2dy <= 4'd2;
    cfg_z_1d <= 4'd0; cfg_z_2dx <= 4'd0; cfg_z_2dy <= 4'd0;
    cfg_k_1d <= 8'd0; cfg_k_2dx <= 8'd0; cfg_k_2dy <= 8'd0;
    cfg_dec <= 16'd1; cfg_keep_full <= 1'b0;
    cfg_discr_en <= 1'b0; cfg_discr_out <= 1'b0; cfg_discr_sel <= 4'd0;
    cfg_discr_min <= {AMP_W{1'b0}}; cfg_discr_max <= {AMP_W{1'b1}};
    // Una ranura (la arquitectura de una ventana), y el retardo que mide
    // sim/tb_mca_mt_latencia para el disparo por pendiente con L = 8, G = 4 y
    // pulsos de subida rapida: latencia 6..9 ciclos, menos los 2 del camino de
    // la muestra, mas 4 de base antes del pie. Con pulsos lentos hace falta
    // mas (la semi-gaussiana de la campana pide ~42): lo ajusta el software.
    cfg_n_acc <= {{(NA_W-1){1'b0}}, 1'b1}; cfg_pre_dly <= 7'd11;
    // El trapecio de un impulso (M = 0): k = 64, m = 32 y la ventana de 16
    // muestras en el centro de la meseta de un escalon que arranca 4 muestras
    // despues de la apertura. sh = 7 deja la altura de un impulso de area A en
    // 8A: los 13 bits de una amplitud positiva alineados a la izquierda de los
    // 16 del bus. Para pulsos con cola, el software calcula M, off y sh (ver
    // docs/mca/register_map_mca.md).
    //
    // Las otras formas del banco arrancan como la mitad de la anterior, con la
    // ventana en el centro de su meseta y el sh que deja la misma altura; los
    // umbrales en cero y una sola forma en uso: el MCA de un solo trapecio.
    for (kr = 0; kr < NF; kr = kr + 1) begin
      cfg_trap_k[kr]   <= 10'd64 >> kr;
      cfg_trap_m[kr]   <= 10'd32 >> kr;
      cfg_trap_lw[kr]  <= (kr < 4) ? 3'd4 - kr[2:0] : 3'd0;
      cfg_trap_sh[kr]  <= 6'd7 - kr[5:0];
      cfg_trap_off[kr] <= (kr == 0) ? 16'd72
                        : 16'd4 + (16'd64 >> kr) + ((16'd32 >> kr) - (16'd16 >> kr)) / 2;
      cfg_trap_antes[kr]   <= {LEN_W{1'b0}};
      cfg_trap_despues[kr] <= {LEN_W{1'b0}};
    end
    cfg_trap_mq <= {TMW{1'b0}}; cfg_n_formas <= 3'd1;
    clr_pulse <= 1'b0; trap_wr <= 1'b0;
  end else begin
    clr_pulse <= 1'b0;
    trap_wr   <= 1'b0;
    if (wr_stb) begin
      case (sys_addr[19:0])
        20'h0000C : begin
                      cfg_run   <= sys_wdata[0];
                      clr_pulse <= sys_wdata[1];     // autolimpiante
                      cfg_chan  <= sys_wdata[8];
                    end
        20'h0001C : cfg_baseline   <= sys_wdata[DW-1:0];
        20'h00020 : begin
                      cfg_bl_auto    <= sys_wdata[0];
                      cfg_bl_k       <= sys_wdata[7:4];
                      cfg_bl_holdoff <= sys_wdata[31:16];
                    end
        20'h00030 : cfg_amp_min    <= sys_wdata[AMP_W-1:0];
        20'h00034 : cfg_amp_max    <= sys_wdata[AMP_W-1:0];
        20'h00038 : begin
                      cfg_amp_src <= sys_wdata[0];
                      cfg_q_shift <= sys_wdata[12:8];
                      // COMPATIBILIDAD: cfg_amp_src era el selector de
                      // estimador del eje 1D. Ahora eso lo dice cfg_sel_1d, y
                      // escribir el registro viejo lo sigue moviendo, asi que
                      // toda la campana de caracterizacion existente anda sin
                      // tocarla. F_PEAK = 0, F_INT = 1.
                      cfg_sel_1d  <= sys_wdata[0] ? 4'd1 : 4'd0;
                      cfg_sel_2dx <= sys_wdata[0] ? 4'd1 : 4'd0;
                    end
        20'h0003C : cfg_h_shift    <= sys_wdata[4:0];
        20'h00040 : cfg_h2_shift   <= sys_wdata[4:0];
        20'h00044 : cfg_dec        <= sys_wdata[15:0];
        20'h000A4 : cfg_keep_full  <= sys_wdata[0];
        20'h00098 : begin
                      cfg_discr_en  <= sys_wdata[0];
                      cfg_discr_out <= sys_wdata[1];
                      cfg_discr_sel <= sys_wdata[7:4];
                    end
        20'h0009C : cfg_discr_min <= sys_wdata[AMP_W-1:0];
        20'h000A0 : cfg_discr_max <= sys_wdata[AMP_W-1:0];
        20'h0004C : begin
          cfg_gate_short <= sys_wdata[LEN_W-1:0];
          cfg_gate_long  <= sys_wdata[16+LEN_W-1:16];
        end
        // Que feature alimenta cada eje. Escribir aca GANA sobre cfg_amp_src,
        // porque es el registro nuevo y explicito.
        20'h00090 : begin
          cfg_sel_1d  <= sys_wdata[3:0];
          cfg_sel_2dx <= sys_wdata[7:4];
          cfg_sel_2dy <= sys_wdata[11:8];
        end
        // Zoom por eje: {k[15:8], z[3:0]}. z=0 = fondo de escala.
        // Las ranuras y la linea de retardo. Los offsets que dejaron libres el
        // Schmitt, la histeresis, el re-armado y el modo de publicacion (0x014,
        // 0x018, 0x028, 0x02C, 0x048, 0x104, 0x108) quedan reservados: se
        // escriben sin efecto y se leen en cero.
        20'h00120 : cfg_n_acc   <= sys_wdata[NA_W-1:0];
        20'h00124 : cfg_pre_dly <= sys_wdata[DLY_W-1:0];
        // La forma 0 del banco (el trapecio unico de antes): escribirla
        // reinicia el estado. Los mismos registros que FORMA_KM/MED de f = 0.
        20'h00128 : begin
                      cfg_trap_k[0] <= sys_wdata[TDAW-1:0];
                      cfg_trap_m[0] <= sys_wdata[16+TDAW-1:16];
                      trap_wr       <= 1'b1;
                    end
        20'h0012C : begin
                      cfg_trap_mq <= sys_wdata[TMW-1:0];
                      trap_wr     <= 1'b1;
                    end
        // La ventana sobre la meseta y la escala: no tocan el estado
        20'h00130 : begin
                      cfg_trap_off[0] <= sys_wdata[LEN_W-1:0];
                      cfg_trap_lw[0]  <= sys_wdata[18:16];
                      cfg_trap_sh[0]  <= sys_wdata[29:24];
                    end
        20'h00134 : cfg_n_formas <= sys_wdata[2:0];
        20'h00094 : begin cfg_z_1d  <= sys_wdata[3:0]; cfg_k_1d  <= sys_wdata[15:8]; end
        20'h000B8 : begin cfg_z_2dx <= sys_wdata[3:0]; cfg_k_2dx <= sys_wdata[15:8]; end
        20'h000BC : begin cfg_z_2dy <= sys_wdata[3:0]; cfg_k_2dy <= sys_wdata[15:8]; end
        default   : ;
      endcase
      // El banco: un bloque de 16 bytes por forma desde 0x180,
      //   +0 FORMA_KM   {m[25:16], k[9:0]}      escribirlo reinicia el estado
      //   +4 FORMA_MED  {sh[29:24], lw[18:16], off[15:0]}
      //   +8 FORMA_UMBR {despues[31:16], antes[15:0]}
      for (kr = 0; kr < NF; kr = kr + 1) begin
        if (sys_addr[19:0] == (20'h00180 + 16*kr)) begin
          cfg_trap_k[kr] <= sys_wdata[TDAW-1:0];
          cfg_trap_m[kr] <= sys_wdata[16+TDAW-1:16];
          trap_wr        <= 1'b1;
        end
        if (sys_addr[19:0] == (20'h00184 + 16*kr)) begin
          cfg_trap_off[kr] <= sys_wdata[LEN_W-1:0];
          cfg_trap_lw[kr]  <= sys_wdata[18:16];
          cfg_trap_sh[kr]  <= sys_wdata[29:24];
        end
        if (sys_addr[19:0] == (20'h00188 + 16*kr)) begin
          cfg_trap_antes[kr]   <= sys_wdata[LEN_W-1:0];
          cfg_trap_despues[kr] <= sys_wdata[16+LEN_W-1:16];
        end
      end
    end
  end
end

//=============================================================================
// Lectura de registros
//
// sys_rdata es un registro PLANO a propósito: el set_false_path del XDC sobre
// inst_sys_bus_cdc/reg_rdata* no engancha nada (sys_bus_cdc.sv hace un assign,
// no tiene ese registro), así que el cruce de datos de lectura se timea de
// verdad y no conviene colgarle lógica combinacional ancha.
//=============================================================================
reg [31:0] rt_hi_shadow, lt_hi_shadow, dt_hi_shadow, vt_hi_shadow;
reg [31:0] tw_hi_shadow, td_hi_shadow, tr_hi_shadow, tc_hi_shadow;
reg [31:0] to_hi_shadow [0:N_ACC];
integer    kq;

// Las dos sumas de contadores que se leen (0x064 y 0x0B0) se registran un
// ciclo antes en vez de sumarse dentro del mux de lectura: dos cadenas de
// carry de 32 b colgadas del decode de dirección eran el peor camino del
// build (addr -> LUT -> 3 CARRY4 -> LUT -> sys_rdata, −0.049 ns). Leerlas
// con un ciclo de atraso es invisible: el ack sale a los 4 ciclos y
// sys_rdata se vuelve a cargar en cada uno.
reg [31:0] sum_supp, sum_lost;
always @(posedge adc_clk_i) begin
  sum_supp <= hist_h_supp + hist_2d_supp;
  sum_lost <= c_lost + hist_h_drop + hist_2d_drop;
end

// La ocupacion se lee por un bloque alineado, 0x140-0x17F: lo de j en
// 0x140 + 8*j y hi en 0x144 + 8*j. El mux de N_ACC+1 contadores se registra un
// ciclo antes, por la misma razon que las sumas de arriba.
reg [31:0] ocup_rd;
wire [2:0] ocup_j  = sys_addr[5:3];
always @(posedge adc_clk_i)
  ocup_rd <= (ocup_j > N_ACC) ? 32'h0
           : sys_addr[2] ? to_hi_shadow[ocup_j] : t_ocup_cnt[ocup_j][31:0];

// Los registros del banco (0x180-0x1BF), con el mismo formato que la
// escritura: el mux tambien se registra un ciclo antes.
function automatic [31:0] forma_km_rd(input integer f);
  forma_km_rd = {{(16-TDAW){1'b0}}, cfg_trap_m[f], {(16-TDAW){1'b0}}, cfg_trap_k[f]};
endfunction
function automatic [31:0] forma_med_rd(input integer f);
  forma_med_rd = {trap_ok[f], 1'b0, cfg_trap_sh[f], 5'h0, cfg_trap_lw[f], cfg_trap_off[f]};
endfunction
reg [31:0] forma_rd;
wire [1:0] forma_j = sys_addr[5:4];
always @(posedge adc_clk_i)
  if (forma_j >= NF) forma_rd <= 32'h0;
  else case (sys_addr[3:2])
    2'd0    : forma_rd <= forma_km_rd(forma_j);
    2'd1    : forma_rd <= forma_med_rd(forma_j);
    2'd2    : forma_rd <= {cfg_trap_despues[forma_j], cfg_trap_antes[forma_j]};
    default : forma_rd <= 32'h0;
  endcase

always @(posedge adc_clk_i) begin
  if (!adc_rstn_i) begin
    sys_ack <= 1'b0; sys_err <= 1'b0; sys_rdata <= 32'h0;
    rt_hi_shadow <= 32'h0; lt_hi_shadow <= 32'h0; dt_hi_shadow <= 32'h0;
    vt_hi_shadow <= 32'h0;
    tw_hi_shadow <= 32'h0; td_hi_shadow <= 32'h0;
    tr_hi_shadow <= 32'h0;
    tc_hi_shadow <= 32'h0;
    for (kq = 0; kq <= N_ACC; kq = kq + 1) to_hi_shadow[kq] <= 32'h0;
  end else begin
    // Ack incondicional a los 4 ciclos, para CUALQUIER dirección.
    sys_ack <= en_sr[3];
    sys_err <= 1'b0;

    // Leer la palabra baja congela la alta (evita lecturas partidas)
    if (rd_stb) begin
      case (sys_addr[19:0])
        20'h00068 : rt_hi_shadow <= realtime_cnt[63:32];
        20'h00070 : lt_hi_shadow <= livetime_cnt[63:32];
        20'h00078 : dt_hi_shadow <= deadtime_cnt[63:32];
        20'h000C0 : vt_hi_shadow <= vetotime_cnt[63:32];
        20'h000C8 : tw_hi_shadow <= t_win_cnt[63:32];
        20'h000D0 : td_hi_shadow <= t_div_cnt[63:32];
        20'h000D8 : tr_hi_shadow <= t_rearm_cnt[63:32];
        20'h000FC : tc_hi_shadow <= t_clear_cnt[63:32];
        default   : ;
      endcase
      // t_ocup[j]: lo en 0x140 + 8*j, hi en 0x144 + 8*j
      for (kq = 0; kq <= N_ACC; kq = kq + 1)
        if (sys_addr[19:0] == (20'h00140 + 8*kq)) to_hi_shadow[kq] <= t_ocup_cnt[kq][63:32];
    end

    casez (sys_addr[19:0])
      // --- identificación ---
      20'h00000 : sys_rdata <= MAGIC;
      20'h00004 : sys_rdata <= {28'h0, 1'b0, (N_FORMAS != 0),
                                EN_HIST_H_PSD[0], EN_HIST_H[0]};
      20'h00008 : sys_rdata <= {8'h0, PSD_AW[7:0], H2_AW[7:0], H_AW[7:0]};

      // --- control y estado ---
      20'h0000C : sys_rdata <= {23'h0, cfg_chan, 6'h0, 1'b0, cfg_run};
      // busy = alguna ranura ocupada; puede_abrir = alguna libre. Con varias
      // ranuras las dos pueden valer 1 a la vez. Bit 4 rearm_pend: el disparo
      // espera re-armar (trig_arm_i = 0), el mismo nombre que tenia cuando el
      // Schmitt estaba adentro; bits 8.. la cantidad de ranuras ocupadas.
      20'h00010 : sys_rdata <= {{(24-OC_W){1'b0}}, n_ocup, 2'h0, puede_abrir, !trig_arm_i,
                                veto_i, bl_stale, feat_busy, clear_busy};

      // --- configuración ---
      20'h0001C : sys_rdata <= {{(32-DW){cfg_baseline[DW-1]}}, cfg_baseline};
      20'h00020 : sys_rdata <= {cfg_bl_holdoff, 8'h0, cfg_bl_k, 3'h0, cfg_bl_auto};
      20'h00024 : sys_rdata <= {{(32-DW){baseline_now[DW-1]}}, baseline_now};
      20'h00030 : sys_rdata <= {{(32-AMP_W){1'b0}}, cfg_amp_min};
      20'h00034 : sys_rdata <= {{(32-AMP_W){1'b0}}, cfg_amp_max};
      20'h00038 : sys_rdata <= {19'h0, cfg_q_shift, 7'h0, cfg_amp_src};
      20'h0003C : sys_rdata <= {27'h0, cfg_h_shift};
      20'h00040 : sys_rdata <= {27'h0, cfg_h2_shift};
      20'h00044 : sys_rdata <= {16'h0, cfg_dec};
      20'h00098 : sys_rdata <= {24'h0, cfg_discr_sel, 2'h0,
                                cfg_discr_out, cfg_discr_en};
      20'h0009C : sys_rdata <= {{(32-AMP_W){1'b0}}, cfg_discr_min};
      20'h000A0 : sys_rdata <= {{(32-AMP_W){1'b0}}, cfg_discr_max};
      20'h000A4 : sys_rdata <= {31'h0, cfg_keep_full};
      20'h000AC : sys_rdata <= cnt_rej_discr;
      20'h000A8 : sys_rdata <= {30'h0, hist_2d_full, hist_h_full};
      20'h000B0 : sys_rdata <= sum_supp;
      20'h0004C : sys_rdata <= {cfg_gate_long, cfg_gate_short};
      20'h00090 : sys_rdata <= {20'h0, cfg_sel_2dy, cfg_sel_2dx, cfg_sel_1d};
      20'h00094 : sys_rdata <= {16'h0, cfg_k_1d,  4'h0, cfg_z_1d };
      20'h000B8 : sys_rdata <= {16'h0, cfg_k_2dx, 4'h0, cfg_z_2dx};
      20'h000BC : sys_rdata <= {16'h0, cfg_k_2dy, 4'h0, cfg_z_2dy};

      // --- contadores de eventos ---
      20'h00050 : sys_rdata <= c_total;
      20'h00054 : sys_rdata <= c_acc;
      20'h00058 : sys_rdata <= c_rej_amp;
      20'h0005C : sys_rdata <= c_rej_psd;
      20'h00060 : sys_rdata <= c_pileup;
      20'h00064 : sys_rdata <= sum_lost;

      // --- relojes (64 b, con sombra en la palabra alta) ---
      20'h00068 : sys_rdata <= realtime_cnt[31:0];
      20'h0006C : sys_rdata <= rt_hi_shadow;
      20'h00070 : sys_rdata <= livetime_cnt[31:0];
      20'h00074 : sys_rdata <= lt_hi_shadow;
      20'h00078 : sys_rdata <= deadtime_cnt[31:0];
      20'h0007C : sys_rdata <= dt_hi_shadow;
      20'h000C0 : sys_rdata <= vetotime_cnt[31:0];
      20'h000C4 : sys_rdata <= vt_hi_shadow;

      // --- teselado del tiempo muerto (ver "Relojes de adquisición") ---
      // realtime == vetotime + t_win + t_div + t_rearm + livetime, exacto. El
      // tiempo muerto del MCA es t_win + t_div, y t_rearm el que agrega el
      // disparo; deadtime_cnt (0x078) es la OCUPACION (alguna ranura ocupada),
      // que con varias ranuras no es tiempo muerto.
      20'h000C8 : sys_rdata <= t_win_cnt[31:0];
      20'h000CC : sys_rdata <= tw_hi_shadow;
      20'h000D0 : sys_rdata <= t_div_cnt[31:0];
      20'h000D4 : sys_rdata <= td_hi_shadow;
      20'h000D8 : sys_rdata <= t_rearm_cnt[31:0];
      20'h000DC : sys_rdata <= tr_hi_shadow;
      20'h000FC : sys_rdata <= t_clear_cnt[31:0];
      20'h00100 : sys_rdata <= tc_hi_shadow;

      // --- distribución del período muerto ---
      20'h000E0 : sys_rdata <= cnt_dead_periods;
      20'h000E4 : sys_rdata <= max_dead_len;
      20'h000E8 : sys_rdata <= cnt_dead_ext;

      // --- atribución de arribos ---
      // cnt_cross == cnt_open + lost_active + cnt_lost_busy + lost_veto, en
      // todo ciclo. cnt_lost_busy va sumado en 0x064 (cnt_dropped).
      20'h000EC : sys_rdata <= c_cross;
      20'h000B4 : sys_rdata <= c_open;
      20'h000F4 : sys_rdata <= c_lost_active;
      20'h000F8 : sys_rdata <= c_lost_veto;

      // --- las ranuras ---
      // La cola de publicacion: cuantas ranuras esperan al publicador, el
      // maximo y el id de la ultima ventana publicada. occ_max == N_ACC quiere
      // decir que el publicador no dio abasto.
      20'h0010C : sys_rdata <= {last_win_id,
                                {(8-OC_W){1'b0}}, pub_occ_max,
                                {(8-OC_W){1'b0}}, pub_occ};
      20'h00110 : sys_rdata <= c_win;
      20'h00118 : sys_rdata <= c_trig;
      20'h0011C : sys_rdata <= N_ACC;
      20'h00120 : sys_rdata <= {{(32-NA_W){1'b0}}, cfg_n_acc};
      20'h00124 : sys_rdata <= {{(32-DLY_W){1'b0}}, cfg_pre_dly};
      20'h00128 : sys_rdata <= forma_km_rd(0);
      20'h0012C : sys_rdata <= {{(32-TMW){1'b0}}, cfg_trap_mq};
      // bit 31: la ventana de la meseta entra en la compuerta (solo lectura)
      20'h00130 : sys_rdata <= forma_med_rd(0);
      // el banco: bit 31 = los umbrales de despues entran en la compuerta
      20'h00134 : sys_rdata <= {umbr_ok, 20'h0, N_FORMAS[2:0], 5'h0, cfg_n_formas};
      20'b0000_0000_0001_01??_???? : sys_rdata <= ocup_rd;   // 0x140-0x17F
      20'b0000_0000_0001_10??_???? : sys_rdata <= forma_rd;  // 0x180-0x1BF

      // --- último evento (depuración) ---
      20'h00080 : sys_rdata <= {{(32-AMP_W){1'b0}}, ev_amp};
      20'h00084 : sys_rdata <= {{(32-PSD_AW){1'b0}}, ev_psd};
      20'h00088 : sys_rdata <= last_qtot;
      20'h0008C : sys_rdata <= last_qtail;

      // --- aperturas de histograma ---
      20'h1???? : sys_rdata <= hist_h_data;
      20'h2???? : sys_rdata <= hist_2d_data;

      default   : sys_rdata <= 32'h0;
    endcase
  end
end

endmodule

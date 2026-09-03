`timescale 1ns/1ps
//=============================================================================
// integration_cfg — región de TOP (integración): esclavo del bus de sistema
//
// Base 0x4060_0000 (slot 6). Dominio adc_clk; el cruce a fclk[0] lo hace
// sys_bus_cdc por slot, así que acá no hace falta CDC.
//
// QUÉ ES ESTA REGIÓN. No es housekeeping. red_pitaya_hk (slot 0) es un módulo
// de Red Pitaya —LEDs, conector de expansión, DNA del chip— y sigue donde
// estaba. Esta región describe y conecta entre sí los bloques propios del
// proyecto (OSC, MULTITRIGGER, MCA, EVENT_RING), que hasta ahora vivían
// cableados a mano en el top y sin forma de ser descubiertos desde el software.
//
// Hace tres cosas:
//
//   1. IDENTIFICA el bitstream (MAGIC, VERSION, hash de git).
//   2. DESCRIBE qué módulos trae, en qué slot vive cada uno y con qué
//      parámetros se sintetizaron. El software descubre el sistema en vez de
//      hardcodear bases y anchos.
//   3. RUTEA el datapath: elige de qué punto de la cadena DSP toma sus
//      muestras cada consumidor (ver ROUTE_* más abajo).
//
// ACK DE LATENCIA FIJA. Mismo contrato que mca_top: el ack sale de un shift
// register incondicional y responde a los 4 ciclos para CUALQUIER dirección,
// mapeada o no. Un esclavo que no hace ack no produce sólo una lectura mala:
// deja el CDC del slot desincronizado para siempre (ver
// docs/bus_sistema_redpitaya.md §7.1).
//=============================================================================

module integration_cfg #(
  // --- identificación ---
  parameter [31:0]      MAGIC     = 32'h494E5447,  // "INTG"
  parameter [31:0]      VERSION   = 32'h0001_0000, // {mayor, menor, parche, variante}
  parameter bit [0:5*32-1] GITH   = '0,            // hash de git (lo inyecta el .tcl)

  // --- presencia de módulos en ESTE bitstream ---
  parameter integer EN_OSC   = 1,
  parameter integer EN_MTRG  = 1,
  parameter integer EN_MCA   = 1,
  parameter integer EN_RING  = 0,
  parameter integer EN_ASG   = 0,
  parameter integer EN_PID   = 0,

  // --- en qué slot vive cada uno (nibble por módulo en SLOTS) ---
  parameter integer SLOT_OSC  = 1,
  parameter integer SLOT_RING = 2,
  parameter integer SLOT_MTRG = 3,
  parameter integer SLOT_TOP  = 6,
  parameter integer SLOT_MCA  = 7,

  // --- parámetros de síntesis que el software necesita conocer ---
  parameter integer N_CH    = 2,
  parameter integer DW      = 14,
  parameter integer RSZ     = 14,
  parameter integer EN_FILT = 0,
  parameter integer H_AW    = 14,
  parameter integer H2_AW   = 7,
  parameter integer PSD_AW  = 6
)(
  input                    adc_clk_i  ,
  input                    adc_rstn_i ,

  // --- ruteo del datapath: 2 b de selección + enable por consumidor ---
  output reg [2-1:0]       route_osc_tap_o  ,
  output reg               route_osc_en_o   ,
  output reg [2-1:0]       route_mtrg_tap_o ,
  output reg               route_mtrg_en_o  ,
  output reg [2-1:0]       route_mca_tap_o  ,
  output reg               route_mca_en_o   ,
  output reg [2-1:0]       route_ring_tap_o ,
  output reg               route_ring_en_o  ,

  // --- control global (abarca los módulos propios, no el hk) ---
  output reg               ctrl_run_o   ,  // nivel
  output reg               ctrl_clear_o ,  // pulso de 1 ciclo (autolimpiante)
  output reg               ctrl_srst_o  ,  // pulso de 1 ciclo (autolimpiante)

  // --- estado observable ---
  input                    pll_locked_i ,

  // --- bus de sistema ---
  input      [32-1:0]      sys_addr   ,
  input      [32-1:0]      sys_wdata  ,
  input                    sys_wen    ,
  input                    sys_ren    ,
  output reg [32-1:0]      sys_rdata  ,
  output reg               sys_err    ,
  output reg               sys_ack
);

//=============================================================================
// Codificación de los taps del datapath — LISTA CANÓNICA.
//
// Se replica como localparam en dsp_tap_mux.sv; si cambia acá, cambia allá.
// No se usa un package a propósito: el .tcl sólo hace un glob explícito de
// rtl/*_pkg.sv, y un paquete en un subdirectorio queda expuesto a problemas de
// orden de compilación en Vivado.
//
//   0  NATIVO      cada consumidor queda como estaba cableado antes del
//                  refactor. Es el valor de RESET, así que en reset el
//                  hardware es bit a bit el de antes: cualquier diferencia de
//                  comportamiento es porque el software escribió un ROUTE_*.
//                  Nativo por consumidor:
//                     OSC   -> adc_bram_in  (post-decimación + post-delay)
//                     MTRG  -> adc_dly_in   (post-decimación, PRE-delay)
//                     MCA   -> adc_dec_in   (post-calib/filtro, pre-decimación)
//                  Ojo: el nativo del MULTITRIGGER no es ninguno de los tres
//                  taps de abajo. Por eso existe el valor 0: sin él no habría
//                  forma de reproducir el comportamiento actual.
//   1  ADC         muestra cruda, ANTES de cualquier bloque del DSP
//   2  DEC_IN      post-calibración y post-ecualizador, PRE-decimación (125 MSPS)
//   3  BRAM_IN     después de todo el DSP (decimación + delay)
//=============================================================================
localparam [1:0] TAP_NATIVE  = 2'd0;
localparam [1:0] TAP_ADC     = 2'd1;
localparam [1:0] TAP_DEC_IN  = 2'd2;
localparam [1:0] TAP_BRAM_IN = 2'd3;

wire sys_en = sys_wen | sys_ren;

//=============================================================================
// Estrobo de UN ciclo. sys_bus_cdc sostiene wen/ren hasta el ack (~5 ciclos),
// así que sin esto ctrl_clear_o y ctrl_srst_o quedarían altos 5 ciclos.
//=============================================================================
reg [7:0] en_sr;
always @(posedge adc_clk_i)
  if (!adc_rstn_i) en_sr <= 8'h0;
  else             en_sr <= {en_sr[6:0], sys_en};

wire wr_stb = sys_wen && !en_sr[0];

//=============================================================================
// Palabras de sólo lectura derivadas de parámetros
//=============================================================================
wire [31:0] w_modules = {26'h0, EN_PID[0], EN_ASG[0],
                                EN_RING[0], EN_MCA[0], EN_MTRG[0], EN_OSC[0]};

wire [31:0] w_slots   = {12'h0, SLOT_MCA[3:0],  SLOT_TOP[3:0],
                                SLOT_MTRG[3:0], SLOT_RING[3:0], SLOT_OSC[3:0]};

wire [31:0] w_caps0   = {7'h0, EN_FILT[0], 2'h0, RSZ[5:0],
                               2'h0, DW[5:0], 4'h0, N_CH[3:0]};

wire [31:0] w_caps1   = {8'h0, PSD_AW[7:0], H2_AW[7:0], H_AW[7:0]};

//=============================================================================
// Escritura de registros
//=============================================================================
always @(posedge adc_clk_i) begin
  if (!adc_rstn_i) begin
    // Reset = comportamiento pre-refactor: todos los consumidores en NATIVO y
    // habilitados. Un bitstream recién cargado se comporta como el anterior.
    route_osc_tap_o  <= TAP_NATIVE;  route_osc_en_o  <= 1'b1;
    route_mtrg_tap_o <= TAP_NATIVE;  route_mtrg_en_o <= 1'b1;
    route_mca_tap_o  <= TAP_NATIVE;  route_mca_en_o  <= 1'b1;
    route_ring_tap_o <= TAP_NATIVE;  route_ring_en_o <= 1'b1;

    ctrl_run_o   <= 1'b0;
    ctrl_clear_o <= 1'b0;
    ctrl_srst_o  <= 1'b0;
  end else begin
    // Autolimpiantes: valen un solo ciclo pase lo que pase.
    ctrl_clear_o <= 1'b0;
    ctrl_srst_o  <= 1'b0;

    if (wr_stb) begin
      case (sys_addr[19:0])
        20'h00030 : begin route_osc_tap_o  <= sys_wdata[1:0]; route_osc_en_o  <= sys_wdata[8]; end
        20'h00034 : begin route_mtrg_tap_o <= sys_wdata[1:0]; route_mtrg_en_o <= sys_wdata[8]; end
        20'h00038 : begin route_mca_tap_o  <= sys_wdata[1:0]; route_mca_en_o  <= sys_wdata[8]; end
        20'h0003C : begin route_ring_tap_o <= sys_wdata[1:0]; route_ring_en_o <= sys_wdata[8]; end
        20'h00040 : begin
                      ctrl_run_o   <= sys_wdata[0];
                      ctrl_clear_o <= sys_wdata[1];
                      ctrl_srst_o  <= sys_wdata[2];
                    end
        default   : ;
      endcase
    end
  end
end

//=============================================================================
// Lectura. sys_rdata es un registro plano: el set_false_path del XDC sobre
// inst_sys_bus_cdc/reg_rdata* no engancha nada (sys_bus_cdc.sv hace un assign,
// no tiene ese registro), así que este cruce se timea de verdad.
//=============================================================================
always @(posedge adc_clk_i) begin
  if (!adc_rstn_i) begin
    sys_ack <= 1'b0; sys_err <= 1'b0; sys_rdata <= 32'h0;
  end else begin
    // Ack incondicional a los 4 ciclos, para CUALQUIER dirección.
    sys_ack <= en_sr[3];
    sys_err <= 1'b0;

    casez (sys_addr[19:0])
      // --- identificación ---
      20'h00000 : sys_rdata <= MAGIC;
      20'h00004 : sys_rdata <= VERSION;
      20'h00008 : sys_rdata <= GITH[32*0 +: 32];
      20'h0000C : sys_rdata <= GITH[32*1 +: 32];
      20'h00010 : sys_rdata <= GITH[32*2 +: 32];
      20'h00014 : sys_rdata <= GITH[32*3 +: 32];
      20'h00018 : sys_rdata <= GITH[32*4 +: 32];

      // --- descripción del sistema ---
      20'h00020 : sys_rdata <= w_modules;
      20'h00024 : sys_rdata <= w_slots;
      20'h00028 : sys_rdata <= w_caps0;
      20'h0002C : sys_rdata <= w_caps1;

      // --- ruteo del datapath ---
      20'h00030 : sys_rdata <= {23'h0, route_osc_en_o,  6'h0, route_osc_tap_o };
      20'h00034 : sys_rdata <= {23'h0, route_mtrg_en_o, 6'h0, route_mtrg_tap_o};
      20'h00038 : sys_rdata <= {23'h0, route_mca_en_o,  6'h0, route_mca_tap_o };
      20'h0003C : sys_rdata <= {23'h0, route_ring_en_o, 6'h0, route_ring_tap_o};

      // --- control y estado global ---
      20'h00040 : sys_rdata <= {31'h0, ctrl_run_o};
      20'h00044 : sys_rdata <= {30'h0, adc_rstn_i, pll_locked_i};

      default   : sys_rdata <= 32'h0;
    endcase
  end
end

endmodule

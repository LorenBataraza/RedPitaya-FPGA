`timescale 1ns/1ps
//============================================================================
// tb_mca_mt_latencia — cuanto tarda el multitrigger en avisar al MCA, y que
// retardo de muestras (cfg_pre_dly) hace falta para que la ventana abra en el
// pie del pulso
//
// mt_top y mca_top conectados como en el top (mca_red_pitaya_top.sv): la MISMA
// muestra entra a los dos y trig_i del MCA es daisy_trig_o del multitrigger
// (scope_trigo en el top). Eso supone que el tap del multitrigger y el del MCA
// son el mismo punto de la cadena DSP; si no lo son, la diferencia de latencia
// entre taps se suma a la de aca.
//
// El multitrigger queda en MODO CONTINUO, que es lo que necesita el MCA:
//   we_keep = 1          la mascara sobrevive al disparo
//   SHIELD src = dst     el holdoff del canal le limpia el disable al vencer,
//                        asi re-arma solo (dur = 0: enseguida)
//   OR_MASK = slope_p    el disparo por pendiente, que ve pulsos montados
//                        sobre la cola de otro
// y el re-armado de verdad es el Schmitt del disparo por pendiente (s baja de
// thr - hyst cuando termina la subida).
//
// Despues, lo mismo con el DISPARO CON POLO-CERO (mt_pz_trig, OR_MASK bit 25):
// k = 2, m = 1 sobre la subida rapida y k = 8, m = 8 sobre una subida lenta
// (constante de 4 muestras), las dos con el Mq de la cola (186 muestras) y el
// umbral en 50 cuentas de amplitud.
//
// Para cada configuracion del trapezoidal rapido (L, G) y dos formas de pulso
// (subida rapida y semi-gaussiana lenta) mide la latencia pie -> trig_i sobre
// un barrido de amplitud (la latencia depende de la amplitud: es el walk de un
// disparo por umbral), y despues VERIFICA con el MCA: con
//     cfg_pre_dly = latencia_max - LAT_TOP + MARGEN
// cada ventana tiene que abrir en el pie o antes.
//============================================================================
module tb_mca_mt_latencia;
  localparam integer DW = 14, N_CH = 2;
  localparam integer LAT_TOP = 2;   // registro de entrada + salida de la linea
  localparam integer MARGEN  = 4;   // muestras de base antes del pie

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  reg signed [DW-1:0] x = 0;

  // ---------------------------------------------------------------- mt_top
  reg  [31:0] m_addr = 0, m_wdata = 0;
  reg         m_wen = 0, m_ren = 0;
  wire [31:0] m_rdata;
  wire        m_err, m_ack, ev, daisy, veto, trig_arm;
  wire [3:0]  ext_asg, trig_ch_o;

  mt_top #(.N_CH(N_CH), .DW(DW)) i_mt (
    .adc_clk_i({N_CH{clk}}), .adc_rstn_i({N_CH{rstn}}),
    .mtrg_dat_i({x, x}), .mtrg_val_i({N_CH{1'b1}}),
    .set_tresh_i({4{14'd8000}}), .set_hyst_i({4{14'd50}}), .set_deb_len_i(20'd0),
    .indep_mode_i(4'h0), .legacy_trig_sw_i(4'h0), .legacy_trig_dis_clr_i(4'h0),
    .adc_rst_do_i(4'h0), .adc_dly_do_i(4'h0), .adc_we_keep_i(4'hF), .dly_valp_i(4'hF),
    .trig_ext_i(1'b0), .trig_asg_i(1'b0),
    .trig_ext_asg_o(ext_asg), .trig_ext_asg_i(ext_asg),
    .trig_ch_i(4'h0), .trig_ch_o(trig_ch_o),
    .trigger_event_o(ev), .daisy_trig_o(daisy), .mca_veto_o(veto), .trig_arm_o(trig_arm),
    .event_snap_o(), .trig_dis_clr_o(), .trg_src_o(), .new_trg_src_o(), .trg_state_o(),
    .sys_addr(m_addr), .sys_wdata(m_wdata), .sys_wen(m_wen), .sys_ren(m_ren),
    .sys_rdata(m_rdata), .sys_err(m_err), .sys_ack(m_ack)
  );

  // --------------------------------------------------------------- mca_top
  reg  [31:0] a_addr = 0, a_wdata = 0;
  reg         a_wen = 0, a_ren = 0;
  wire [31:0] a_rdata;
  wire        a_err, a_ack;

  mca_top #(.DW(DW), .H_AW(8), .H2_AW(4), .PSD_AW(4)) i_mca (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .mca_dat_i({x, x}), .mca_val_i(2'b11), .veto_i(1'b0), .trig_i(daisy), .trig_arm_i(trig_arm),
    .sys_addr(a_addr), .sys_wdata(a_wdata), .sys_wen(a_wen), .sys_ren(a_ren),
    .sys_rdata(a_rdata), .sys_err(a_err), .sys_ack(a_ack)
  );

  task automatic m_wr(input [19:0] a, input [31:0] d);
    begin
      @(negedge clk); m_addr = {12'h403, a}; m_wdata = d; m_wen = 1'b1;
      while (!m_ack) @(negedge clk);
      @(negedge clk); m_wen = 1'b0; m_addr = 0;
      while (m_ack) @(negedge clk);
      @(negedge clk);
    end
  endtask
  task automatic a_wr(input [19:0] a, input [31:0] d);
    begin
      @(negedge clk); a_addr = {12'h407, a}; a_wdata = d; a_wen = 1'b1;
      while (!a_ack) @(negedge clk);
      @(negedge clk); a_wen = 1'b0; a_addr = 0;
      while (a_ack) @(negedge clk);
      @(negedge clk);
    end
  endtask

  // ------------------------------------------------------------- medicion
  longint ciclo = 0;
  always @(posedge clk) ciclo <= ciclo + 1;

  longint t_pie, t_trig, t_abre;
  bit     visto_trig, visto_abre;
  reg     daisy_q = 0;
  always @(posedge clk) begin
    daisy_q <= daisy;
    if (daisy && !daisy_q && !visto_trig) begin visto_trig = 1; t_trig = ciclo; end
    // la decision de abrir se toma en este flanco: la muestra que mira es la
    // de hace LAT_TOP + cfg_pre_dly ciclos
    if (i_mca.i_feat.i_win.abre && !visto_abre) begin visto_abre = 1; t_abre = ciclo; end
  end

  integer pass_cnt = 0, fail_cnt = 0;
  task automatic check(input string name, input bit cond);
    if (cond) pass_cnt++; else begin fail_cnt++; $display("  FAIL: %s", name); end
  endtask

  // Un pulso: forma 0 = subida de 2 muestras y cola de 186; forma 1 =
  // semi-gaussiana (CR-RC^4) con pico a ~1 us, como el pulso de la campana;
  // forma 2 = subida exponencial de constante 4 muestras y cola de 186.
  function automatic real forma(input integer f, input integer k, input real a);
    real t;
    if (k < 0) return 0.0;
    if (f == 0) return (k == 0) ? a * 0.5 : a * $exp(-(k - 1) / 186.0);
    if (f == 2) return a * (1.0 - $exp(-(k + 1) / 4.0)) * $exp(-k / 186.0);
    t = k / 31.0;                       // tau del CR-RC^4: pico en 4*tau = 124 muestras
    return a * (t**4) * $exp(4.0 - t) / 256.0;
  endfunction

  task automatic pulso(input integer f, input real a, input integer largo);
    integer k; real s;
    begin
      visto_trig = 0; visto_abre = 0;
      for (k = 0; k < largo; k++) begin
        @(negedge clk);
        s = 20.0 + forma(f, k, a) + (int'($urandom_range(0, 6)) - 3);
        if (s > 8000.0) s = 8000.0;
        x = $rtoi(s);
        if (k == 0) t_pie = ciclo;       // la muestra del pie entra en el flanco que viene
      end
    end
  endtask

  integer cfg, f, i, lat, lat_max, lat_min, pre, adelanto, n_ev, n_sin, thr;
  integer Ls [3] = '{4, 8, 16};
  integer Gs [3] = '{2, 4, 8};
  real    a;
  // el polo-cero: forma del pulso, k, m y sh (la ganancia queda en 5.83 por
  // cuenta: 16*k*(1+M) >> sh con M = 185.5, la de la cola de 186)
  integer zf  [2] = '{0, 2};
  integer zk  [2] = '{2, 8};
  integer zm  [2] = '{1, 8};
  integer zsh [2] = '{10, 12};
  localparam integer Z_MQ = 2968;          // 16 / (e^(1/186) - 1)

  // Mide la latencia sobre el barrido de amplitud, fija cfg_pre_dly y verifica
  // que la ventana abra en el pie. nombre: para el reporte.
  task automatic medir_y_verificar(input integer f, input string nombre);
    a_wr(20'h00124, 0);
    lat_max = -1; lat_min = 1 << 30; n_sin = 0;
    for (i = 0; i < 12; i++) begin
      a = 400.0 + i * 300.0;
      pulso(f, a, 2500);
      if (visto_trig) begin
        lat = t_trig - t_pie;
        if (lat > lat_max) lat_max = lat;
        if (lat < lat_min) lat_min = lat;
      end else n_sin++;
    end
    check($sformatf("%s: disparan todos", nombre), n_sin == 0);
    pre = lat_max - LAT_TOP + MARGEN;
    if (pre < 0) pre = 0;
    if (pre > 127) pre = 127;
    a_wr(20'h00124, pre);
    n_ev = 0;
    for (i = 0; i < 12; i++) begin
      a = 400.0 + i * 300.0;
      pulso(f, a, 2500);
      if (visto_abre) begin
        adelanto = t_pie - (t_abre - LAT_TOP - pre);
        if (adelanto >= 0 && adelanto <= lat_max - lat_min + MARGEN) n_ev++;
        else $display("    A=%0.0f: la ventana abrio %0d muestras antes del pie", a, adelanto);
      end
    end
    check($sformatf("%s: la ventana abre en el pie", nombre), n_ev == 12);
    $display("  %s: latencia %0d..%0d ciclos -> cfg_pre_dly = %0d", nombre, lat_min, lat_max, pre);
  endtask

  initial begin
    process::self().srandom(5);
    repeat (10) @(negedge clk); rstn = 1; repeat (10) @(negedge clk);
    // el MCA: cuatro ranuras, compuerta larga, todo aceptado
    a_wr(20'h00120, 4);
    a_wr(20'h0004C, {16'd384, 16'd32});
    a_wr(20'h0000C, 1);
    // el multitrigger en modo continuo, re-armado por el shield
    m_wr(20'h010, 32'h0000_0101);          // shield: src = ch0, dst = ch0, dur = 0

    for (cfg = 0; cfg < 3; cfg++) begin
      for (f = 0; f < 2; f++) begin
        // Umbral. Subida rapida: la mitad de la respuesta a un escalon de 300
        // cuentas (s = L*A). Semi-gaussiana: para una rampa de m cuentas por
        // muestra s = L*(L+G)*m, y la pendiente maxima de este pulso es
        // ~0.015*A por muestra (6 cuentas para A = 400): se pone el umbral en
        // una rampa de 2 cuentas por muestra, muy arriba del ruido
        // (sigma_s = sigma*sqrt(2L) ~ 10).
        thr = (f == 0) ? Ls[cfg] * 150 : Ls[cfg] * (Ls[cfg] + Gs[cfg]) * 2;
        m_wr(20'h070, thr);
        m_wr(20'h080, thr / 2);
        m_wr(20'h060, 32'h8000_0000 | (Gs[cfg] << 8) | Ls[cfg]);
        repeat (80) @(negedge clk);
        m_wr(20'h040, 32'h0002_0000);       // OR_MASK ch0 = slope_p

        // 1) la latencia, sobre un barrido de amplitud
        a_wr(20'h00124, 0);
        lat_max = -1; lat_min = 1 << 30; n_sin = 0;
        for (i = 0; i < 12; i++) begin
          a = 400.0 + i * 300.0;
          pulso(f, a, 2500);
          if (visto_trig) begin
            lat = t_trig - t_pie;
            if (lat > lat_max) lat_max = lat;
            if (lat < lat_min) lat_min = lat;
          end else n_sin++;
        end
        check($sformatf("L=%0d G=%0d forma %0d: disparan todos", Ls[cfg], Gs[cfg], f), n_sin == 0);

        // 2) la verificacion, con el retardo que sale de la medicion
        pre = lat_max - LAT_TOP + MARGEN;
        if (pre < 0) pre = 0;
        if (pre > 127) pre = 127;
        a_wr(20'h00124, pre);
        n_ev = 0;
        for (i = 0; i < 12; i++) begin
          a = 400.0 + i * 300.0;
          pulso(f, a, 2500);
          if (visto_abre) begin
            // ciclos que la muestra de apertura esta ANTES del pie
            adelanto = t_pie - (t_abre - LAT_TOP - pre);
            if (adelanto >= 0 && adelanto <= lat_max - lat_min + MARGEN) n_ev++;
            else $display("    A=%0.0f: la ventana abrio %0d muestras antes del pie", a, adelanto);
          end
        end
        check($sformatf("L=%0d G=%0d forma %0d: la ventana abre en el pie", Ls[cfg], Gs[cfg], f), n_ev == 12);
        $display("  L=%2d G=%2d forma %0d (%s): latencia %0d..%0d ciclos -> cfg_pre_dly = %0d",
                 Ls[cfg], Gs[cfg], f, f ? "semi-gaussiana" : "subida rapida ", lat_min, lat_max, pre);
        m_wr(20'h040, 32'h0);
        m_wr(20'h060, 32'h0);
      end
    end

    // El disparo con polo-cero
    for (cfg = 0; cfg < 2; cfg++) begin
      m_wr(20'h0B0, 50 * 583 / 100);            // PZ_THR: 50 cuentas
      m_wr(20'h0C0, 25 * 583 / 100);            // PZ_HYST: 25 cuentas
      m_wr(20'h0A0, Z_MQ);
      m_wr(20'h090, 32'h8000_0000 | (zsh[cfg] << 24) | (zm[cfg] << 8) | zk[cfg]);
      repeat (80) @(negedge clk);
      m_wr(20'h040, 32'h0200_0000);             // OR_MASK ch0 = pz_p (bit 25)
      medir_y_verificar(zf[cfg], $sformatf("polo-cero k=%0d m=%0d forma %0d (%s)", zk[cfg], zm[cfg],
                        zf[cfg], zf[cfg] ? "subida lenta  " : "subida rapida "));
      m_wr(20'h040, 32'h0);
      m_wr(20'h090, 32'h0);
    end

    $display("tb_mca_mt_latencia: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt != 0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end
endmodule

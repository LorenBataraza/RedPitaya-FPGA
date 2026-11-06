`timescale 1ns/1ps
// Mediciones del event_ring: tiempos por slot, tasa maxima, ventana maxima.
// No es un TB de regresion: mide y escribe los .txt de esta carpeta, de donde salen
// figura_tiempos.py y las tablas de docs/event_ring/logica_de_captura_y_axi.md.
//
// Es el MEJOR caso del lado de DDR: AXI ideal (wrdy=1) y un ring de 32 MB que no se
// queda sin creditos en ninguna corrida. Lo que limita aca es el RTL del ring.
//
// Se corre fuera del repo, y los .txt se copian aca (R = raiz del repo):
//   vlib work
//   vlog -sv -timescale 1ns/1ps $R/rtl/classic/axi_wr_fifo.v \
//        $R/prj/MCA/modulos/event_ring/rtl/event_*.sv tb_ring_medir.sv
//   vsim -c -do "run -all; quit -f" tb_ring_medir -voptargs=+acc [-gPRE_AW=.. -gDATA_AW=..]
module tb_ring_medir #(
  parameter integer PRE_AW  = 11,
  parameter integer DATA_AW = 12,
  parameter integer PALABRA = 0    // 1 = el stream de la captura trae {ch1, ch0} por ciclo
);
  reg clk = 0; always #4 clk = ~clk;
  reg rstn = 0;
  reg [27:0] dat = 0; reg dv = 1; reg trig = 0; reg [16:0] snap = 17'h2;
  wire [31:0] waddr; wire [63:0] wdata; wire [7:0] wsel; wire [2:0] wsize; wire wvalid; wire [3:0] wlen; wire wfixed;
  reg [31:0] a = 0, wd = 0; reg wen = 0, ren = 0; wire [31:0] rd; wire err, ack;

  event_ring_top #(.PRE_AW(PRE_AW), .DATA_AW(DATA_AW)) dut (
    .adc_clk_i(clk), .adc_rstn_i(rstn), .dat_i(dat), .dv_i(dv), .trig_i(trig), .snapshot_i(snap),
    .axi_waddr_o(waddr), .axi_wdata_o(wdata), .axi_wsel_o(wsel), .axi_wsize_o(wsize),
    .axi_wvalid_o(wvalid), .axi_wlen_o(wlen), .axi_wfixed_o(wfixed), .axi_werr_i(1'b0), .axi_wrdy_i(1'b1),
    .sys_addr(a), .sys_wdata(wd), .sys_wen(wen), .sys_ren(ren), .sys_rdata(rd), .sys_err(err), .sys_ack(ack));

  // rampa: ch0 = cuenta, ch1 = ~cuenta (14 b)
  reg [13:0] n = 0;
  always @(posedge clk) begin n <= n + 1; dat <= {~n, n}; end

  integer ciclo = 0; always @(posedge clk) ciclo <= ciclo + 1;

  task w(input [31:0] ad, input [31:0] v); begin
    @(negedge clk); a = ad; wd = v; wen = 1; @(negedge clk); wen = 0; repeat (6) @(negedge clk);
  end endtask
  function automatic integer rreg(input [31:0] ad); begin
    case (ad)
      32'h20: rreg = dut.wr_slot;
      32'h30: rreg = dut.drop_busy_cnt;
      32'h34: rreg = dut.drop_full_cnt;
      32'h38: rreg = dut.ev_cnt;
      default: rreg = 0;
    endcase
  end endfunction

  task config_ring(input integer pre, input integer post, input integer shift, input integer ring); begin
    w(32'h00, 0); repeat (20) @(negedge clk);
    while (dut.gst != 0) @(negedge clk);
    w(32'h00, 2);
    w(32'h08, 32'h0A00_0000); w(32'h0C, ring); w(32'h10, shift); w(32'h14, pre); w(32'h18, post);
    w(32'h00, 1); repeat (2100) @(negedge clk);
  end endtask
  task disparo; begin
    @(negedge clk); trig = 1; @(negedge clk); trig = 0;
  end endtask

  // ---- rastreo de cambios, para la figura de tiempos -------------------------------
  integer fd = 0; reg rastrear = 0;
  reg [1:0] cst_d; reg [2:0] wst_d; reg [31:0] ws_d, db_d, df_d, ev_d; reg [2:0] ml_d;
  always @(posedge clk) begin
    cst_d <= dut.i_capture.st; wst_d <= dut.i_writer.st; ws_d <= dut.wr_slot;
    db_d <= dut.drop_busy_cnt; df_d <= dut.drop_full_cnt; ev_d <= dut.ev_cnt; ml_d <= dut.stg_ev_lvl;
    if (rastrear) begin
      if (trig && !dut.i_capture.trig_d) $fdisplay(fd, "%0d trig", ciclo);
      if (dut.i_capture.st != cst_d) $fdisplay(fd, "%0d cap %0d", ciclo, dut.i_capture.st);
      if (dut.i_writer.st != wst_d)  $fdisplay(fd, "%0d wrt %0d", ciclo, dut.i_writer.st);
      if (dut.wr_slot != ws_d)       $fdisplay(fd, "%0d wr_slot %0d", ciclo, dut.wr_slot);
      if (dut.drop_busy_cnt != db_d) $fdisplay(fd, "%0d busy %0d", ciclo, dut.drop_busy_cnt);
      if (dut.drop_full_cnt != df_d) $fdisplay(fd, "%0d full %0d", ciclo, dut.drop_full_cnt);
      if (dut.ev_cnt != ev_d)        $fdisplay(fd, "%0d ev %0d", ciclo, dut.ev_cnt);
      if (dut.stg_ev_lvl != ml_d)    $fdisplay(fd, "%0d lvl %0d", ciclo, dut.stg_ev_lvl);
    end
  end

  // ---- un evento suelto: ciclos de captura y de writer ------------------------------
  integer t_cap0 = 0, t_cap1 = 0, t_w0 = 0, t_w1 = 0;
  reg [1:0] c_d = 0; reg [2:0] w_d = 0; reg [31:0] s_d = 0;
  always @(posedge clk) begin
    c_d <= dut.i_capture.st; w_d <= dut.i_writer.st; s_d <= dut.wr_slot;
    if (c_d == 0 && dut.i_capture.st != 0) t_cap0 = ciclo;
    if (c_d != 0 && dut.i_capture.st == 0) t_cap1 = ciclo;
    if (w_d == 0 && dut.i_writer.st != 0)  t_w0   = ciclo;
    if (dut.wr_slot != s_d)                t_w1   = ciclo;
  end

  // ---- continuidad de la rampa en el stream de la captura ---------------------------
  integer rampa_mal = 0, rampa_ev = 0; integer idx = 0; reg [13:0] prev0; reg primera = 1;
  always @(posedge clk) if (dut.cap_val) begin
    if (dut.cap_sof) begin primera = 1; idx = 0; rampa_ev = rampa_ev + 1; end
    if (PALABRA || idx % 2 == 0) begin
      if (!primera && dut.cap_dat[13:0] !== (prev0 + 14'd1)) rampa_mal = rampa_mal + 1;
      prev0 = dut.cap_dat[13:0]; primera = 0;
    end
    idx = idx + 1;
  end

  // ---- medicion con tasa dada: periodico o Poisson ----------------------------------
  integer semilla = 7;
  task tren(input integer n_trig, input real tasa, input integer poisson, output integer dt_tot); 
    integer i, t0; real dt; begin
    t0 = ciclo;
    for (i = 0; i < n_trig; i = i + 1) begin
      if (poisson) dt = -$ln(1.0 - $dist_uniform(semilla, 0, 999999) / 1000000.0) * 125e6 / tasa;
      else dt = 125e6 / tasa - 2;      // `disparo` ya lleva dos ciclos
      repeat ($rtoi(dt)) @(negedge clk);
      disparo;
    end
    repeat (5000) @(negedge clk);
    dt_tot = ciclo - t0;
  end endtask

  integer dt_tot, i, k, fr; integer pres[0:5], posts[0:5], shifts[0:5];
  real tasas[0:4];
  integer per[0:8];
  initial begin
    repeat (20) @(negedge clk); rstn = 1; repeat (20) @(negedge clk);

    // ---- A) tiempos de un evento suelto ---
    fd = $fopen("eventos_suelto.txt", "w");
    config_ring(8, 24, 8, 32'h0200_0000);
    rastrear = 1; disparo; repeat (600) @(negedge clk); rastrear = 0; $fclose(fd);
    fd = $fopen("eventos_suelto_512.txt", "w");
    config_ring(8, 24, 9, 32'h0200_0000);
    rastrear = 1; disparo; repeat (600) @(negedge clk); rastrear = 0; $fclose(fd);

    // ---- B) la rafaga para la figura: 8+24, slot 512 B, un trigger cada 72 ciclos, y uno en medio ---
    fd = $fopen("eventos_rafaga.txt", "w");
    config_ring(8, 24, 9, 32'h0200_0000);
    rastrear = 1;
    repeat (20) @(negedge clk);
    disparo; repeat (38) @(negedge clk);   // cae adentro del drenaje
    disparo; repeat (38) @(negedge clk);
    for (i = 0; i < 12; i = i + 1) begin disparo; repeat (70) @(negedge clk); end
    repeat (1500) @(negedge clk);
    rastrear = 0; $fclose(fd);
    if ($test$plusargs("solo_rafaga")) begin $display("FIN"); $finish; end

    // ---- C) tasa maxima periodica ---
    fr = $fopen("periodico.txt", "w");
    per[0]=70; per[1]=80; per[2]=86; per[3]=88; per[4]=90; per[5]=100; per[6]=118; per[7]=120; per[8]=125;
    for (k = 8; k <= 9; k = k + 1) for (i = 0; i <= 8; i = i + 1) begin
      config_ring(8, 24, k, 32'h0200_0000);
      tren(3000, 125e6 / per[i], 0, dt_tot);
      $fdisplay(fr, "shift=%0d periodo=%0d ev=%0d busy=%0d full=%0d", k, per[i], dut.ev_cnt, dut.drop_busy_cnt, dut.drop_full_cnt);
    end
    $fclose(fr);

    // ---- G) cuanto tarda un evento suelto, por geometria ---
    pres[0]=8;  posts[0]=24;  shifts[0]=8;
    pres[1]=16; posts[1]=112; shifts[1]=10;
    pres[2]=16; posts[2]=240; shifts[2]=11;
    pres[3]=16; posts[3]=479; shifts[3]=12;
    pres[4]=16; posts[4]=998; shifts[4]=12;
    pres[5]=32; posts[5]=992; shifts[5]=13;
    fr = $fopen("geometrias.txt", "w");
    for (k = 0; k <= 5; k = k + 1) begin
      config_ring(pres[k], posts[k], shifts[k], 32'h0200_0000);
      disparo; repeat (16000) @(negedge clk);
      // el periodo en regimen es el tramo medido + 2: W_DONE -> W_IDLE -> W_HDR
      $fdisplay(fr, "pre=%0d post=%0d shift=%0d captura=%0d writer=%0d", pres[k], posts[k], shifts[k], t_cap1 - t_cap0, t_w1 - t_w0 + 2);
    end
    $fclose(fr);

    // ---- D) Poisson: tasa aceptada por geometria ---
    fr = $fopen("poisson.txt", "w");
    tasas[0]=10e3; tasas[1]=30e3; tasas[2]=100e3; tasas[3]=300e3; tasas[4]=1e6;
    for (k = 0; k <= 5; k = k + 1) for (i = 0; i <= 4; i = i + 1) begin
      config_ring(pres[k], posts[k], shifts[k], 32'h0200_0000);
      rampa_mal = 0; rampa_ev = 0;
      tren(2000, tasas[i], 1, dt_tot);
      $fdisplay(fr, "pre=%0d post=%0d shift=%0d tasa=%0.0f trig=2000 ev=%0d busy=%0d full=%0d wr=%0d dt=%0d rampa_mal=%0d",
                pres[k], posts[k], shifts[k], tasas[i], dut.ev_cnt, dut.drop_busy_cnt, dut.drop_full_cnt, dut.wr_slot, dt_tot, rampa_mal);
    end
    $fclose(fr);

    // ---- E) ventana maxima: continuidad de la rampa ---
    fr = $fopen("ventana_max.txt", "w");
    for (k = 0; k < 6; k = k + 1) begin
      case (k)
        0: begin pres[0]=32;  posts[0]=992;  end
        1: begin pres[0]=511; posts[0]=513;  end
        2: begin pres[0]=512; posts[0]=512;  end
        3: begin pres[0]=512; posts[0]=1023; end   // pre + ventana = 2047
        4: begin pres[0]=512; posts[0]=1024; end   // 2048: se pasa con PRE_AW=11
        5: begin pres[0]=0;   posts[0]=2047; end
      endcase
      config_ring(pres[0], posts[0], 14, 32'h0200_0000);
      rampa_mal = 0; rampa_ev = 0;
      for (i = 0; i < 5; i = i + 1) begin disparo; repeat (24000) @(negedge clk); end
      $fdisplay(fr, "pre=%0d post=%0d pre+ventana=%0d ev=%0d saltos_en_rampa=%0d", pres[0], posts[0], 2*pres[0]+posts[0], rampa_ev, rampa_mal);
    end
    $fclose(fr);
    $display("FIN"); $finish;
  end
endmodule

`timescale 1ns/1ps
//============================================================================
// tb_ring_sistema — el ring con el resto del sistema, sin el MCA.
//
// Los TB de modulos/event_ring/sim/ le dan al ring el trigger y las muestras a
// mano. Este lo cablea como en event_ring_red_pitaya_top.sv:
//
//   bus (fclk[0]) -> sys_bus_interconnect -> un sys_bus_cdc por slot (adc_clk)
//     slot 1, 3   rp_scope_mt_com: OSC y multitrigger, sacan muestra y evento
//     slot 2      event_ring_top -> axi_master -> modelo de HP2 + DDR
//     slot 6      integration_cfg
//     slot 7      vacio: es donde iria el MCA
//
// QUIEN LO MANEJA. software/API/tests/placa/hw_ring_swtrig.py, el mismo script
// que corre en la placa y sin cambios. El TB lo lanza por medio de
// correr_hw_ring_swtrig.py, que reemplaza /dev/mem por dos FIFOs con este
// protocolo de una linea por pedido, siempre con una respuesta:
//
//   W <addr> <dato>    escribe por el bus            -> "ok"
//   R <addr>           lee por el bus                -> dato
//   D <addr> <bytes>   lee la DDR sin pasar tiempo   -> palabras de 64 b
//   I <ciclos>         espera                        -> "ok"
//   Z                  contadores de este TB         -> ver mas abajo
//   Q <rc>             termina; rc es el resultado del script
//
// QUE NO MODELA. Este no es el bitstream: no hay PS ni axi4_slave (el bus lo
// maneja un BFM con su contrato), la DDR es un modelo, el reloj es ideal y no
// hay timing.
//
// Plusargs:
//   +CLIENTE=<py>  +FIFO=<prefijo>  +N=<triggers del escenario A>
//   +GAP=<ciclos>  espera de la CPU antes de cada acceso; 250 son 2 us
//   +AW_PCT=<p> +W_PCT=<p>  probabilidad de AWREADY y WREADY, para frenar al master
//   +B_LAT=<ciclos>  latencia de la respuesta de escritura
//   +TOPE=<ciclos>   lo mas que dura un time.sleep() del script
//============================================================================
module tb_ring_sistema;

  localparam real PER_PS  = 8.0;   // clk_fpga_0, del PS7
  localparam real PER_ADC = 8.0;   // adc_clk, del PLL del ADC
  localparam real SKEW    = 2.6;   // asincronicos: desfasaje fijo

  // La region reservada que discover_ddr() encuentra en la placa (labuf).
  localparam [31:0] DDR_BASE = 32'h0A00_0000;
  localparam [31:0] DDR_SIZE = 32'h0200_0000;

  localparam [31:0] ADDR_TRIG_SW = 32'h4010_0004;   // lo que dispara el script

  logic clk_ps = 1'b0, clk_adc = 1'b0;
  initial forever #(PER_PS/2.0) clk_ps = ~clk_ps;
  initial begin
    #(SKEW);
    forever #(PER_ADC/2.0) clk_adc = ~clk_adc;
  end

  logic rstn_ps = 1'b0, rstn_adc = 1'b0;
  initial begin repeat (5) @(posedge clk_ps);  rstn_ps  = 1'b1; end
  initial begin repeat (5) @(posedge clk_adc); rstn_adc = 1'b1; end

  //--------------------------------------------------------------------------
  // El bus, como en el top
  //--------------------------------------------------------------------------
  sys_bus_if ps_sys      (.clk (clk_ps ), .rstn (rstn_ps ));
  sys_bus_if sys [8-1:0] (.clk (clk_adc), .rstn (rstn_adc));

  sys_bus_interconnect #(.SN(8), .SW(20)) i_ic (
    .pll_locked_i (1'b1),
    .bus_m        (ps_sys),
    .bus_s        (sys)
  );

  sys_bus_stub i_stub0 (.bus (sys[0]));
  sys_bus_stub i_stub4 (.bus (sys[4]));
  sys_bus_stub i_stub5 (.bus (sys[5]));
  sys_bus_stub i_stub7 (.bus (sys[7]));   // el slot del MCA

  //--------------------------------------------------------------------------
  // ADC: una rampa, para poder ubicar cada muestra. ch1 es el complemento, asi
  // que un canal cruzado o una muestra corrida no pasan inadvertidos.
  //--------------------------------------------------------------------------
  reg [13:0] adc0 = 14'd0, adc1 = ~14'd0;
  always @(posedge clk_adc) begin
    adc0 <= adc0 + 14'd1;
    adc1 <= ~(adc0 + 14'd1);
  end

  //--------------------------------------------------------------------------
  // Scope + multitrigger (slots 1 y 3)
  //--------------------------------------------------------------------------
  wire [1:0]    r_osc_tap, r_mtrg_tap, r_mca_tap;
  wire          r_osc_en,  r_mtrg_en,  r_mca_en;
  wire [2*14-1:0] muestra;
  wire [2-1:0]    muestra_val;
  wire            ring_trig;
  wire [16:0]     ring_snap;

  rp_scope_mt_com #(
    .CHN(0), .N_CH(2), .DW(14), .RSZ(13), .EN_FILT(0), .EN_AXI(0)
  ) i_scope (
    .adc_clk_i({2{clk_adc}}), .adc_rstn_i({2{rstn_adc}}),
    .adc_dat_i({adc1, adc0}),
    .mca_dat_o(muestra), .mca_val_o(muestra_val),
    .event_trig_o(ring_trig), .event_snap_o(ring_snap),
    .trig_ext_i(1'b0), .trig_ch_o(), .trig_ch_i(4'h0),
    .trig_asg_i(1'b0), .trig_ext_asg_o(), .trig_ext_asg_i(4'h0),
    .daisy_trig_o(),
    .axi_clk_o(), .axi_rstn_o(), .axi_waddr_o(), .axi_wdata_o(),
    .axi_wsel_o(), .axi_wvalid_o(), .axi_wlen_o(), .axi_wfixed_o(),
    .axi_werr_i(2'h0), .axi_wrdy_i(2'h3),
    .adc_state_o(), .adc_state_i(16'h0),
    .axi_state_o(), .axi_state_i(16'h0),
    .trg_state_o(), .trg_state_i(16'h0),
    .route_osc_tap_i (r_osc_tap ), .route_osc_en_i (r_osc_en ),
    .route_mtrg_tap_i(r_mtrg_tap), .route_mtrg_en_i(r_mtrg_en),
    .route_mca_tap_i (r_mca_tap ), .route_mca_en_i (r_mca_en ),
    .sys_osc_addr (sys[1].addr), .sys_osc_wdata(sys[1].wdata), .sys_osc_wen(sys[1].wen),
    .sys_osc_ren  (sys[1].ren ), .sys_osc_rdata(sys[1].rdata), .sys_osc_err(sys[1].err),
    .sys_osc_ack  (sys[1].ack ),
    .sys_mtrg_addr(sys[3].addr), .sys_mtrg_wdata(sys[3].wdata), .sys_mtrg_wen(sys[3].wen),
    .sys_mtrg_ren (sys[3].ren ), .sys_mtrg_rdata(sys[3].rdata), .sys_mtrg_err(sys[3].err),
    .sys_mtrg_ack (sys[3].ack )
  );

  integration_cfg #(
    .MAGIC(32'h494E5447), .GITH('0),
    .EN_OSC(1), .EN_MTRG(1), .EN_MCA(0), .EN_RING(1),
    .SLOT_OSC(1), .SLOT_RING(2), .SLOT_MTRG(3), .SLOT_TOP(6), .SLOT_MCA(7),
    .N_CH(2), .DW(14), .RSZ(13), .EN_FILT(0)
  ) i_integration (
    .adc_clk_i(clk_adc), .adc_rstn_i(rstn_adc),
    .route_osc_tap_o (r_osc_tap ), .route_osc_en_o (r_osc_en ),
    .route_mtrg_tap_o(r_mtrg_tap), .route_mtrg_en_o(r_mtrg_en),
    .route_mca_tap_o (r_mca_tap ), .route_mca_en_o (r_mca_en ),
    .route_ring_tap_o(), .route_ring_en_o(),
    .ctrl_run_o(), .ctrl_clear_o(), .ctrl_srst_o(),
    .pll_locked_i(1'b1),
    .sys_addr(sys[6].addr), .sys_wdata(sys[6].wdata), .sys_wen(sys[6].wen),
    .sys_ren (sys[6].ren ), .sys_rdata(sys[6].rdata), .sys_err(sys[6].err),
    .sys_ack (sys[6].ack )
  );

  //--------------------------------------------------------------------------
  // El ring (slot 2), con los parametros del top
  //--------------------------------------------------------------------------
  wire [31:0] w_addr;
  wire [63:0] w_data;
  wire [ 7:0] w_sel;
  wire [ 2:0] w_size;
  wire        w_valid;
  wire [ 3:0] w_len;
  wire        w_fixed;
  wire        w_err, w_rdy;

  event_ring_top #(
    .DW(14), .N_CH(2), .PRE_AW(11), .S_AW(11), .DATA_AW(12), .E(4)
  ) i_event_ring (
    .adc_clk_i(clk_adc), .adc_rstn_i(rstn_adc),
    .dat_i(muestra), .dv_i(muestra_val[0]),
    .trig_i(ring_trig), .snapshot_i(ring_snap),
    .axi_waddr_o(w_addr), .axi_wdata_o(w_data), .axi_wsel_o(w_sel),
    .axi_wsize_o(w_size), .axi_wvalid_o(w_valid), .axi_wlen_o(w_len),
    .axi_wfixed_o(w_fixed), .axi_werr_i(w_err), .axi_wrdy_i(w_rdy),
    .sys_addr(sys[2].addr), .sys_wdata(sys[2].wdata), .sys_wen(sys[2].wen),
    .sys_ren (sys[2].ren ), .sys_rdata(sys[2].rdata), .sys_err(sys[2].err),
    .sys_ack (sys[2].ack )
  );

  //--------------------------------------------------------------------------
  // axi_master_2, con los parametros de red_pitaya_ps.sv
  //--------------------------------------------------------------------------
  wire [ 3:0] awid, wid;
  wire [31:0] awaddr;
  wire [ 3:0] awlen;
  wire [ 2:0] awsize;
  wire [ 1:0] awburst;
  wire        awvalid, wvalid, wlast, bready;
  wire [63:0] wdata;
  wire [ 7:0] wstrb;
  logic       awready = 1'b0, wready = 1'b0, bvalid = 1'b0;

  axi_master #(
    .DW(64), .AW(32), .ID(3), .IW(4), .LW(4)
  ) axi_master_2 (
    .axi_clk_i(clk_adc), .axi_rstn_i(rstn_adc),
    .axi_awid_o(awid), .axi_awaddr_o(awaddr), .axi_awlen_o(awlen),
    .axi_awsize_o(awsize), .axi_awburst_o(awburst), .axi_awlock_o(),
    .axi_awcache_o(), .axi_awprot_o(), .axi_awvalid_o(awvalid),
    .axi_awready_i(awready),
    .axi_wid_o(wid), .axi_wdata_o(wdata), .axi_wstrb_o(wstrb),
    .axi_wlast_o(wlast), .axi_wvalid_o(wvalid), .axi_wready_i(wready),
    .axi_bid_i(4'd3), .axi_bresp_i(2'd0), .axi_bvalid_i(bvalid),
    .axi_bready_o(bready),
    .axi_arid_o(), .axi_araddr_o(), .axi_arlen_o(), .axi_arsize_o(),
    .axi_arburst_o(), .axi_arlock_o(), .axi_arcache_o(), .axi_arprot_o(),
    .axi_arvalid_o(), .axi_arready_i(1'b0),
    .axi_rid_i(4'd0), .axi_rdata_i(64'd0), .axi_rresp_i(2'd0), .axi_rlast_i(1'b0),
    .axi_rvalid_i(1'b0), .axi_rready_o(),
    .sys_waddr_i(w_addr), .sys_wdata_i(w_data), .sys_wsel_i(w_sel),
    .sys_wsize_i(w_size), .sys_wvalid_i(w_valid), .sys_wlen_i(w_len),
    .sys_wfixed_i(w_fixed), .sys_werr_o(w_err), .sys_wrdy_o(w_rdy),
    .sys_raddr_i(32'd0), .sys_rvalid_i(1'b0), .sys_rsel_i(8'd0),
    .sys_rsize_i(3'd0), .sys_rardy_o(), .sys_rlen_i(4'd0), .sys_rfixed_i(1'b0),
    .sys_rdata_o(), .sys_rrdy_i(1'b0), .sys_rrdy_o(), .sys_rerr_o()
  );

  //--------------------------------------------------------------------------
  // Modelo de HP2 + DDR, con los chequeos que solo se pueden hacer aca: el ring
  // tiene que escribir rafagas legales y dentro de su region.
  //--------------------------------------------------------------------------
  typedef struct packed { logic [31:0] addr; logic [3:0] len; } aw_t;
  typedef struct packed { logic [63:0] data; logic [7:0] strb; logic last; } w_t;

  aw_t cola_aw[$];
  w_t  cola_w[$];
  int  cola_b[$];
  logic [63:0] ddr [int unsigned];   // por palabra de 64 b

  int aw_pct = 100, w_pct = 100, b_lat = 0;
  int beat = 0, rafagas = 0, beats = 0, axi_errores = 0;

  function automatic void axi_error(input string msg);
    axi_errores++;
    if (axi_errores <= 10) $display("  FAIL AXI: %s", msg);
  endfunction

  always @(posedge clk_adc) begin : hp2
    aw_t a; w_t w; logic [63:0] viejo; int unsigned k;
    if (!rstn_adc) begin
      awready <= 1'b0; wready <= 1'b0; bvalid <= 1'b0;
    end else begin
      awready <= ($urandom_range(99) < aw_pct);
      wready  <= ($urandom_range(99) < w_pct);

      if (awvalid && awready) begin
        if (awaddr[2:0] != 3'd0)  axi_error($sformatf("direccion no alineada %h", awaddr));
        if (awsize  != 3'd3)      axi_error($sformatf("AWSIZE %0d", awsize));
        if (awburst != 2'b01)     axi_error($sformatf("AWBURST %b", awburst));
        if (awid    != 4'd3)      axi_error($sformatf("AWID %0d", awid));
        if (awaddr < DDR_BASE || awaddr + (awlen + 1) * 8 > DDR_BASE + DDR_SIZE)
          axi_error($sformatf("fuera de la region: %h, len %0d", awaddr, awlen));
        if (awaddr[11:0] + (awlen + 1) * 8 > 4096)
          axi_error($sformatf("cruza un limite de 4 KB: %h, len %0d", awaddr, awlen));
        cola_aw.push_back('{awaddr, awlen});
      end
      if (wvalid && wready) begin
        if (wid != 4'd3) axi_error($sformatf("WID %0d", wid));
        cola_w.push_back('{wdata, wstrb, wlast});
      end

      // AXI deja que el dato llegue antes que la direccion: se aparean aca.
      while (cola_aw.size() > 0 && cola_w.size() > 0) begin
        a = cola_aw[0];
        w = cola_w.pop_front();
        k = (a.addr >> 3) + beat;
        viejo = ddr.exists(k) ? ddr[k] : 64'hA5A5_A5A5_A5A5_A5A5;
        for (int b = 0; b < 8; b++)
          if (w.strb[b]) viejo[b*8 +: 8] = w.data[b*8 +: 8];
        ddr[k] = viejo;
        beats++;
        if (w.last != (beat == a.len))
          axi_error($sformatf("WLAST en el beat %0d de %0d, direccion %h", beat, a.len, a.addr));
        if (beat == a.len) begin
          void'(cola_aw.pop_front());
          cola_b.push_back(b_lat);
          beat = 0;
          rafagas++;
        end else begin
          beat++;
        end
      end

      // Respuesta de escritura. El master tiene BREADY siempre arriba.
      foreach (cola_b[i]) if (cola_b[i] > 0) cola_b[i]--;
      if (cola_b.size() > 0 && cola_b[0] == 0) begin
        bvalid <= 1'b1;
        void'(cola_b.pop_front());
      end else begin
        bvalid <= 1'b0;
      end
    end
  end

  //--------------------------------------------------------------------------
  // Lo que el TB cuenta por su cuenta, sin creerle al ring
  //--------------------------------------------------------------------------
  reg trig_d = 1'b0;
  int trig_flancos = 0, trig_ciclos = 0, ciclos = 0;
  always @(posedge clk_adc) begin
    ciclos++;
    trig_d <= ring_trig;
    if (ring_trig)            trig_ciclos++;
    if (ring_trig && !trig_d) trig_flancos++;
  end

  //--------------------------------------------------------------------------
  // BFM del bus: el contrato de axi4_slave (ver tb_sys_bus_proto)
  //--------------------------------------------------------------------------
  localparam integer ACK_LIMIT = 32;   // el timeout de axi4_slave.sv:193
  int ack_timeouts = 0, escrituras_sw = 0, gap = 250;

  task automatic bus_access(input bit is_write, input [31:0] a, input [31:0] d,
                            output [31:0] rd);
    integer n;
    begin
      repeat (gap) @(posedge clk_ps);
      @(posedge clk_ps);
      ps_sys.addr  <= a;
      ps_sys.wdata <= d;
      ps_sys.wen   <= is_write;
      ps_sys.ren   <= !is_write;
      n = 0;
      @(negedge clk_ps);
      while (!ps_sys.ack && n < ACK_LIMIT) begin
        @(negedge clk_ps);
        n = n + 1;
      end
      rd = ps_sys.rdata;
      if (!ps_sys.ack) begin
        ack_timeouts++;
        $display("  FAIL: sin ack en %s a %08h",
                 is_write ? "escritura" : "lectura", a);
      end
      @(posedge clk_ps);
      ps_sys.wen <= 1'b0;
      ps_sys.ren <= 1'b0;
      repeat (4) @(posedge clk_ps);
    end
  endtask

  //--------------------------------------------------------------------------
  // Servidor: atiende al script hasta que termina
  //--------------------------------------------------------------------------
  initial begin : servidor
    string cliente, fifo, linea, lanzar;
    int cmd_fd, rsp_fd, n_trig, tope, rc, n, nbytes;
    byte op;
    logic [31:0] a, d, rd;
    int unsigned k;

    n_trig = 200; tope = 20000; rc = -1;
    ps_sys.addr = '0; ps_sys.wdata = '0; ps_sys.wen = 1'b0; ps_sys.ren = 1'b0;

    if (!$value$plusargs("CLIENTE=%s", cliente) || !$value$plusargs("FIFO=%s", fifo)) begin
      $display("faltan +CLIENTE y +FIFO");
      $display("RESULT: FAIL");
      $finish;
    end
    void'($value$plusargs("N=%d", n_trig));
    void'($value$plusargs("GAP=%d", gap));
    void'($value$plusargs("AW_PCT=%d", aw_pct));
    void'($value$plusargs("W_PCT=%d", w_pct));
    void'($value$plusargs("B_LAT=%d", b_lat));
    void'($value$plusargs("TOPE=%d", tope));

    repeat (20) @(posedge clk_ps);

    // El orden de los $fopen es el mismo que del otro lado: si no, los dos se
    // quedan esperando. Si el script ni arranca, la segunda mitad del comando
    // abre los FIFOs y cierra, asi el TB ve el fin de archivo y falla en vez de
    // colgarse.
    $system($sformatf("rm -f %s.cmd %s.rsp; mkfifo %s.cmd %s.rsp", fifo, fifo, fifo, fifo));
    lanzar = $sformatf("( python3 -u %s %s.cmd %s.rsp %0d %0d || timeout 5 sh -c ': > %s.cmd; : < %s.rsp' ) &",
                       cliente, fifo, fifo, n_trig, tope, fifo, fifo);
    $system(lanzar);
    cmd_fd = $fopen({fifo, ".cmd"}, "r");
    rsp_fd = $fopen({fifo, ".rsp"}, "w");

    forever begin
      if ($fgets(linea, cmd_fd) == 0) begin
        $display("  FAIL: el script se fue sin dar un resultado");
        break;
      end
      op = linea[0];
      case (op)
        "W": begin
          n = $sscanf(linea.substr(2, linea.len() - 1), "%h %h", a, d);
          if (a == ADDR_TRIG_SW && d == 32'h1) escrituras_sw++;
          bus_access(1'b1, a, d, rd);
          $fdisplay(rsp_fd, "ok");
        end
        "R": begin
          n = $sscanf(linea.substr(2, linea.len() - 1), "%h", a);
          bus_access(1'b0, a, 32'h0, rd);
          $fdisplay(rsp_fd, "%08h", rd);
        end
        "D": begin
          n = $sscanf(linea.substr(2, linea.len() - 1), "%h %d", a, nbytes);
          for (int i = 0; i < nbytes / 8; i++) begin
            k = (a >> 3) + i;
            $fwrite(rsp_fd, "%016h", ddr.exists(k) ? ddr[k] : 64'hA5A5_A5A5_A5A5_A5A5);
          end
          $fdisplay(rsp_fd, "");
        end
        "I": begin
          n = $sscanf(linea.substr(2, linea.len() - 1), "%d", nbytes);
          repeat (nbytes) @(posedge clk_adc);
          $fdisplay(rsp_fd, "ok");
        end
        "Z": $fdisplay(rsp_fd, "%0d %0d %0d %0d %0d %0d %0d %0d",
                       escrituras_sw, trig_flancos, trig_ciclos, ack_timeouts,
                       axi_errores, rafagas, beats, ciclos);
        "Q": begin
          n = $sscanf(linea.substr(2, linea.len() - 1), "%d", rc);
          $fdisplay(rsp_fd, "ok");
          $fflush(rsp_fd);
          break;
        end
        default: begin
          $display("  FAIL: pedido desconocido: %s", linea);
          $fdisplay(rsp_fd, "error");
        end
      endcase
      $fflush(rsp_fd);
    end

    $display("tb_ring_sistema: %0d ciclos, %0d rafagas AXI, %0d beats",
             ciclos, rafagas, beats);
    if (rc == 0 && ack_timeouts == 0 && axi_errores == 0)
      $display("RESULT: PASS");
    else
      $display("RESULT: FAIL  (script rc=%0d, sin ack=%0d, errores AXI=%0d)",
               rc, ack_timeouts, axi_errores);
    $finish;
  end

endmodule

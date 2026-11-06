`timescale 1ns/1ps
//============================================================================
// tb_mt_pz_trig — el disparo con polo-cero: trapecio bit a bit, Schmitt,
// arranque, re-arranque y resolucion de pares
//
// Lo que verifica, contra modelos escritos aca (no copiados del RTL):
//
//   1. EL TRAPECIO BIT A BIT. Un modelo entero de Jordanov-Knoll con historia
//      cero desde cada re-arranque (la convencion de mca_trap) predice la
//      salida interna `y` en cada ciclo, con huecos de val y con cambios de
//      configuracion a mitad de la corrida. k y k + m se saturan como dice el
//      RTL: k >= 1, k + m <= 31.
//   2. EL SCHMITT. Un Schmitt de referencia sobre la salida predice pz_p_o en
//      cada ciclo, desde que el modulo termina el arranque: dispara con
//      y >= thr, re-arma con y < thr - hyst, un pulso de un ciclo.
//   3. EL ARRANQUE. Desde el re-arranque tienen que pasar entre k + l + LAT y
//      k + l + LAT + 4 muestras antes de evaluar (es lo que tapa el escalon de
//      la continua), y con continuas de -1000 a +1800 no sale ningun pulso
//      falso; despues un pulso de 300 dispara una sola vez.
//   4. LA DETECCION, con la medida de verdad: pulsos de Poisson con cola de 250
//      sobre una base de 5 cuentas y ruido de 4.5 (como la placa). Cada pulso
//      aislado de A >= 100 da exactamente un disparo, entre 8 y 14 muestras
//      despues del pie.
//   5. PARES, con la subida de la cadena (10-90 % en 1.2 muestras): 2000 y 1200
//      separados Dt dan dos disparos desde Dt = 7 y uno hasta Dt = 6, y uno de
//      300 sobre la cola de uno de 8000 tambien dispara desde Dt = 7: la cola
//      no tapa nada. Con una subida mas lenta el limite se corre (con 10-90 %
//      en 2.6 muestras, 8000 -> 300 separa recien desde 12): lo que queda de la
//      subida del grande tarda en bajar del re-armado.
//============================================================================
module tb_mt_pz_trig;
  localparam integer DW = 14, LAT = 8, TAU = 250;
  // subida 1 - e^(-t/TR): 10-90 % en 1.2 muestras, la de la cadena de la placa
  localparam real TR = 1.2 / 2.197;

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  reg signed [DW-1:0] x = 0;
  reg                 dv = 1;
  reg                 en = 0;
  reg  [4:0]          k = 2, m = 1;
  reg  [19:0]         mq = 3992;
  reg  [5:0]          sh = 10;
  reg  [17:0]         thr = 353, hyst = 177;
  wire                pz_p;

  mt_pz_trig #(.DW(DW)) dut (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .adc_dat_i(x), .adc_dv_i(dv),
    .cfg_en_i(en), .cfg_k_i(k), .cfg_m_i(m), .cfg_mq_i(mq), .cfg_sh_i(sh),
    .cfg_thr_i(thr), .cfg_hyst_i(hyst),
    .pz_p_o(pz_p)
  );

  integer pass_cnt = 0, fail_cnt = 0, err_y = 0, err_p = 0, comp_y = 0, comp_p = 0;
  task automatic check(input string name, input bit cond);
    if (cond) begin pass_cnt++; $display("  PASS: %s", name); end
    else begin fail_cnt++; $display("  FAIL: %s", name); end
  endtask

  //--------------------------------------------------------------------------
  // Modelo del trapecio: historia cero desde el re-arranque
  //--------------------------------------------------------------------------
  int      hist[$];                  // muestras desde el re-arranque
  longint  p_m, s_m;
  int      outs[$];                  // salida por muestra
  int      y_exp;
  int      kk_m, ll_m;               // k y l efectivos del modelo

  function automatic int v_at(int j);   // v[n - j] con n = la ultima
    int idx = hist.size() - 1 - j;
    return (idx < 0) ? 0 : hist[idx];
  endfunction

  function automatic int sat18(longint q);
    if (q > 131071) return 131071;
    if (q < -131072) return -131072;
    return int'(q);
  endfunction

  task automatic modelo_reset();
    hist.delete(); outs.delete(); p_m = 0; s_m = 0;
  endtask

  task automatic modelo_paso(input int xv);
    longint d;
    hist.push_back(xv);
    d = v_at(0) - v_at(kk_m) - v_at(ll_m) + v_at(kk_m + ll_m);
    p_m += d;
    s_m += 16 * p_m + longint'(mq) * d;
    outs.push_back(sat18(s_m >>> sh));
  endtask

  // la salida que tiene que haber con N muestras procesadas
  function automatic int y_modelo();
    int n = outs.size();
    return (n < LAT) ? 0 : outs[n - LAT];
  endfunction

  //--------------------------------------------------------------------------
  // Schmitt de referencia, desde que termina el arranque
  //--------------------------------------------------------------------------
  reg  ref_st = 1, ref_st_q = 1, ref_p = 0;
  reg  [17:0] thr_d = 0, hyst_d = 0;
  int  n_desde_rearr;                // muestras validas desde el re-arranque
  int  lleno_en_muestras;            // a cuantas termino el arranque
  bit  midiendo = 0;                 // comparar y y pz_p
  int  arranques_mal = 0, arranques = 0;
  bit  lleno_ant = 0;

  // Todo se toma ANTES del flanco: x, dv y la config cambian en negedge.
  always @(posedge clk) begin
    int ykk, yref;
    bit st_n, st_q_n, p_n;
    // el modelo del trapecio
    kk_m = (k == 0) ? 1 : k;
    ll_m = (kk_m + m > 31) ? 31 : kk_m + m;
    if (dut.restart) begin
      modelo_reset();
      n_desde_rearr = 0;
    end else if (dv) begin
      modelo_paso(x);
      n_desde_rearr++;
    end
    // el arranque: cuando sube lleno
    if (dut.lleno && !lleno_ant) begin
      arranques++;
      lleno_en_muestras = n_desde_rearr;
      if (n_desde_rearr < kk_m + ll_m + LAT || n_desde_rearr > kk_m + ll_m + LAT + 4) begin
        arranques_mal++;
        $display("  FAIL arranque: lleno a las %0d muestras (k=%0d l=%0d)", n_desde_rearr, kk_m, ll_m);
      end
    end
    lleno_ant = dut.lleno;
    // el Schmitt de referencia (con la config registrada un ciclo, como el RTL)
    yref = dut.y;
    st_n = ref_st; st_q_n = ref_st_q;
    if (!rstn) begin st_n = 1; st_q_n = 1; end
    else if (!dut.lleno) begin st_n = 1; st_q_n = 1; end
    else begin
      if (yref >= $signed({1'b0, thr_d})) st_n = 1;
      else if (yref < $signed({1'b0, thr_d}) - $signed({1'b0, hyst_d})) st_n = 0;
      st_q_n = ref_st;
    end
    p_n = rstn && ref_st && !ref_st_q;
    ref_st <= st_n; ref_st_q <= st_q_n; ref_p <= p_n;
    thr_d <= thr; hyst_d <= hyst;
  end

  // la comparacion, despues del flanco
  always @(negedge clk) if (rstn && midiendo) begin
    comp_y++;
    if (!dut.restart && dut.y !== y_modelo()) begin
      err_y++;
      if (err_y <= 10) $display("  FAIL y: DUT=%0d modelo=%0d (muestra %0d)", dut.y, y_modelo(), outs.size());
    end
    comp_p++;
    if (pz_p !== ref_p) begin
      err_p++;
      if (err_p <= 10) $display("  FAIL pz_p: DUT=%b ref=%b @%0t", pz_p, ref_p, $time);
    end
  end

  // los disparos, con el indice de muestra
  longint ciclo = 0;
  always @(posedge clk) ciclo <= ciclo + 1;
  int disparos[$];
  always @(posedge clk) if (pz_p) disparos.push_back(int'(ciclo));

  //--------------------------------------------------------------------------
  // Estimulo: una traza precalculada, una muestra por ciclo con dv
  //--------------------------------------------------------------------------
  real traza[];
  int  pies[$]; real amps[$];

  task automatic agregar_pulso(input int t0, input real a, input real tr);
    for (int t = t0; t < traza.size() && t < t0 + 8 * TAU; t++) begin
      real u = t - t0;
      traza[t] += a * (1.0 - $exp(-(u + 1.0) / tr)) * $exp(-u / TAU);
    end
  endtask

  function automatic real gauss(real sigma);
    real u1 = ($urandom_range(1, 1000000)) / 1000000.0;
    real u2 = ($urandom_range(0, 1000000)) / 1000000.0;
    return sigma * $sqrt(-2.0 * $ln(u1)) * $cos(6.283185307 * u2);
  endfunction

  function automatic logic signed [DW-1:0] a_muestra(real v);
    int q = $rtoi(v >= 0 ? v + 0.5 : v - 0.5);
    if (q > 8191) q = 8191;
    if (q < -8192) q = -8192;
    return q[DW-1:0];
  endfunction

  // Pasa la traza; con dec > 1, dv vale uno de cada dec ciclos. Devuelve el
  // ciclo en que entro la muestra 0.
  task automatic reproducir(input int dec, output longint c0);
    c0 = -1;
    for (int i = 0; i < traza.size(); i++) begin
      for (int j = 0; j < dec; j++) begin
        @(negedge clk);
        if (j == dec - 1) begin
          dv = 1; x = a_muestra(traza[i]);
          if (c0 < 0) c0 = ciclo;
        end else begin
          dv = 0; x = $urandom_range(0, 16383);
        end
      end
    end
    @(negedge clk); dv = 1;
  endtask

  task automatic base(input real nivel, input int n, input real ruido);
    traza = new[n];
    foreach (traza[i]) traza[i] = nivel + ((ruido > 0) ? gauss(ruido) : 0.0);
  endtask

  // Re-arranca el modulo con la base `nivel` en la entrada.
  task automatic rearrancar(input real nivel);
    @(negedge clk); en = 0; x = a_muestra(nivel);
    repeat (6) @(negedge clk);
    en = 1;
    repeat (4) @(negedge clk);
  endtask

  int n_ok, n_mal, n_rep;
  longint c0;
  int dt_vals[] = '{1, 2, 3, 6, 7, 8, 9, 10, 12, 16};
  real niveles[] = '{-1000.0, 5.0, 1000.0, 1800.0};

  // El cuerpo va en una tarea automatica: las variables locales de cada bloque
  // (dt, a, prev...) se inicializan con expresiones no constantes.
  task automatic correr();
    process::self().srandom(7);
    repeat (4) @(posedge clk);
    #1 rstn = 1;
    midiendo = 1;

    //------------------------------------------------------------------------
    // 3. Arranque con continua: sin falsos, y despues un pulso dispara una vez
    //------------------------------------------------------------------------
    $display("-- arranque con continua --");
    foreach (niveles[i]) begin
      real nivel;
      nivel = niveles[i];
      x = a_muestra(nivel);
      rearrancar(nivel);
      base(nivel, 3000, 4.5);
      agregar_pulso(2000, 300.0, TR);
      disparos.delete();
      reproducir(1, c0);
      check($sformatf("continua %0.0f: el arranque no dispara y el pulso de 300 dispara una vez (%0d disparos)",
                      nivel, disparos.size()),
            disparos.size() == 1 && disparos[0] - c0 >= 2000 && disparos[0] - c0 <= 2014);
    end

    //------------------------------------------------------------------------
    // 4. Deteccion sobre un tren de Poisson como el de la placa
    //------------------------------------------------------------------------
    $display("-- tren de Poisson (base 5, ruido 4.5, cola 250) --");
    rearrancar(5.0);
    base(5.0, 200000, 4.5);
    pies.delete(); amps.delete();
    begin
      int t = 500;
      while (t < 199000) begin
        real a = 100.0 * $pow(80.0, $urandom_range(0, 1000000) / 1000000.0);
        pies.push_back(t); amps.push_back(a);
        agregar_pulso(t, a, TR);
        t += 30 + $urandom_range(0, 600);
      end
    end
    disparos.delete();
    reproducir(1, c0);
    n_ok = 0; n_mal = 0;
    foreach (pies[i]) begin
      int prev = (i > 0) ? pies[i] - pies[i-1] : 1000;
      int sig  = (i < pies.size() - 1) ? pies[i+1] - pies[i] : 1000;
      if (prev >= 50 && sig >= 50) begin
        int n = 0;
        foreach (disparos[j]) if (disparos[j] - c0 >= pies[i] + 8 && disparos[j] - c0 <= pies[i] + 14) n++;
        if (n == 1) n_ok++; else begin
          n_mal++;
          if (n_mal <= 5) $display("  pie %0d A=%0.0f: %0d disparos", pies[i], amps[i], n);
        end
      end
    end
    check($sformatf("cada pulso aislado de A >= 100 da un disparo (%0d de %0d)", n_ok, n_ok + n_mal),
          n_mal == 0 && n_ok > 100);
    begin
      int falsos = 0;
      foreach (disparos[j]) begin
        bit cerca = 0;
        foreach (pies[i]) if (disparos[j] - c0 >= pies[i] && disparos[j] - c0 <= pies[i] + 14) cerca = 1;
        if (!cerca) falsos++;
      end
      check($sformatf("ningun disparo lejos de un pie (%0d falsos)", falsos), falsos == 0);
    end

    //------------------------------------------------------------------------
    // 1 + 2 con decimacion: dv uno de cada 4 ciclos
    //------------------------------------------------------------------------
    $display("-- con decimacion (dv 1 de cada 4) --");
    rearrancar(5.0);
    base(5.0, 6000, 4.5);
    for (int t = 300; t < 5800; t += 400) agregar_pulso(t, 500.0 + 20.0 * (t % 7), TR);
    disparos.delete();
    reproducir(4, c0);
    check($sformatf("decimado: un disparo por pulso (%0d de 14)", disparos.size()), disparos.size() == 14);

    //------------------------------------------------------------------------
    // Re-arranque por cambio de configuracion a mitad de la corrida
    //------------------------------------------------------------------------
    $display("-- cambio de forma a mitad de la corrida --");
    base(5.0, 4000, 4.5);
    for (int t = 200; t < 3900; t += 300) agregar_pulso(t, 800.0, TR);
    fork
      reproducir(1, c0);
      begin
        repeat (1000) @(negedge clk); k = 3; m = 2;
        repeat (1000) @(negedge clk); k = 0; m = 0;     // k = 0 se toma como 1
        repeat (1000) @(negedge clk); k = 31; m = 31;   // k + m satura en 31
        repeat (500)  @(negedge clk); k = 2; m = 1;
      end
    join
    check($sformatf("re-arranques medidos con el largo correcto (%0d)", arranques), arranques_mal == 0);

    //------------------------------------------------------------------------
    // 5. Pares
    //------------------------------------------------------------------------
    $display("-- pares --");
    rearrancar(5.0);
    foreach (dt_vals[q]) begin
      int dt = dt_vals[q];
      base(5.0, 400, 0.0);
      agregar_pulso(100, 2000.0, TR);
      agregar_pulso(100 + dt, 1200.0, TR);
      disparos.delete();
      reproducir(1, c0);
      $display("  2000 -> 1200 a Dt = %0d: %0d disparos", dt, disparos.size());
      if (dt >= 7) check($sformatf("2000 -> 1200 a Dt = %0d: dos disparos", dt), disparos.size() == 2);
      else         check($sformatf("2000 -> 1200 a Dt = %0d: uno", dt), disparos.size() == 1);
    end
    foreach (dt_vals[q]) if (dt_vals[q] >= 6) begin
      int dt = dt_vals[q];
      base(5.0, 400, 0.0);
      agregar_pulso(100, 8000.0, TR);
      agregar_pulso(100 + dt, 300.0, TR);
      disparos.delete();
      reproducir(1, c0);
      $display("  8000 -> 300 a Dt = %0d: %0d disparos", dt, disparos.size());
      if (dt >= 7) check($sformatf("8000 -> 300 a Dt = %0d: dos disparos", dt), disparos.size() == 2);
      else         check($sformatf("8000 -> 300 a Dt = %0d: uno", dt), disparos.size() == 1);
    end

    //------------------------------------------------------------------------
    // en = 0: ni un pulso
    //------------------------------------------------------------------------
    @(negedge clk); en = 0;
    base(5.0, 2000, 4.5);
    for (int t = 100; t < 1900; t += 200) agregar_pulso(t, 3000.0, TR);
    disparos.delete();
    reproducir(1, c0);
    check("en = 0: ningun disparo", disparos.size() == 0);

    midiendo = 0;
    check($sformatf("trapecio bit a bit (%0d comparaciones, %0d errores)", comp_y, err_y), err_y == 0);
    check($sformatf("Schmitt contra la referencia (%0d ciclos, %0d errores)", comp_p, err_p), err_p == 0);

    $display("---------------------------------------------");
    $display("tb_mt_pz_trig: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt != 0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  endtask

  initial correr();

  initial begin #20ms; $display("TIMEOUT"); $display("RESULT: FAIL"); $finish; end

endmodule

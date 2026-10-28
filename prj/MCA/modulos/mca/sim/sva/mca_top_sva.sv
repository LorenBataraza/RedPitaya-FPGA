// Assertions de mca_top, enganchadas por `bind` desde sim/sva/bind_mca.sv.
//
// Van aparte del RTL a proposito: el RTL sintetizable no se toca, no hace falta
// un `ifndef SYNTHESIS`, y estas propiedades nunca entran a files.f, asi que
// Vivado ni las ve. Se compilan solo en el flujo de simulacion.
//
// El modulo replica los puertos del DUT que quiere observar; el bind con `.*`
// los conecta por nombre. `.*` alcanza tambien las senales INTERNAS de mca_top,
// que es lo que permite verificar el teselado de los relojes sin exponerlo al
// bus.
//
// QUE SE PRUEBA ACA, Y POR QUE IMPORTA
//
// El seguimiento del tiempo muerto es "exhaustivo" en un sentido preciso y
// verificable: cada ciclo de adc_clk se atribuye a exactamente un casillero de
// tiempo, y cada cruce de thr_hi a exactamente un casillero de eventos. Las dos
// cosas son INVARIANTES, no mediciones que haya que creer, y estan abajo como
// ap_suma_relojes y ap_atribucion_arribos.
//
// Es la diferencia entre agregar contadores y poder afirmar que no falta
// ninguno. El bug que motivo todo esto —deadtime_cnt contaba `feat_busy`, que
// no es la condicion de bloqueo— habria sido imposible con ap_suma_relojes
// puesta: el tiempo de re-armado no cerraba la cuenta.

module mca_top_sva (
    input logic adc_clk_i,
    input logic adc_rstn_i,

    // --- control y veto ---
    input logic        cfg_run,
    input logic        veto_i,
    input logic        clr_pulse,

    // --- casilleros de tiempo muerto, del extractor ---
    input logic        dt_win,
    input logic        dt_div,
    input logic        dt_rearm,
    input logic        puede_abrir,
    input logic        arribo,
    input logic        feat_busy,

    // --- relojes ---
    input logic [63:0] realtime_cnt,
    input logic [63:0] livetime_cnt,
    input logic [63:0] deadtime_cnt,
    input logic [63:0] vetotime_cnt,
    input logic [63:0] t_win_cnt,
    input logic [63:0] t_div_cnt,
    input logic [63:0] t_rearm_cnt,

    // --- distribucion del periodo muerto ---
    input logic        bloqueado,
    input logic [31:0] dead_len,
    input logic [31:0] max_dead_len,
    input logic [31:0] cnt_dead_periods,
    input logic [31:0] cnt_dead_ext,

    // --- atribucion de arribos ---
    input logic [31:0] c_cross,
    input logic [31:0] c_open,
    input logic [31:0] c_lost_rearm,
    input logic [31:0] c_lost_active,
    input logic [31:0] c_lost,          // cnt_lost_busy: sin donde publicar
    input logic [31:0] c_lost_veto,
    input logic [31:0] c_total,

    // --- FASE 2: politicas de ventana y arbitro de publicacion ---
    input logic [1:0]  cfg_trig_src,
    input logic        cfg_rearm_mode,
    input logic        cfg_pub_mode,
    input logic [31:0] c_lost_notrig,
    input logic [31:0] c_win,
    input logic [31:0] c_trig
);

  default clocking cb @(posedge adc_clk_i); endclocking
  default disable iff (!adc_rstn_i);

  //---------------------------------------------------------------------------
  // 0. Modo mixto: la precondicion de las identidades de compatibilidad
  //---------------------------------------------------------------------------
  // Los relojes son ACUMULATIVOS y cfg_pub_mode cambia que casillero recibe la
  // contrapresion. Si el modo cambia a mitad de una cuenta, la cuenta mezcla dos
  // definiciones y NINGUNA identidad con deadtime_cnt vale -- sin que haya
  // ningun bug. Hay que decirlo explicitamente en vez de escribir una propiedad
  // que falla por una razon que no es un error: una assertion que grita en un
  // caso legitimo se termina desactivando, y entonces ya no protege nada.
  //
  // El flag se limpia con clr_pulse, que es lo que el software hace igual antes
  // de cada corrida.
  logic modo_mixto, pub_mode_q;
  always @(posedge adc_clk_i)
    if (!adc_rstn_i) begin
      modo_mixto <= 1'b0;
      pub_mode_q <= cfg_pub_mode;
    end else begin
      if      (clr_pulse)                  modo_mixto <= 1'b0;
      else if (cfg_pub_mode != pub_mode_q) modo_mixto <= 1'b1;
      pub_mode_q <= cfg_pub_mode;
    end

  // El flag registrado llega UN CICLO TARDE: en el ciclo mismo del cambio,
  // cfg_pub_mode ya vale lo nuevo y modo_mixto todavia lo viejo, asi que la
  // identidad se evaluaria contra contadores de la otra definicion. El termino
  // combinacional cierra ese agujero de un ciclo.
  wire modo_cambia = (cfg_pub_mode != pub_mode_q);
  wire modo_sucio  = modo_mixto || modo_cambia;

  //---------------------------------------------------------------------------
  // 1. El teselado del TIEMPO
  //---------------------------------------------------------------------------
  // Los tres casilleros particionan el estado del extractor: dt_win = S_ACTIVE,
  // dt_div = S_DIV, dt_rearm = S_IDLE sin re-armar. Son disjuntos por
  // construccion, y esta propiedad lo fija para que siga siendo cierto si
  // alguien agrega un estado a la FSM.
  ap_dt_disjuntos: assert property (
    $onehot0({dt_win, dt_div, dt_rearm})
  ) else $error("casilleros de tiempo muerto solapados: win=%b div=%b rearm=%b",
                dt_win, dt_div, dt_rearm);

  // Y son el COMPLEMENTO de poder abrir. Esto es lo que hace que el teselado
  // sea exhaustivo: no hay un cuarto estado en que el modulo no pueda abrir.
  ap_puede_abrir_complemento: assert property (
    puede_abrir == !(dt_win || dt_div || dt_rearm)
  ) else $error("puede_abrir no es el complemento de los casilleros");

  // LA INVARIANTE CENTRAL. Cada ciclo con cfg_run suma a exactamente uno de los
  // cinco relojes, asi que la suma cierra en todo ciclo. Si se agrega una causa
  // de bloqueo y se olvida su reloj, esta propiedad falla.
  ap_suma_relojes: assert property (
    realtime_cnt == vetotime_cnt + t_win_cnt + t_div_cnt + t_rearm_cnt
                                 + livetime_cnt
  ) else $error("los relojes no teselan realtime: rt=%0d vt=%0d win=%0d div=%0d rearm=%0d lt=%0d",
                realtime_cnt, vetotime_cnt, t_win_cnt, t_div_cnt,
                t_rearm_cnt, livetime_cnt);

  // deadtime_cnt (0x078) conserva la definicion VIEJA —solo t_win + t_div— y por
  // lo tanto SUBESTIMA el bloqueo real. Esta propiedad fija ese hecho: el
  // registro de compatibilidad nunca puede dar mas que el total honesto. Es la
  // forma de que el bug original quede documentado como una desigualdad probada
  // en vez de una nota al pie.
  ap_deadtime_viejo_subestima: assert property (
    deadtime_cnt <= (t_win_cnt + t_div_cnt + t_rearm_cnt)
  ) else $error("deadtime_cnt (%0d) excede el total honesto (%0d)",
                deadtime_cnt, t_win_cnt + t_div_cnt + t_rearm_cnt);

  // El reloj viejo es exactamente t_win + t_div mientras no haya veto. Con veto
  // los dos lados se congelan, asi que la igualdad se mantiene.
  //
  // FASE 2: la identidad depende del MODO DE PUBLICACION, y eso es informacion,
  // no una molestia. En modo bloqueante dt_div == S_ACTIVE-o-S_DIV == feat_busy,
  // y la identidad es la de siempre. En modo FIFO la contrapresion ocurre con la
  // FSM de ventana en REPOSO, asi que feat_busy no la ve y el registro viejo se
  // queda solo con la ventana: miente MAS, no menos.
  ap_deadtime_viejo_identidad: assert property (
    (!cfg_pub_mode && !modo_sucio) |-> deadtime_cnt == (t_win_cnt + t_div_cnt)
  ) else $error("modo bloqueante: deadtime_cnt (%0d) != t_win + t_div (%0d)",
                deadtime_cnt, t_win_cnt + t_div_cnt);

  ap_deadtime_viejo_fifo: assert property (
    (cfg_pub_mode && !modo_sucio) |-> deadtime_cnt == t_win_cnt
  ) else $error("modo FIFO: deadtime_cnt (%0d) != t_win (%0d)",
                deadtime_cnt, t_win_cnt);

  // feat_busy y los casilleros que lo componen tienen que coincidir ciclo a
  // ciclo: es lo que justifica las identidades de arriba. En modo FIFO feat_busy
  // es solo la ventana, porque el bloqueo por publicacion ya no tiene estado.
  ap_busy_es_win_o_div: assert property (
    feat_busy == (cfg_pub_mode ? dt_win : (dt_win || dt_div))
  ) else $error("feat_busy no coincide con los casilleros (pub_mode=%b)",
                cfg_pub_mode);

  // EL CASILLERO DEL ARBITRO NO PUEDE QUEDAR AFUERA. En modo FIFO, un ciclo con
  // dt_div y la ventana en reposo es contrapresion: el modulo no puede abrir y
  // feat_busy esta BAJO. Esta propiedad fija que ese ciclo igual va a t_div y no
  // a livetime, que es la unica forma de que el tiempo muerto oculto de la Fase
  // 1 no se mude del Schmitt al arbitro.
  ap_contrapresion_es_muerta: assert property (
    (cfg_pub_mode && dt_div && !feat_busy) |-> bloqueado || veto_i || !cfg_run
  ) else $error("contrapresion de FIFO sin contar como tiempo muerto");

  //---------------------------------------------------------------------------
  // 2. El teselado de los EVENTOS
  //---------------------------------------------------------------------------
  // Cada cruce de thr_hi hacia arriba va a exactamente un casillero. Es la
  // version por eventos de ap_suma_relojes, y la que garantiza que no haya
  // pulsos que se pierdan "sin dejar rastro" — que es lo que pasaba con los que
  // llegaban durante el bloqueo por re-armado.
  // FASE 2: el casillero lost_notrig entra en la MISMA invariante. Con apertura
  // por trigger externo un cruce puede encontrar al modulo libre y no abrir, y
  // sin este termino la suma se rompe exactamente al cambiar de fuente.
  ap_atribucion_arribos: assert property (
    c_cross == c_open + c_lost_rearm + c_lost_active + c_lost + c_lost_veto
               + c_lost_notrig
  ) else $error("arribos sin atribuir: cross=%0d open=%0d rearm=%0d active=%0d busy=%0d veto=%0d notrig=%0d",
                c_cross, c_open, c_lost_rearm, c_lost_active, c_lost,
                c_lost_veto, c_lost_notrig);

  // Toda ventana que abre termina cerrandose: cnt_total cuenta cierres y cnt_win
  // aperturas, asi que difieren como mucho en la ventana en vuelo. Si cnt_total
  // se adelantara habria cierres sin apertura.
  //
  // VA CONTRA cnt_win Y NO cnt_open, y eso es Fase 2: cnt_open cuenta CRUCES que
  // abrieron, y con re-armado por contador sobre una senal que se queda arriba,
  // o con apertura por trigger, hay ventanas que abren SIN cruce. Contra c_open
  // esta propiedad fallaria por una razon que no es un bug.
  ap_win_vs_total: assert property (
    (c_win >= c_total) && ((c_win - c_total) <= 32'd1)
  ) else $error("win=%0d y total=%0d difieren en mas de una ventana en vuelo",
                c_win, c_total);

  // Y los cruces que abrieron nunca pueden ser mas que las ventanas abiertas.
  ap_open_acotado_por_win: assert property (
    c_open <= c_win
  ) else $error("cruces que abrieron (%0d) > ventanas abiertas (%0d)",
                c_open, c_win);

  // Un arribo con el modulo libre y sin veto TIENE que abrir: no hay ninguna
  // otra forma de perder un pulso, y si apareciera, cnt_cross dejaria de cerrar.
  // Se restringe a la fuente INTERNA: con trigger externo un cruce libre
  // legitimamente no abre, y eso ya lo cubre lost_notrig.
  ap_arribo_libre_abre: assert property (
    (arribo && puede_abrir && cfg_run && !veto_i && (cfg_trig_src == 2'd0))
    |=> $changed(c_open)
  ) else $error("arribo con el modulo libre que no abrio ventana");

  // Que la apertura externa sea por FLANCO y no por nivel NO se puede escribir
  // como "c_win <= c_trig": los contadores son acumulativos y una corrida que
  // empieza en modo interno ya trae ventanas sin trigger. Se verifica en el
  // testbench, con los contadores recien borrados (tb_mca_pulse_feature, 16c:
  // trigger alto 5 muestras -> UNA ventana). Aca solo queda la cobertura.

  //---------------------------------------------------------------------------
  // 3. La distribucion del periodo muerto
  //---------------------------------------------------------------------------
  // Cada periodo dura al menos un ciclo, asi que la suma de los largos —que es
  // el total honesto— acota la cantidad de periodos.
  ap_periodos_acotados: assert property (
    64'(cnt_dead_periods) <= (t_win_cnt + t_div_cnt + t_rearm_cnt)
  ) else $error("mas periodos muertos (%0d) que ciclos muertos (%0d)",
                cnt_dead_periods, t_win_cnt + t_div_cnt + t_rearm_cnt);

  // cnt_dead_ext cuenta periodos EXTENDIDOS, uno por periodo como maximo: es la
  // diferencia que lo vuelve un estimador de P(L > tau) y no un conteo de
  // extensiones.
  ap_ext_acotado_por_periodos: assert property (
    cnt_dead_ext <= cnt_dead_periods
  ) else $error("periodos extendidos (%0d) > periodos (%0d)",
                cnt_dead_ext, cnt_dead_periods);

  // Y cada extension es un arribo perdido durante el bloqueo, asi que los tres
  // casilleros de perdida la acotan.
  ap_ext_acotado_por_perdidas: assert property (
    cnt_dead_ext <= (c_lost_rearm + c_lost_active + c_lost)
  ) else $error("extensiones (%0d) > arribos perdidos durante el bloqueo (%0d)",
                cnt_dead_ext, c_lost_rearm + c_lost_active + c_lost);

  // El maximo nunca puede exceder el total.
  ap_max_len_acotado: assert property (
    64'(max_dead_len) <= (t_win_cnt + t_div_cnt + t_rearm_cnt)
  ) else $error("max_dead_len (%0d) > ciclos muertos totales (%0d)",
                max_dead_len, t_win_cnt + t_div_cnt + t_rearm_cnt);

  // El largo en curso solo avanza mientras hay bloqueo, y arranca en 1 en el
  // flanco. Fuera del bloqueo queda congelado para que el flanco de bajada
  // pueda compararlo contra el maximo.
  ap_dead_len_congelado: assert property (
    (!bloqueado && !clr_pulse) |=> $stable(dead_len)
  ) else $error("dead_len cambio sin bloqueo");

  //---------------------------------------------------------------------------
  // 4. Cobertura: que los testbenches realmente lleguen a los casos nuevos
  //---------------------------------------------------------------------------
  // Sin esto es facil que todo pase porque nunca se ejercito el bloqueo por
  // re-armado, que es justo el caso que el diseno viejo no veia.
  cp_rearm:       cover property (dt_rearm);
  cp_lost_rearm:  cover property ($changed(c_lost_rearm));
  cp_lost_active: cover property ($changed(c_lost_active));
  cp_lost_busy:   cover property ($changed(c_lost));
  cp_ext:         cover property ($changed(cnt_dead_ext));
  cp_periodo:     cover property ($changed(cnt_dead_periods));
  // El caso que separa el contador viejo del honesto: bloqueado pero sin busy.
  cp_oculto:      cover property (bloqueado && !feat_busy);

  //---------------------------------------------------------------------------
  // 5. FASE 2: cobertura de las politicas nuevas
  //---------------------------------------------------------------------------
  // Cada politica tiene que haberse ejercitado de verdad, si no las propiedades
  // condicionadas por modo pasan sin haber mirado nada.
  cp_trig_ext:    cover property (cfg_trig_src == 2'd1);
  cp_trig_ambos:  cover property (cfg_trig_src == 2'd2);
  cp_rearm_cnt:   cover property (cfg_rearm_mode);
  cp_pub_fifo:    cover property (cfg_pub_mode);
  cp_trig_flanco: cover property ($changed(c_trig));
  cp_notrig:      cover property ($changed(c_lost_notrig));
  // Ventana abierta SIN cruce de thr_hi: pasa con re-armado por contador sobre
  // una senal sostenida, y con apertura por trigger. Es el caso que obligo a
  // separar cnt_win de cnt_open.
  cp_win_sin_cruce: cover property ($changed(c_win) && !arribo);
  // LA CONTRAPRESION DEL ARBITRO. Si este cover no se alcanza, la FIFO nunca se
  // lleno en ninguna simulacion y el casillero nuevo del teselado esta sin
  // probar.
  cp_contrapresion: cover property (cfg_pub_mode && dt_div && !feat_busy);

endmodule

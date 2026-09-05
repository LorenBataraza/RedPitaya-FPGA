`timescale 1ns/1ps
//=============================================================================
// mca_hist — motor de histograma genérico (una implementación, N instancias)
//
// Memoria de 2^AW bins de CW bits, inferida como BRAM simple-dual-port:
//   Puerto A: SÓLO ESCRITURA  — write-back del incremento, y barrido de borrado
//   Puerto B: SÓLO LECTURA    — lectura del bus, y lectura del pipeline
//
// Por qué no un read-modify-write de 3 estados (como el axis_histogram.v de
// pavel-demin): un puerto de BRAM tiene UNA dirección por ciclo, así que no
// puede leer addr(n) y escribir addr(n-2) a la vez. Con la lectura en el
// puerto B y la escritura en el A se consigue 1 incremento por ciclo, a costa
// de necesitar forwarding (abajo). El de 3 estados acepta 1 evento cada 3
// ciclos, lo que obligaría a decimar un futuro mapa de persistencia.
//
// FORWARDING (2 etapas). El evento que lee en el ciclo m tiene su dato en m+1
// y escribe en m+2. Un evento a la MISMA dirección en m+1 o m+2 leería un
// valor viejo, así que hay que puentear:
//   - distancia 1: la escritura que ocurre en este mismo ciclo  -> wdata2
//   - distancia 2: la escritura que ocurrió en el ciclo anterior -> wdata3
//   - distancia >=3: la memoria ya está actualizada, no hace falta.
// La prioridad va de más nuevo a más viejo.
//
// BARRIDO DE BORRADO: usa SÓLO el puerto de escritura, así que el puerto de
// lectura queda vivo durante todo el barrido. Es un requisito duro: un barrido
// de 16384 bins son 16384 ciclos = 131 us, ~500 veces el timeout de 32 ciclos
// de axi4_slave.sv:193. Si el barrido frenara el ack, el bus se colgaría.
//
// CONTENCIÓN: la lectura del bus tiene prioridad sobre el puerto B. Un evento
// que llegue en ese ciclo (o durante el barrido) se descarta y se CUENTA en
// dropped_o, para que la pérdida sea medible. Con eventos separados por
// cientos de ciclos y lecturas de bus separadas por microsegundos, la
// probabilidad de colisión es despreciable; leer con run=0 la elimina.
//
// NOTA: rd_i tiene que ser un PULSO DE 1 CICLO, no el `ren` sostenido del bus.
// sys_bus_cdc mantiene ren alto hasta el ack (~4 ciclos); si se conectara
// directo, cada acceso del bus robaría 4 ciclos al pipeline en vez de 1.
//=============================================================================

module mca_hist #(
  parameter integer AW = 12,   // bins = 2^AW
  parameter integer CW = 32    // ancho del contador (saturante)
)(
  input                 clk_i      ,
  input                 rstn_i     ,   // reset síncrono activo-bajo

  // --- entrada de eventos: 1 incremento por ciclo ---
  input                 inc_i      ,
  input      [AW-1:0]   inc_addr_i ,

  // --- borrado ---
  input                 clear_i    ,   // pulso: arranca el barrido
  output                busy_o     ,   // barrido en progreso

  // --- lectura de bus (prioridad sobre el pipeline) ---
  input                 rd_i       ,   // PULSO de 1 ciclo
  input      [AW-1:0]   rd_addr_i  ,
  output     [CW-1:0]   rd_data_o  ,   // válido 2 ciclos después de rd_i

  // --- saturacion ---
  // `full_o` es PEGAJOSO: se pone en el primer bin que llega al tope y solo lo
  // limpia el barrido de borrado. Con `cfg_keep_i = 0` la acumulacion se congela
  // ahi mismo, en TODO el histograma y no solo en el bin saturado: un espectro
  // con unos canales congelados y otros no ya no es un espectro, porque las
  // areas relativas dejan de corresponder al mismo live time.
  //
  // Escala, para no sobredimensionar el problema: 2^32 cuentas a 794 kcps con
  // TODO en un solo pico son ~14 h. Es real en una corrida larga, pero esta a
  // cuatro ordenes de magnitud de la deriva, que es lo que de verdad limita
  // (docs/mca/limites_resolucion_y_deriva.md §7). Sirve sobre todo como
  // disparador de rebanada y como seguro contra la saturacion silenciosa.
  input                 cfg_keep_i ,   // 1 = seguir contando aunque haya full
  output reg            full_o     ,   // pegajoso: algun bin llego al tope

  // --- diagnóstico ---
  output reg [32-1:0]   dropped_o  ,   // eventos perdidos por colisión/barrido
  output reg [32-1:0]   suppressed_o   // eventos NO contados por histograma lleno
);

localparam integer N_BINS = (1 << AW);

(* ram_style = "block" *) reg [CW-1:0] mem [0:N_BINS-1];

// Inicialización a cero: en hardware la hace el bitstream (INIT de la BRAM);
// acá además evita que la simulación arranque con X.
integer ii;
initial for (ii = 0; ii < N_BINS; ii = ii + 1) mem[ii] = {CW{1'b0}};

//-----------------------------------------------------------------------------
// Barrido de borrado (puerto de escritura)
//-----------------------------------------------------------------------------
reg [AW-1:0] clr_addr;
reg          clr_busy;
wire         clr_start = clear_i && !clr_busy;
wire         clr_last  = clr_busy && (clr_addr == {AW{1'b1}});

assign busy_o = clr_busy;

always @(posedge clk_i) begin
  if (!rstn_i) begin
    clr_addr <= {AW{1'b0}};
    clr_busy <= 1'b0;
  end else if (clr_start) begin
    clr_addr <= {AW{1'b0}};
    clr_busy <= 1'b1;
  end else if (clr_busy) begin
    clr_addr <= clr_addr + {{(AW-1){1'b0}}, 1'b1};
    if (clr_last) clr_busy <= 1'b0;
  end
end

//-----------------------------------------------------------------------------
// Puerto B: lectura. El bus gana; si no, lee el pipeline de incremento.
//-----------------------------------------------------------------------------
wire [AW-1:0] pb_addr = rd_i ? rd_addr_i : inc_addr_i;

reg [CW-1:0] pb_dout;      // latencia 1: lo consume el pipeline de incremento
reg [CW-1:0] rd_data_r;    // latencia 2: lo consume el bus, y SE MANTIENE
reg          rd_d1;

// rd_data_r se carga SOLO en el ciclo en que pb_dout trae el dato pedido, y
// después se mantiene. Sin ese enable el dato vivía un único ciclo: apenas
// baja rd_i el puerto B vuelve a la dirección del pipeline de incremento y
// pb_dout pasa a ser mem[inc_addr]. Como el ack del bus llega recién 4 ciclos
// más tarde (mca_top), toda lectura devolvía el bin del ÚLTIMO evento en vez
// del bin pedido: el espectro entero se leía como un valor repetido.
always @(posedge clk_i) begin
  rd_d1   <= rd_i;
  pb_dout <= mem[pb_addr];
  if (rd_d1) rd_data_r <= pb_dout;
end

assign rd_data_o = rd_data_r;

//-----------------------------------------------------------------------------
// Pipeline de incremento
//   etapa 0 (m)  : dirección presentada al puerto B
//   etapa 1 (m+1): dato disponible, se calcula el valor nuevo
//   etapa 2 (m+2): escritura por el puerto A
//-----------------------------------------------------------------------------
// `congelado` para la acumulacion entera al primer bin saturado. Los eventos
// que llegan ahi NO se cuentan como `dropped` (eso es colision de lectura o
// barrido, que es otra cosa) sino en su propio contador, para que la perdida sea
// medible y atribuible.
wire congelado = full_o && !cfg_keep_i;
wire accept = inc_i && !rd_i && !clr_busy && !congelado;
wire drop   = inc_i && !accept && !congelado;
wire supp   = inc_i && congelado;

reg  [AW-1:0] a1, a2, a3;
reg           v1, v2, v3;
reg  [CW-1:0] wdata2, wdata3;

// Valor actual del bin, con los dos puentes de forwarding.
wire fwd2 = v2 && (a2 == a1);       // escritura de ESTE ciclo
wire fwd3 = v3 && (a3 == a1);       // escritura del ciclo ANTERIOR
wire [CW-1:0] cur = fwd2 ? wdata2 :
                    fwd3 ? wdata3 : pb_dout;

// Incremento saturante: al llegar a todo unos se queda ahí.
wire [CW-1:0] nxt = (&cur) ? cur : (cur + {{(CW-1){1'b0}}, 1'b1});
// El bin que se esta por escribir ya estaba al tope: la cuenta se perdio.
wire          topea = v1 && (&cur);

always @(posedge clk_i) begin
  if (!rstn_i) begin
    v1 <= 1'b0; v2 <= 1'b0; v3 <= 1'b0;
    a1 <= {AW{1'b0}}; a2 <= {AW{1'b0}}; a3 <= {AW{1'b0}};
    wdata2 <= {CW{1'b0}}; wdata3 <= {CW{1'b0}};
  end else if (clr_start) begin
    // Se descartan los eventos en vuelo: si no, escribirían después del
    // barrido y dejarían cuentas sueltas en un histograma recién borrado.
    v1 <= 1'b0; v2 <= 1'b0; v3 <= 1'b0;
  end else begin
    v1     <= accept;
    a1     <= inc_addr_i;

    v2     <= v1;
    a2     <= a1;
    wdata2 <= nxt;

    v3     <= v2;
    a3     <= a2;
    wdata3 <= wdata2;
  end
end

//-----------------------------------------------------------------------------
// Puerto A: escritura (barrido de borrado o write-back del incremento)
//-----------------------------------------------------------------------------
wire [AW-1:0] pa_addr = clr_busy ? clr_addr    : a2;
wire [CW-1:0] pa_data = clr_busy ? {CW{1'b0}}  : wdata2;
wire          pa_we   = clr_busy ? 1'b1        : v2;

always @(posedge clk_i)
  if (pa_we) mem[pa_addr] <= pa_data;

//-----------------------------------------------------------------------------
// Contadores y bandera de lleno. El borrado los resetea: empieza una
// adquisición nueva, y con ella un live time nuevo.
//-----------------------------------------------------------------------------
always @(posedge clk_i) begin
  if (!rstn_i)          dropped_o <= 32'h0;
  else if (clr_start)   dropped_o <= drop ? 32'h1 : 32'h0;
  else if (drop)        dropped_o <= dropped_o + 32'h1;
end

always @(posedge clk_i) begin
  if (!rstn_i)          suppressed_o <= 32'h0;
  else if (clr_start)   suppressed_o <= supp ? 32'h1 : 32'h0;
  else if (supp)        suppressed_o <= suppressed_o + 32'h1;
end

always @(posedge clk_i) begin
  if (!rstn_i)          full_o <= 1'b0;
  else if (clr_start)   full_o <= 1'b0;
  else if (topea)       full_o <= 1'b1;
end

endmodule

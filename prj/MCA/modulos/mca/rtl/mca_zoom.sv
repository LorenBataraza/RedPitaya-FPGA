`timescale 1ns/1ps
//=============================================================================
// mca_zoom — de una feature de FW bits al bin de un eje de AW bits, con zoom
// ALINEADO A POTENCIAS DE 2.
//
// La ventana es  [k*2^(FW-z), (k+1)*2^(FW-z))  con z el nivel de zoom y k el
// indice de ventana. Sobre una feature de FW bits eso es puro rebanado:
//
//     dentro de la ventana  <=>  los z bits ALTOS de feat valen k
//     bin                    =   los AW bits siguientes
//
// Ni restador ni multiplicador: un comparador y un corrimiento variable. Es mas
// barato que un offset arbitrario, no mas caro.
//
// POR QUE ALINEADO A POTENCIAS DE 2, y no un offset libre. Con offsets
// arbitrarios dos espectros tomados con ventanas distintas tienen bordes de bin
// que NO coinciden, y combinarlos exige re-samplear —con su jacobiano y el peine
// de DNL que eso introduce (ver docs/mca/limites_resolucion_y_deriva.md §5).
// Alineado, los bins de cada nivel son subdivisiones EXACTAMENTE anidadas de los
// del nivel anterior: un bin de nivel z es la suma ENTERA de dos de nivel z+1.
// Se cosen con aritmetica entera, sin interpolar y sin agregar DNL.
//
// LO QUE EL ZOOM NO HACE: no mejora la resolucion. Solo recupera la perdida por
// binning (Sheppard), que a 8.6 canales/FWHM ya es 0.31 % de sigma. Sirve para
// UBICAR el eje sobre dos picos juntos y para poder usar un histograma mas
// chico, no para inventar precision que la feature no tiene.
//
// FUERA DE LA VENTANA SATURA, no envuelve ni descarta: un evento por encima va
// al ultimo canal y uno por debajo al canal 0. Es el mismo contrato que ya tenia
// el eje sin zoom —un evento nunca puede aparecer en el extremo opuesto— y deja
// los bins de los extremos como indicadores visibles de desborde. Con la deriva
// medida esto importa: a z=3 un corrimiento del 6.45 % mueve el pico un 41 % del
// ancho de la ventana, asi que los extremos avisan.
//
// z SE SATURA a FW-AW: mas alla no quedan bits que rebanar. Y k se ENMASCARA a
// los z bits utiles, para que z=0 fuerce k=0 en vez de mandar todo al canal 0 en
// silencio si alguien deja un k viejo escrito.
//=============================================================================

module mca_zoom #(
  parameter integer FW = 16,   // ancho de la feature
  parameter integer AW = 13    // bits del eje de destino
)(
  input      [FW-1:0] feat_i ,
  input      [3:0]    z_i    ,   // nivel de zoom: ventana = 2^-z del fondo
  input      [7:0]    k_i    ,   // indice de ventana, 0 .. 2^z-1
  output     [AW-1:0] bin_o
);

localparam integer ZMAX = (FW > AW) ? (FW - AW) : 0;

// Saturacion de z y enmascarado de k: los dos evitan configuraciones que
// pareceria que funcionan y no.
wire [3:0] z = (z_i > ZMAX[3:0]) ? ZMAX[3:0] : z_i;
wire [7:0] kmask = (z == 4'd0) ? 8'h00 : (8'hFF >> (4'd8 - z));
wire [7:0] k     = k_i & kmask;

// Los z bits altos de la feature, y k llevado al mismo ancho para comparar.
wire [FW-1:0] alto = (z == 4'd0) ? {FW{1'b0}} : (feat_i >> (FW[4:0] - {1'b0,z}));
wire [FW-1:0] kx   = {{(FW-8){1'b0}}, k};

// La ventana llevada al tope: los AW bits de mas peso ya son el bin.
wire [FW-1:0] desp = feat_i << z;

assign bin_o = (alto > kx) ? {AW{1'b1}} :      // por encima: satura arriba
               (alto < kx) ? {AW{1'b0}} :      // por debajo: satura abajo
                             desp[FW-1 -: AW];

endmodule

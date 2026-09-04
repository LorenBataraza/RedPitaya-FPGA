`timescale 1ns/1ps
//=============================================================================
// mca_discriminator — acepta o rechaza un evento por el valor de UNA feature.
//
// Antes esto eran dos lineas sueltas adentro de la FSM del extractor
// (`amp_ok`): una condicion, feature FIJA (la amplitud seleccionada), y solo
// intervalo interno. Aca pasa a ser un bloque con selector, y el intervalo
// puede ser interno [min,max] o su complemento.
//
// VA DESPUES DE LOS DIVISORES, no antes. Es lo que permite que el selector
// alcance tambien a las features de FORMA, que no existen hasta que el divisor
// termina. Y esa es justamente la que importa: medido por Monte-Carlo sobre el
// espectro de una linea a 100 kcps, un corte por ANCHO (Pico/Q_total) rechaza
// el 99.1 % de los apilados y baja el continuo sobre el fotopico de 32.4 % a
// 0.8 %, sin perder un solo evento limpio. El eje de forma que ya estaba en el
// hardware (Q_cola/Q_total) rechaza el 29.6 % en modo histeresis y EXACTAMENTE
// NADA en modo compuerta. Ver software/monte-carlo/.
//
// El costo de estar despues del divisor es que todo evento paga su latencia
// antes de poder ser rechazado. Son DIV_W ciclos = 128 ns contra una ventana de
// 3.07 us: el 4 %.
//
// EL CORTE HAY QUE CALIBRARLO CONTRA LA AMPLITUD. `Pico/Q_total` NO es
// constante: en modo histeresis la ventana cierra cuando la cola cruza el
// umbral, o sea que su largo crece con el logaritmo de la amplitud, y el
// cociente deriva ~21 % de punta a punta del rango. Un umbral fijo cortaria los
// pulsos limpios chicos y dejaria pasar los apilados grandes. La calibracion se
// hace con un pulser DESLIZANTE y no con el espectro fuente: con una linea
// monoenergetica el lugar geometrico queda definido en un punado de canales y el
// corte terminaria rechazando por caer fuera del rango calibrado y no por tener
// la forma mal — un corte en amplitud disfrazado de corte en forma, que da un
// resultado espectacular y falso.
//
// INTERVALO VACIO: con min > max el conjunto interno es vacio por definicion,
// asi que `interno` rechaza TODO y `externo` acepta todo. No es un caso de
// error, es la respuesta correcta a lo que se pidio, y esta fijado por un test
// para que nadie lo "arregle" despues.
//=============================================================================

module mca_discriminator #(
  parameter integer FW    = 16,   // ancho de una feature
  parameter integer NFEAT = 16    // ranuras del bus
)(
  input      [NFEAT*FW-1:0] ev_feat_i ,
  input                     cfg_en_i  ,   // 0 = pasa todo (default)
  input      [3:0]          cfg_sel_i ,   // que feature mira (indices F_* )
  input                     cfg_out_i ,   // 0 = interno [min,max], 1 = externo
  input      [FW-1:0]       cfg_min_i ,
  input      [FW-1:0]       cfg_max_i ,
  output                    accept_o
);

// Part-select indexada, no una function: dentro de un assign continuo una
// function no queda sensible a lo que lee del alcance exterior, y el mux se
// quedaria clavado en el valor de reset. Ya paso una vez en mca_top.
wire [FW-1:0] f = ev_feat_i[cfg_sel_i * FW +: FW];

// Comparacion SIN signo: todas las ranuras del bus son uint16 por contrato.
wire dentro = (f >= cfg_min_i) && (f <= cfg_max_i);

assign accept_o = !cfg_en_i ? 1'b1
                            : (cfg_out_i ? !dentro : dentro);

endmodule

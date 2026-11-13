#!/usr/bin/env python3
"""Genera event_ring_red_pitaya_top.sv a partir de mca_red_pitaya_top.sv.

El top del ring es el del MCA con cuatro diferencias:

  1. event_ring_top en la mitad baja del slot 2 (0x4020_0000), donde el top del
     MCA tiene un stub (la otra mitad, 0x4021_0000, es de gen_pulsos en los
     dos), escribiendo a la DDR por HP2 (axi2_sys)
  2. axi2_sys en adc_clk, no en dac_axi_clk
  3. i_scope con EN_AXI(0): sin la captura a DDR por AXI, que el ring reemplaza
  4. integration_cfg con EN_RING(1)

Antes eran dos archivos escritos a mano, y el del ring se fue quedando atrás: no
declaraba route_osc_tap, route_mtrg_tap ni route_mca_tap (eran nets implícitas de
1 bit, y el bit alto del tap se perdía) y decía H_AW 14 con un MCA de 8192 canales.
Ahora el del ring no se edita: se regenera.

    python3 gen_event_ring_top.py           # escribe event_ring_red_pitaya_top.sv
    python3 gen_event_ring_top.py --check   # falla si el que está no es el generado

Cada reemplazo tiene que encontrar su ancla exactamente una vez; si el top del
MCA cambia ahí, falla en vez de generar algo a medias.
"""
import argparse
import pathlib
import sys

AQUI = pathlib.Path(__file__).resolve().parent
ORIGEN = AQUI / 'mca_red_pitaya_top.sv'
DESTINO = AQUI / 'event_ring_red_pitaya_top.sv'

CABECERA = """\
// =============================================================================
// event_ring_red_pitaya_top — el MCA con el event_ring
//
// GENERADO por gen_event_ring_top.py a partir de mca_red_pitaya_top.sv: no se
// edita a mano. Difiere del top del MCA en cuatro cosas, y en ninguna otra:
//   1. event_ring_top en la mitad baja del slot 2 (0x4020_0000), donde el top
//      del MCA tiene un stub (0x4021_0000 es de gen_pulsos en los dos),
//      escribiendo a la DDR por HP2 (axi2_sys)
//   2. axi2_sys en adc_clk, no en dac_axi_clk (ver su declaracion)
//   3. i_scope con EN_AXI(0): sin la captura a DDR por AXI (rp_axi_sm), que el
//      ring reemplaza. Es lo que hace lugar al ring; ver EN_AXI en
//      rp_scope_mt_com.sv
//   4. integration_cfg con EN_RING(1)
//
// Lo construye red_pitaya_vivado_Z10_v3_event_ring.tcl
// (make bitstream-event-ring), que lo regenera antes de sintetizar.
//
// Lo que sigue es la cabecera del top del MCA, que dice en que difiere el MCA
// de red_pitaya_top.sv.
// =============================================================================
"""

RING = """\
// --- SLOT 2: event_ring (en el top del MCA, un stub) ---------------------
// Base 0x4020_0000: la parte del slot 2 que no es de gen_pulsos (ver
// sys_bus_split, arriba). Toma el puerto HP2 que dejo libre el ASG. Las
// muestras son mca_dat_bus, las mismas que consume el MCA: post-calibracion y
// PRE-decimacion. El trigger es el evento conjunto del multitrigger, el mismo
// que llega a rp_bram_sm y, como scope_trigo, al MCA: el ring no agrega una
// fuente de disparo, agrega un camino de salida.
event_ring_top #(
  .DW      (14),
  .N_CH    (2),
  .PRE_AW  (11),   // 2048 palabras: ventanas de hasta 1024 muestras por canal
  .S_AW    (11),
  .DATA_AW (12),   // stage: 4096 muestras (~2 RAMB36)
  .E       (4)
) i_event_ring (
  .adc_clk_i    (adc_clk          ),
  .adc_rstn_i   (adc_rstn         ),

  .dat_i        (mca_dat_bus      ),
  .dv_i         (mca_val_bus[0]   ),
  .trig_i       (ring_trig        ),
  .snapshot_i   (ring_snap        ),

  .axi_waddr_o  (axi2_sys.waddr   ),
  .axi_wdata_o  (axi2_sys.wdata   ),
  .axi_wsel_o   (axi2_sys.wsel    ),
  .axi_wsize_o  (axi2_sys.wsize   ),
  .axi_wvalid_o (axi2_sys.wvalid  ),
  .axi_wlen_o   (axi2_sys.wlen    ),
  .axi_wfixed_o (axi2_sys.wfixed  ),
  .axi_werr_i   (axi2_sys.werr    ),
  .axi_wrdy_i   (axi2_sys.wrdy    ),

  .sys_addr     (sys2_ring.addr   ),
  .sys_wdata    (sys2_ring.wdata  ),
  .sys_wen      (sys2_ring.wen    ),
  .sys_ren      (sys2_ring.ren    ),
  .sys_rdata    (sys2_ring.rdata  ),
  .sys_err      (sys2_ring.err    ),
  .sys_ack      (sys2_ring.ack    )
);
"""

# (ancla, reemplazo): cada ancla tiene que estar exactamente una vez
REEMPLAZOS = [
    ('module mca_red_pitaya_top #(', 'module event_ring_red_pitaya_top #('),
    ('endmodule: mca_red_pitaya_top', 'endmodule: event_ring_red_pitaya_top'),

    # el diagrama: los anchos no cambian, asi el recuadro sigue cerrando
    ('|<-------+ axi0_sys, axi1_sys    #', '|<-------+ axi2_sys, del ring    #'),
    ('| (64 b, del scope)     #',          '| (64 b; 0, 1, 3 en 0)  #'),
    ('| AXI-HP0/1  /--------------\\', '| AXI-HP2    /--------------\\'),
    ('(slot 2: gen_pulsos -> asg_dat, trig_asg)',
     '(slot 2: event_ring -> HP2, y gen_pulsos)'),

    (' *     i_scope -> axi0_sys/axi1_sys -> axi_master -> S_AXI_HP0/HP1 -> DDR\n'
     ' *   `axi_master` convierte las escrituras del bus custom en bursts AXI4 de\n'
     ' *   64 b contra los puertos HP del PS. Hay cuatro instancias; HP2/HP3 eran del\n'
     ' *   ASG y quedan atadas a cero (ver mas abajo).\n',
     ' *     i_event_ring -> axi2_sys -> axi_master -> S_AXI_HP2 -> DDR\n'
     ' *   `axi_master` convierte las escrituras del bus custom en bursts AXI4 de\n'
     ' *   64 b contra los puertos HP del PS. Hay cuatro instancias y solo anda la\n'
     ' *   de HP2. HP0/HP1 eran de la captura AXI del scope, que este top no tiene\n'
     ' *   (EN_AXI = 0), y HP3 era del ASG: quedan atadas a cero.\n'),
    (' *   2  gen_pulsos           0x4021_0000: pulsos al DAC, en el lugar del ASG\n',
     ' *   2  event_ring_top       0x4020_0000: ventanas de evento a la DDR, por HP2\n'
     ' *      gen_pulsos           0x4021_0000: pulsos al DAC, en el lugar del ASG\n'),

    ('// =============================================================================\n'
     '// mca_red_pitaya_top — top del Analizador Multicanal (MCA)\n'
     '//\n',
     CABECERA + '//\n'),

    ('axi_sys_if axi2_sys (.clk(dac_axi_clk), .rstn(dac_axi_rstn));\n',
     '// HP2 en adc_clk: lo maneja el event_ring, que vive entero en adc_clk. En\n'
     '// el top del MCA cuelga de dac_axi_clk (250 MHz) porque era del ASG; dejarlo\n'
     '// asi seria un cruce de dominios sin sincronizar sobre wvalid/wrdy. El build\n'
     '// lo acompania con hp2_clk_freq = 125 MHz en el PS7.\n'
     'axi_sys_if axi2_sys (.clk(adc_clk    ), .rstn(adc_rstn    ));\n'),

    ('// Defino con la misma interface que el scope original\n\nrp_scope_mt_com#(\n',
     '// El evento conjunto hacia el event_ring, y su snapshot.\n'
     'wire        ring_trig;\n'
     'wire [16:0] ring_snap;\n\n'
     '// Defino con la misma interface que el scope original\n\nrp_scope_mt_com#(\n'),
    ('  .EN_FILT(0)) i_scope (      // sin ecualizador: ver la cabecera\n',
     '  .EN_FILT(0),                // sin ecualizador: ver la cabecera\n'
     '  .EN_AXI(0)) i_scope (       // sin captura AXI: la reemplaza el ring\n'),
    ('  .mca_veto_o    (mca_veto    ),  // veto externo hacia el MCA\n',
     '  .mca_veto_o    (mca_veto    ),  // veto externo hacia el MCA\n'
     '  .event_trig_o  (ring_trig   ),  // evento conjunto hacia el event_ring\n'
     '  .event_snap_o  (ring_snap   ),\n'),

    ('sys_bus_stub sys_bus_stub_2 (sys2_ring);   // sin event_ring en este top\n', RING),
    ('//     es del ring (aca un stub; el ring vive en event_ring_red_pitaya_top) y\n',
     '//     es del ring (i_event_ring, mas abajo) y\n'),
    ('// Los puertos AXI-HP del ASG se atan para que su axi_master quede inactivo.\n'
     "assign axi2_sys.waddr = '0;  assign axi3_sys.waddr = '0;\n"
     "assign axi2_sys.wdata = '0;  assign axi3_sys.wdata = '0;\n"
     "assign axi2_sys.wsel  = '0;  assign axi3_sys.wsel  = '0;\n"
     "assign axi2_sys.wlen  = '0;  assign axi3_sys.wlen  = '0;\n"
     "assign axi2_sys.wsize = '0;  assign axi3_sys.wsize = '0;\n"
     "assign axi2_sys.wfixed= 1'b0; assign axi3_sys.wfixed= 1'b0;\n"
     "assign axi2_sys.wvalid= 1'b0; assign axi3_sys.wvalid= 1'b0;\n",
     '// HP3 era del ASG: se ata para que su axi_master quede inactivo. Las\n'
     '// escrituras de HP2 son del ring; sus lecturas no se usan.\n'
     "assign axi3_sys.waddr = '0;\n"
     "assign axi3_sys.wdata = '0;\n"
     "assign axi3_sys.wsel  = '0;\n"
     "assign axi3_sys.wlen  = '0;\n"
     "assign axi3_sys.wsize = '0;\n"
     "assign axi3_sys.wfixed= 1'b0;\n"
     "assign axi3_sys.wvalid= 1'b0;\n"),

    ('  // sin event_ring (ese vive en event_ring_red_pitaya_top)\n'
     '  .EN_OSC(1), .EN_MTRG(1), .EN_MCA(1), .EN_RING(0), .EN_ASG(0), .EN_PID(0),\n',
     '  // con el event_ring en el slot 2\n'
     '  .EN_OSC(1), .EN_MTRG(1), .EN_MCA(1), .EN_RING(1), .EN_ASG(0), .EN_PID(0),\n'),

    ('  // FASE 2: apertura de ventana por trigger externo. Este top no tiene\n'
     '  // event_ring, asi que la fuente es `scope_trigo` — que es el MISMO\n'
     '  // `event_signal` del multitrigger que alla sale por event_trig_o\n',
     '  // FASE 2: apertura de ventana por trigger externo. La fuente es\n'
     '  // `scope_trigo`, como en el top del MCA — que es el MISMO\n'
     '  // `event_signal` del multitrigger que le llega al ring por event_trig_o\n'),
]


def generar(texto):
    for ancla, nuevo in REEMPLAZOS:
        n = texto.count(ancla)
        if n != 1:
            raise SystemExit(f'gen_event_ring_top: el ancla aparece {n} veces en '
                             f'{ORIGEN.name}, no 1:\n{ancla}')
        texto = texto.replace(ancla, nuevo)
    return texto


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--check', action='store_true',
                    help='no escribe: falla si el archivo no es el generado')
    a = ap.parse_args()
    nuevo = generar(ORIGEN.read_text(encoding='utf-8'))
    if a.check:
        viejo = DESTINO.read_text(encoding='utf-8') if DESTINO.exists() else ''
        if viejo != nuevo:
            sys.exit(f'{DESTINO.name} no es el que sale de {ORIGEN.name}: '
                     f'correr {pathlib.Path(__file__).name}')
        print(f'{DESTINO.name}: al dia')
        return
    DESTINO.write_text(nuevo, encoding='utf-8')
    print(f'{DESTINO.name} generado desde {ORIGEN.name}')


if __name__ == '__main__':
    main()

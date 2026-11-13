MODULE := event_ring
TOP    := event_ring_top
# gen_eventos: el generador que event_ring_top instancia con EN_GEN = 1.
DEPS   := gen_eventos
TBS    := tb_event_window_capture \
          tb_event_stage_fifo \
          tb_event_slot_writer \
          tb_event_ring_top \
          tb_event_ring_ventana \
          tb_event_ring_gen

# El unico acople real con el software: este TB ESCRIBE el volcado que decodifica
# API/tests/test_ring_format.py. La ruta va por plusarg porque el CWD de vsim es
# esta carpeta. Asignacion con `=`: MCA_ROOT lo define module.mk mas abajo.
PLUS_tb_event_ring_top = +ring_dump=$(MCA_ROOT)/software/API/tests/datos_ref/ring_dump.hex

include ../../mk/module.mk

/* Mapa de registros del event_ring (slot 2, event_ring_top.sv).
 *
 * Es la misma informacion que las constantes R_* de API/osciloscope_ring.py, y
 * API/tests/test_ring_source.py comprueba que coincidan una por una. El mapa es
 * docs/event_ring/diseno_y_register_map.md.
 *
 * X-macro: la misma lista genera el enum y osciloscope_ring_reg_info.
 */
#ifndef OSCILOSCOPE_RING_REGS_H
#define OSCILOSCOPE_RING_REGS_H

/* X(NOMBRE, offset). SLOT_BASE, RING_SZ, SLOT_SHIFT, PRE y POST se toman solo con el
 * ring parado: escritos corriendo, se pierden y prenden err_cfg (STATUS bit 5).
 * N_SLOTS no es un registro: el RTL devuelve RING_SZ >> SLOT_SHIFT. Los GEN_* son
 * los del motor de disparos (gen_disparos.h) desde 0x100, en el mismo orden que en
 * gen_pulsos; docs/event_ring/generador.md §3. */
#define OSCILOSCOPE_RING_REGS(X)                                            \
    X(CTRL,       0x00) X(STATUS,     0x04)                                 \
    X(SLOT_BASE,  0x08) X(RING_SZ,    0x0C) X(SLOT_SHIFT, 0x10)             \
    X(PRE,        0x14) X(POST,       0x18)                                 \
    X(WR_SLOT,    0x20) X(RD_SLOT,    0x24) X(SEQ,        0x28)             \
    X(N_SLOTS,    0x2C)                                                     \
    X(DROP_BUSY,  0x30) X(DROP_FULL,  0x34) X(EV_CNT,     0x38)             \
    X(LVL,        0x3C) X(TS_LO,      0x40) X(TS_HI,      0x44)             \
    X(AXI_ADDR,   0x48) X(MAGIC,      0x50)                                 \
    /* el generador de eventos (gen_eventos.sv, EN_GEN = 1): leen 0 sin el */ \
    X(GEN_CTRL,   0x100) X(GEN_PERIODO, 0x104) X(GEN_UMBRAL, 0x108)         \
    X(GEN_DT_MIN, 0x10C) X(GEN_N,       0x110) X(GEN_SEMILLA, 0x114)        \
    X(GEN_CNT,    0x118) X(GEN_ESTADO,  0x11C) X(GEN_MAGIC,  0x120)

#define OSCILOSCOPE_RING_X_ENUM_REG(n, off) OSCILOSCOPE_RING_R_##n = off,
enum osciloscope_ring_reg { OSCILOSCOPE_RING_REGS(OSCILOSCOPE_RING_X_ENUM_REG) };
#undef OSCILOSCOPE_RING_X_ENUM_REG

#endif /* OSCILOSCOPE_RING_REGS_H */

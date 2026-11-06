/* Mapa de registros de la region de TOP (slot 6, integration_cfg.sv).
 *
 * Es la misma informacion que las constantes R_* de API/integration.py, y
 * API/tests/test_libmca_integration.py comprueba que coincidan una por una, y
 * contra los offsets que decodifica el RTL.
 *
 * Es una X-macro: la misma lista genera el enum de offsets y la tabla que se
 * exporta (integration_reg_info).
 */
#ifndef INTEGRATION_REGS_H
#define INTEGRATION_REGS_H

/* X(NOMBRE, offset). docs/TOP/register_map_top.md */
#define INTEGRATION_REGS(X)                                                 \
    /* identificacion */                                                    \
    X(MAGIC,      0x000) X(VERSION,    0x004)                               \
    X(GITH_0,     0x008) X(GITH_1,     0x00C) X(GITH_2,     0x010)          \
    X(GITH_3,     0x014) X(GITH_4,     0x018)                               \
    /* descripcion del sistema */                                           \
    X(MODULES,    0x020) X(SLOTS,      0x024)                               \
    X(CAPS_0,     0x028) X(CAPS_1,     0x02C)                               \
    /* ruteo del datapath */                                                \
    X(ROUTE_OSC,  0x030) X(ROUTE_MTRG, 0x034)                               \
    X(ROUTE_MCA,  0x038) X(ROUTE_RING, 0x03C)                               \
    /* control y estado global */                                           \
    X(CTRL,       0x040) X(STATUS,     0x044)

#define INTEGRATION_X_ENUM_REG(n, off) INTEGRATION_R_##n = off,
enum integration_reg { INTEGRATION_REGS(INTEGRATION_X_ENUM_REG) };
#undef INTEGRATION_X_ENUM_REG

#endif /* INTEGRATION_REGS_H */

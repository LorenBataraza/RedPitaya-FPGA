/* Mapa de registros de gen_pulsos (slot 2, 0x4021_0000; gen_pulsos.sv).
 *
 * Es la misma informacion que las constantes R_* de API/generadores.py, y
 * API/tests/test_libmca_generadores.py comprueba que coincidan una por una, y
 * contra el comentario de registros del RTL. El mapa es
 * docs/gen_eventos/generador_pulsos.md §4.
 *
 * X-macro: la misma lista genera el enum y gen_pulsos_reg_info.
 */
#ifndef GEN_PULSOS_REGS_H
#define GEN_PULSOS_REGS_H

/* X(NOMBRE, offset). Los seis primeros y GEN_CNT/ESTADO son los del motor de
 * disparos (gen_disparos.h), en el mismo orden que en gen_eventos. TABLA es la
 * entrada 0; la i esta en TABLA + 4 i. */
#define GEN_PULSOS_REGS(X)                                                  \
    X(CTRL,    0x0000) X(PERIODO, 0x0004) X(UMBRAL,  0x0008)                \
    X(DT_MIN,  0x000C) X(N,       0x0010) X(SEMILLA, 0x0014)                \
    X(GEN_CNT, 0x0018) X(ESTADO,  0x001C) X(MAGIC,   0x0020)                \
    X(DECAE,   0x0024) X(SUBIDA,  0x0028) X(AMP_N,   0x002C)                \
    X(BASE,    0x0030) X(RUIDO,   0x0034)                                   \
    X(TABLA,   0x1000)

#define GEN_PULSOS_X_ENUM_REG(n, off) GEN_PULSOS_R_##n = off,
enum gen_pulsos_reg { GEN_PULSOS_REGS(GEN_PULSOS_X_ENUM_REG) };
#undef GEN_PULSOS_X_ENUM_REG

#endif /* GEN_PULSOS_REGS_H */

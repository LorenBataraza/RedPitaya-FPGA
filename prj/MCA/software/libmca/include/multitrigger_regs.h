/* Mapa de registros del multitrigger (slot 3, mt_cfg.sv) y su tabla de campos.
 *
 * Es la misma informacion que las constantes R_*, R3_* y el dict _CAMPOS de
 * API/multitrigger.py, y API/tests/test_libmca_multitrigger.py comprueba que
 * coincidan una por una, y contra los offsets que decodifica el RTL.
 *
 * Las dos tablas son X-macros: la misma lista genera el enum y lo que se exporta
 * (multitrigger_reg_info, multitrigger_field_info).
 */
#ifndef MULTITRIGGER_REGS_H
#define MULTITRIGGER_REGS_H

/* X(NOMBRE, offset). docs/mt/register_map_mt.md. SLOPE_* y PZ_* son la base de
 * una familia: el canal ch esta en base + 4 * ch, como OR_MASK. TRIG_SW (0x020),
 * TRIG_DIS_CLR (0x024) y el readback de la mascara activa (0x028) existen en el RTL
 * y no figuran: la API los usa por el puente legacy del slot 1. */
#define MULTITRIGGER_REGS(X)                                                \
    /* identificacion */                                                    \
    X(MAGIC,       0x000) X(CAPS,        0x004)                             \
    /* trigger_shield, snapshot y flags */                                  \
    X(SHIELD_CFG,  0x010) X(SHIELD_RUN,  0x014)                             \
    X(TRIG_SNAP,   0x018) X(FLAGS,       0x01C)                             \
    /* mascaras OR */                                                       \
    X(OR_MASK_CH0, 0x040) X(OR_MASK_CH1, 0x044)                             \
    X(OR_MASK_CH2, 0x048) X(OR_MASK_CH3, 0x04C)                             \
    /* disparo por pendiente, + 4 * ch */                                   \
    X(SLOPE_CFG,   0x060) X(SLOPE_THR,   0x070) X(SLOPE_HYST,  0x080)       \
    /* disparo con polo-cero, + 4 * ch */                                   \
    X(PZ_CFG,      0x090) X(PZ_MQ,       0x0A0)                             \
    X(PZ_THR,      0x0B0) X(PZ_HYST,     0x0C0)

#define MULTITRIGGER_X_ENUM_REG(n, off) MULTITRIGGER_R_##n = off,
enum multitrigger_reg { MULTITRIGGER_REGS(MULTITRIGGER_X_ENUM_REG) };
#undef MULTITRIGGER_X_ENUM_REG

/* X(campo, registro, shift, mascara). El orden es el de multitrigger_get_config. */
#define MULTITRIGGER_FIELDS(X)                                              \
    X(or_mask_ch0, OR_MASK_CH0, 0,  0xFFFFFFFFu)                            \
    X(or_mask_ch1, OR_MASK_CH1, 0,  0xFFFFFFFFu)                            \
    X(shield_src,  SHIELD_CFG,  0,  0x7Fu)                                  \
    X(shield_dst,  SHIELD_CFG,  8,  0x1Fu)                                  \
    X(shield_dur,  SHIELD_CFG,  16, 0xFFFFu)

#define MULTITRIGGER_X_ENUM_CAMPO(n, reg, sh, msk) MULTITRIGGER_FIELD_##n,
enum multitrigger_field { MULTITRIGGER_FIELDS(MULTITRIGGER_X_ENUM_CAMPO) MULTITRIGGER_N_FIELDS };
#undef MULTITRIGGER_X_ENUM_CAMPO

#endif /* MULTITRIGGER_REGS_H */

/* Mapa de registros del osciloscopio (slot 1, osc_cfg.sv) y su tabla de campos.
 *
 * Es la misma informacion que las constantes R_* y el dict _CAMPOS de
 * API/osciloscope.py, y API/tests/test_libmca_osciloscope.py comprueba que coincidan
 * una por una, y contra los offsets que decodifica el RTL.
 *
 * Las dos tablas son X-macros: la misma lista genera el enum y lo que se exporta
 * (osciloscope_reg_info, osciloscope_field_info).
 */
#ifndef OSCILOSCOPE_REGS_H
#define OSCILOSCOPE_REGS_H

/* X(NOMBRE, offset). Son el mapa LEGACY, el que tambien usa librp, salvo los dos
 * CANON del final: la geometria solo esta en el mapa canonico. Sufijo _CH1: el mismo
 * registro del canal 1, que no siempre esta a la misma distancia. */
#define OSCILOSCOPE_REGS(X)                                                 \
    /* W: arm[0] rst[1] we_keep[3] indep[5] | R: adc_state */               \
    X(CMD,          0x000)                                                  \
    /* W: [3:0] == 1 dispara | R: trg_state */                              \
    X(SW_TRIG,      0x004)                                                  \
    X(THR_CH0,      0x008) X(THR_CH1,      0x00C)                           \
    X(DLY_CH0,      0x010) X(DLY_CH1,      0x110)                           \
    X(DEC_CH0,      0x014) X(DEC_CH1,      0x114)                           \
    X(WP_CUR_CH0,   0x018) X(WP_CUR_CH1,   0x118)                           \
    X(WP_TRIG_CH0,  0x01C) X(WP_TRIG_CH1,  0x11C)                           \
    X(HYST_CH0,     0x020) X(HYST_CH1,     0x024)                           \
    X(AVG_EN,       0x028)                                                  \
    X(WE_CNT_CH0,   0x02C) X(WE_CNT_CH1,   0x12C)                           \
    X(DEB_LEN,      0x090) X(TRIG_DIS_CLR, 0x094) X(FILT_BYPASS,  0x098)    \
    X(CALIB_OFF_CH0,  0x200) X(CALIB_GAIN_CH0, 0x204)                       \
    X(CALIB_OFF_CH1,  0x208) X(CALIB_GAIN_CH1, 0x20C)                       \
    /* mapa canonico: {RSZ[21:16], DW[13:8], N_CH[3:0]} */                  \
    X(CANON_MAGIC,  0x1000) X(CANON_CAPS,  0x1004)

#define OSCILOSCOPE_X_ENUM_REG(n, off) OSCILOSCOPE_R_##n = off,
enum osciloscope_reg { OSCILOSCOPE_REGS(OSCILOSCOPE_X_ENUM_REG) };
#undef OSCILOSCOPE_X_ENUM_REG

/* X(campo, registro, shift, mascara, con_signo). El orden es el de
 * osciloscope_get_config. Las mascaras salen de osc_cfg.sv, no de suponer 32 bits.
 * avg_en no es un bit por canal contiguo: el RTL lo lee como un BYTE por canal. */
#define OSCILOSCOPE_FIELDS(X)                                               \
    X(thr_ch0,        THR_CH0,        0, 0x3FFFu,     1)                    \
    X(thr_ch1,        THR_CH1,        0, 0x3FFFu,     1)                    \
    X(hyst_ch0,       HYST_CH0,       0, 0x3FFFu,     0)                    \
    X(hyst_ch1,       HYST_CH1,       0, 0x3FFFu,     0)                    \
    X(dec_ch0,        DEC_CH0,        0, 0x1FFFFu,    0)                    \
    X(dec_ch1,        DEC_CH1,        0, 0x1FFFFu,    0)                    \
    X(dly_ch0,        DLY_CH0,        0, 0xFFFFFFFFu, 0)                    \
    X(dly_ch1,        DLY_CH1,        0, 0xFFFFFFFFu, 0)                    \
    X(avg_en_ch0,     AVG_EN,         0, 0x1u,        0)                    \
    X(avg_en_ch1,     AVG_EN,         8, 0x1u,        0)                    \
    X(deb_len,        DEB_LEN,        0, 0xFFFFFu,    0)                    \
    X(filt_bypass,    FILT_BYPASS,    0, 0xFu,        0)                    \
    X(calib_off_ch0,  CALIB_OFF_CH0,  0, 0x3FFFu,     1)                    \
    X(calib_gain_ch0, CALIB_GAIN_CH0, 0, 0xFFFFu,     0)                    \
    X(calib_off_ch1,  CALIB_OFF_CH1,  0, 0x3FFFu,     1)                    \
    X(calib_gain_ch1, CALIB_GAIN_CH1, 0, 0xFFFFu,     0)

#define OSCILOSCOPE_X_ENUM_CAMPO(n, reg, sh, msk, sig) OSCILOSCOPE_FIELD_##n,
enum osciloscope_field { OSCILOSCOPE_FIELDS(OSCILOSCOPE_X_ENUM_CAMPO) OSCILOSCOPE_N_FIELDS };
#undef OSCILOSCOPE_X_ENUM_CAMPO

#endif /* OSCILOSCOPE_REGS_H */

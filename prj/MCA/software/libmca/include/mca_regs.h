/* Mapa de registros del MCA (slot 7, mca_top.sv) y la tabla de campos.
 *
 * Es el mapa "MCA2". Es la misma informacion que las constantes R_* y el
 * dict _CAMPOS de API/mca.py, y API/tests/test_libmca_mca.py comprueba que coincidan una por
 * una: la tabla de C es la que usa el hardware, la de Python es la que leen
 * los scripts, y que diverjan seria escribir un campo en el registro de otro.
 *
 * Las dos tablas son X-macros: una sola lista genera el enum de offsets, la
 * tabla que se exporta (mca_reg_info, mca_field_info) y los get/set por campo
 * de mca.h.
 */
#ifndef MCA_REGS_H
#define MCA_REGS_H

/* X(NOMBRE, offset). El mapa "MCA2" (docs/mca/register_map_mca.md): los
 * offsets que dejaron libres el Schmitt, la histeresis, maxlen, tail_dly, el
 * modo de compuerta y las politicas (0x014, 0x018, 0x028, 0x02C, 0x048, 0x104,
 * 0x108, 0x0D8/0x0DC, 0x0F0, 0x114) estan reservados y no figuran. */
#define MCA_REGS(X)                                                         \
    /* identificacion */                                                    \
    X(MAGIC,        0x000) X(CAPS,         0x004) X(WIDTHS,       0x008)    \
    /* control y estado */                                                  \
    X(CTRL,         0x00C) X(STATUS,       0x010)                           \
    /* configuracion */                                                     \
    X(BASELINE,     0x01C) X(BL_CTRL,      0x020) X(BASELINE_NOW, 0x024)    \
    X(AMP_MIN,      0x030) X(AMP_MAX,      0x034) X(AMP_SRC,      0x038)    \
    X(DEC,          0x044) X(GATE_LEN,     0x04C)                           \
    /* deprecados: se leen y escriben, pero ya no afectan al datapath */    \
    X(H_SHIFT,      0x03C) X(H2_SHIFT,     0x040)                           \
    /* selector de feature, zoom y discriminador */                         \
    X(HIST_SEL,     0x090) X(ZOOM_1D,      0x094) X(ZOOM_2DX,     0x0B8)    \
    X(ZOOM_2DY,     0x0BC) X(DISCR_CTRL,   0x098) X(DISCR_MIN,    0x09C)    \
    X(DISCR_MAX,    0x0A0)                                                  \
    /* histograma lleno */                                                  \
    X(HIST_CTRL,    0x0A4) X(HIST_STATUS,  0x0A8) X(CNT_REJ_DISCR, 0x0AC)   \
    X(CNT_FULL_SUPP, 0x0B0)                                                 \
    /* contadores de eventos */                                             \
    X(CNT_TOTAL,    0x050) X(CNT_ACCEPTED, 0x054) X(CNT_REJ_AMP,  0x058)    \
    X(CNT_REJ_PSD,  0x05C) X(CNT_PILEUP,   0x060) X(CNT_DROPPED,  0x064)    \
    /* relojes de 64 b: leer la palabra BAJA congela la ALTA */             \
    X(REALTIME_LO,  0x068) X(REALTIME_HI,  0x06C)                           \
    X(LIVETIME_LO,  0x070) X(LIVETIME_HI,  0x074)                           \
    X(DEADTIME_LO,  0x078) X(DEADTIME_HI,  0x07C)                           \
    X(VETOTIME_LO,  0x0C0) X(VETOTIME_HI,  0x0C4)                           \
    X(T_WIN_LO,     0x0C8) X(T_WIN_HI,     0x0CC)                           \
    X(T_DIV_LO,     0x0D0) X(T_DIV_HI,     0x0D4)                           \
    X(T_CLEAR_LO,   0x0FC) X(T_CLEAR_HI,   0x100)                           \
    X(T_OCUP,       0x140)              /* + 8*j: j ranuras ocupadas */      \
    /* periodo muerto y atribucion de arribos */                            \
    X(DEAD_PERIODS, 0x0E0) X(DEAD_LEN_MAX, 0x0E4) X(DEAD_EXT,     0x0E8)    \
    X(CNT_CROSS,    0x0EC) X(CNT_OPEN,     0x0B4) X(LOST_ACTIVE,  0x0F4)    \
    X(LOST_VETO,    0x0F8) X(CNT_WIN,      0x110) X(CNT_TRIG,     0x118)    \
    /* las ranuras */                                                       \
    X(PUB_STATE,    0x10C) X(N_ACC_MAX,    0x11C) X(N_ACC,        0x120)    \
    X(PRE_DLY,      0x124)                                                  \
    /* el conformado trapezoidal */                                         \
    X(TRAP_KM,      0x128) X(TRAP_MQ,      0x12C) X(TRAP_MED,     0x130)    \
    /* el banco de trapecios: la forma 0 es TRAP_KM/TRAP_MED */            \
    X(N_FORMAS,     0x134) X(TRAP_UMBR,    0x188)                           \
    X(FORMA1_KM,    0x190) X(FORMA1_MED,   0x194) X(FORMA1_UMBR,  0x198)    \
    X(FORMA2_KM,    0x1A0) X(FORMA2_MED,   0x1A4) X(FORMA2_UMBR,  0x1A8)    \
    X(FORMA3_KM,    0x1B0) X(FORMA3_MED,   0x1B4) X(FORMA3_UMBR,  0x1B8)    \
    /* ultimo evento */                                                     \
    X(LAST_AMP,     0x080) X(LAST_PSD,     0x084) X(LAST_QTOT,    0x088)    \
    X(LAST_QTAIL,   0x08C)

#define MCA_X_ENUM_REG(n, off) MCA_R_##n = off,
enum mca_reg { MCA_REGS(MCA_X_ENUM_REG) };
#undef MCA_X_ENUM_REG

#define MCA_APERTURE_H   0x10000u       /* espectro 1D */
#define MCA_APERTURE_2D  0x20000u       /* amplitud x factor de forma */

/* Los campos de configuracion, EN EL ORDEN de _CAMPOS (API/ref_py/mca2.py y
 * API/mca.py): es el orden de mca_get_config y por lo tanto el de la metadata
 * guardada.
 *
 *   X(nombre, REGISTRO, desplazamiento, mascara, tipo, setter)
 *
 *   tipo    CAMPO    el valor se enmascara: set(v) escribe v & mascara
 *           BANDERA  un bit: set(v) escribe 1 si v != 0, como el
 *                    `1 if v else 0` de Python
 *   setter  GEN      el get y el set salen de esta tabla
 *           ESP      el set esta escrito a mano en mca.c porque valida o
 *                    satura (dec, n_acc, pre_dly, trap_k, trap_mq, los
 *                    selectores, el zoom z, n_formas, forma<f>_k)
 */
#define MCA_FIELDS(X)                                                       \
    X(baseline,     BASELINE,   0,  0x3FFF,  CAMPO,   GEN)                  \
    X(bl_auto,      BL_CTRL,    0,  0x1,     BANDERA, GEN)                  \
    X(bl_k,         BL_CTRL,    4,  0xF,     CAMPO,   GEN)                  \
    X(bl_holdoff,   BL_CTRL,    16, 0xFFFF,  CAMPO,   GEN)                  \
    X(amp_min,      AMP_MIN,    0,  0xFFFF,  CAMPO,   GEN)                  \
    X(amp_max,      AMP_MAX,    0,  0xFFFF,  CAMPO,   GEN)                  \
    X(amp_src,      AMP_SRC,    0,  0x1,     BANDERA, GEN)                  \
    X(q_shift,      AMP_SRC,    8,  0x1F,    CAMPO,   GEN)                  \
    X(dec,          DEC,        0,  0xFFFF,  CAMPO,   ESP)                  \
    X(gate_short,   GATE_LEN,   0,  0xFFFF,  CAMPO,   GEN)                  \
    X(gate_long,    GATE_LEN,   16, 0xFFFF,  CAMPO,   GEN)                  \
    X(channel,      CTRL,       8,  0x1,     BANDERA, GEN)                  \
    X(n_acc,        N_ACC,      0,  0x7,     CAMPO,   ESP)                  \
    X(pre_dly,      PRE_DLY,    0,  0x7F,    CAMPO,   ESP)                  \
    X(trap_k,       TRAP_KM,    0,  0x3FF,   CAMPO,   ESP)                  \
    X(trap_m,       TRAP_KM,    16, 0x3FF,   CAMPO,   GEN)                  \
    X(trap_mq,      TRAP_MQ,    0,  0xFFFFF, CAMPO,   ESP)                  \
    X(trap_off,     TRAP_MED,   0,  0xFFFF,  CAMPO,   GEN)                  \
    X(trap_lw,      TRAP_MED,   16, 0x7,     CAMPO,   GEN)                  \
    X(trap_sh,      TRAP_MED,   24, 0x3F,    CAMPO,   GEN)                  \
    X(sel_1d,       HIST_SEL,   0,  0xF,     CAMPO,   ESP)                  \
    X(sel_2dx,      HIST_SEL,   4,  0xF,     CAMPO,   ESP)                  \
    X(sel_2dy,      HIST_SEL,   8,  0xF,     CAMPO,   ESP)                  \
    X(zoom_1d_z,    ZOOM_1D,    0,  0xF,     CAMPO,   ESP)                  \
    X(zoom_1d_k,    ZOOM_1D,    8,  0xFF,    CAMPO,   GEN)                  \
    X(zoom_2dx_z,   ZOOM_2DX,   0,  0xF,     CAMPO,   ESP)                  \
    X(zoom_2dx_k,   ZOOM_2DX,   8,  0xFF,    CAMPO,   GEN)                  \
    X(zoom_2dy_z,   ZOOM_2DY,   0,  0xF,     CAMPO,   ESP)                  \
    X(zoom_2dy_k,   ZOOM_2DY,   8,  0xFF,    CAMPO,   GEN)                  \
    X(discr_en,     DISCR_CTRL, 0,  0x1,     BANDERA, GEN)                  \
    X(discr_ext,    DISCR_CTRL, 1,  0x1,     BANDERA, GEN)                  \
    X(discr_sel,    DISCR_CTRL, 4,  0xF,     CAMPO,   ESP)                  \
    X(discr_min,    DISCR_MIN,  0,  0xFFFF,  CAMPO,   GEN)                  \
    X(discr_max,    DISCR_MAX,  0,  0xFFFF,  CAMPO,   GEN)                  \
    X(keep_if_full, HIST_CTRL,  0,  0x1,     BANDERA, GEN)                  \
    /* el banco de trapecios, al final: no corre el orden de la metadata */ \
    X(n_formas,     N_FORMAS,   0  , 0x7     , CAMPO,   ESP)  \
    X(trap_antes,   TRAP_UMBR,  0  , 0xFFFF  , CAMPO,   GEN)  \
    X(trap_despues, TRAP_UMBR,  16 , 0xFFFF  , CAMPO,   GEN)  \
    X(forma1_k,     FORMA1_KM,  0  , 0x3FF   , CAMPO,   ESP)  \
    X(forma1_m,     FORMA1_KM,  16 , 0x3FF   , CAMPO,   GEN)  \
    X(forma1_off,   FORMA1_MED, 0  , 0xFFFF  , CAMPO,   GEN)  \
    X(forma1_lw,    FORMA1_MED, 16 , 0x7     , CAMPO,   GEN)  \
    X(forma1_sh,    FORMA1_MED, 24 , 0x3F    , CAMPO,   GEN)  \
    X(forma1_antes, FORMA1_UMBR,0  , 0xFFFF  , CAMPO,   GEN)  \
    X(forma1_despues,FORMA1_UMBR,16 , 0xFFFF  , CAMPO,   GEN)  \
    X(forma2_k,     FORMA2_KM,  0  , 0x3FF   , CAMPO,   ESP)  \
    X(forma2_m,     FORMA2_KM,  16 , 0x3FF   , CAMPO,   GEN)  \
    X(forma2_off,   FORMA2_MED, 0  , 0xFFFF  , CAMPO,   GEN)  \
    X(forma2_lw,    FORMA2_MED, 16 , 0x7     , CAMPO,   GEN)  \
    X(forma2_sh,    FORMA2_MED, 24 , 0x3F    , CAMPO,   GEN)  \
    X(forma2_antes, FORMA2_UMBR,0  , 0xFFFF  , CAMPO,   GEN)  \
    X(forma2_despues,FORMA2_UMBR,16 , 0xFFFF  , CAMPO,   GEN)  \
    X(forma3_k,     FORMA3_KM,  0  , 0x3FF   , CAMPO,   ESP)  \
    X(forma3_m,     FORMA3_KM,  16 , 0x3FF   , CAMPO,   GEN)  \
    X(forma3_off,   FORMA3_MED, 0  , 0xFFFF  , CAMPO,   GEN)  \
    X(forma3_lw,    FORMA3_MED, 16 , 0x7     , CAMPO,   GEN)  \
    X(forma3_sh,    FORMA3_MED, 24 , 0x3F    , CAMPO,   GEN)  \
    X(forma3_antes, FORMA3_UMBR,0  , 0xFFFF  , CAMPO,   GEN)  \
    X(forma3_despues,FORMA3_UMBR,16 , 0xFFFF  , CAMPO,   GEN)

#define MCA_X_ENUM_CAMPO(n, reg, sh, msk, tipo, set) MCA_FIELD_##n,
enum mca_field { MCA_FIELDS(MCA_X_ENUM_CAMPO) MCA_N_FIELDS };
#undef MCA_X_ENUM_CAMPO

#endif /* MCA_REGS_H */

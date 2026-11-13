/* El analizador multicanal con ranuras, "MCA2" (slot 7 del bus de sistema,
 * base 0x4070_0000). El mapa es docs/mca/register_map_mca.md; el MCA1 ya no
 * lo habla libmca: se abre con mca_open(impl='py') desde Python.
 *
 * Es la API de API/mca.py, en C y con la forma de rp-api: cada funcion recibe
 * el handle, devuelve MCA_OK o un MCA_E*, y entrega los resultados por
 * puntero. Los nombres son los mismos que en Python, asi que
 *
 *     mca_set_n_acc(h, 4)                 # Python
 *     mca_set_n_acc(h, 4);                // C
 *
 * hacen exactamente lo mismo: la funcion de Python ES una llamada a esta.
 *
 * Cuando una funcion falla con un motivo que vale la pena explicar (una
 * configuracion invalida, una relectura que no coincide, un magic que no es el
 * del MCA), el detalle queda en mca_last_error(h). Es el texto que el binding
 * de Python pone en la excepcion.
 *
 *     mca_h *h;
 *     if (mca_open(&h, MCA_PHYS, MCA_SIZE, 1) != MCA_OK)
 *         fprintf(stderr, "%s\n", mca_last_error(NULL));
 *     mca_config_t cfg;
 *     mca_config_default(&cfg);
 *     cfg.n_acc = 4;
 *     mca_configure(h, &cfg);
 *     mca_start(h);              (el disparo lo arma el multitrigger)
 *     ...
 *     mca_close(h);
 *
 * Sin locks, igual que rp-api: un handle tiene un solo duenio. El servidor
 * (app/mca_server.py) serializa con su propio lock.
 */
#ifndef MCA_H
#define MCA_H

#include <stddef.h>
#include <stdint.h>

#include "mca_api.h"
#include "mca_bus.h"
#include "mca_regs.h"

#ifdef __cplusplus
extern "C" {
#endif

#define MCA_PHYS  0x40700000u
#define MCA_SIZE  0x30000u      /* registros + las dos aperturas */
#define MCA_MAGIC      0x4D434132u   /* "MCA2" */
#define MCA_MAGIC_MCA1 0x4D434131u   /* el mapa anterior: para el mensaje */

#define MCA_CAP_HIST_H      (1u << 0)
#define MCA_CAP_HIST_H_PSD  (1u << 1)
#define MCA_CAP_TRAP        (1u << 2)   /* conformado trapezoidal, F_TRAP */

/* cfg_n_acc es de 3 bits: a lo sumo 7 ranuras, y t_ocup tiene N_ACC + 1
 * casilleros. Los demas topes son los anchos de los registros. */
#define MCA_N_ACC_TOPE   7
#define MCA_PRE_DLY_MAX  127
#define MCA_TRAP_KL_MAX  1023
#define MCA_TRAP_MQ_MAX  0xFFFFFu
#define MCA_TRAP_LAT     8      /* la latencia de mca_trap: entra en trap_ok */
#define MCA_N_FORMAS_TOPE 4     /* el banco: el mapa tiene cuatro bloques */

#define MCA_FS_HZ 125e6         /* muestreo del ADC: los relojes cuentan esto */
#define MCA_AMP_W 16            /* ancho del bus de features */

typedef struct mca_h mca_h;

/* ---- features: los F_* de mca_pulse_feature.sv ---------------------------- */

typedef enum {
    MCA_F_PEAK = 0,             /* "pico"      amplitud de pico               */
    MCA_F_INT  = 1,             /* "integral"  Q_total >> q_shift             */
    MCA_F_PSD  = 2,             /* "psd"       Q_cola / Q_total               */
    MCA_F_INVW = 3,             /* "ancho_inv" pico / Q_total                 */
    MCA_F_LEN  = 4,             /* "largo"     muestras de la ventana         */
    MCA_F_TRISE = 5,            /* "t_subida"  muestras del disparo al pico   */
    MCA_F_DTPREV = 6,           /* "dt_anterior"  desde el disparo anterior   */
    MCA_F_DTNEXT = 7,           /* "dt_siguiente" hasta el siguiente          */
    MCA_F_SOLAPE = 8,           /* "solape"    {perdido, adentro, otras}      */
    MCA_F_TRAP  = 9,            /* "trapecio"  meseta del trapecio (CAPS b2)  */
    MCA_F_FORMA = 10,           /* "forma"     forma del banco, 0xFFFF marcado */
    MCA_N_FEATURES = 11,
} mca_feature_t;

/* Valores especiales de un selector de feature, fuera del rango de indices:
 *   MCA_F_DEFAULT      "el que corresponde" (el None de Python)
 *   MCA_F_DESCONOCIDA  un nombre que no existe: se rechaza en el MISMO punto
 *                      en que se rechazaria un indice invalido, para que una
 *                      configuracion mala deje los registros igual que en
 *                      Python. */
#define MCA_F_DEFAULT      INT32_MIN
#define MCA_F_DESCONOCIDA  (INT32_MIN + 1)

MCA_API int mca_feature_from_name(const char *nombre, int32_t *idx);
MCA_API const char *mca_feature_name(int32_t idx);     /* NULL si no existe */

/* ---- apertura ------------------------------------------------------------- */

/* Abre /dev/mem, mapea el slot y lee CAPS y WIDTHS. Con check_magic, un slot
 * que no tiene el MCA da MCA_ENOTPRESENT (sin crear handle). */
MCA_API int mca_open(mca_h **h, uint32_t phys, uint32_t size, int check_magic);

/* Lo mismo sobre un bus ya abierto (devmem o callbacks). Con `propio`, el
 * handle cierra el bus en mca_close; si no, lo cierra quien lo abrio. */
MCA_API int mca_open_bus(mca_h **h, mca_bus *bus, int propio, int check_magic);

/* Un handle con la geometria dada, SIN tocar el bus. Es el constructor de
 * Python `MCA(mem, fd, caps, h_aw, h2_aw, psd_aw)`, que no lee nada. */
MCA_API int mca_wrap(mca_h **h, mca_bus *bus, int propio, uint32_t caps,
                     uint32_t h_aw, uint32_t h2_aw, uint32_t psd_aw);

MCA_API void mca_close(mca_h *h);

/* El detalle del ultimo error de `h`. Con h == NULL, el del ultimo mca_open*
 * que fallo en este hilo (que no llego a crear handle). "" si no hay. */
MCA_API const char *mca_last_error(const mca_h *h);

/* La geometria leida al abrir (o dada a mca_wrap). Cualquiera puede ser NULL. */
MCA_API int mca_get_geometry(const mca_h *h, uint32_t *caps, uint32_t *h_aw,
                             uint32_t *h2_aw, uint32_t *psd_aw);

/* ---- acceso crudo (nivel 2, a traves del bus del handle) ------------------ */

MCA_API int mca_r32(mca_h *h, uint32_t off, uint32_t *v);
MCA_API int mca_w32(mca_h *h, uint32_t off, uint32_t v);
MCA_API int mca_read_words(mca_h *h, uint32_t off, uint32_t n, uint32_t *dst);
/* Un reloj de 64 b: LO primero, porque leerla congela HI en un registro sombra. */
MCA_API int mca_r64(mca_h *h, uint32_t off_lo, uint32_t off_hi, uint64_t *v);

/* ---- identificacion ------------------------------------------------------- */

typedef struct {
    uint32_t magic;
    int32_t  hist_h, hist_h_psd;
    uint32_t h_aw, h2_aw, psd_aw;
    uint32_t n_channels;
    uint32_t map2d_rows, map2d_cols;
    int32_t  trap;              /* CAPS bit 2 */
    uint32_t n_acc_max;         /* ranuras con que se sintetizo */
    int32_t  features;          /* tiene el bus de features: mca_tiene_features */
    uint32_t n_formas_max;      /* N_FORMAS del banco (0x134); 0: sin banco */
} mca_info_t;

MCA_API int mca_identify(mca_h *h, mca_info_t *info);

/* En el MCA2 el bus de features viene siempre: lo dice el magic. */
MCA_API int mca_tiene_features(mca_h *h, int32_t *si);
MCA_API int mca_exigir_features(mca_h *h);           /* MCA_ENOTPRESENT si no */

/* ---- control de adquisicion ----------------------------------------------- */

MCA_API int mca_start(mca_h *h);
MCA_API int mca_stop(mca_h *h);
/* Borra histogramas, contadores y relojes y espera el barrido (131 us con
 * 16384 canales). MCA_ETIMEOUT si clear_busy no baja en timeout_s. */
MCA_API int mca_clear(mca_h *h, double timeout_s);

/* ---- campos de configuracion: un get/set por campo de mca_regs.h ----------- */

#define MCA_X_GET(n, reg, sh, msk, tipo, set) \
    MCA_API int mca_get_##n(mca_h *h, uint32_t *v);
#define MCA_X_SET_GEN(n) MCA_API int mca_set_##n(mca_h *h, uint32_t v);
#define MCA_X_SET_ESP(n)
#define MCA_X_SET(n, reg, sh, msk, tipo, set) MCA_X_SET_##set(n)
MCA_FIELDS(MCA_X_GET)
MCA_FIELDS(MCA_X_SET)
#undef MCA_X_GET
#undef MCA_X_SET_GEN
#undef MCA_X_SET_ESP
#undef MCA_X_SET

/* Los que validan. Reciben int64 para rechazar un negativo igual que Python,
 * en vez de verlo como un uint32 enorme que pasaria la comparacion. Son los
 * campos que el RTL satura o envuelve en silencio. */
MCA_API int mca_set_dec(mca_h *h, int64_t v);        /* >= 1 */
MCA_API int mca_set_n_acc(mca_h *h, int64_t v);      /* 1..N_ACC (lee 0x11C) */
MCA_API int mca_set_pre_dly(mca_h *h, int64_t v);    /* 0..127 ciclos */
MCA_API int mca_set_trap_k(mca_h *h, int64_t v);     /* 1..1023 muestras */
MCA_API int mca_set_trap_mq(mca_h *h, int64_t v);    /* 0..2^20-1 (M*16) */
MCA_API int mca_set_n_formas(mca_h *h, int64_t v);   /* 1..N_FORMAS (lee 0x134) */
MCA_API int mca_set_forma1_k(mca_h *h, int64_t v);   /* 1..1023 muestras */
MCA_API int mca_set_forma2_k(mca_h *h, int64_t v);
MCA_API int mca_set_forma3_k(mca_h *h, int64_t v);
/* Satura z a AMP_W - (ancho del eje), como mca_zoom.sv, en vez de dejar que
 * el RTL lo recorte en silencio. */
MCA_API int mca_set_zoom_1d_z(mca_h *h, int64_t z);
MCA_API int mca_set_zoom_2dx_z(mca_h *h, int64_t z);
MCA_API int mca_set_zoom_2dy_z(mca_h *h, int64_t z);
/* Un indice sin productor apunta a una ranura reservada que vale cero: el
 * espectro caeria entero en el canal 0 sin error. Se rechaza (MCA_EINVAL), y
 * tambien F_TRAP en un bitstream sin el trapecio. */
MCA_API int mca_set_sel_1d(mca_h *h, int32_t f);     /* default: pico      */
MCA_API int mca_set_sel_2dx(mca_h *h, int32_t f);    /* default: pico      */
MCA_API int mca_set_sel_2dy(mca_h *h, int32_t f);    /* default: psd       */
MCA_API int mca_set_discr_sel(mca_h *h, int32_t f);  /* default: pico      */

/* La tabla, para quien quiera recorrerla (y para el test de consistencia). */

MCA_API int32_t mca_field_count(void);
MCA_API const mca_field_t *mca_field_info(int32_t i);     /* NULL fuera de rango */
MCA_API int mca_get_field(mca_h *h, int32_t i, uint32_t *v);
/* Read-modify-write generico, SIN las validaciones de los setters ESP. */
MCA_API int mca_set_field(mca_h *h, int32_t i, uint32_t v);
/* Todos los campos, en el orden de la tabla. n tiene que ser mca_field_count(). */
MCA_API int mca_get_config(mca_h *h, uint32_t *vals, int32_t n);

MCA_API int32_t mca_reg_count(void);
MCA_API const mca_reg_t *mca_reg_info(int32_t i);

/* sizeof de los structs publicos, por nombre ("mca_config_t", ...). El binding
 * de Python lo compara con los suyos al cargar: un campo agregado de un solo
 * lado haria que ctypes lea corrido sin ningun error. 0 si no existe. */
MCA_API size_t mca_sizeof(const char *tipo);

/* ---- estatus (solo lectura) ----------------------------------------------- */

MCA_API int mca_get_status(mca_h *h, uint32_t *v);
MCA_API int mca_get_running(mca_h *h, uint32_t *v);
MCA_API int mca_get_clear_busy(mca_h *h, uint32_t *v);
MCA_API int mca_get_busy(mca_h *h, uint32_t *v);          /* alguna ranura ocupada */
MCA_API int mca_get_baseline_stale(mca_h *h, uint32_t *v);
MCA_API int mca_get_vetoed(mca_h *h, uint32_t *v);
MCA_API int mca_get_puede_abrir(mca_h *h, uint32_t *v);   /* alguna libre */
MCA_API int mca_get_n_ocup(mca_h *h, uint32_t *v);        /* ranuras ocupadas */
MCA_API int mca_get_n_acc_max(mca_h *h, uint32_t *v);     /* N_ACC del RTL */
MCA_API int mca_get_trap_ok(mca_h *h, uint32_t *v);       /* la ventana de la forma 0 entra */
MCA_API int mca_get_n_formas_max(mca_h *h, uint32_t *v);  /* N_FORMAS del RTL; 0: sin banco */
/* Los umbrales de despues de las formas en uso entran en la compuerta. */
MCA_API int mca_get_umbr_ok(mca_h *h, uint32_t *v);
/* Bit f de *mascara: la ventana de la forma f entra en la compuerta; *n son las
 * formas en uso (n_formas, recortado como lo hace el RTL). Los bits de las que
 * no se usan valen cero. */
MCA_API int mca_get_formas_ok(mca_h *h, uint32_t *mascara, uint32_t *n);
MCA_API int mca_get_baseline_now(mca_h *h, int32_t *v);   /* 14 b con signo */
MCA_API int mca_get_caps(mca_h *h, uint32_t *v);          /* lee el registro */
MCA_API int mca_get_widths(mca_h *h, uint32_t *h_aw, uint32_t *h2_aw,
                           uint32_t *psd_aw);

/* ---- configuracion en bloque ---------------------------------------------- */

/* Una forma del banco de trapecios. */
typedef struct {
    int64_t k, m, off, lw, sh, antes, despues;
} mca_forma_t;

/* Los argumentos de MCA.configure(), con los mismos defaults. Los enteros son
 * int64 por la misma razon que en los setters que validan: la comparacion se
 * hace sobre el valor pedido, el enmascarado sobre lo que se escribe.
 *
 * El banco va aca y no en una funcion aparte porque configure es TODO el estado
 * y porque su validez depende de la compuerta. Los defaults son los del reset
 * del RTL: una forma en uso, sin umbrales, el MCA de un solo trapecio. La forma
 * 0 son los trap_* mas trap_antes/trap_despues; forma[f - 1], las demas. */
typedef struct {
    int64_t baseline;
    int32_t bl_auto;
    int64_t bl_k, bl_holdoff, amp_min, amp_max;
    int32_t amp_src;
    int64_t q_shift, dec;
    int32_t channel;
    int64_t gate_short, gate_long, n_acc, pre_dly;
    int64_t trap_k, trap_m, trap_mq, trap_off, trap_lw, trap_sh;
    int32_t verify;
    int32_t sel_1d, sel_2dx, sel_2dy;           /* MCA_F_DEFAULT o un indice */
    int64_t zoom_1d_z, zoom_1d_k, zoom_2dx_z, zoom_2dx_k, zoom_2dy_z, zoom_2dy_k;
    int32_t discr_en;                           /* 0 = discr=None: apagado   */
    int32_t discr_sel;
    int64_t discr_min, discr_max;
    int32_t discr_ext;
    int32_t keep_if_full;
    int64_t n_formas;
    int64_t trap_antes, trap_despues;
    mca_forma_t forma[MCA_N_FORMAS_TOPE - 1];
} mca_config_t;

MCA_API void mca_config_default(mca_config_t *c);

/* Valida TODO antes de escribir (MCA_EINVAL y nada escrito), para el MCA
 * (run=0) y escribe el bloque en el orden de MCA.configure(); con verify
 * relee ocho campos (MCA_EVERIFY si no coinciden).
 *
 * Del banco valida lo que el RTL haria en silencio: n_formas en 1..N_FORMAS; k
 * en 1..1023 y k + m <= 1023; en cada forma en uso, que la ventana entre en la
 * compuerta (lo que despues leeria trap_ok), que `despues` tambien (umbr_ok) y
 * que tenga la misma ganancia que la forma 0, k / 2^sh, o el pico se parte. La
 * ventana solo se exige si se la usa: varias formas, o un eje o el
 * discriminador en F_TRAP o F_FORMA. */
MCA_API int mca_configure(mca_h *h, const mca_config_t *c);

/* ---- lectura ---------------------------------------------------------------- */

/* El dict de MCA.counters(), en el mismo orden de claves (t_ocup_s va al final,
 * con n_t_ocup = N_ACC + 1 casilleros validos), mas los relojes crudos en
 * ciclos. Ver la docstring de counters() en API/ref_py/mca2.py. */
typedef struct {
    uint32_t total, accepted, rej_amp, rej_psd, pileup, dropped;
    uint32_t rej_discr, full_supp;
    double   realtime_s, livetime_s, deadtime_s, vetotime_s;
    double   t_win_s, t_div_s, t_rearm_s, t_clear_s, deadtime_real_s;
    uint32_t dead_periods;
    double   dead_len_max_s, dead_len_mean_s;
    uint32_t dead_ext;
    double   dead_ext_frac;
    uint32_t cross, open, lost_active, lost_veto, windows, trig_edges;
    uint32_t pub_occ, pub_occ_max, last_win_id, n_acc, n_acc_max;
    int32_t  pub_saturada;
    int32_t  clear_busy, busy, baseline_stale, vetoed, rearm_pend, puede_abrir;
    uint32_t n_ocup;
    int32_t  full_1d, full_2d, trap_ok;
    double   t_ocup_s[MCA_N_ACC_TOPE + 1];
    int32_t  n_t_ocup;
    /* crudos */
    uint64_t realtime, livetime, deadtime, vetotime;
    uint64_t t_win, t_div, t_rearm, t_clear;
    uint64_t t_ocup[MCA_N_ACC_TOPE + 1];
} mca_counters_t;

MCA_API int mca_read_counters(mca_h *h, mca_counters_t *c);

/* n tiene que ser 2^h_aw (y 2^(h2_aw + psd_aw) en el mapa): un buffer de otro
 * tamanio es casi siempre un handle con la geometria de otro bitstream. */
MCA_API int mca_read_histogram(mca_h *h, uint32_t *dst, uint32_t n);
MCA_API int mca_read_map2d(mca_h *h, uint32_t *dst, uint32_t n);   /* MCA_ENOSYS sin 2D */

typedef struct {
    uint32_t amp, psd, q_tot, q_tail;
    int32_t  baseline;
} mca_last_event_t;

MCA_API int mca_read_last_event(mca_h *h, mca_last_event_t *ev);

/* Adquisicion temporizada: [stop, clear,] start, dormir, stop, espera a que se
 * vacien las ranuras (busy, hasta 10 ms) y despues lee mapa, espectro y
 * contadores. El disparo lo arma el multitrigger: sin el no abre ninguna
 * ventana. Cualquiera de los tres buffers puede ser NULL
 * para no leerlo (el mapa se saltea solo si el bitstream no tiene 2D). La
 * espera ocurre aca adentro: desde Python, con el GIL suelto. */
MCA_API int mca_read_acquire(mca_h *h, double seconds, int clear_first,
                             uint32_t *hist, uint32_t n_hist,
                             uint32_t *m2d, uint32_t n_m2d,
                             mca_counters_t *cnt);

/* `seconds` en el MISMO histograma, en n = round(seconds / chunk_s) rebanadas.
 * Entre rebanadas, con el MCA parado, llama a on_chunk(ctx, k); si devuelve
 * algo distinto de 0, se corta con MCA_EBACKEND. */
typedef int (*mca_chunk_fn)(void *ctx, int32_t k);

MCA_API int mca_read_acquire_chunks(mca_h *h, double seconds, double chunk_s,
                                    mca_chunk_fn on_chunk, void *ctx,
                                    uint32_t *hist, uint32_t n_hist,
                                    uint32_t *m2d, uint32_t n_m2d,
                                    mca_counters_t *cnt);

/* Adquiere `seconds` y despeja q_shift del ultimo evento. *shift queda en -1
 * si no hubo eventos (el None de Python). */
MCA_API int mca_autoscale_q_shift(mca_h *h, double target_channel,
                                  double seconds, int32_t *shift);

#ifdef __cplusplus
}
#endif

#endif /* MCA_H */

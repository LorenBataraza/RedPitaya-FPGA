/* El osciloscopio clasico: umbral, decimacion, delay, histeresis, filtros,
 * calibracion, punteros de escritura y la lectura de la BRAM (slot 1, base
 * 0x4010_0000; integration_get_base da la del bitstream cargado). El mapa esta en
 * modulos/osc/rtl/osc_cfg.sv.
 *
 * Es la API de los metodos de Osciloscope y de las funciones osciloscope_* de
 * API/osciloscope.py, en C y con la forma de mca.h: un solo handle sobre la region, y
 * cada funcion devuelve MCA_OK o un MCA_E*, con los resultados por puntero y el
 * detalle del error en osciloscope_last_error.
 *
 *     osciloscope_h *osc;
 *     if (osciloscope_open(&osc, OSCILOSCOPE_PHYS, 0) != MCA_OK)
 *         fprintf(stderr, "%s\n", osciloscope_last_error(NULL));
 *     osciloscope_set_decim(osc, 8, OSCILOSCOPE_AMBOS);
 *     osciloscope_close(osc);
 *
 * Los volts son la escala fija LV, 8192 cuentas por volt, sin la calibracion de la
 * EEPROM: es lo que el umbral guarda y lo que hacia la API de Python.
 *
 * Lo que queda en Python, y por que: comprobar que la PL este programada antes de
 * abrir (sysfs, API/fpga.py); verify_bitstream y los debug_*, que se componen sobre
 * r32; lo que cruza con el multitrigger, cuyo orden importa
 * (docs/osc/orden_arm_trigger_captura.md); y la captura por librp hasta que el lazo
 * por evento pase a C. Sin locks, igual que mca.h.
 */
#ifndef OSCILOSCOPE_H
#define OSCILOSCOPE_H

#include <stddef.h>
#include <stdint.h>

#include "mca_api.h"
#include "mca_bus.h"
#include "osciloscope_regs.h"

#ifdef __cplusplus
extern "C" {
#endif

#define OSCILOSCOPE_PHYS       0x40100000u
#define OSCILOSCOPE_MAGIC      0x4F534331u  /* "OSC1"; los bitstreams viejos no lo tienen */
#define OSCILOSCOPE_CNT_PER_V  8192
#define OSCILOSCOPE_RSZ_DEFECTO  14
#define OSCILOSCOPE_N_CH_DEFECTO 2
#define OSCILOSCOPE_DW_DEFECTO   14
#define OSCILOSCOPE_APERTURA_0    0x10000u  /* la BRAM del canal 0 */
#define OSCILOSCOPE_APERTURA_PASO 0x10000u  /* fijo: lo decide sys_addr[19:16] */
#define OSCILOSCOPE_N_APERTURAS   4

/* Como `ch` de los set: escribe los dos canales, el 0 primero. */
#define OSCILOSCOPE_AMBOS INT64_MIN

typedef struct osciloscope_h osciloscope_h;

/* ---- los tipos que cruzan la interfaz ------------------------------------- */

/* La geometria del bitstream. `descubierta` es 0 si el bitstream no publica el mapa
 * canonico: entonces son los valores por defecto, no un dato leido. `size` llega hasta
 * el final de la apertura del ultimo canal, y `aperturas` tiene n_ch validas. */
typedef struct {
    uint32_t rsz, n_ch, dw, n_buf, size;
    int32_t  descubierta;
    uint32_t aperturas[OSCILOSCOPE_N_APERTURAS];
} osciloscope_geometria_t;

typedef struct { uint32_t offset, gain; } osciloscope_calib_t;

/* Lo que se refresca en pantalla: estado de las FSM y punteros. */
typedef struct {
    uint32_t adc_state, trg_state;
    uint32_t wp_cur_ch0, wp_cur_ch1;
    uint32_t wp_trig_ch0, wp_trig_ch1;
    uint32_t we_cnt_ch0, we_cnt_ch1;
} osciloscope_status_t;

/* ---- ciclo de vida -------------------------------------------------------- */

/* Mapea `size` bytes de `phys`. Con size = 0 los descubre: mapea una sonda, lee la
 * geometria del mapa canonico y re-mapea lo que hace falta. Con 4 canales el valor
 * historico de 0x30000 deja dos aperturas afuera. No lee el magic: un bitstream sin
 * mapa canonico abre igual, con la geometria por defecto. */
MCA_API int osciloscope_open(osciloscope_h **h, uint32_t phys, uint32_t size);

/* Lo mismo sobre un fichero comun en vez de /dev/mem, como mca_bus_open_file: sirve
 * para probar en la PC la sonda y el mapeo, sin la placa. */
MCA_API int osciloscope_open_file(osciloscope_h **h, const char *path, uint32_t phys,
                                  uint32_t size);

/* Sobre un bus ya abierto. No lee nada. Con `propio`, el close cierra el bus. */
MCA_API int osciloscope_open_bus(osciloscope_h **h, mca_bus *bus, int propio);

MCA_API void osciloscope_close(osciloscope_h *h);

/* El detalle del ultimo error; con NULL, el de la ultima apertura de este hilo. */
MCA_API const char *osciloscope_last_error(const osciloscope_h *h);

/* ---- tablas --------------------------------------------------------------- */

MCA_API int32_t osciloscope_reg_count(void);
MCA_API const mca_reg_t *osciloscope_reg_info(int32_t i);
MCA_API int32_t osciloscope_field_count(void);
/* `bandera` es 1 si el campo tiene signo: complemento a dos sobre su mascara. */
MCA_API const mca_field_t *osciloscope_field_info(int32_t i);
MCA_API size_t osciloscope_sizeof(const char *tipo);

/* ---- acceso crudo --------------------------------------------------------- */

MCA_API int osciloscope_r32(osciloscope_h *h, uint32_t off, uint32_t *v);
MCA_API int osciloscope_w32(osciloscope_h *h, uint32_t off, uint32_t v);

/* ---- geometria ------------------------------------------------------------ */

/* La cuenta, para un (rsz, n_ch) dados. MCA_EINVAL fuera de rango. */
MCA_API int osciloscope_geometria_de(int64_t rsz, int64_t n_ch, osciloscope_geometria_t *g);

/* La del bitstream cargado. Se lee una vez y queda guardada en el handle. */
MCA_API int osciloscope_get_geometria(osciloscope_h *h, osciloscope_geometria_t *g);

/* ---- configuracion por canal ---------------------------------------------- */

/* `ch` es 0 o 1: el mapa legacy tiene dos. Los set aceptan ademas OSCILOSCOPE_AMBOS,
 * y un canal invalido no escribe nada. Un set de thr o de histeresis no recorta: los
 * bits de mas se pierden, como en el RTL. Un no-finito es MCA_EINVAL. */
MCA_API int osciloscope_get_thr(osciloscope_h *h, int64_t ch, double *volts);
MCA_API int osciloscope_set_thr(osciloscope_h *h, double volts, int64_t ch);
MCA_API int osciloscope_get_decim(osciloscope_h *h, int64_t ch, uint32_t *v);
/* Solo 1, 8, 64, 1024, 8192 y 65536. */
MCA_API int osciloscope_set_decim(osciloscope_h *h, int64_t v, int64_t ch);
MCA_API int osciloscope_get_delay(osciloscope_h *h, int64_t ch, uint32_t *v);
/* En crudo. Es tiempo muerto real: mientras corre, adc_dly_do no deja actualizar
 * adc_wp_trig (rp_bram_sm.v:91). */
MCA_API int osciloscope_set_delay(osciloscope_h *h, uint32_t v, int64_t ch);
MCA_API int osciloscope_get_hysteresis(osciloscope_h *h, int64_t ch, double *volts);
/* Toma el modulo, y nunca escribe 0. */
MCA_API int osciloscope_set_hysteresis(osciloscope_h *h, double volts, int64_t ch);
MCA_API int osciloscope_get_calibration(osciloscope_h *h, int64_t ch, osciloscope_calib_t *c);
MCA_API int osciloscope_set_calib_offset(osciloscope_h *h, int64_t ch, uint32_t v);
MCA_API int osciloscope_set_calib_gain(osciloscope_h *h, int64_t ch, uint32_t v);

/* ---- configuracion global ------------------------------------------------- */

/* Solo el canal 0: ver avg_en_ch1 en la tabla de campos. */
MCA_API int osciloscope_get_avg(osciloscope_h *h, int32_t *en);
MCA_API int osciloscope_set_avg(osciloscope_h *h, int32_t en);
MCA_API int osciloscope_get_deb_len(osciloscope_h *h, uint32_t *v);
MCA_API int osciloscope_set_deb_len(osciloscope_h *h, uint32_t v);
MCA_API int osciloscope_get_filter_bypass(osciloscope_h *h, uint32_t *v);
MCA_API int osciloscope_set_filter_bypass(osciloscope_h *h, uint32_t v);

/* ---- configuracion en bloque ---------------------------------------------- */

/* Todos los campos, en el orden de la tabla y con su signo. `n` es
 * OSCILOSCOPE_N_FIELDS. En cuentas: la conversion a volts depende del jumper. */
MCA_API int osciloscope_get_config(osciloscope_h *h, int64_t *vals, int32_t n);

/* n campos por indice. Lee y escribe una vez por registro, para que los que comparten
 * palabra no se pisen, en el orden en que aparece cada registro. Sin relectura, como la
 * referencia. Un indice fuera de tabla no escribe nada. */
MCA_API int osciloscope_configure(osciloscope_h *h, const int32_t *campos,
                                  const uint32_t *valores, int32_t n);

/* ---- estado (solo lectura, sin efectos) ------------------------------------ */

MCA_API int osciloscope_get_adc_state(osciloscope_h *h, uint32_t *v);
MCA_API int osciloscope_get_trg_state(osciloscope_h *h, uint32_t *v);
MCA_API int osciloscope_get_wp_cur(osciloscope_h *h, int64_t ch, uint32_t *v);
MCA_API int osciloscope_get_wp_trig(osciloscope_h *h, int64_t ch, uint32_t *v);
MCA_API int osciloscope_get_we_cnt(osciloscope_h *h, int64_t ch, uint32_t *v);
MCA_API int osciloscope_get_status(osciloscope_h *h, osciloscope_status_t *st);

/* ---- comandos -------------------------------------------------------------- */

/* Reset de la FSM de los dos canales y desbloqueo de adc_trg_dis. */
MCA_API int osciloscope_reset(osciloscope_h *h);
MCA_API int osciloscope_sw_trigger(osciloscope_h *h);

/* Reset, desbloqueo, decimacion, umbral y delay de los dos canales, en ese orden. Un
 * decim ilegal o un umbral no finito no escriben nada. */
MCA_API int osciloscope_acq_base(osciloscope_h *h, double thr_volts, uint32_t delay,
                                 int64_t decim);

/* ---- la BRAM ---------------------------------------------------------------- */

/* n muestras del canal `ch` desde la posicion `start`, en cuentas con el signo
 * extendido y sin calibrar. De a una palabra: una rafaga sobre esta memoria reinicia
 * la placa (docs/TOP/bus_sistema_redpitaya.md §7.3).
 *
 * `start` se reduce al anillo y la ventana da la vuelta: wp - pre se puede pasar tal
 * cual. El largo del anillo es el del bitstream. Pedir mas que eso es MCA_EINVAL, y
 * no un error de bus: la apertura aliasea y devolveria el buffer repetido sin avisar.
 * En single-shot la lectura tiene sentido con el buffer congelado. */
MCA_API int osciloscope_read_bram(osciloscope_h *h, int64_t ch, int64_t start, int64_t n,
                                  int16_t *dst);

#ifdef __cplusplus
}
#endif

#endif /* OSCILOSCOPE_H */

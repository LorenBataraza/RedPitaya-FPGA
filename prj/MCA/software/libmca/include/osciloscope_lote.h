/* El lazo por evento del osciloscopio, en C: lo que hacia `BramSource` desde Python,
 * evento por evento, y la calibracion de librp para dejar de depender de `rp`.
 *
 * Es la vuelta (a) de docs/API/figuras/maquinas_estados.svg. Por cada evento:
 *
 *   esperar   single-shot: adc_we == 0 (bit 0 de 0x000), el buffer congelado.
 *             Continuo: un cambio de wp_trig.
 *   anotar    t_ns (CLOCK_MONOTONIC, el reloj de time.perf_counter_ns), wp_trig, el
 *             snapshot del multitrigger y los descartados desde el evento anterior.
 *   leer      la ventana [wp - pre, wp + post) de cada canal, calibrada.
 *   re-armar  0x000 = 0x101 en el osciloscopio y RECIEN DESPUES las dos mascaras del
 *             multitrigger. Al reves, un flanco que llegue en el medio gasta la mascara
 *             con la FSM sin armar (docs/osc/orden_arm_trigger_captura.md).
 *
 * Mientras corre no hace falta el GIL: ctypes lo suelta durante la llamada, y el
 * escritor de Python usa el otro nucleo. Vuelve al llenar el lote o al vencer el plazo,
 * para que quien llama pueda parar.
 *
 * Sin lote (`lote` NULL) cuenta el evento como descartado y re-arma sin leer: es lo que
 * hacia el lector de Python cuando no habia un batch libre. Los descartados van al
 * `gap` del proximo evento que se guarde, y su total exacto a `asignados`.
 */
#ifndef OSCILOSCOPE_LOTE_H
#define OSCILOSCOPE_LOTE_H

#include <stdint.h>

#include "mca_api.h"
#include "multitrigger.h"
#include "osciloscope.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ---- la calibracion del ADC ------------------------------------------------ */

/* La de librp para un canal (cmn_CalibCntsSigned, rp-api 2.00): con s la cuenta del ADC
 * con el signo extendido,
 *
 *     m = gain * (s - offset) / base        division entera: trunca hacia cero
 *
 * recortada a [-2^(dw-1), 2^(dw-1)]. Los tres numeros salen de la EEPROM, por
 * rp_CalibGetFastADCCalibValueI en LV y DC. gain = base y offset = 0 es sin calibrar.
 *
 * En LV la escala es 1 V: m / 8192 es exactamente el float que devuelve
 * rp_AcqGetDataPosV, y m es lo que antes se guardaba como rint(V * 8192). */
typedef struct {
    uint32_t gain, base;
    int32_t  offset;
} osciloscope_adc_cal_t;

/* n palabras crudas de la BRAM (se usan los dw bits bajos) a cuentas calibradas.
 * MCA_EINVAL si la calibracion desborda los 32 bits de la cuenta de librp. */
MCA_API int osciloscope_calibrar(const osciloscope_adc_cal_t *cal, int64_t dw,
                                 const uint32_t *crudo, int16_t *dst, int64_t n);

/* osciloscope_read_bram, calibrada: las mismas reglas de canal, anillo y largo. */
MCA_API int osciloscope_read_cal(osciloscope_h *h, int64_t ch, int64_t start, int64_t n,
                                 const osciloscope_adc_cal_t *cal, int16_t *dst);

/* ---- el lazo ----------------------------------------------------------------- */

typedef struct {
    uint32_t pre, post;     /* muestras antes de wp_trig y desde wp_trig */
    uint32_t n_ch;          /* canales que se leen, desde el 0. 0: sin ventana */
    uint32_t mascara;       /* lo que el re-armado escribe en OR_MASK_CH0 y CH1 */
    uint32_t wp_off;        /* OSCILOSCOPE_R_WP_TRIG_CH0 o _CH1 */
    int32_t  single_shot;   /* 1: espera adc_we == 0. 0: un cambio de wp_trig */
    int32_t  rearmar;       /* 0: no re-arma (capture_n_events, con we_keep) */
    int32_t  leer_snap;     /* 0: snap = 0, sin leer el registro */
    osciloscope_adc_cal_t cal[OSCILOSCOPE_N_APERTURAS];   /* n_ch validas */
} osciloscope_lote_cfg_t;

/* Lo que sigue de una llamada a la otra. Lo inicializa osciloscope_lote_iniciar. */
typedef struct {
    uint64_t pendientes;    /* descartados desde el ultimo evento guardado */
    uint32_t wp_prev;       /* continuo: el ultimo wp_trig visto */
    uint32_t reservado;
} osciloscope_lote_estado_t;

/* Las columnas, cada una desde la fila donde empieza a escribir. NULL no guarda esa
 * columna; con wave NULL tampoco se lee la ventana. wave es (n_max, n_ch, pre + post). */
typedef struct {
    int16_t  *wave;
    int64_t  *t_ns;
    int32_t  *wp;
    uint32_t *snap;
    uint8_t  *gap;          /* satura en 255: el total exacto va a `asignados` */
    int64_t  *dead_ns;      /* del disparo visto al re-armado: el tiempo ciego */
} osciloscope_lote_t;

typedef struct {
    uint32_t n;             /* eventos guardados */
    uint32_t reservado;
    uint64_t descartados;   /* eventos vistos sin lote */
    uint64_t asignados;     /* descartados que fueron al gap de los guardados */
} osciloscope_lote_resultado_t;

/* Valida la configuracion y deja el estado listo: sin pendientes, y wp_prev con el
 * wp_trig de ahora. Se llama despues de armar. */
MCA_API int osciloscope_lote_iniciar(osciloscope_h *osc, const osciloscope_lote_cfg_t *cfg,
                                     osciloscope_lote_estado_t *st);

/* Hasta n_max eventos (o descartados, sin lote), o hasta que pase plazo_ns, en el reloj
 * de CLOCK_MONOTONIC. `mt` puede ser NULL si no se re-arma ni se lee el snapshot. Si
 * algo falla a mitad de camino, `res` cuenta lo que ya quedo escrito. */
MCA_API int osciloscope_leer_lote(osciloscope_h *osc, multitrigger_h *mt,
                                  const osciloscope_lote_cfg_t *cfg,
                                  osciloscope_lote_estado_t *st,
                                  const osciloscope_lote_t *lote, uint32_t n_max,
                                  int64_t plazo_ns, osciloscope_lote_resultado_t *res);

/* El reloj del lazo, para que quien llama arme el plazo: el de time.perf_counter_ns. */
MCA_API int64_t osciloscope_ahora_ns(void);

#ifdef __cplusplus
}
#endif

#endif /* OSCILOSCOPE_LOTE_H */

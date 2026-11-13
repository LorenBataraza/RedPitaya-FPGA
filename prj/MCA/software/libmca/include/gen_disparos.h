/* El motor de disparos que comparten los dos generadores de prueba de la PL:
 *
 *   gen_pulsos   en el lugar del ASG (slot 2, 0x4021_0000): pulsos para el
 *                multitrigger y el MCA. Ver gen_pulsos.h.
 *   gen_eventos  dentro del event_ring (0x4020_0100): disparos y un dato conocido
 *                para medir el ring. Ver osciloscope_ring_gen_* en osciloscope_ring.h.
 *
 * Los dos instancian gen_disparos.sv, con los mismos seis registros en el mismo
 * orden (CTRL, PERIODO, UMBRAL, DT_MIN, N, SEMILLA), y los mismos dos de lectura
 * (GEN_CNT, ESTADO). Los docs son docs/gen_eventos/generador_pulsos.md y
 * docs/event_ring/generador.md.
 *
 * Decide en cada ciclo de adc_clk (125 MHz) si dispara:
 *
 *   periodico   uno cada `periodo` ciclos
 *   aleatorio   con probabilidad umbral / 2^32 por ciclo, y despues espera
 *               dt_min - 1 ciclos: un Poisson discreto con tiempo muerto no
 *               paralizable, de intervalo medio (dt_min - 1) + 2^32 / umbral
 *
 * hasta `n` disparos (0 = sin fin). Todo el estado se reinicia al arrancar, y con
 * la misma semilla los disparos caen siempre en el mismo ciclo:
 * gen_disparos_predecir los da, igual que `disparos` del modelo de Python
 * (modulos/gen_eventos/modelos/python_model/gen_eventos_model.py).
 *
 * Lo de este header no toca el hardware: son los tipos y las cuentas.
 */
#ifndef GEN_DISPAROS_H
#define GEN_DISPAROS_H

#include <stddef.h>
#include <stdint.h>

#include "mca_api.h"

#ifdef __cplusplus
extern "C" {
#endif

#define GEN_FS_HZ        125e6          /* adc_clk: un ciclo por muestra */
#define GEN_SEMILLA_0    0x2545F491u    /* la que usa el RTL con SEMILLA = 0 */
#define GEN_PERIODO_MIN  2u             /* la captura toma el disparo por flanco */
#define GEN_DT_MIN_MIN   2u
#define GEN_DT_MIN_MAX   0xFFFFu        /* DT_MIN tiene 16 bits */

/* Los bits de ESTADO, iguales en los dos generadores. */
#define GEN_ST_GENERANDO (1u << 0)
#define GEN_ST_TERMINADO (1u << 1)      /* llego a N */
#define GEN_ST_DESBORDE  (1u << 2)      /* solo gen_pulsos: y1 se desbordo */

/* Los registros del motor, en el orden del RTL. `aleatorio` es 0 o 1. Con
 * aleatorio = 0 no se mira ni umbral ni dt_min, y con 1 no se mira periodo, pero
 * se escriben igual. */
typedef struct {
    uint32_t aleatorio;
    uint32_t periodo;           /* ciclos entre disparos, >= 2 */
    uint32_t umbral;            /* probabilidad por ciclo * 2^32, > 0 */
    uint32_t dt_min;            /* ciclos minimos entre disparos, 2..65535 */
    uint32_t n;                 /* cuantos; 0 = sin fin */
    uint32_t semilla;           /* del xorshift32; 0 = GEN_SEMILLA_0 */
} gen_disparos_cfg_t;

/* Lo que se lee de los dos generadores. Los disparos que salen se cuentan desde el
 * arranque, y el contador no se borra al parar. */
typedef struct {
    uint32_t gen_cnt;           /* GEN_CNT */
    uint32_t estado;            /* ESTADO crudo */
    int32_t  generando;         /* ESTADO[0] */
    int32_t  terminado;         /* ESTADO[1]: llego a N */
    int32_t  desborde;          /* ESTADO[2], solo gen_pulsos: la traza no sirve */
} gen_estado_t;

/* El reset del RTL: periodico de 1000 ciclos (125 kHz), sin fin. */
MCA_API void gen_disparos_default(gen_disparos_cfg_t *c);

/* MCA_EINVAL si lo que se pide no es lo que hace el RTL: un periodo de menos de 2,
 * un dt_min fuera de 2..65535 o un umbral 0 (no dispararia nunca), en el modo que
 * se usa. El detalle va a gen_disparos_last_error(). */
MCA_API int gen_disparos_validar(const gen_disparos_cfg_t *c);

/* El detalle del ultimo error de las funciones de este header (por hilo). */
MCA_API const char *gen_disparos_last_error(void);

/* El umbral que da `tasa_hz` disparos por segundo en el modo aleatorio con ese
 * dt_min (el que se usa: los menores de 2 valen 2). Es `umbral_para` del modelo,
 * con el mismo redondeo. MCA_ERANGE si la tasa no se alcanza con ese dt_min. */
MCA_API int gen_disparos_umbral_para(double tasa_hz, uint32_t dt_min, uint32_t *umbral);

/* El periodo mas cercano a `tasa_hz` en el modo periodico (redondeado). MCA_ERANGE
 * si da menos de 2 o mas de 2^32 - 1 ciclos. */
MCA_API int gen_disparos_periodo_para(double tasa_hz, uint32_t *periodo);

/* La tasa media que da una configuracion, en Hz: fs / periodo, o
 * fs / ((dt_min - 1) + 2^32 / umbral). */
MCA_API int gen_disparos_tasa(const gen_disparos_cfg_t *c, double *tasa_hz);

/* Los ciclos en que cae cada disparo decidido en los primeros `n_ciclos` desde el
 * arranque, hasta `n_max` (o los `n` de la configuracion, si son menos). Cada uno es
 * el ciclo de la decision mas `lat`, asi que el ultimo puede caer en n_ciclos o
 * despues:
 *
 *   gen_pulsos    lat = GEN_PULSOS_LAT_TRIG (1): el ciclo de trig_o, el `trig`
 *                 de `traza` del modelo
 *   gen_eventos   lat = OSCILOSCOPE_RING_GEN_LAT_TS (2): la marca del slot del
 *                 ring (w0), lo que da `disparos` del modelo
 *
 * `*n` son los que se escribieron en `t`. */
MCA_API int gen_disparos_predecir(const gen_disparos_cfg_t *c, uint64_t n_ciclos,
                                  uint32_t lat, uint64_t *t, uint32_t n_max,
                                  uint32_t *n);

MCA_API size_t gen_disparos_sizeof(const char *tipo);

#ifdef __cplusplus
}
#endif

#endif /* GEN_DISPAROS_H */

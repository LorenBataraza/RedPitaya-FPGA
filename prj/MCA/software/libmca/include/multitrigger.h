/* El multitrigger: mascaras OR, trigger_shield, snapshot de fuentes y los dos
 * disparos propios, por pendiente y con polo-cero (slot 3 del top del MCA, base
 * 0x4030_0000; en el red_pitaya_top clasico esta en el 7: integration_get_base da
 * la del bitstream cargado). El mapa es docs/mt/register_map_mt.md.
 *
 * Es la API de los metodos de MultiTrigger y MtRegion de API/multitrigger.py, en C
 * y con la forma de mca.h: un solo handle sobre la region, y cada funcion devuelve
 * MCA_OK o un MCA_E*, con los resultados por puntero y el detalle del error en
 * multitrigger_last_error. Las dos fachadas de Python difieren en la firma, no en
 * los registros.
 *
 *     multitrigger_h *mt;
 *     if (multitrigger_open(&mt, MULTITRIGGER_PHYS, MULTITRIGGER_SIZE, 1) != MCA_OK)
 *         fprintf(stderr, "%s\n", multitrigger_last_error(NULL));
 *     multitrigger_set_slope(mt, 0, 8, 4, 600, 300, 1);
 *     multitrigger_close(mt);
 *
 * Lo que cruza con el osciloscopio (multitrigger_arm, multitrigger_armar_mca) se
 * compone en Python: arm y we_keep son registros del slot 1, y el orden importa
 * (docs/osc/orden_arm_trigger_captura.md). Sin locks, igual que mca.h.
 */
#ifndef MULTITRIGGER_H
#define MULTITRIGGER_H

#include <stddef.h>
#include <stdint.h>

#include "mca_api.h"
#include "mca_bus.h"
#include "multitrigger_regs.h"

#ifdef __cplusplus
extern "C" {
#endif

#define MULTITRIGGER_PHYS  0x40300000u
#define MULTITRIGGER_SIZE  0x1000u
#define MULTITRIGGER_MAGIC 0x4D545247u  /* "MTRG" */
#define MULTITRIGGER_N_CH  4

#define MULTITRIGGER_CAPS_HAS_SLOPE (1u << 16)
#define MULTITRIGGER_CAPS_HAS_PZ    (1u << 17)

/* Los rangos de mt_slope_trig y mt_pz_trig con los parametros del top. */
#define MULTITRIGGER_SLOPE_LMAX 16
#define MULTITRIGGER_SLOPE_GMAX 31
#define MULTITRIGGER_SLOPE_TMAX 0x3FFFF
#define MULTITRIGGER_PZ_LMAX    31      /* k + m: las lineas tienen 32 muestras */
#define MULTITRIGGER_PZ_MQMAX   0xFFFFF
#define MULTITRIGGER_PZ_SHMAX   63
#define MULTITRIGGER_PZ_TMAX    0x3FFFF

typedef struct multitrigger_h multitrigger_h;

/* ---- los tipos que cruzan la interfaz ------------------------------------- */

/* src y dst son mascaras: los 4 bits bajos, los canales del scope. runtime es
 * SHIELD_RUN: {mca_veto[17], active[16], cnt[15:0]}. */
typedef struct { uint32_t dur, dst, src, runtime; } multitrigger_shield_t;

typedef struct { int32_t en; uint32_t L, G, thr, hyst; } multitrigger_slope_t;

typedef struct { int32_t en; uint32_t k, m, sh, mq, thr, hyst; } multitrigger_pz_t;

typedef struct {
    uint32_t snapshot, flags, shield_runtime;
    int32_t  shield_active, mca_veto;
} multitrigger_status_t;

/* ---- ciclo de vida -------------------------------------------------------- */

/* Mapea /dev/mem y, con check_magic, valida el magic (MCA_ENOTPRESENT si no). */
MCA_API int multitrigger_open(multitrigger_h **h, uint32_t phys, uint32_t size,
                              int check_magic);

/* Sobre un bus ya abierto. Con `propio`, multitrigger_close() lo cierra. Sin
 * check_magic no hace ningun acceso. */
MCA_API int multitrigger_open_bus(multitrigger_h **h, mca_bus *bus, int propio,
                                  int check_magic);

MCA_API void multitrigger_close(multitrigger_h *h);
MCA_API const char *multitrigger_last_error(const multitrigger_h *h);

/* ---- tablas --------------------------------------------------------------- */

MCA_API int32_t multitrigger_reg_count(void);
MCA_API const mca_reg_t *multitrigger_reg_info(int32_t i);      /* NULL fuera de rango */
MCA_API int32_t multitrigger_field_count(void);
MCA_API const mca_field_t *multitrigger_field_info(int32_t i);  /* NULL fuera de rango */

/* sizeof de los structs publicos, por nombre. Ver mca_sizeof. 0 si no existe. */
MCA_API size_t multitrigger_sizeof(const char *tipo);

/* ---- acceso crudo --------------------------------------------------------- */

MCA_API int multitrigger_r32(multitrigger_h *h, uint32_t off, uint32_t *v);
MCA_API int multitrigger_w32(multitrigger_h *h, uint32_t off, uint32_t v);

/* ---- capacidades ---------------------------------------------------------- */

MCA_API int multitrigger_get_caps(multitrigger_h *h, uint32_t *caps);
MCA_API int multitrigger_has_slope(multitrigger_h *h, int32_t *si);
MCA_API int multitrigger_has_pz(multitrigger_h *h, int32_t *si);

/* ---- mascaras OR ---------------------------------------------------------- */
/* Todo `ch` fuera de 0..3 da MCA_EINVAL sin tocar nada: con ch = 4, base + 4 * ch
 * es OTRO registro (SLOPE_CFG del canal 4 es SLOPE_THR del canal 0). */

/* Una escritura, sin relectura: una escritura a esta direccion recarga la mascara
 * activa de mt_trig_src, incluso con v = 0, y la relectura devuelve lo escrito
 * (trg_src_stored), no la activa. */
MCA_API int multitrigger_set_or_mask(multitrigger_h *h, int64_t ch, uint32_t v);
MCA_API int multitrigger_get_or_mask(multitrigger_h *h, int64_t ch, uint32_t *v);

/* Los dos canales de una, con relectura: MCA_EVERIFY si no latcheo. Recibe int64
 * porque compara contra lo pedido: un valor que no entra en 32 b se escribe
 * recortado y no coincide. */
MCA_API int multitrigger_set_or_masks(multitrigger_h *h, int64_t ch0, int64_t ch1);

/* ---- trigger_shield ------------------------------------------------------- */

MCA_API int multitrigger_set_shield(multitrigger_h *h, uint32_t src, uint32_t dst,
                                    uint32_t dur);
MCA_API int multitrigger_get_shield(multitrigger_h *h, multitrigger_shield_t *s);

/* Clear automatico de adc_trg_dis: `channels` como fuente y como destino. Con dur=0
 * el clear sale en el mismo ciclo del trigger. */
MCA_API int multitrigger_shield_autorearm(multitrigger_h *h, uint32_t channels,
                                          uint32_t dur);
MCA_API int multitrigger_disable_shield(multitrigger_h *h);

/* ---- snapshot y flags ----------------------------------------------------- */

MCA_API int multitrigger_get_snapshot(multitrigger_h *h, uint32_t *v);  /* sticky */
MCA_API int multitrigger_get_flags(multitrigger_h *h, uint32_t *v);     /* {we_keep[7:4], dis_act[3:0]} */

/* ---- disparo por pendiente ------------------------------------------------ */

/* L: muestras de cada suma (1..16). G: separacion entre sumas (0..31). thr, hyst:
 * en unidades de s; con en, hyst < thr o el Schmitt no re-arma. Valida todo antes
 * de escribir (MCA_EINVAL; MCA_ENOSYS sin CAPS[16]). Umbrales primero: el filtro se
 * habilita con el Schmitt ya configurado. MCA_EVERIFY si un registro no retuvo. */
MCA_API int multitrigger_set_slope(multitrigger_h *h, int64_t ch, int64_t L, int64_t G,
                                   int64_t thr, int64_t hyst, int32_t en);
MCA_API int multitrigger_get_slope(multitrigger_h *h, int64_t ch, multitrigger_slope_t *s);
MCA_API int multitrigger_disable_slope(multitrigger_h *h, int64_t ch);

/* ---- disparo con polo-cero ------------------------------------------------ */

/* k, m: subida y meseta (k >= 1, k + m <= 31). mq: la constante polo-cero, M * 16.
 * sh: corrimiento de la salida (0..63). thr, hyst: en unidades de la salida. Valida
 * como multitrigger_set_slope (MCA_ENOSYS sin CAPS[17]). */
MCA_API int multitrigger_set_pz(multitrigger_h *h, int64_t ch, int64_t k, int64_t m,
                                int64_t mq, int64_t sh, int64_t thr, int64_t hyst,
                                int32_t en);
MCA_API int multitrigger_get_pz(multitrigger_h *h, int64_t ch, multitrigger_pz_t *p);
MCA_API int multitrigger_disable_pz(multitrigger_h *h, int64_t ch);

/* ---- configuracion en bloque ---------------------------------------------- */

/* Todos los campos, en el orden de la tabla. n tiene que ser multitrigger_field_count(). */
MCA_API int multitrigger_get_config(multitrigger_h *h, uint32_t *vals, int32_t n);

/* Escribe n campos (indices de la tabla, sin repetir), agrupando los que comparten
 * registro: los tres del shield viven en la misma palabra. Un read-modify-write y
 * una relectura por registro, en el orden en que aparece cada registro. */
MCA_API int multitrigger_configure(multitrigger_h *h, const int32_t *campos,
                                   const uint32_t *valores, int32_t n);

MCA_API int multitrigger_get_status(multitrigger_h *h, multitrigger_status_t *st);

#ifdef __cplusplus
}
#endif

#endif /* MULTITRIGGER_H */

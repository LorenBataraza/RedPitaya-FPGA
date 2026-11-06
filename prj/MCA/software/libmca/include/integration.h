/* La region de TOP (slot 6 del bus de sistema, base 0x4060_0000): que bitstream
 * esta cargado, que modulos trae, en que slot vive cada uno y de donde toma sus
 * muestras cada consumidor de la cadena DSP. El mapa es
 * docs/TOP/register_map_top.md.
 *
 * Es la API de API/integration.py, en C y con la forma de mca.h: cada funcion
 * recibe el handle, devuelve MCA_OK o un MCA_E* y entrega los resultados por
 * puntero. Los nombres son los mismos que en Python.
 *
 *     integration_h *ig;
 *     if (integration_open(&ig, INTEGRATION_PHYS, INTEGRATION_SIZE, 1) != MCA_OK)
 *         fprintf(stderr, "%s\n", integration_last_error(NULL));
 *     integration_set_route(ig, INTEGRATION_CONS_MCA, INTEGRATION_TAP_ADC, 1, 1);
 *     integration_close(ig);
 *
 * Que falte no es fatal: un bitstream anterior al refactor de registros no trae
 * esta region (MCA_ENOTPRESENT) y los demas bloques andan igual con sus bases
 * por defecto. Sin locks, igual que mca.h: un handle tiene un solo duenio.
 */
#ifndef INTEGRATION_H
#define INTEGRATION_H

#include <stddef.h>
#include <stdint.h>

#include "mca_api.h"
#include "mca_bus.h"
#include "integration_regs.h"

#ifdef __cplusplus
extern "C" {
#endif

#define INTEGRATION_PHYS  0x40600000u
#define INTEGRATION_SIZE  0x1000u       /* la region entera son 64 registros */
#define INTEGRATION_MAGIC 0x494E5447u   /* "INTG" */

#define INTEGRATION_BUS_BASE 0x40000000u /* slot n = BASE + n * SLOT */
#define INTEGRATION_BUS_SLOT 0x00100000u

typedef struct integration_h integration_h;

/* Los consumidores de la cadena DSP, en el orden de sus registros ROUTE_*. */
typedef enum {
    INTEGRATION_CONS_OSC, INTEGRATION_CONS_MTRG,
    INTEGRATION_CONS_MCA, INTEGRATION_CONS_RING,
    INTEGRATION_N_CONSUMIDORES
} integration_consumidor_t;

/* Los modulos que publican su slot, en el orden de sus nibbles en SLOTS. */
typedef enum {
    INTEGRATION_SLOT_OSC, INTEGRATION_SLOT_RING, INTEGRATION_SLOT_MTRG,
    INTEGRATION_SLOT_TOP, INTEGRATION_SLOT_MCA,
    INTEGRATION_N_SLOTS
} integration_slot_t;

/* Los puntos de la cadena DSP. INTEGRATION_TAP_NATIVE es el reset: cada
 * consumidor en el nodo que tenia cableado antes del refactor. */
typedef enum {
    INTEGRATION_TAP_NATIVE, INTEGRATION_TAP_ADC,
    INTEGRATION_TAP_DEC_IN, INTEGRATION_TAP_BRAM_IN,
    INTEGRATION_N_TAPS
} integration_tap_t;

/* Lo que el binding pasa como tap cuando no le dieron un entero: el mensaje de
 * error no puede repetir un valor que no cruzo a C. */
#define INTEGRATION_TAP_NO_ENTERO INT64_MIN

/* ---- los bits de los registros -------------------------------------------- */

#define INTEGRATION_MOD_OSC  (1u << 0)
#define INTEGRATION_MOD_MTRG (1u << 1)
#define INTEGRATION_MOD_MCA  (1u << 2)
#define INTEGRATION_MOD_RING (1u << 3)
#define INTEGRATION_MOD_ASG  (1u << 4)
#define INTEGRATION_MOD_PID  (1u << 5)

#define INTEGRATION_CTRL_RUN   (1u << 0)
#define INTEGRATION_CTRL_CLEAR (1u << 1)    /* autolimpiante en HW (un ciclo) */
#define INTEGRATION_CTRL_SRST  (1u << 2)    /* autolimpiante en HW (un ciclo) */

#define INTEGRATION_ST_PLL_LOCKED (1u << 0)
#define INTEGRATION_ST_ADC_RSTN   (1u << 1)

/* ---- los tipos que cruzan la interfaz ------------------------------------- */

typedef struct {
    uint32_t magic;
    uint32_t version[4];        /* mayor, menor, parche, variante */
    char     gith[41];          /* hash de git en hexa, terminado en NUL */
} integration_info_t;

typedef struct { int32_t osc, mtrg, mca, ring, asg, pid; } integration_modules_t;

typedef struct { uint32_t osc, ring, mtrg, top, mca; } integration_slots_t;

/* h_aw, h2_aw y psd_aw son informativos y pueden mentir: la fuente de verdad es
 * WIDTHS del MCA (mca_get_widths). Ver el docstring de Integration.caps. */
typedef struct {
    uint32_t n_ch, dw, rsz;
    int32_t  en_filt;
    uint32_t h_aw, h2_aw, psd_aw;
} integration_caps_t;

typedef struct {
    uint32_t    tap;
    const char *nombre;         /* cadena estatica, no se libera */
    int32_t     enable;
} integration_route_t;

typedef struct { int32_t pll_locked, adc_rstn; } integration_status_t;

/* ---- ciclo de vida -------------------------------------------------------- */

/* Mapea /dev/mem y, con check_magic, valida el magic (MCA_ENOTPRESENT si no).
 * Si la PL no esta programada, la PRIMERA lectura mata el proceso con SIGBUS. */
MCA_API int integration_open(integration_h **h, uint32_t phys, uint32_t size,
                             int check_magic);

/* Sobre un bus ya abierto. Con `propio`, integration_close() lo cierra. Sin
 * check_magic no hace ningun acceso. */
MCA_API int integration_open_bus(integration_h **h, mca_bus *bus, int propio,
                                 int check_magic);

MCA_API void integration_close(integration_h *h);

/* El detalle del ultimo error del handle, o el de la ultima apertura con NULL. */
MCA_API const char *integration_last_error(const integration_h *h);

/* ---- tablas --------------------------------------------------------------- */

MCA_API int32_t integration_reg_count(void);
MCA_API const mca_reg_t *integration_reg_info(int32_t i);   /* NULL fuera de rango */

/* "osc", "mtrg", ... Para que el binding compare sus tablas. NULL fuera de rango. */
MCA_API const char *integration_consumidor_name(int32_t i);
MCA_API const char *integration_slot_name(int32_t i);

/* sizeof de los structs publicos, por nombre. Ver mca_sizeof. 0 si no existe. */
MCA_API size_t integration_sizeof(const char *tipo);

/* ---- acceso crudo --------------------------------------------------------- */

MCA_API int integration_r32(integration_h *h, uint32_t off, uint32_t *v);
MCA_API int integration_w32(integration_h *h, uint32_t off, uint32_t v);

/* ---- identificacion y descripcion del sistema ----------------------------- */

MCA_API int integration_identify(integration_h *h, integration_info_t *info);
MCA_API int integration_get_modules(integration_h *h, integration_modules_t *m);
MCA_API int integration_get_slots(integration_h *h, integration_slots_t *s);
MCA_API int integration_get_caps(integration_h *h, integration_caps_t *c);

/* La direccion fisica de un modulo, segun el mapa real del bitstream: el
 * multitrigger esta en el slot 3 del top del MCA y en el 7 del red_pitaya_top
 * clasico. `slot` es un integration_slot_t; MCA_ENOKEY si no lo es. */
MCA_API int integration_get_base(integration_h *h, int32_t slot, uint32_t *base);

/* ---- ruteo del datapath --------------------------------------------------- */

/* `consumidor` es un integration_consumidor_t; MCA_ENOKEY si no lo es. */
MCA_API int integration_get_route(integration_h *h, int32_t consumidor,
                                  integration_route_t *r);

/* Los cuatro. n tiene que ser INTEGRATION_N_CONSUMIDORES. */
MCA_API int integration_get_routes(integration_h *h, integration_route_t *r, int32_t n);

/* Elige de que punto de la cadena toma sus muestras un consumidor. Con enable=0
 * su `val` se fuerza a 0. Con verify, relee y da MCA_EVERIFY si no latcheo. Un
 * tap fuera de rango da MCA_EINVAL antes de mirar el consumidor, y sin escribir.
 *
 * Cambiar de tap corre la latencia (rp_bram_sm cuenta el delay en muestras
 * decimadas), y el camino a DDR por AXI no se rutea. */
MCA_API int integration_set_route(integration_h *h, int32_t consumidor, int64_t tap,
                                  int32_t enable, int32_t verify);

/* Los cuatro a nativo y habilitados, con verify: el estado de reset del hardware. */
MCA_API int integration_reset_routes(integration_h *h);

/* ---- control y estado global ---------------------------------------------- */

MCA_API int integration_set_run(integration_h *h, int32_t on);
MCA_API int integration_get_run(integration_h *h, int32_t *on);

/* Pulsos globales autolimpiantes. Conservan el bit run. */
MCA_API int integration_clear(integration_h *h);
MCA_API int integration_soft_reset(integration_h *h);

MCA_API int integration_get_status(integration_h *h, integration_status_t *st);

#ifdef __cplusplus
}
#endif

#endif /* INTEGRATION_H */

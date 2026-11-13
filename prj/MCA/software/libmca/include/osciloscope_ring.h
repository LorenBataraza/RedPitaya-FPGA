/* El event_ring (slot 2, base 0x4020_0000) y su lector por lote: lo que hacia
 * `RingSource` desde Python, en C. El mapa y la secuencia de uso son
 * docs/event_ring/diseno_y_register_map.md.
 *
 * El ring copia cada evento a un slot de una region reservada de DDR, y se re-arma
 * solo: el PS no esta en el camino del disparo. Hay dos regiones:
 *
 *   los registros   por el bus (mca_bus.h): de a 32 bits, como todo bloque de la PL
 *   los slots       por la DDR (mca_mem.h): memoria comun no cacheable, se copia
 *
 * El slot (2^slot_shift bytes, palabras de 64 b en little-endian):
 *
 *   w0     la marca de tiempo: ciclos de adc_clk desde que arranco el ring
 *   w1     {flags[63:56], n_ch[55:48], n_samp[47:32], seq[31:0]}
 *   w2     {event_id[63:32] (hoy 0), snapshot[16:0]}: que fuente disparo
 *   w3     0
 *   w4..   las muestras, int16 con el signo extendido, canales intercalados
 *   ultima el footer {~seq, seq}: el commit del slot
 *
 *     osciloscope_ring_h *r;
 *     osciloscope_ring_open(&r, OSCILOSCOPE_RING_PHYS, OSCILOSCOPE_RING_SIZE,
 *                           0x0A000000, 32u << 20, 1);
 *     osciloscope_ring_configurar(r, &cfg, &st);    // parado: geometria, footers
 *     ... armar el disparo (multitrigger) ...
 *     osciloscope_ring_correr(r);
 *     osciloscope_ring_leer_lote(r, &cfg, &st, &lote, n, plazo, &res);   // en lazo
 *     osciloscope_ring_parar(r, plazo);
 *
 * Como el resto de libmca: cada funcion devuelve MCA_OK o un MCA_E*, y el detalle
 * queda en osciloscope_ring_last_error(). Un handle tiene un solo duenio.
 */
#ifndef OSCILOSCOPE_RING_H
#define OSCILOSCOPE_RING_H

#include <stddef.h>
#include <stdint.h>

#include "gen_disparos.h"
#include "mca_api.h"
#include "mca_bus.h"
#include "mca_mem.h"
#include "osciloscope_lote.h"
#include "osciloscope_ring_regs.h"

#ifdef __cplusplus
extern "C" {
#endif

#define OSCILOSCOPE_RING_PHYS   0x40200000u
#define OSCILOSCOPE_RING_SIZE   0x1000u
#define OSCILOSCOPE_RING_MAGIC  0x45564E54u    /* "EVNT" */

/* Lo que construye event_ring_red_pitaya_top. El RTL escribe siempre sus N_CH canales:
 * el tamano del slot y los limites de la ventana se cuentan con ellos, aunque se
 * entreguen menos. */
#define OSCILOSCOPE_RING_N_CH      2u
#define OSCILOSCOPE_RING_PRE_BUF   2048u      /* palabras del pre-buffer: PRE_AW = 11 */
#define OSCILOSCOPE_RING_STAGE     4096u      /* muestras del stage: DATA_AW = 12 */
#define OSCILOSCOPE_RING_VENTANA_MAX 2047u    /* PRE y POST tienen 11 bits (S_AW) */
#define OSCILOSCOPE_RING_SLOT_MIN  6u         /* cabecera y footer: 40 B */
#define OSCILOSCOPE_RING_SLOT_MAX  18u        /* el contador de palabras tiene 16 bits */
#define OSCILOSCOPE_RING_HDR       32u
#define OSCILOSCOPE_RING_FOOTER    8u
/* Lo que se valida de una vez, por defecto: 64 KB fue el optimo medido en la placa
 * desde Python, y el credito se devuelve una vez por bloque, no por evento. */
#define OSCILOSCOPE_RING_LOTE      65536u

#define OSCILOSCOPE_RING_CTRL_RUN  (1u << 0)
#define OSCILOSCOPE_RING_CTRL_CLR  (1u << 1)  /* contadores y sticky; autolimpiante */
#define OSCILOSCOPE_RING_ST_ESTADO 0x3u       /* 0 parado, 1 corriendo, 2 drenando */
#define OSCILOSCOPE_RING_ST_SIN_CREDITO (1u << 4)
#define OSCILOSCOPE_RING_ST_ERR_CFG     (1u << 5)
#define OSCILOSCOPE_RING_ST_ERR_SLOT    (1u << 6)
#define OSCILOSCOPE_RING_ST_ERR_FIFO    (1u << 7)

/* El generador de eventos (gen_eventos.sv): en el bitstream del ring desde
 * 78e26188 (EN_GEN = 1). Sus registros son los GEN_* de osciloscope_ring_regs.h. */
#define OSCILOSCOPE_RING_GEN_MAGIC      0x47454E31u   /* "GEN1" */
#define OSCILOSCOPE_RING_GEN_CTRL_EN     (1u << 0)
#define OSCILOSCOPE_RING_GEN_CTRL_ALEATORIO (1u << 1)
#define OSCILOSCOPE_RING_GEN_CTRL_PATRON (1u << 2)
/* Del ciclo de la decision a la marca del slot (w0): ts = g + 2, con el ring en 0
 * el primer ciclo en RUNNING. Es el `lat` de gen_disparos_predecir. */
#define OSCILOSCOPE_RING_GEN_LAT_TS     2u
/* El snapshot (w2) de un evento generado: {1, k[15:0]}, k su indice desde el
 * arranque. */
#define OSCILOSCOPE_RING_GEN_SNAP_MARCA (1u << 16)

typedef struct osciloscope_ring_h osciloscope_ring_h;

/* ---- los tipos que cruzan la interfaz ------------------------------------- */

typedef struct {
    uint32_t pre, post;         /* muestras por canal, antes y desde el disparo */
    uint32_t n_ch;              /* canales que se entregan: los primeros del RTL */
    uint32_t dw;                /* bits de la muestra: 14 */
    uint32_t slot_shift;        /* log2 de los bytes del slot; 0 = el menor que entra */
    uint32_t ring_bytes;        /* 0 = la region entera, en slots enteros */
    uint32_t lote_bytes;        /* lo que se valida de una vez; 0 = OSCILOSCOPE_RING_LOTE */
    uint32_t reservado;
    osciloscope_adc_cal_t cal[OSCILOSCOPE_N_APERTURAS];    /* n_ch validas */
} osciloscope_ring_cfg_t;

/* Lo que sale de la configuracion, antes de tocar el hardware. */
typedef struct {
    uint32_t muestras;          /* pre + post */
    uint32_t slot_shift, slot_bytes, n_slots, ring_bytes;
    uint32_t lote_slots;
} osciloscope_ring_geometria_t;

/* Lo que el lazo lleva de una llamada a la otra. Lo deja en cero configurar. */
typedef struct {
    uint32_t next;              /* seq del proximo slot a entregar */
    uint32_t publicado;         /* el ultimo RD_SLOT escrito */
    uint32_t slot_shift, n_slots;   /* la geometria que quedo configurada */
    uint32_t drop_prev;         /* DROP_BUSY + DROP_FULL en la ultima lectura */
    uint32_t reservado;
    uint64_t pendientes;        /* descartados que todavia no fueron a ningun gap */
} osciloscope_ring_estado_t;

/* Las columnas del lote, desde la fila donde se empieza a escribir. Cualquiera puede
 * ser NULL. `wave` es (n, n_ch, pre + post). */
typedef struct {
    int16_t  *wave;             /* cuentas calibradas, como el lazo de la BRAM */
    int64_t  *t_ns;             /* cuando se leyo: CLOCK_MONOTONIC */
    int32_t  *wp;               /* -1: el ring no tiene wp_trig */
    uint32_t *snap;             /* el snapshot de la cabecera del MISMO slot */
    uint8_t  *gap;              /* descartados antes de este evento, saturado */
    int64_t  *dead_ns;          /* 0: el PS no esta en el re-armado */
    int64_t  *ts_hw;            /* la marca de la cabecera (w0) */
    uint32_t *seq;              /* el seq del slot */
} osciloscope_ring_lote_t;

typedef struct {
    uint32_t status, ev_cnt, drop_busy, drop_full;
    uint32_t wr_slot, rd_slot, seq, n_slots;
    uint32_t lvl, axi_addr;
    uint64_t ts;                /* el contador libre (TS_HI:TS_LO) */
} osciloscope_ring_contadores_t;

/* ---- ciclo de vida -------------------------------------------------------- */

/* Mapea los registros de /dev/mem y la region de DDR [ddr_phys, ddr_phys + ddr_size).
 * Con check_magic, MCA_ENOTPRESENT si el slot no tiene el ring. */
MCA_API int osciloscope_ring_open(osciloscope_ring_h **h, uint32_t phys, uint32_t size,
                                  uint32_t ddr_phys, uint32_t ddr_size, int check_magic);

/* Sobre un bus y una region ya abiertos. Con `propio` / `ddr_propio`, close los cierra.
 * Si falla, siguen siendo de quien llama. */
MCA_API int osciloscope_ring_open_bus(osciloscope_ring_h **h, mca_bus *bus, int propio,
                                      mca_mem *ddr, int ddr_propio, int check_magic);
MCA_API void osciloscope_ring_close(osciloscope_ring_h *h);

/* El detalle del ultimo error del handle; con NULL, el del ultimo open o el de
 * osciloscope_ring_geometria. */
MCA_API const char *osciloscope_ring_last_error(const osciloscope_ring_h *h);

MCA_API int32_t osciloscope_ring_reg_count(void);
MCA_API const mca_reg_t *osciloscope_ring_reg_info(int32_t i);
MCA_API size_t osciloscope_ring_sizeof(const char *tipo);

MCA_API int osciloscope_ring_r32(osciloscope_ring_h *h, uint32_t off, uint32_t *v);
MCA_API int osciloscope_ring_w32(osciloscope_ring_h *h, uint32_t off, uint32_t v);

/* La region de DDR: su direccion fisica y sus bytes. */
MCA_API int osciloscope_ring_ddr(osciloscope_ring_h *h, uint32_t *phys, uint32_t *size);

/* ---- geometria y control -------------------------------------------------- */

/* Valida la ventana y el slot contra lo que construye el RTL, y calcula la geometria.
 * Con ddr_size 0 no mira el ring. No mira la calibracion. */
MCA_API int osciloscope_ring_geometria(const osciloscope_ring_cfg_t *cfg, uint32_t ddr_size,
                                       osciloscope_ring_geometria_t *g);

/* Con el ring parado (lo para, y espera que termine de drenar): limpia contadores,
 * borra los footers de todos los slots, escribe la geometria y la relee. Deja `st`
 * en cero. No lo arranca. */
MCA_API int osciloscope_ring_configurar(osciloscope_ring_h *h,
                                        const osciloscope_ring_cfg_t *cfg,
                                        osciloscope_ring_estado_t *st);

MCA_API int osciloscope_ring_correr(osciloscope_ring_h *h);

/* CTRL = 0 y espera que termine la ventana en vuelo (MCA_ETIMEOUT si no, a plazo_ns
 * de CLOCK_MONOTONIC). */
MCA_API int osciloscope_ring_parar(osciloscope_ring_h *h, int64_t plazo_ns);

MCA_API int osciloscope_ring_contadores(osciloscope_ring_h *h,
                                        osciloscope_ring_contadores_t *c);

/* ---- el lazo -------------------------------------------------------------- */

/* Hasta n_max eventos, o hasta plazo_ns. Por bloque de slots:
 *
 *   cuantos   WR_SLOT dice cuantos slots cerro el writer (una lectura por bloque)
 *   commit    el footer de cada uno, con el seq esperado: el primero que no esta
 *             corta el bloque (WR_SLOT avanza al aceptarse el footer, no al llegar)
 *   barrera   los footers antes que los datos
 *   leer      cabecera y muestras de cada slot: columnas y ventana calibrada
 *   credito   RD_SLOT, una escritura por bloque, despues de otra barrera
 *
 * Los descartados los cuenta el hardware (DROP_BUSY + DROP_FULL): se leen antes de
 * cada bloque y al volver, y van al `gap` del primer evento que se guarda despues, con
 * el total exacto en `asignados`. El slot no dice cuales se perdieron antes de el (event_id
 * es 0), asi que el `gap` del ring es por bloque, no por evento.
 *
 * Sin lote no se consume nada: los eventos esperan en la DDR, y si el ring se llena
 * el hardware los descarta y los cuenta. Espera hasta el plazo y lee los contadores.
 * `res` es el de la BRAM: guardados, descartados vistos y asignados a un gap. */
MCA_API int osciloscope_ring_leer_lote(osciloscope_ring_h *h,
                                       const osciloscope_ring_cfg_t *cfg,
                                       osciloscope_ring_estado_t *st,
                                       const osciloscope_ring_lote_t *lote,
                                       uint32_t n_max, int64_t plazo_ns,
                                       osciloscope_lote_resultado_t *res);

/* ---- medir la tasa -------------------------------------------------------- */

/* Los lazos de las etapas de docs/event_ring/generador.md §6, para saber que parte
 * limita. Los tres consumen como leer_lote (WR_SLOT una vez por sondeo, el credito
 * una vez por bloque) pero no entregan nada:
 *
 *   CREDITOS   etapa A: RD_SLOT <- WR_SLOT, sin tocar la DDR. Si se pierde algo, lo
 *              pierden la PL, el AXI o la DDR
 *   COPIA      el footer y la copia de cada slot (cabecera y muestras), como
 *              leer_lote, sin mirarla: lo que cuesta sacar el dato de la DDR
 *   VERIFICAR  etapa B: la copia y lo que tiene que tener un slot del generador de
 *              eventos con el patron (osciloscope_ring_gen_configurar, patron = 1):
 *              la cabecera configurada, la marca {1, k}, k y ts que avanzan, y cada
 *              muestra desde el arranque. Un slot que no cumple se cuenta y se sigue
 */
#define OSCILOSCOPE_RING_MEDIR_CREDITOS  0u
#define OSCILOSCOPE_RING_MEDIR_COPIA     1u
#define OSCILOSCOPE_RING_MEDIR_VERIFICAR 2u

/* Lo que se acumula de una llamada a la otra: en cero antes de la primera (C) o al
 * configurar el lector (Python). */
typedef struct {
    uint64_t eventos;           /* slots consumidos: su credito se devolvio */
    uint64_t bytes;             /* copiados de la DDR (0 con CREDITOS) */
    uint64_t sondeos;           /* lecturas de WR_SLOT */
    uint64_t bloques;           /* las que trajeron slots */
    uint64_t descartados;       /* DROP_BUSY + DROP_FULL nuevos, leidos al volver */
    int64_t  t0_ns, t1_ns;      /* el primer bloque y el fin del ultimo (CLOCK_MONOTONIC) */
    int64_t  trabajo_ns;        /* dentro de los bloques: lo demas es sondear vacio */
    uint32_t ocupacion_max;     /* el mayor WR_SLOT - RD_SLOT visto: cuanto se lleno */
    uint32_t primer_error_seq;  /* el seq del primer slot con algun error; UINT32_MAX */
    /* VERIFICAR: los slots con cada error (uno puede tener varios) */
    uint64_t err_cabecera;      /* seq, n_samp o n_ch que no son los configurados */
    uint64_t err_marca;         /* el snapshot no es {1, k}: no lo genero el generador */
    uint64_t err_k;             /* k repetido, que no avanza, o de mas de los N */
    uint64_t err_ts;            /* ts que no avanza, o que el motor no da (ver abajo) */
    uint64_t err_patron;        /* alguna muestra desde el arranque no es el patron */
    uint64_t muestras_malas;    /* cuantas, entre todos esos slots */
    uint64_t k_saltos;          /* los k que faltan antes de cada slot: los descartados */
    int64_t  k_ultimo;          /* k del ultimo slot con marca, sin la vuelta; -1 ninguno */
    int64_t  ts_ultimo;         /* su marca */
} osciloscope_ring_medida_t;

/* Hasta n_max eventos o hasta plazo_ns, como leer_lote, en el modo `modo`. Los
 * errores del slot no cortan: van a `m`. Corta un MCA_E* del bus o de la DDR, o un
 * WR_SLOT imposible (MCA_EVERIFY).
 *
 * k: el snapshot trae k[15:0], y el lector lo extiende con el del slot anterior, asi
 * que una racha de 65 536 o mas descartados seguidos se ve como 65 536 menos. Con
 * `gen` (la configuracion del generador; NULL = no se conoce), ademas:
 *
 *   periodico   la marca es exacta, ts = (k + 1) * periodo - 1 + GEN_LAT_TS: da k
 *               sin ambiguedad y se compara con el del snapshot
 *   aleatorio   entre dos slots hay al menos dt_min ciclos por cada k: ts >= ts_ant +
 *               dt_min * (k - k_ant), y ts >= GEN_LAT_TS + dt_min * k
 *   n           k < n
 *
 * Al terminar la corrida (parado y leido todo), con el GEN_CNT del generador:
 * k_saltos + (GEN_CNT - 1 - k_ultimo) == DROP_BUSY + DROP_FULL.
 *
 * Los descartados que lee van a st->pendientes, como en leer_lote: medir no asigna
 * gaps. Las muestras de antes del arranque (ts - pre + j < 0) no se miran: son las
 * que quedaron en el pre-buffer (docs/event_ring/logica_de_captura_y_axi.md §2.3). */
MCA_API int osciloscope_ring_medir(osciloscope_ring_h *h, const osciloscope_ring_cfg_t *cfg,
                                   osciloscope_ring_estado_t *st, uint32_t modo,
                                   const gen_disparos_cfg_t *gen, uint32_t n_max,
                                   int64_t plazo_ns, osciloscope_ring_medida_t *m);

/* m en cero, con primer_error_seq = UINT32_MAX y k_ultimo = -1. */
MCA_API void osciloscope_ring_medida_cero(osciloscope_ring_medida_t *m);

/* ---- el generador de eventos ---------------------------------------------- */

/* Reemplaza, adentro del ring, los disparos del multitrigger por los del motor
 * (gen_disparos.h) y el dato por un patron que se verifica en forma absoluta:
 *
 *   ch0[j] = (TS - PRE + j) mod 2^14      ch1[j] = ~ch0[j]   (14 bits, con signo
 *                                                             en el slot)
 *
 * con TS la marca de la cabecera. Los disparos salen solo con el ring en RUNNING, y
 * su estado se reinicia al arrancarlo: con la misma semilla, gen_disparos_predecir
 * (lat = OSCILOSCOPE_RING_GEN_LAT_TS) da la marca de cada slot. Sin perder nada de
 * vista:
 *
 *   EV_CNT + DROP_BUSY + DROP_FULL == GEN_CNT
 *
 * y el snapshot de cada slot dice cual de los generados es. Ver
 * docs/event_ring/generador.md. */

/* *si = 1 si el ring de este bitstream tiene el generador (GEN_MAGIC "GEN1"). */
MCA_API int osciloscope_ring_gen_presente(osciloscope_ring_h *h, int32_t *si);

/* Con el ring parado (MCA_EINVAL si no: GEN_CNT y EV_CNT tienen que contar desde el
 * mismo arranque). `d` son los disparos del motor; con NULL siguen los del
 * multitrigger. `patron` reemplaza el dato. Escribe, relee (MCA_EVERIFY) y deja el
 * generador prendido: corre cuando corra el ring. MCA_ENOSYS si el bitstream no lo
 * tiene. */
MCA_API int osciloscope_ring_gen_configurar(osciloscope_ring_h *h,
                                            const gen_disparos_cfg_t *d, int32_t patron);

/* CTRL = 0: el ring vuelve a los disparos y al dato de la cadena del scope. */
MCA_API int osciloscope_ring_gen_apagar(osciloscope_ring_h *h);

/* GEN_CNT y ESTADO. GEN_CNT no se borra al parar el ring: se lee despues de
 * osciloscope_ring_parar, junto con los contadores del ring. */
MCA_API int osciloscope_ring_gen_estado(osciloscope_ring_h *h, gen_estado_t *e);

#ifdef __cplusplus
}
#endif

#endif /* OSCILOSCOPE_RING_H */

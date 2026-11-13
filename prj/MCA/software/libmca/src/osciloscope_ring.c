/* El event_ring y su lector por lote. Ver include/osciloscope_ring.h.
 *
 * La referencia es el `RingSource` de Python hasta la Parte 7 del plan de libmca
 * (prefetch en bloque, validacion por footer, RD_SLOT por bloque), con tres cosas que
 * aquel no hacia:
 *
 *   - el footer se lee ANTES que los datos, con una barrera en el medio. Python copiaba
 *     el bloque y miraba el footer en la copia: un memcpy hacia adelante lee los datos
 *     antes que el footer, y un footer que aterriza en el medio valida datos viejos;
 *   - configurar borra los footers: el slot k de la corrida anterior tiene el mismo seq
 *     que el de esta, con un footer valido;
 *   - configurar espera que el ring termine de drenar antes de escribir la geometria,
 *     que el RTL solo toma parado (escrita drenando se pierde y prende err_cfg).
 *
 * Los registros pasan por mca_bus; los slots, por mca_mem. Nada de este fichero toca
 * memoria de dispositivo.
 */
#define _DEFAULT_SOURCE         /* clock_nanosleep con -std=c11 */

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "bloque.h"
#include "gen_priv.h"
#include "osciloscope_priv.h"
#include "osciloscope_ring.h"

struct osciloscope_ring_h {
    mca_bloque b;               /* primer miembro: ver bloque.h */
    mca_mem *ddr;
    int ddr_propio;
    uint8_t *slot;              /* un slot, copiado de la DDR: cabecera y muestras */
    uint32_t slot_len;
};

#define fallar(h, ...) bloque_fallar((mca_bloque *)(h), __VA_ARGS__)

#define X_REG(n, off) { #n, off },
static const mca_reg_t REGS[] = { OSCILOSCOPE_RING_REGS(X_REG) };
#undef X_REG

int32_t osciloscope_ring_reg_count(void)
{
    return (int32_t)(sizeof(REGS) / sizeof(REGS[0]));
}

const mca_reg_t *osciloscope_ring_reg_info(int32_t i)
{
    return (i >= 0 && i < osciloscope_ring_reg_count()) ? &REGS[i] : NULL;
}

size_t osciloscope_ring_sizeof(const char *tipo)
{
    static const struct { const char *n; size_t s; } t[] = {
        { "osciloscope_ring_cfg_t",        sizeof(osciloscope_ring_cfg_t) },
        { "osciloscope_ring_geometria_t",  sizeof(osciloscope_ring_geometria_t) },
        { "osciloscope_ring_estado_t",     sizeof(osciloscope_ring_estado_t) },
        { "osciloscope_ring_lote_t",       sizeof(osciloscope_ring_lote_t) },
        { "osciloscope_ring_contadores_t", sizeof(osciloscope_ring_contadores_t) },
        { "osciloscope_ring_medida_t",     sizeof(osciloscope_ring_medida_t) },
    };
    for (size_t i = 0; tipo != NULL && i < sizeof(t) / sizeof(t[0]); i++)
        if (strcmp(t[i].n, tipo) == 0)
            return t[i].s;
    return 0;
}

/* =========================================================================
 * Ciclo de vida
 * ========================================================================= */

int osciloscope_ring_open_bus(osciloscope_ring_h **h, mca_bus *bus, int propio,
                              mca_mem *ddr, int ddr_propio, int check_magic)
{
    if (h == NULL || bus == NULL || ddr == NULL)
        return MCA_EINVAL;
    *h = NULL;
    bloque_limpiar_apertura();
    if (check_magic) {
        uint32_t magic;
        TRY(mca_bus_r32(bus, OSCILOSCOPE_RING_R_MAGIC, &magic));
        if (magic != OSCILOSCOPE_RING_MAGIC)
            return bloque_fallar(NULL, MCA_ENOTPRESENT, "el bitstream cargado no tiene "
                                 "el event_ring en el slot 2 (MAGIC 0x%08" PRIX32 " en "
                                 "0x050; se esperaba 0x%08" PRIX32 ", \"EVNT\")", magic,
                                 OSCILOSCOPE_RING_MAGIC);
    }
    osciloscope_ring_h *n = calloc(1, sizeof(*n));
    if (n == NULL)
        return MCA_ENOMEM;
    n->b.bus = bus;
    n->b.propio = propio;
    n->ddr = ddr;
    n->ddr_propio = ddr_propio;
    *h = n;
    return MCA_OK;
}

int osciloscope_ring_open(osciloscope_ring_h **h, uint32_t phys, uint32_t size,
                          uint32_t ddr_phys, uint32_t ddr_size, int check_magic)
{
    if (h == NULL)
        return MCA_EINVAL;
    *h = NULL;
    bloque_limpiar_apertura();
    mca_bus *b;
    TRY(bloque_abrir_devmem(&b, phys, size));
    mca_mem *m;
    int rc = mca_mem_open_devmem(&m, ddr_phys, ddr_size);
    if (rc != MCA_OK) {
        mca_bus_close(b);
        if (rc == MCA_EINVAL)
            return bloque_fallar(NULL, rc, "la regi\xc3\xb3n de DDR (0x%08" PRIX32 ", %"
                                 PRIu32 " B) tiene que estar alineada a 8 y no ser vac\xc3\xad" "a",
                                 ddr_phys, ddr_size);
        return bloque_fallar(NULL, rc, "/dev/mem @ 0x%08" PRIX32 " (DDR): %s", ddr_phys,
                             strerror(errno));
    }
    rc = osciloscope_ring_open_bus(h, b, 1, m, 1, check_magic);
    if (rc != MCA_OK) {
        mca_mem_close(m);
        mca_bus_close(b);
    }
    return rc;
}

void osciloscope_ring_close(osciloscope_ring_h *h)
{
    if (h == NULL)
        return;
    if (h->b.propio)
        mca_bus_close(h->b.bus);
    if (h->ddr_propio)
        mca_mem_close(h->ddr);
    free(h->slot);
    free(h);
}

const char *osciloscope_ring_last_error(const osciloscope_ring_h *h)
{
    return bloque_ultimo_error((const mca_bloque *)h);
}

int osciloscope_ring_r32(osciloscope_ring_h *h, uint32_t off, uint32_t *v)
{
    INICIO(h);
    return mca_bus_r32(h->b.bus, off, v);
}

int osciloscope_ring_w32(osciloscope_ring_h *h, uint32_t off, uint32_t v)
{
    INICIO(h);
    return mca_bus_w32(h->b.bus, off, v);
}

int osciloscope_ring_ddr(osciloscope_ring_h *h, uint32_t *phys, uint32_t *size)
{
    INICIO(h);
    if (phys != NULL)
        *phys = mca_mem_phys(h->ddr);
    if (size != NULL)
        *size = mca_mem_size(h->ddr);
    return MCA_OK;
}

/* =========================================================================
 * Geometria
 * ========================================================================= */

static int geometria(mca_bloque *b, const osciloscope_ring_cfg_t *c, uint32_t ddr_size,
                     osciloscope_ring_geometria_t *g)
{
    const uint32_t N = OSCILOSCOPE_RING_N_CH;
    memset(g, 0, sizeof(*g));
    if (c->n_ch < 1 || c->n_ch > N)
        return bloque_fallar(b, MCA_EINVAL, "n_ch=%" PRIu32 ": el ring escribe %" PRIu32
                             " canales", c->n_ch, N);
    if (c->pre > OSCILOSCOPE_RING_VENTANA_MAX || c->post > OSCILOSCOPE_RING_VENTANA_MAX)
        return bloque_fallar(b, MCA_EINVAL, "pre=%" PRIu32 ", post=%" PRIu32 ": PRE y POST "
                             "tienen 11 bits (hasta %u)", c->pre, c->post,
                             OSCILOSCOPE_RING_VENTANA_MAX);
    const uint32_t S = c->pre + c->post;
    if (S == 0)
        return bloque_fallar(b, MCA_EINVAL, "pre=0 y post=0: la ventana no tiene muestras");
    /* El hardware no verifica ninguna de las dos. Si el rezago llega al pre-buffer, las
     * muestras se pisan sin error ni contador; si la ventana no entra en el stage, se
     * descartan todos los eventos. */
    const uint32_t rezago = S * N - c->post;
    if (rezago >= OSCILOSCOPE_RING_PRE_BUF)
        return bloque_fallar(b, MCA_EINVAL, "pre=%" PRIu32 ", post=%" PRIu32 ": el rezago "
                             "de la captura es %" PRIu32 " y tiene que ser menor que %u "
                             "(con %" PRIu32 " canales, %" PRIu32 "\xc2\xb7pre + "
                             "%spost)", c->pre, c->post, rezago, OSCILOSCOPE_RING_PRE_BUF,
                             N, N, N == 2 ? "" : "(n_ch - 1)\xc2\xb7");
    if (S * N > OSCILOSCOPE_RING_STAGE)
        return bloque_fallar(b, MCA_EINVAL, "pre=%" PRIu32 ", post=%" PRIu32 ": la ventana "
                             "ocupa %" PRIu32 " muestras y el stage tiene %u", c->pre,
                             c->post, S * N, OSCILOSCOPE_RING_STAGE);

    const uint32_t hace_falta = OSCILOSCOPE_RING_HDR + S * N * 2u + OSCILOSCOPE_RING_FOOTER;
    uint32_t sh = c->slot_shift;
    if (sh == 0) {
        sh = OSCILOSCOPE_RING_SLOT_MIN;
        while ((1u << sh) < hace_falta)
            sh++;
    } else if (sh < OSCILOSCOPE_RING_SLOT_MIN || sh > OSCILOSCOPE_RING_SLOT_MAX) {
        return bloque_fallar(b, MCA_EINVAL, "slot_shift=%" PRIu32 ": el RTL acepta de %u "
                             "a %u (slots de 64 B a 256 KB)", sh, OSCILOSCOPE_RING_SLOT_MIN,
                             OSCILOSCOPE_RING_SLOT_MAX);
    } else if ((1u << sh) < hace_falta) {
        return bloque_fallar(b, MCA_EINVAL, "slot_shift=%" PRIu32 " da %u B pero hacen "
                             "falta %" PRIu32 " B (cabecera+ventana+footer)", sh, 1u << sh,
                             hace_falta);
    }
    g->muestras = S;
    g->slot_shift = sh;
    g->slot_bytes = 1u << sh;
    uint32_t lb = c->lote_bytes ? c->lote_bytes : OSCILOSCOPE_RING_LOTE;
    g->lote_slots = (lb >> sh) ? (lb >> sh) : 1u;

    if (ddr_size == 0)
        return MCA_OK;
    uint32_t rb = c->ring_bytes;
    if (rb == 0) {
        rb = (ddr_size >> sh) << sh;
    } else if (rb > ddr_size) {
        return bloque_fallar(b, MCA_EINVAL, "ring_bytes=%" PRIu32 ": la regi\xc3\xb3n de "
                             "DDR tiene %" PRIu32 " B", rb, ddr_size);
    } else if (rb & (g->slot_bytes - 1u)) {
        /* El writer da la vuelta en SLOT_BASE + RING_SZ - 8: con un pedazo de slot al
         * final, el slot que cae ahi se parte en dos. */
        return bloque_fallar(b, MCA_EINVAL, "ring_bytes=%" PRIu32 ": tiene que ser un "
                             "m\xc3\xbaltiplo del slot (%" PRIu32 " B)", rb, g->slot_bytes);
    }
    if (rb == 0)
        return bloque_fallar(b, MCA_EINVAL, "la regi\xc3\xb3n de DDR (%" PRIu32 " B) no "
                             "tiene lugar para un slot de %" PRIu32 " B", ddr_size,
                             g->slot_bytes);
    g->ring_bytes = rb;
    g->n_slots = rb >> sh;
    return MCA_OK;
}

int osciloscope_ring_geometria(const osciloscope_ring_cfg_t *cfg, uint32_t ddr_size,
                               osciloscope_ring_geometria_t *g)
{
    bloque_limpiar_apertura();
    if (cfg == NULL || g == NULL)
        return MCA_EINVAL;
    return geometria(NULL, cfg, ddr_size, g);
}

/* La geometria y, si cal no es NULL, la calibracion de los canales que se entregan. */
static int validar(osciloscope_ring_h *h, const osciloscope_ring_cfg_t *c,
                   osciloscope_ring_geometria_t *g, osc_cal_t *cal)
{
    TRY(geometria(&h->b, c, mca_mem_size(h->ddr), g));
    if (cal == NULL)
        return MCA_OK;
    return osc_cal_canales(&h->b, c->cal, c->n_ch, c->dw, cal);
}

/* =========================================================================
 * Control
 * ========================================================================= */

int osciloscope_ring_correr(osciloscope_ring_h *h)
{
    INICIO(h);
    return mca_bus_w32(h->b.bus, OSCILOSCOPE_RING_R_CTRL, OSCILOSCOPE_RING_CTRL_RUN);
}

static int parar(osciloscope_ring_h *h, int64_t plazo)
{
    TRY(mca_bus_w32(h->b.bus, OSCILOSCOPE_RING_R_CTRL, 0));
    uint32_t st;
    for (;;) {
        TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_STATUS, &st));
        if ((st & OSCILOSCOPE_RING_ST_ESTADO) == 0)
            return MCA_OK;
        if (osciloscope_ahora_ns() > plazo)
            return fallar(h, MCA_ETIMEOUT, "el ring no termin\xc3\xb3 de drenar la ventana "
                          "en vuelo (STATUS=0x%08" PRIX32 ")", st);
    }
}

int osciloscope_ring_parar(osciloscope_ring_h *h, int64_t plazo_ns)
{
    INICIO(h);
    return parar(h, plazo_ns);
}

int osciloscope_ring_contadores(osciloscope_ring_h *h, osciloscope_ring_contadores_t *c)
{
    INICIO(h);
    if (c == NULL)
        return MCA_EINVAL;
    mca_bus *b = h->b.bus;
    uint32_t lo, hi;
    TRY(mca_bus_r32(b, OSCILOSCOPE_RING_R_STATUS, &c->status));
    TRY(mca_bus_r32(b, OSCILOSCOPE_RING_R_EV_CNT, &c->ev_cnt));
    TRY(mca_bus_r32(b, OSCILOSCOPE_RING_R_DROP_BUSY, &c->drop_busy));
    TRY(mca_bus_r32(b, OSCILOSCOPE_RING_R_DROP_FULL, &c->drop_full));
    TRY(mca_bus_r32(b, OSCILOSCOPE_RING_R_WR_SLOT, &c->wr_slot));
    TRY(mca_bus_r32(b, OSCILOSCOPE_RING_R_RD_SLOT, &c->rd_slot));
    TRY(mca_bus_r32(b, OSCILOSCOPE_RING_R_SEQ, &c->seq));
    TRY(mca_bus_r32(b, OSCILOSCOPE_RING_R_N_SLOTS, &c->n_slots));
    TRY(mca_bus_r32(b, OSCILOSCOPE_RING_R_LVL, &c->lvl));
    TRY(mca_bus_r32(b, OSCILOSCOPE_RING_R_AXI_ADDR, &c->axi_addr));
    TRY(mca_bus_r32(b, OSCILOSCOPE_RING_R_TS_LO, &lo));
    TRY(mca_bus_r32(b, OSCILOSCOPE_RING_R_TS_HI, &hi));
    c->ts = ((uint64_t)hi << 32) | lo;
    return MCA_OK;
}

/* Escribe y relee: un registro de geometria que no quedo es un ring que no esta
 * parado (err_cfg) o uno que no es este. */
static int poner(osciloscope_ring_h *h, uint32_t off, const char *nombre, uint32_t v)
{
    uint32_t r;
    TRY(mca_bus_w32(h->b.bus, off, v));
    TRY(mca_bus_r32(h->b.bus, off, &r));
    if (r != v)
        return fallar(h, MCA_EVERIFY, "%s: se escribi\xc3\xb3 %" PRIu32 " y se ley\xc3\xb3 "
                      "%" PRIu32, nombre, v, r);
    return MCA_OK;
}

int osciloscope_ring_configurar(osciloscope_ring_h *h, const osciloscope_ring_cfg_t *cfg,
                                osciloscope_ring_estado_t *st)
{
    INICIO(h);
    if (cfg == NULL || st == NULL)
        return MCA_EINVAL;
    osciloscope_ring_geometria_t g;
    osc_cal_t cal[OSCILOSCOPE_N_APERTURAS];
    TRY(validar(h, cfg, &g, cal));

    uint8_t *slot = realloc(h->slot, g.slot_bytes);
    if (slot == NULL)
        return MCA_ENOMEM;
    h->slot = slot;
    h->slot_len = g.slot_bytes;

    /* Parado del todo: la geometria se toma solo en STOPPED. */
    TRY(parar(h, osciloscope_ahora_ns() + 500000000LL));
    TRY(mca_bus_w32(h->b.bus, OSCILOSCOPE_RING_R_CTRL, OSCILOSCOPE_RING_CTRL_CLR));

    /* El slot k de la corrida anterior tiene el mismo seq que el de esta, y un footer
     * valido: sin borrarlo, la primera vuelta podria entregarlo. */
    const uint64_t cero = 0;
    for (uint32_t i = 0; i < g.n_slots; i++) {
        int rc = mca_mem_write(h->ddr, ((i + 1u) << g.slot_shift) - OSCILOSCOPE_RING_FOOTER,
                               OSCILOSCOPE_RING_FOOTER, &cero);
        if (rc == MCA_ENOSYS)
            return fallar(h, rc, "la regi\xc3\xb3n de DDR es de solo lectura: hace falta "
                          "escribirla para borrar los footers");
        TRY(rc);
    }
    __sync_synchronize();       /* los footers en cero, antes de que el ring corra */

    TRY(poner(h, OSCILOSCOPE_RING_R_SLOT_BASE, "SLOT_BASE", mca_mem_phys(h->ddr)));
    TRY(poner(h, OSCILOSCOPE_RING_R_RING_SZ, "RING_SZ", g.ring_bytes));
    TRY(poner(h, OSCILOSCOPE_RING_R_SLOT_SHIFT, "SLOT_SHIFT", g.slot_shift));
    TRY(poner(h, OSCILOSCOPE_RING_R_PRE, "PRE", cfg->pre));
    TRY(poner(h, OSCILOSCOPE_RING_R_POST, "POST", cfg->post));

    uint32_t n, s, wr, busy, full;
    TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_N_SLOTS, &n));
    if (n != g.n_slots)
        return fallar(h, MCA_EVERIFY, "N_SLOTS=%" PRIu32 ", esperaba %" PRIu32, n,
                      g.n_slots);
    TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_STATUS, &s));
    if (s & OSCILOSCOPE_RING_ST_ERR_CFG)
        return fallar(h, MCA_EVERIFY, "err_cfg prendido despu\xc3\xa9s de configurar "
                      "(STATUS=0x%08" PRIX32 "): se escribi\xc3\xb3 la geometr\xc3\xad"
                      "a con el ring corriendo", s);
    TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_WR_SLOT, &wr));
    TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_DROP_BUSY, &busy));
    TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_DROP_FULL, &full));
    if (wr != 0)
        return fallar(h, MCA_EVERIFY, "WR_SLOT=%" PRIu32 " despu\xc3\xa9s de clr: el ring "
                      "no se limpi\xc3\xb3", wr);

    memset(st, 0, sizeof(*st));
    st->slot_shift = g.slot_shift;
    st->n_slots = g.n_slots;
    st->drop_prev = busy + full;
    return MCA_OK;
}

/* =========================================================================
 * El lazo
 * ========================================================================= */

static int footer_listo(uint64_t f, uint32_t seq)
{
    uint32_t lo = (uint32_t)f, hi = (uint32_t)(f >> 32);
    return hi == (uint32_t)~lo && lo == seq;
}

/* Los descartados que conto el hardware desde la ultima lectura. Contadores libres de
 * 32 b: la resta cierra en modulo 2^32. */
static int descartes(osciloscope_ring_h *h, osciloscope_ring_estado_t *st,
                     osciloscope_lote_resultado_t *res)
{
    uint32_t busy, full;
    TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_DROP_BUSY, &busy));
    TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_DROP_FULL, &full));
    uint32_t d = busy + full, nuevos = d - st->drop_prev;
    st->drop_prev = d;
    st->pendientes += nuevos;
    res->descartados += nuevos;
    return MCA_OK;
}

/* Devuelve los creditos: una escritura, despues de terminar de leer los slots. */
static int publicar(osciloscope_ring_h *h, osciloscope_ring_estado_t *st)
{
    if (st->next == st->publicado)
        return MCA_OK;
    __sync_synchronize();       /* los datos leidos antes de liberar el slot */
    TRY(mca_bus_w32(h->b.bus, OSCILOSCOPE_RING_R_RD_SLOT, st->next));
    st->publicado = st->next;
    return MCA_OK;
}

static uint32_t minimo(uint32_t a, uint32_t b)
{
    return a < b ? a : b;
}

/* Un slot ya validado por su footer, a la fila i del lote. */
static int leer_slot(osciloscope_ring_h *h, const osciloscope_ring_cfg_t *c,
                     const osciloscope_ring_estado_t *st, const osc_cal_t *cal,
                     const osciloscope_ring_lote_t *lote, uint32_t i, uint32_t seq,
                     int64_t t)
{
    const uint32_t N = OSCILOSCOPE_RING_N_CH, S = c->pre + c->post;
    const uint32_t off = (seq % st->n_slots) << st->slot_shift;
    const uint32_t datos = (S * N * 2u + 7u) & ~7u;
    TRY(mca_mem_read(h->ddr, off, OSCILOSCOPE_RING_HDR + datos, h->slot));

    uint64_t w[4];
    memcpy(w, h->slot, sizeof(w));          /* little-endian, como el A9 */
    const uint32_t seq_h = (uint32_t)w[1];
    const uint32_t n_samp = (uint32_t)(w[1] >> 32) & 0xFFFFu;
    const uint32_t n_ch = (uint32_t)(w[1] >> 48) & 0xFFu;
    if (seq_h != seq)
        return fallar(h, MCA_EVERIFY, "slot %" PRIu32 ": el footer dice seq=%" PRIu32
                      " y la cabecera %" PRIu32, off >> st->slot_shift, seq, seq_h);
    if (n_samp != S || n_ch != N)
        return fallar(h, MCA_EVERIFY, "slot %" PRIu32 " (seq %" PRIu32 "): trae %" PRIu32
                      " muestras de %" PRIu32 " canales, y se configur\xc3\xb3 %" PRIu32
                      " de %" PRIu32, off >> st->slot_shift, seq, n_samp, n_ch, S, N);

    if (lote->t_ns != NULL)
        lote->t_ns[i] = t;
    if (lote->wp != NULL)
        lote->wp[i] = -1;
    if (lote->snap != NULL)
        lote->snap[i] = (uint32_t)w[2] & 0x1FFFFu;
    if (lote->dead_ns != NULL)
        lote->dead_ns[i] = 0;
    if (lote->ts_hw != NULL)
        lote->ts_hw[i] = (int64_t)w[0];
    if (lote->seq != NULL)
        lote->seq[i] = seq;
    if (lote->wave != NULL) {
        const uint8_t *p = h->slot + OSCILOSCOPE_RING_HDR;
        int16_t *fila = lote->wave + (size_t)i * c->n_ch * S;
        for (uint32_t k = 0; k < c->n_ch; k++)
            for (uint32_t s = 0; s < S; s++) {
                int16_t m;
                memcpy(&m, p + 2u * (s * N + k), sizeof(m));
                fila[(size_t)k * S + s] = osc_calibrar(&cal[k], m);
            }
    }
    return MCA_OK;
}

int osciloscope_ring_leer_lote(osciloscope_ring_h *h, const osciloscope_ring_cfg_t *cfg,
                               osciloscope_ring_estado_t *st,
                               const osciloscope_ring_lote_t *lote, uint32_t n_max,
                               int64_t plazo_ns, osciloscope_lote_resultado_t *res)
{
    INICIO(h);
    if (cfg == NULL || st == NULL || res == NULL)
        return MCA_EINVAL;
    memset(res, 0, sizeof(*res));
    if (st->n_slots == 0)
        return fallar(h, MCA_EINVAL, "el ring no est\xc3\xa1 configurado: falta "
                      "osciloscope_ring_configurar");
    osciloscope_ring_geometria_t g;
    osc_cal_t cal[OSCILOSCOPE_N_APERTURAS];
    TRY(validar(h, cfg, &g, lote != NULL && lote->wave != NULL ? cal : NULL));
    if (g.slot_shift != st->slot_shift || g.n_slots != st->n_slots)
        return fallar(h, MCA_EINVAL, "la configuraci\xc3\xb3n no es la que se arm\xc3\xb3 "
                      "(slots de 2^%" PRIu32 " B x %" PRIu32 ", y configurado 2^%" PRIu32
                      " x %" PRIu32 ")", g.slot_shift, g.n_slots, st->slot_shift,
                      st->n_slots);
    if (h->slot == NULL || h->slot_len < g.slot_bytes)
        return fallar(h, MCA_EINVAL, "el ring no est\xc3\xa1 configurado en este handle");

    if (lote == NULL) {
        /* Sin destino no se consume: los eventos esperan en la DDR. */
        struct timespec ts = { (time_t)(plazo_ns / 1000000000LL),
                               (long)(plazo_ns % 1000000000LL) };
        if (plazo_ns > osciloscope_ahora_ns())
            clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL);
        return descartes(h, st, res);
    }

    while (res->n < n_max) {
        uint32_t wr;
        TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_WR_SLOT, &wr));
        const uint32_t hay = wr - st->next;
        if (hay > st->n_slots)
            return fallar(h, MCA_EVERIFY, "WR_SLOT=%" PRIu32 " con %" PRIu32 " entregados: "
                          "%" PRIu32 " slots llenos en un ring de %" PRIu32, wr, st->next,
                          hay, st->n_slots);
        uint32_t k = 0;
        if (hay != 0) {
            const uint32_t idx = st->next % st->n_slots;
            /* El bloque no da la vuelta al ring: el resto viene en el siguiente. */
            const uint32_t pedir = minimo(minimo(hay, g.lote_slots),
                                          minimo(st->n_slots - idx, n_max - res->n));
            for (; k < pedir; k++) {
                uint64_t f;
                TRY(mca_mem_read(h->ddr, ((idx + k + 1u) << st->slot_shift)
                                 - OSCILOSCOPE_RING_FOOTER, OSCILOSCOPE_RING_FOOTER, &f));
                if (!footer_listo(f, st->next + k))
                    break;      /* todavia en vuelo: se vuelve a pedir */
            }
        }
        if (k == 0) {
            TRY(publicar(h, st));
            if (osciloscope_ahora_ns() > plazo_ns)
                break;
            continue;
        }

        __sync_synchronize();   /* los footers antes que los datos */
        TRY(descartes(h, st, res));
        const int64_t t = osciloscope_ahora_ns();
        for (uint32_t j = 0; j < k; j++) {
            const uint32_t i = res->n;
            TRY(leer_slot(h, cfg, st, cal, lote, i, st->next, t));
            if (lote->gap != NULL)
                lote->gap[i] = st->pendientes < 255u ? (uint8_t)st->pendientes : 255u;
            res->asignados += st->pendientes;
            st->pendientes = 0;
            st->next++;
            res->n = i + 1;
        }
        TRY(publicar(h, st));
        /* Con eventos sin pausa nunca falta un slot: el plazo se mira tambien aca. */
        if (t > plazo_ns)
            break;
    }
    TRY(publicar(h, st));
    /* Los de despues del ultimo bloque quedan pendientes: van al gap del proximo
     * evento, o son los del final de la corrida. */
    return descartes(h, st, res);
}

/* =========================================================================
 * Medir la tasa
 * ========================================================================= */

/* El ancho de la muestra del ring (DW de event_ring_top): el patron es de 14 bits. */
#define RING_DW 14u

void osciloscope_ring_medida_cero(osciloscope_ring_medida_t *m)
{
    if (m == NULL)
        return;
    memset(m, 0, sizeof(*m));
    m->primer_error_seq = UINT32_MAX;
    m->k_ultimo = -1;
}

static void marcar_error(osciloscope_ring_medida_t *m, uint32_t seq)
{
    if (m->primer_error_seq == UINT32_MAX)
        m->primer_error_seq = seq;
}

/* La palabra de 14 bits con el signo extendido, como la guarda el slot. */
static int16_t con_signo(uint32_t x)
{
    const uint32_t m = 1u << (RING_DW - 1u);
    return (int16_t)((int32_t)((x & ((1u << RING_DW) - 1u)) ^ m) - (int32_t)m);
}

/* k y ts del slot contra el anterior y, si se conoce, contra el motor. */
static void verificar_k(osciloscope_ring_medida_t *m, const gen_disparos_cfg_t *gen,
                        uint32_t snap, int64_t ts, uint32_t seq)
{
    const int hay_previo = m->k_ultimo >= 0;
    const uint32_t k16 = snap & 0xFFFFu;
    int err_k = 0, err_ts = 0;
    int64_t k;
    if (hay_previo) {
        /* El mismo k16 da k = k_ultimo: k repetido, salvo que la marca del periodico
         * diga que faltaron 65 536 justos. */
        k = m->k_ultimo + (int64_t)((k16 - (uint32_t)m->k_ultimo) & 0xFFFFu);
    } else {
        k = k16;
    }
    if (gen != NULL && !gen->aleatorio) {
        /* Periodico: la marca da k exacto, sin la vuelta de 16 bits. */
        const int64_t per = gen->periodo < 2u ? 2 : (int64_t)gen->periodo;
        const int64_t num = ts - (int64_t)OSCILOSCOPE_RING_GEN_LAT_TS + 1;
        if (num <= 0 || num % per != 0) {
            err_ts = 1;
        } else {
            const int64_t kt = num / per - 1;
            if ((uint32_t)(kt & 0xFFFF) != k16)
                err_k = 1;
            else
                k = kt;
        }
    } else if (gen != NULL) {
        /* Aleatorio: al menos dt_min ciclos por cada k. */
        const int64_t dtm = (gen->dt_min & 0xFFFFu) < 2u ? 2 : (int64_t)(gen->dt_min & 0xFFFFu);
        if (hay_previo ? ts - m->ts_ultimo < dtm * (k - m->k_ultimo)
                       : ts < (int64_t)OSCILOSCOPE_RING_GEN_LAT_TS + dtm * k)
            err_ts = 1;
    }
    if (hay_previo && ts <= m->ts_ultimo)
        err_ts = 1;
    if (hay_previo && k <= m->k_ultimo)
        err_k = 1;
    if (gen != NULL && gen->n != 0 && k >= (int64_t)gen->n)
        err_k = 1;
    m->err_k += (uint64_t)err_k;
    m->err_ts += (uint64_t)err_ts;
    if (err_k || err_ts)
        marcar_error(m, seq);
    if (!hay_previo || k > m->k_ultimo) {
        m->k_saltos += (uint64_t)(k - (hay_previo ? m->k_ultimo + 1 : 0));
        m->k_ultimo = k;
    }
    m->ts_ultimo = ts;
}

/* Un slot copiado en h->slot, contra lo que pone el generador con el patron. */
static void verificar_slot(osciloscope_ring_h *h, const osciloscope_ring_cfg_t *c,
                           const gen_disparos_cfg_t *gen, uint32_t seq,
                           osciloscope_ring_medida_t *m)
{
    const uint32_t N = OSCILOSCOPE_RING_N_CH, S = c->pre + c->post;
    uint64_t w[4];
    memcpy(w, h->slot, sizeof(w));
    const uint32_t n_samp = (uint32_t)(w[1] >> 32) & 0xFFFFu;
    const uint32_t n_ch = (uint32_t)(w[1] >> 48) & 0xFFu;
    if ((uint32_t)w[1] != seq || n_samp != S || n_ch != N) {
        /* Sin la cabecera no se sabe de donde es el resto: no se mira mas. */
        m->err_cabecera++;
        marcar_error(m, seq);
        return;
    }
    const int64_t ts = (int64_t)w[0];
    const uint32_t snap = (uint32_t)w[2] & 0x1FFFFu;
    if (snap & OSCILOSCOPE_RING_GEN_SNAP_MARCA) {
        verificar_k(m, gen, snap, ts, seq);
    } else {
        m->err_marca++;
        marcar_error(m, seq);
    }

    /* ch0[j] = (ts - pre + j) mod 2^14 y ch1[j] = ~ch0[j], con signo; los canales
     * pares como el 0 y los impares como el 1. */
    const uint8_t *p = h->slot + OSCILOSCOPE_RING_HDR;
    uint64_t malas = 0;
    for (uint32_t j = 0; j < S; j++) {
        const int64_t t = ts - (int64_t)c->pre + (int64_t)j;
        if (t < 0)
            continue;               /* de antes del arranque: lo que quedo en el buffer */
        const int16_t par = con_signo((uint32_t)t), impar = (int16_t)~par;
        for (uint32_t k = 0; k < N; k++) {
            int16_t v;
            memcpy(&v, p + 2u * (j * N + k), sizeof(v));
            malas += v != ((k & 1u) ? impar : par);
        }
    }
    if (malas) {
        m->err_patron++;
        m->muestras_malas += malas;
        marcar_error(m, seq);
    }
}

int osciloscope_ring_medir(osciloscope_ring_h *h, const osciloscope_ring_cfg_t *cfg,
                           osciloscope_ring_estado_t *st, uint32_t modo,
                           const gen_disparos_cfg_t *gen, uint32_t n_max,
                           int64_t plazo_ns, osciloscope_ring_medida_t *m)
{
    INICIO(h);
    if (cfg == NULL || st == NULL || m == NULL)
        return MCA_EINVAL;
    if (modo > OSCILOSCOPE_RING_MEDIR_VERIFICAR)
        return fallar(h, MCA_EINVAL, "modo=%" PRIu32 ": es 0 (cr\xc3\xa9" "ditos), 1 "
                      "(copia) o 2 (verificar)", modo);
    if (gen != NULL)
        TRY(gen_disparos_validar_en(&h->b, gen));
    if (st->n_slots == 0)
        return fallar(h, MCA_EINVAL, "el ring no est\xc3\xa1 configurado: falta "
                      "osciloscope_ring_configurar");
    osciloscope_ring_geometria_t g;
    TRY(validar(h, cfg, &g, NULL));
    if (g.slot_shift != st->slot_shift || g.n_slots != st->n_slots)
        return fallar(h, MCA_EINVAL, "la configuraci\xc3\xb3n no es la que se arm\xc3\xb3 "
                      "(slots de 2^%" PRIu32 " B x %" PRIu32 ", y configurado 2^%" PRIu32
                      " x %" PRIu32 ")", g.slot_shift, g.n_slots, st->slot_shift,
                      st->n_slots);
    if (h->slot == NULL || h->slot_len < g.slot_bytes)
        return fallar(h, MCA_EINVAL, "el ring no est\xc3\xa1 configurado en este handle");

    const uint32_t N = OSCILOSCOPE_RING_N_CH;
    const uint32_t datos = ((cfg->pre + cfg->post) * N * 2u + 7u) & ~7u;
    uint32_t n = 0;
    while (n < n_max) {
        uint32_t wr;
        TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_WR_SLOT, &wr));
        m->sondeos++;
        const uint32_t hay = wr - st->next;
        if (hay > st->n_slots)
            return fallar(h, MCA_EVERIFY, "WR_SLOT=%" PRIu32 " con %" PRIu32 " entregados: "
                          "%" PRIu32 " slots llenos en un ring de %" PRIu32, wr, st->next,
                          hay, st->n_slots);
        /* Lo que el hardware ve ocupado: el credito ya se devolvio hasta next. */
        if (hay > m->ocupacion_max)
            m->ocupacion_max = hay;
        if (hay == 0) {
            if (osciloscope_ahora_ns() > plazo_ns)
                break;
            continue;
        }
        const int64_t t = osciloscope_ahora_ns();
        uint32_t k = 0;
        if (modo == OSCILOSCOPE_RING_MEDIR_CREDITOS) {
            k = minimo(hay, n_max - n);
            st->next += k;
        } else {
            const uint32_t idx = st->next % st->n_slots;
            const uint32_t pedir = minimo(minimo(hay, g.lote_slots),
                                          minimo(st->n_slots - idx, n_max - n));
            for (; k < pedir; k++) {
                uint64_t f;
                TRY(mca_mem_read(h->ddr, ((idx + k + 1u) << st->slot_shift)
                                 - OSCILOSCOPE_RING_FOOTER, OSCILOSCOPE_RING_FOOTER, &f));
                if (!footer_listo(f, st->next + k))
                    break;      /* todavia en vuelo: se vuelve a pedir */
            }
            if (k == 0) {
                TRY(publicar(h, st));
                if (t > plazo_ns)
                    break;
                continue;
            }
            __sync_synchronize();   /* los footers antes que los datos */
            for (uint32_t j = 0; j < k; j++) {
                const uint32_t off = ((idx + j) % st->n_slots) << st->slot_shift;
                TRY(mca_mem_read(h->ddr, off, OSCILOSCOPE_RING_HDR + datos, h->slot));
                if (modo == OSCILOSCOPE_RING_MEDIR_VERIFICAR)
                    verificar_slot(h, cfg, gen, st->next, m);
                st->next++;
            }
            m->bytes += (uint64_t)k * (OSCILOSCOPE_RING_HDR + datos);
        }
        TRY(publicar(h, st));
        if (m->eventos == 0)
            m->t0_ns = t;
        n += k;
        m->eventos += k;
        m->bloques++;
        m->t1_ns = osciloscope_ahora_ns();
        m->trabajo_ns += m->t1_ns - t;
        if (m->t1_ns > plazo_ns)
            break;
    }
    TRY(publicar(h, st));
    /* Los descartados, una vez por llamada: medir no asigna gaps. */
    uint32_t busy, full;
    TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_DROP_BUSY, &busy));
    TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_DROP_FULL, &full));
    const uint32_t d = busy + full, nuevos = d - st->drop_prev;
    st->drop_prev = d;
    st->pendientes += nuevos;
    m->descartados += nuevos;
    return MCA_OK;
}

/* =========================================================================
 * El generador de eventos
 * ========================================================================= */

#define GEN_BASE OSCILOSCOPE_RING_R_GEN_CTRL

int osciloscope_ring_gen_presente(osciloscope_ring_h *h, int32_t *si)
{
    INICIO(h);
    if (si == NULL)
        return MCA_EINVAL;
    uint32_t magic;
    TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_GEN_MAGIC, &magic));
    *si = magic == OSCILOSCOPE_RING_GEN_MAGIC;
    return MCA_OK;
}

int osciloscope_ring_gen_configurar(osciloscope_ring_h *h, const gen_disparos_cfg_t *d,
                                    int32_t patron)
{
    INICIO(h);
    if (patron != 0 && patron != 1)
        return fallar(h, MCA_EINVAL, "patron = %" PRId32 ": es 0 o 1", patron);
    uint32_t magic, st;
    TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_GEN_MAGIC, &magic));
    if (magic != OSCILOSCOPE_RING_GEN_MAGIC)
        return fallar(h, MCA_ENOSYS, "el ring de este bitstream no tiene el generador "
                      "(EN_GEN = 0): GEN_MAGIC 0x%08" PRIX32 " en 0x120; se esperaba "
                      "0x%08" PRIX32 ", \"GEN1\"", magic, OSCILOSCOPE_RING_GEN_MAGIC);
    TRY(mca_bus_r32(h->b.bus, OSCILOSCOPE_RING_R_STATUS, &st));
    if ((st & OSCILOSCOPE_RING_ST_ESTADO) != 0)
        return fallar(h, MCA_EINVAL, "el ring est\xc3\xa1 corriendo (STATUS=0x%08" PRIX32
                      "): el generador se configura con el ring parado, para que GEN_CNT "
                      "y EV_CNT cuenten desde el mismo arranque", st);
    if (d != NULL)
        TRY(gen_disparos_validar_en(&h->b, d));
    TRY(mca_bus_w32(h->b.bus, GEN_BASE, 0));
    if (d != NULL)
        TRY(gen_disparos_escribir(&h->b, GEN_BASE, d));
    const uint32_t ctrl = (d != NULL ? OSCILOSCOPE_RING_GEN_CTRL_EN : 0u)
                        | (d != NULL && d->aleatorio ? OSCILOSCOPE_RING_GEN_CTRL_ALEATORIO : 0u)
                        | (patron ? OSCILOSCOPE_RING_GEN_CTRL_PATRON : 0u);
    return gen_poner(&h->b, GEN_BASE, "GEN_CTRL", ctrl, ctrl);
}

int osciloscope_ring_gen_apagar(osciloscope_ring_h *h)
{
    INICIO(h);
    return mca_bus_w32(h->b.bus, GEN_BASE, 0);
}

int osciloscope_ring_gen_estado(osciloscope_ring_h *h, gen_estado_t *e)
{
    INICIO(h);
    return gen_estado_leer(&h->b, GEN_BASE, e);
}

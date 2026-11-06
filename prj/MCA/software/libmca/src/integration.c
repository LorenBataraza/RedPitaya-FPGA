/* La region de TOP en C: identificacion, descubrimiento y ruteo (slot 6).
 *
 * La referencia es API/ref_py/integration.py y la regla es la de mca.c: para
 * cada funcion publica, las dos hacen las MISMAS escrituras en el MISMO orden y
 * devuelven lo mismo, tambien en los casos de error. Lo comprueba
 * API/tests/test_libmca_integration.py contra un modelo de registros.
 *
 * Nada de este fichero toca memoria de dispositivo: todo pasa por mca_bus.
 */
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bloque.h"
#include "integration.h"

struct integration_h {
    mca_bloque b;               /* primer miembro: ver bloque.h */
};

#define fallar(h, ...) bloque_fallar((mca_bloque *)(h), __VA_ARGS__)

static int rd(integration_h *h, uint32_t off, uint32_t *v)
{
    return mca_bus_r32(h->b.bus, off, v);
}

static int wr(integration_h *h, uint32_t off, uint32_t v)
{
    return mca_bus_w32(h->b.bus, off, v);
}

/* =========================================================================
 * Tablas
 * ========================================================================= */

#define X_REG(n, off) { "R_" #n, off },
static const mca_reg_t REGS[] = { INTEGRATION_REGS(X_REG) };
#undef X_REG

int32_t integration_reg_count(void)
{
    return (int32_t)(sizeof(REGS) / sizeof(REGS[0]));
}

const mca_reg_t *integration_reg_info(int32_t i)
{
    return (i >= 0 && i < integration_reg_count()) ? &REGS[i] : NULL;
}

/* El nativo de cada consumidor, para informarlo sin adivinar. El del
 * multitrigger NO es ninguno de los tres taps: es adc_dly_in, post-decimacion
 * pero pre-delay. Por eso TAP_NATIVE existe como valor aparte. */
static const struct {
    const char *nombre, *mayus, *nativo;
    uint32_t reg;
} RUTAS[INTEGRATION_N_CONSUMIDORES] = {
    { "osc",  "OSC",  "adc_bram_in (nativo)", INTEGRATION_R_ROUTE_OSC  },
    { "mtrg", "MTRG", "adc_dly_in (nativo)",  INTEGRATION_R_ROUTE_MTRG },
    { "mca",  "MCA",  "adc_dec_in (nativo)",  INTEGRATION_R_ROUTE_MCA  },
    { "ring", "RING", "adc_dec_in (nativo)",  INTEGRATION_R_ROUTE_RING },
};

/* La lista canonica vive en integration_cfg.sv. El nativo sale de RUTAS. */
static const char *const TAPS[INTEGRATION_N_TAPS] = {
    NULL, "adc_dat", "adc_dec_in", "adc_bram_in",
};

static const char *const SLOTS[INTEGRATION_N_SLOTS] = {
    "osc", "ring", "mtrg", "top", "mca",
};

const char *integration_consumidor_name(int32_t i)
{
    return (i >= 0 && i < INTEGRATION_N_CONSUMIDORES) ? RUTAS[i].nombre : NULL;
}

const char *integration_slot_name(int32_t i)
{
    return (i >= 0 && i < INTEGRATION_N_SLOTS) ? SLOTS[i] : NULL;
}

size_t integration_sizeof(const char *tipo)
{
    static const struct { const char *n; size_t s; } t[] = {
        { "integration_info_t",    sizeof(integration_info_t) },
        { "integration_modules_t", sizeof(integration_modules_t) },
        { "integration_slots_t",   sizeof(integration_slots_t) },
        { "integration_caps_t",    sizeof(integration_caps_t) },
        { "integration_route_t",   sizeof(integration_route_t) },
        { "integration_status_t",  sizeof(integration_status_t) },
    };
    for (size_t i = 0; tipo != NULL && i < sizeof(t) / sizeof(t[0]); i++)
        if (strcmp(tipo, t[i].n) == 0)
            return t[i].s;
    return 0;
}

/* =========================================================================
 * Ciclo de vida
 * ========================================================================= */

/* `donde` es la base en hexa si se conoce, para el mensaje de magic malo. */
static int abrir_sobre(integration_h **h, mca_bus *bus, int propio, int check_magic,
                       const char *donde)
{
    if (h == NULL || bus == NULL)
        return MCA_EINVAL;
    *h = NULL;
    bloque_limpiar_apertura();

    if (check_magic) {
        uint32_t magic;
        TRY(mca_bus_r32(bus, INTEGRATION_R_MAGIC, &magic));
        if (magic != INTEGRATION_MAGIC)
            return bloque_fallar(NULL, MCA_ENOTPRESENT,
                                 "MAGIC 0x%08" PRIx32 " en %s, esperado 0x%08" PRIx32
                                 " (\"INTG\"). El bitstream no tiene regi\xc3\xb3n de "
                                 "TOP: es anterior al refactor de registros, o el "
                                 "slot 6 lo ocupa otra cosa.",
                                 magic, donde, (uint32_t)INTEGRATION_MAGIC);
    }
    integration_h *n = calloc(1, sizeof(*n));
    if (n == NULL)
        return MCA_ENOMEM;
    n->b.bus = bus;
    n->b.propio = propio;
    *h = n;
    return MCA_OK;
}

int integration_open_bus(integration_h **h, mca_bus *bus, int propio, int check_magic)
{
    return abrir_sobre(h, bus, propio, check_magic, "el bus");
}

int integration_open(integration_h **h, uint32_t phys, uint32_t size, int check_magic)
{
    if (h == NULL)
        return MCA_EINVAL;
    *h = NULL;
    bloque_limpiar_apertura();
    mca_bus *b;
    TRY(bloque_abrir_devmem(&b, phys, size));
    char donde[16];
    snprintf(donde, sizeof(donde), "0x%08" PRIx32, phys);
    int rc = abrir_sobre(h, b, 1, check_magic, donde);
    if (rc != MCA_OK)
        mca_bus_close(b);
    return rc;
}

void integration_close(integration_h *h)
{
    if (h == NULL)
        return;
    if (h->b.propio)
        mca_bus_close(h->b.bus);
    free(h);
}

const char *integration_last_error(const integration_h *h)
{
    return bloque_ultimo_error((const mca_bloque *)h);
}

/* =========================================================================
 * Acceso crudo
 * ========================================================================= */

int integration_r32(integration_h *h, uint32_t off, uint32_t *v)
{
    INICIO(h);
    return rd(h, off, v);
}

int integration_w32(integration_h *h, uint32_t off, uint32_t v)
{
    INICIO(h);
    return wr(h, off, v);
}

/* =========================================================================
 * Identificacion y descripcion del sistema
 * ========================================================================= */

int integration_identify(integration_h *h, integration_info_t *info)
{
    INICIO(h);
    if (info == NULL)
        return MCA_EINVAL;
    uint32_t v;
    TRY(rd(h, INTEGRATION_R_VERSION, &v));
    info->version[0] = (v >> 24) & 0xFFu;
    info->version[1] = (v >> 16) & 0xFFu;
    info->version[2] = (v >> 8) & 0xFFu;
    info->version[3] = v & 0xFFu;
    TRY(rd(h, INTEGRATION_R_MAGIC, &info->magic));
    /* La palabra alta del hash primero: es como se lee un hash de git. */
    for (int i = 0; i < 5; i++) {
        uint32_t w;
        TRY(rd(h, INTEGRATION_R_GITH_4 - 4u * (uint32_t)i, &w));
        snprintf(&info->gith[8 * i], 9, "%08" PRIx32, w);
    }
    return MCA_OK;
}

int integration_get_modules(integration_h *h, integration_modules_t *m)
{
    INICIO(h);
    if (m == NULL)
        return MCA_EINVAL;
    uint32_t w;
    TRY(rd(h, INTEGRATION_R_MODULES, &w));
    m->osc  = (w & INTEGRATION_MOD_OSC) != 0;
    m->mtrg = (w & INTEGRATION_MOD_MTRG) != 0;
    m->mca  = (w & INTEGRATION_MOD_MCA) != 0;
    m->ring = (w & INTEGRATION_MOD_RING) != 0;
    m->asg  = (w & INTEGRATION_MOD_ASG) != 0;
    m->pid  = (w & INTEGRATION_MOD_PID) != 0;
    return MCA_OK;
}

int integration_get_slots(integration_h *h, integration_slots_t *s)
{
    INICIO(h);
    if (s == NULL)
        return MCA_EINVAL;
    uint32_t w;
    TRY(rd(h, INTEGRATION_R_SLOTS, &w));
    s->osc  = (w >> 0) & 0xFu;
    s->ring = (w >> 4) & 0xFu;
    s->mtrg = (w >> 8) & 0xFu;
    s->top  = (w >> 12) & 0xFu;
    s->mca  = (w >> 16) & 0xFu;
    return MCA_OK;
}

int integration_get_base(integration_h *h, int32_t slot, uint32_t *base)
{
    INICIO(h);
    if (base == NULL)
        return MCA_EINVAL;
    if (slot < 0 || slot >= INTEGRATION_N_SLOTS)
        return MCA_ENOKEY;
    uint32_t w;
    TRY(rd(h, INTEGRATION_R_SLOTS, &w));
    *base = INTEGRATION_BUS_BASE
            + ((w >> (4 * slot)) & 0xFu) * INTEGRATION_BUS_SLOT;
    return MCA_OK;
}

int integration_get_caps(integration_h *h, integration_caps_t *c)
{
    INICIO(h);
    if (c == NULL)
        return MCA_EINVAL;
    uint32_t c0, c1;
    TRY(rd(h, INTEGRATION_R_CAPS_0, &c0));
    TRY(rd(h, INTEGRATION_R_CAPS_1, &c1));
    c->n_ch    = (c0 >> 0) & 0xFu;
    c->dw      = (c0 >> 8) & 0x3Fu;
    c->rsz     = (c0 >> 16) & 0x3Fu;
    c->en_filt = (c0 & (1u << 24)) != 0;
    c->h_aw    = (c1 >> 0) & 0xFFu;
    c->h2_aw   = (c1 >> 8) & 0xFFu;
    c->psd_aw  = (c1 >> 16) & 0xFFu;
    return MCA_OK;
}

/* =========================================================================
 * Ruteo del datapath
 * ========================================================================= */

/* El registro: {en[8], tap[1:0]}. */
#define ROUTE_EN        (1u << 8)
#define ROUTE_TAP       0x3u

static int consumidor_valido(int32_t c)
{
    return c >= 0 && c < INTEGRATION_N_CONSUMIDORES;
}

static int leer_ruta(integration_h *h, int32_t c, integration_route_t *r)
{
    uint32_t w;
    TRY(rd(h, RUTAS[c].reg, &w));
    r->tap = w & ROUTE_TAP;
    r->nombre = r->tap == INTEGRATION_TAP_NATIVE ? RUTAS[c].nativo : TAPS[r->tap];
    r->enable = (w & ROUTE_EN) != 0;
    return MCA_OK;
}

int integration_get_route(integration_h *h, int32_t consumidor, integration_route_t *r)
{
    INICIO(h);
    if (r == NULL)
        return MCA_EINVAL;
    if (!consumidor_valido(consumidor))
        return MCA_ENOKEY;
    return leer_ruta(h, consumidor, r);
}

int integration_get_routes(integration_h *h, integration_route_t *r, int32_t n)
{
    INICIO(h);
    if (r == NULL || n != INTEGRATION_N_CONSUMIDORES)
        return MCA_EINVAL;
    for (int32_t c = 0; c < INTEGRATION_N_CONSUMIDORES; c++)
        TRY(leer_ruta(h, c, &r[c]));
    return MCA_OK;
}

#define TAPS_VALIDOS "usar TAP_NATIVE/TAP_ADC/TAP_DEC_IN/TAP_BRAM_IN"

static int escribir_ruta(integration_h *h, int32_t consumidor, int64_t tap,
                         int32_t enable, int32_t verify)
{
    if (tap == INTEGRATION_TAP_NO_ENTERO)
        return fallar(h, MCA_EINVAL, "tap inv\xc3\xa1lido; " TAPS_VALIDOS);
    if (tap < 0 || tap >= INTEGRATION_N_TAPS)
        return fallar(h, MCA_EINVAL, "tap %" PRId64 " inv\xc3\xa1lido; " TAPS_VALIDOS,
                      tap);
    if (!consumidor_valido(consumidor))
        return MCA_ENOKEY;
    uint32_t esperado = (uint32_t)tap | (enable ? ROUTE_EN : 0u);
    TRY(wr(h, RUTAS[consumidor].reg, esperado));
    if (verify) {
        uint32_t rb;
        TRY(rd(h, RUTAS[consumidor].reg, &rb));
        if ((rb & (ROUTE_EN | ROUTE_TAP)) != esperado)
            return fallar(h, MCA_EVERIFY,
                          "ROUTE_%s no latche\xc3\xb3: 0x%08" PRIx32 " != 0x%08" PRIx32,
                          RUTAS[consumidor].mayus, rb, esperado);
    }
    return MCA_OK;
}

int integration_set_route(integration_h *h, int32_t consumidor, int64_t tap,
                          int32_t enable, int32_t verify)
{
    INICIO(h);
    return escribir_ruta(h, consumidor, tap, enable, verify);
}

int integration_reset_routes(integration_h *h)
{
    INICIO(h);
    for (int32_t c = 0; c < INTEGRATION_N_CONSUMIDORES; c++)
        TRY(escribir_ruta(h, c, INTEGRATION_TAP_NATIVE, 1, 1));
    return MCA_OK;
}

/* =========================================================================
 * Control y estado global
 * ========================================================================= */

int integration_set_run(integration_h *h, int32_t on)
{
    INICIO(h);
    return wr(h, INTEGRATION_R_CTRL, on ? INTEGRATION_CTRL_RUN : 0u);
}

int integration_get_run(integration_h *h, int32_t *on)
{
    INICIO(h);
    if (on == NULL)
        return MCA_EINVAL;
    uint32_t w;
    TRY(rd(h, INTEGRATION_R_CTRL, &w));
    *on = (w & INTEGRATION_CTRL_RUN) != 0;
    return MCA_OK;
}

/* Un pulso autolimpiante que conserva el bit run. */
static int pulso(integration_h *h, uint32_t bit)
{
    uint32_t w;
    TRY(rd(h, INTEGRATION_R_CTRL, &w));
    return wr(h, INTEGRATION_R_CTRL, (w & INTEGRATION_CTRL_RUN) | bit);
}

int integration_clear(integration_h *h)
{
    INICIO(h);
    return pulso(h, INTEGRATION_CTRL_CLEAR);
}

int integration_soft_reset(integration_h *h)
{
    INICIO(h);
    return pulso(h, INTEGRATION_CTRL_SRST);
}

int integration_get_status(integration_h *h, integration_status_t *st)
{
    INICIO(h);
    if (st == NULL)
        return MCA_EINVAL;
    uint32_t w;
    TRY(rd(h, INTEGRATION_R_STATUS, &w));
    st->pll_locked = (w & INTEGRATION_ST_PLL_LOCKED) != 0;
    st->adc_rstn   = (w & INTEGRATION_ST_ADC_RSTN) != 0;
    return MCA_OK;
}

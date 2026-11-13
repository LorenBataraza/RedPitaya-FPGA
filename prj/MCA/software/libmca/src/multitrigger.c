/* El multitrigger en C: la region del slot 3.
 *
 * La referencia es API/ref_py/multitrigger2.py y la regla es la de mca.c: para cada
 * funcion publica, las dos hacen las MISMAS escrituras en el MISMO orden y devuelven
 * lo mismo, tambien en los casos de error, y con los mismos mensajes. Lo comprueba
 * API/tests/test_libmca_multitrigger.py contra un modelo de registros.
 *
 * La excepcion deliberada es `ch` fuera de 0..3: la referencia calcula
 * base + 4 * ch y escribe en otro registro; aca es un error.
 *
 * Nada de este fichero toca memoria de dispositivo: todo pasa por mca_bus.
 */
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bloque.h"
#include "multitrigger.h"

struct multitrigger_h {
    mca_bloque b;               /* primer miembro: ver bloque.h */
};

#define fallar(h, ...) bloque_fallar((mca_bloque *)(h), __VA_ARGS__)

static int rd(multitrigger_h *h, uint32_t off, uint32_t *v)
{
    return mca_bus_r32(h->b.bus, off, v);
}

static int wr(multitrigger_h *h, uint32_t off, uint32_t v)
{
    return mca_bus_w32(h->b.bus, off, v);
}

/* =========================================================================
 * Tablas
 * ========================================================================= */

#define X_REG(n, off) { "R_" #n, off },
static const mca_reg_t REGS[] = { MULTITRIGGER_REGS(X_REG) };
#undef X_REG

#define X_CAMPO(n, reg, sh, msk) { #n, MULTITRIGGER_R_##reg, sh, msk, 0 },
static const mca_field_t CAMPOS[MULTITRIGGER_N_FIELDS] = { MULTITRIGGER_FIELDS(X_CAMPO) };
#undef X_CAMPO

int32_t multitrigger_reg_count(void)
{
    return (int32_t)(sizeof(REGS) / sizeof(REGS[0]));
}

const mca_reg_t *multitrigger_reg_info(int32_t i)
{
    return (i >= 0 && i < multitrigger_reg_count()) ? &REGS[i] : NULL;
}

int32_t multitrigger_field_count(void)
{
    return MULTITRIGGER_N_FIELDS;
}

const mca_field_t *multitrigger_field_info(int32_t i)
{
    return (i >= 0 && i < MULTITRIGGER_N_FIELDS) ? &CAMPOS[i] : NULL;
}

size_t multitrigger_sizeof(const char *tipo)
{
    static const struct { const char *n; size_t s; } t[] = {
        { "multitrigger_shield_t", sizeof(multitrigger_shield_t) },
        { "multitrigger_slope_t",  sizeof(multitrigger_slope_t) },
        { "multitrigger_pz_t",     sizeof(multitrigger_pz_t) },
        { "multitrigger_status_t", sizeof(multitrigger_status_t) },
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
static int abrir_sobre(multitrigger_h **h, mca_bus *bus, int propio, int check_magic,
                       const char *donde)
{
    if (h == NULL || bus == NULL)
        return MCA_EINVAL;
    *h = NULL;
    bloque_limpiar_apertura();

    if (check_magic) {
        uint32_t magic;
        TRY(mca_bus_r32(bus, MULTITRIGGER_R_MAGIC, &magic));
        if (magic != MULTITRIGGER_MAGIC)
            return bloque_fallar(NULL, MCA_ENOTPRESENT,
                                 "%s no es la regi\xc3\xb3n del multitrigger (MAGIC "
                                 "0x%08" PRIx32 " != 0x%08" PRIx32 "). "
                                 "Integration.base('mtrg') da el slot de este bitstream.",
                                 donde, magic, (uint32_t)MULTITRIGGER_MAGIC);
    }
    multitrigger_h *n = calloc(1, sizeof(*n));
    if (n == NULL)
        return MCA_ENOMEM;
    n->b.bus = bus;
    n->b.propio = propio;
    *h = n;
    return MCA_OK;
}

int multitrigger_open_bus(multitrigger_h **h, mca_bus *bus, int propio, int check_magic)
{
    return abrir_sobre(h, bus, propio, check_magic, "el bus");
}

int multitrigger_open(multitrigger_h **h, uint32_t phys, uint32_t size, int check_magic)
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

void multitrigger_close(multitrigger_h *h)
{
    if (h == NULL)
        return;
    if (h->b.propio)
        mca_bus_close(h->b.bus);
    free(h);
}

const char *multitrigger_last_error(const multitrigger_h *h)
{
    return bloque_ultimo_error((const mca_bloque *)h);
}

/* =========================================================================
 * Acceso crudo
 * ========================================================================= */

int multitrigger_r32(multitrigger_h *h, uint32_t off, uint32_t *v)
{
    INICIO(h);
    return rd(h, off, v);
}

int multitrigger_w32(multitrigger_h *h, uint32_t off, uint32_t v)
{
    INICIO(h);
    return wr(h, off, v);
}

/* =========================================================================
 * Validaciones y relectura
 * ========================================================================= */

static int exigir_canal(multitrigger_h *h, int64_t ch)
{
    if (ch < 0 || ch >= MULTITRIGGER_N_CH)
        return fallar(h, MCA_EINVAL, "canal %" PRId64 " fuera de 0..3", ch);
    return MCA_OK;
}

static uint32_t por_canal(uint32_t base, int64_t ch)
{
    return base + 4u * (uint32_t)ch;
}

/* Escribe, relee y exige lo escrito: lo que deja al disparo sin armar y sin ningun
 * otro sintoma. */
static int escribir_y_releer(multitrigger_h *h, uint32_t off, uint32_t v)
{
    uint32_t leido;
    TRY(wr(h, off, v));
    TRY(rd(h, off, &leido));
    if (leido != v)
        return fallar(h, MCA_EVERIFY,
                      "el registro 0x%03" PRIx32 " no retuvo lo escrito: 0x%08" PRIx32
                      " != 0x%08" PRIx32, off, leido, v);
    return MCA_OK;
}

/* =========================================================================
 * Capacidades
 * ========================================================================= */

int multitrigger_get_caps(multitrigger_h *h, uint32_t *caps)
{
    INICIO(h);
    if (caps == NULL)
        return MCA_EINVAL;
    return rd(h, MULTITRIGGER_R_CAPS, caps);
}

static int tiene(multitrigger_h *h, uint32_t bit, int32_t *si)
{
    uint32_t caps;
    TRY(rd(h, MULTITRIGGER_R_CAPS, &caps));
    *si = (caps & bit) != 0;
    return MCA_OK;
}

int multitrigger_has_slope(multitrigger_h *h, int32_t *si)
{
    INICIO(h);
    if (si == NULL)
        return MCA_EINVAL;
    return tiene(h, MULTITRIGGER_CAPS_HAS_SLOPE, si);
}

int multitrigger_has_pz(multitrigger_h *h, int32_t *si)
{
    INICIO(h);
    if (si == NULL)
        return MCA_EINVAL;
    return tiene(h, MULTITRIGGER_CAPS_HAS_PZ, si);
}

/* =========================================================================
 * Mascaras OR
 * ========================================================================= */

int multitrigger_set_or_mask(multitrigger_h *h, int64_t ch, uint32_t v)
{
    INICIO(h);
    TRY(exigir_canal(h, ch));
    return wr(h, por_canal(MULTITRIGGER_R_OR_MASK_CH0, ch), v);
}

int multitrigger_get_or_mask(multitrigger_h *h, int64_t ch, uint32_t *v)
{
    INICIO(h);
    if (v == NULL)
        return MCA_EINVAL;
    TRY(exigir_canal(h, ch));
    return rd(h, por_canal(MULTITRIGGER_R_OR_MASK_CH0, ch), v);
}

int multitrigger_set_or_masks(multitrigger_h *h, int64_t ch0, int64_t ch1)
{
    INICIO(h);
    uint32_t rb0, rb1;
    TRY(wr(h, MULTITRIGGER_R_OR_MASK_CH0, (uint32_t)ch0));
    TRY(wr(h, MULTITRIGGER_R_OR_MASK_CH1, (uint32_t)ch1));
    TRY(rd(h, MULTITRIGGER_R_OR_MASK_CH0, &rb0));
    TRY(rd(h, MULTITRIGGER_R_OR_MASK_CH1, &rb1));
    if ((int64_t)rb0 != ch0)
        return fallar(h, MCA_EVERIFY, "OR_MASK ch0 no latcheada: 0x%08" PRIx32
                      " != 0x%08" PRIx32, rb0, (uint32_t)ch0);
    if ((int64_t)rb1 != ch1)
        return fallar(h, MCA_EVERIFY, "OR_MASK ch1 no latcheada: 0x%08" PRIx32
                      " != 0x%08" PRIx32, rb1, (uint32_t)ch1);
    return MCA_OK;
}

/* =========================================================================
 * trigger_shield
 * ========================================================================= */

/* {dur[31:16], dst[12:8], src[6:0]} */
static uint32_t palabra_shield(uint32_t src, uint32_t dst, uint32_t dur)
{
    return ((dur & 0xFFFFu) << 16) | ((dst & 0x1Fu) << 8) | (src & 0x7Fu);
}

int multitrigger_set_shield(multitrigger_h *h, uint32_t src, uint32_t dst, uint32_t dur)
{
    INICIO(h);
    return wr(h, MULTITRIGGER_R_SHIELD_CFG, palabra_shield(src, dst, dur));
}

int multitrigger_get_shield(multitrigger_h *h, multitrigger_shield_t *s)
{
    INICIO(h);
    if (s == NULL)
        return MCA_EINVAL;
    uint32_t w;
    TRY(rd(h, MULTITRIGGER_R_SHIELD_CFG, &w));
    s->dur = (w >> 16) & 0xFFFFu;
    s->dst = (w >> 8) & 0x1Fu;
    s->src = w & 0x7Fu;
    return rd(h, MULTITRIGGER_R_SHIELD_RUN, &s->runtime);
}

int multitrigger_shield_autorearm(multitrigger_h *h, uint32_t channels, uint32_t dur)
{
    INICIO(h);
    /* Solo los canales del scope: no prende las entradas externas ni el veto. */
    channels &= 0xFu;
    return wr(h, MULTITRIGGER_R_SHIELD_CFG, palabra_shield(channels, channels, dur));
}

int multitrigger_disable_shield(multitrigger_h *h)
{
    INICIO(h);
    return wr(h, MULTITRIGGER_R_SHIELD_CFG, 0);
}

/* =========================================================================
 * Snapshot y flags
 * ========================================================================= */

int multitrigger_get_snapshot(multitrigger_h *h, uint32_t *v)
{
    INICIO(h);
    if (v == NULL)
        return MCA_EINVAL;
    return rd(h, MULTITRIGGER_R_TRIG_SNAP, v);
}

int multitrigger_get_flags(multitrigger_h *h, uint32_t *v)
{
    INICIO(h);
    if (v == NULL)
        return MCA_EINVAL;
    return rd(h, MULTITRIGGER_R_FLAGS, v);
}

/* =========================================================================
 * Disparo por pendiente
 * ========================================================================= */

#define NO_REARMA "hyst=%" PRId64 " >= thr=%" PRId64 ": no re-arma nunca"
#define CFG_EN    (1u << 31)

int multitrigger_set_slope(multitrigger_h *h, int64_t ch, int64_t L, int64_t G,
                           int64_t thr, int64_t hyst, int32_t en)
{
    INICIO(h);
    TRY(exigir_canal(h, ch));
    if (L < 1 || L > MULTITRIGGER_SLOPE_LMAX)
        return fallar(h, MCA_EINVAL, "L=%" PRId64 " fuera de 1..%d", L,
                      MULTITRIGGER_SLOPE_LMAX);
    if (G < 0 || G > MULTITRIGGER_SLOPE_GMAX)
        return fallar(h, MCA_EINVAL, "G=%" PRId64 " fuera de 0..%d", G,
                      MULTITRIGGER_SLOPE_GMAX);
    if (thr < 0 || thr > MULTITRIGGER_SLOPE_TMAX
        || hyst < 0 || hyst > MULTITRIGGER_SLOPE_TMAX)
        return fallar(h, MCA_EINVAL, "thr/hyst fuera de 0..%d", MULTITRIGGER_SLOPE_TMAX);
    if (en && hyst >= thr)
        return fallar(h, MCA_EINVAL, NO_REARMA, hyst, thr);
    int32_t si;
    TRY(tiene(h, MULTITRIGGER_CAPS_HAS_SLOPE, &si));
    if (!si)
        return fallar(h, MCA_ENOSYS, "el bitstream cargado no tiene disparo por "
                      "pendiente (CAPS[16] = 0)");
    uint32_t cfg = (en ? CFG_EN : 0u) | ((uint32_t)G << 8) | (uint32_t)L;
    TRY(escribir_y_releer(h, por_canal(MULTITRIGGER_R_SLOPE_THR, ch), (uint32_t)thr));
    TRY(escribir_y_releer(h, por_canal(MULTITRIGGER_R_SLOPE_HYST, ch), (uint32_t)hyst));
    return escribir_y_releer(h, por_canal(MULTITRIGGER_R_SLOPE_CFG, ch), cfg);
}

int multitrigger_get_slope(multitrigger_h *h, int64_t ch, multitrigger_slope_t *s)
{
    INICIO(h);
    if (s == NULL)
        return MCA_EINVAL;
    TRY(exigir_canal(h, ch));
    uint32_t cfg;
    TRY(rd(h, por_canal(MULTITRIGGER_R_SLOPE_CFG, ch), &cfg));
    s->en = (cfg >> 31) != 0;
    s->L = cfg & 0x1Fu;
    s->G = (cfg >> 8) & 0x1Fu;
    TRY(rd(h, por_canal(MULTITRIGGER_R_SLOPE_THR, ch), &s->thr));
    return rd(h, por_canal(MULTITRIGGER_R_SLOPE_HYST, ch), &s->hyst);
}

int multitrigger_disable_slope(multitrigger_h *h, int64_t ch)
{
    INICIO(h);
    TRY(exigir_canal(h, ch));
    return wr(h, por_canal(MULTITRIGGER_R_SLOPE_CFG, ch), 0);
}

/* =========================================================================
 * Disparo con polo-cero
 * ========================================================================= */

int multitrigger_set_pz(multitrigger_h *h, int64_t ch, int64_t k, int64_t m, int64_t mq,
                        int64_t sh, int64_t thr, int64_t hyst, int32_t en)
{
    INICIO(h);
    TRY(exigir_canal(h, ch));
    /* k + m <= LMAX, sin sumar: los dos pueden venir saturados a int64. */
    if (k < 1 || m < 0 || k > MULTITRIGGER_PZ_LMAX || m > MULTITRIGGER_PZ_LMAX - k)
        return fallar(h, MCA_EINVAL, "k=%" PRId64 ", m=%" PRId64 ": hace falta k >= 1 "
                      "y k + m <= %d", k, m, MULTITRIGGER_PZ_LMAX);
    if (mq < 0 || mq > MULTITRIGGER_PZ_MQMAX)
        return fallar(h, MCA_EINVAL, "mq=%" PRId64 " fuera de 0..%d", mq,
                      MULTITRIGGER_PZ_MQMAX);
    if (sh < 0 || sh > MULTITRIGGER_PZ_SHMAX)
        return fallar(h, MCA_EINVAL, "sh=%" PRId64 " fuera de 0..%d", sh,
                      MULTITRIGGER_PZ_SHMAX);
    if (thr < 0 || thr > MULTITRIGGER_PZ_TMAX
        || hyst < 0 || hyst > MULTITRIGGER_PZ_TMAX)
        return fallar(h, MCA_EINVAL, "thr/hyst fuera de 0..%d", MULTITRIGGER_PZ_TMAX);
    if (en && hyst >= thr)
        return fallar(h, MCA_EINVAL, NO_REARMA, hyst, thr);
    int32_t si;
    TRY(tiene(h, MULTITRIGGER_CAPS_HAS_PZ, &si));
    if (!si)
        return fallar(h, MCA_ENOSYS, "el bitstream cargado no tiene disparo con "
                      "polo-cero (CAPS[17] = 0)");
    uint32_t cfg = (en ? CFG_EN : 0u) | ((uint32_t)sh << 24) | ((uint32_t)m << 8)
                   | (uint32_t)k;
    /* Umbrales y M primero: el trapecio se habilita ya configurado. */
    TRY(escribir_y_releer(h, por_canal(MULTITRIGGER_R_PZ_THR, ch), (uint32_t)thr));
    TRY(escribir_y_releer(h, por_canal(MULTITRIGGER_R_PZ_HYST, ch), (uint32_t)hyst));
    TRY(escribir_y_releer(h, por_canal(MULTITRIGGER_R_PZ_MQ, ch), (uint32_t)mq));
    return escribir_y_releer(h, por_canal(MULTITRIGGER_R_PZ_CFG, ch), cfg);
}

int multitrigger_get_pz(multitrigger_h *h, int64_t ch, multitrigger_pz_t *p)
{
    INICIO(h);
    if (p == NULL)
        return MCA_EINVAL;
    TRY(exigir_canal(h, ch));
    uint32_t cfg;
    TRY(rd(h, por_canal(MULTITRIGGER_R_PZ_CFG, ch), &cfg));
    p->en = (cfg >> 31) != 0;
    p->k = cfg & 0x1Fu;
    p->m = (cfg >> 8) & 0x1Fu;
    p->sh = (cfg >> 24) & 0x3Fu;
    TRY(rd(h, por_canal(MULTITRIGGER_R_PZ_MQ, ch), &p->mq));
    TRY(rd(h, por_canal(MULTITRIGGER_R_PZ_THR, ch), &p->thr));
    return rd(h, por_canal(MULTITRIGGER_R_PZ_HYST, ch), &p->hyst);
}

int multitrigger_disable_pz(multitrigger_h *h, int64_t ch)
{
    INICIO(h);
    TRY(exigir_canal(h, ch));
    return wr(h, por_canal(MULTITRIGGER_R_PZ_CFG, ch), 0);
}

/* =========================================================================
 * Configuracion en bloque
 * ========================================================================= */

int multitrigger_get_config(multitrigger_h *h, uint32_t *vals, int32_t n)
{
    INICIO(h);
    if (vals == NULL || n != MULTITRIGGER_N_FIELDS)
        return MCA_EINVAL;
    for (int32_t i = 0; i < MULTITRIGGER_N_FIELDS; i++) {
        uint32_t w;
        TRY(rd(h, CAMPOS[i].offset, &w));
        vals[i] = (w >> CAMPOS[i].shift) & CAMPOS[i].mascara;
    }
    return MCA_OK;
}

int multitrigger_configure(multitrigger_h *h, const int32_t *campos,
                           const uint32_t *valores, int32_t n)
{
    INICIO(h);
    if (n < 0 || (n > 0 && (campos == NULL || valores == NULL)))
        return MCA_EINVAL;
    for (int32_t i = 0; i < n; i++)
        if (multitrigger_field_info(campos[i]) == NULL)
            return MCA_EINVAL;

    for (int32_t i = 0; i < n; i++) {
        uint32_t off = CAMPOS[campos[i]].offset;
        int ya_escrito = 0;
        for (int32_t j = 0; j < i; j++)
            ya_escrito |= CAMPOS[campos[j]].offset == off;
        if (ya_escrito)
            continue;
        uint32_t w, leido;
        TRY(rd(h, off, &w));
        for (int32_t j = i; j < n; j++) {
            const mca_field_t *c = &CAMPOS[campos[j]];
            if (c->offset == off)
                w = (w & ~(c->mascara << c->shift))
                    | ((valores[j] & c->mascara) << c->shift);
        }
        TRY(wr(h, off, w));
        TRY(rd(h, off, &leido));
        if (leido != w)
            return fallar(h, MCA_EVERIFY,
                          "el registro 0x%03" PRIx32 " no retuvo lo escrito: 0x%08" PRIx32
                          " != 0x%08" PRIx32 ". \xc2\xbf" "Es este el bitstream correcto?",
                          off, leido, w);
    }
    return MCA_OK;
}

int multitrigger_get_status(multitrigger_h *h, multitrigger_status_t *st)
{
    INICIO(h);
    if (st == NULL)
        return MCA_EINVAL;
    TRY(rd(h, MULTITRIGGER_R_TRIG_SNAP, &st->snapshot));
    TRY(rd(h, MULTITRIGGER_R_SHIELD_RUN, &st->shield_runtime));
    TRY(rd(h, MULTITRIGGER_R_FLAGS, &st->flags));
    st->shield_active = (st->shield_runtime & (1u << 16)) != 0;
    st->mca_veto = (st->shield_runtime & (1u << 17)) != 0;
    st->trig_arm = (st->shield_runtime & (1u << 18)) != 0;
    return MCA_OK;
}

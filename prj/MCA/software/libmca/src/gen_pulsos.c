/* El generador de pulsos. Ver include/gen_pulsos.h.
 *
 * La referencia es gen_pulsos.sv (los anchos de cada registro, la tabla con el
 * signo extendido al leerla) y su modelo, gen_pulsos_model.py (decae_para,
 * m_polo_cero, sigma_ruido, tabla_cdf). Los registros pasan por mca_bus: nada de
 * este fichero toca memoria de dispositivo.
 */
#define _DEFAULT_SOURCE         /* nanosleep con -std=c11 */

#include <inttypes.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "bloque.h"
#include "gen_priv.h"
#include "gen_pulsos.h"
#include "osciloscope_priv.h"

struct gen_pulsos_h {
    mca_bloque b;               /* primer miembro: ver bloque.h */
    mca_bus *hk;                /* housekeeping, por el lazo digital; puede ser NULL */
    int hk_propio;
};

#define fallar(h, ...) bloque_fallar((mca_bloque *)(h), __VA_ARGS__)

#define X_REG(n, off) { #n, off },
static const mca_reg_t REGS[] = { GEN_PULSOS_REGS(X_REG) };
#undef X_REG

int32_t gen_pulsos_reg_count(void)
{
    return (int32_t)(sizeof(REGS) / sizeof(REGS[0]));
}

const mca_reg_t *gen_pulsos_reg_info(int32_t i)
{
    return (i >= 0 && i < gen_pulsos_reg_count()) ? &REGS[i] : NULL;
}

size_t gen_pulsos_sizeof(const char *tipo)
{
    if (tipo != NULL && strcmp(tipo, "gen_pulsos_cfg_t") == 0)
        return sizeof(gen_pulsos_cfg_t);
    return gen_disparos_sizeof(tipo);
}

/* =========================================================================
 * Ciclo de vida
 * ========================================================================= */

int gen_pulsos_open_bus(gen_pulsos_h **h, mca_bus *bus, int propio, mca_bus *hk,
                        int hk_propio, int check_magic)
{
    if (h == NULL || bus == NULL)
        return MCA_EINVAL;
    *h = NULL;
    bloque_limpiar_apertura();
    if (check_magic) {
        uint32_t magic;
        TRY(mca_bus_r32(bus, GEN_PULSOS_R_MAGIC, &magic));
        if (magic != GEN_PULSOS_MAGIC)
            return bloque_fallar(NULL, MCA_ENOTPRESENT, "el bitstream cargado no tiene "
                                 "el generador de pulsos en 0x4021_0000 (MAGIC 0x%08"
                                 PRIX32 " en 0x020; se esperaba 0x%08" PRIX32 ", "
                                 "\"PUL1\")", magic, GEN_PULSOS_MAGIC);
    }
    gen_pulsos_h *n = calloc(1, sizeof(*n));
    if (n == NULL)
        return MCA_ENOMEM;
    n->b.bus = bus;
    n->b.propio = propio;
    n->hk = hk;
    n->hk_propio = hk != NULL && hk_propio;
    *h = n;
    return MCA_OK;
}

int gen_pulsos_open(gen_pulsos_h **h, uint32_t phys, uint32_t size, int check_magic)
{
    if (h == NULL)
        return MCA_EINVAL;
    *h = NULL;
    bloque_limpiar_apertura();
    mca_bus *b, *hk;
    TRY(bloque_abrir_devmem(&b, phys, size));
    int rc = bloque_abrir_devmem(&hk, GEN_PULSOS_HK_PHYS, GEN_PULSOS_HK_SIZE);
    if (rc != MCA_OK) {
        mca_bus_close(b);
        return rc;
    }
    rc = gen_pulsos_open_bus(h, b, 1, hk, 1, check_magic);
    if (rc != MCA_OK) {
        mca_bus_close(hk);
        mca_bus_close(b);
    }
    return rc;
}

void gen_pulsos_close(gen_pulsos_h *h)
{
    if (h == NULL)
        return;
    if (h->b.propio)
        mca_bus_close(h->b.bus);
    if (h->hk_propio)
        mca_bus_close(h->hk);
    free(h);
}

const char *gen_pulsos_last_error(const gen_pulsos_h *h)
{
    return bloque_ultimo_error(h ? &h->b : NULL);
}

int gen_pulsos_r32(gen_pulsos_h *h, uint32_t off, uint32_t *v)
{
    INICIO(h);
    return mca_bus_r32(h->b.bus, off, v);
}

int gen_pulsos_w32(gen_pulsos_h *h, uint32_t off, uint32_t v)
{
    INICIO(h);
    return mca_bus_w32(h->b.bus, off, v);
}

/* =========================================================================
 * Configuracion
 * ========================================================================= */

void gen_pulsos_config_default(gen_pulsos_cfg_t *c)
{
    if (c == NULL)
        return;
    memset(c, 0, sizeof(*c));
    gen_disparos_default(&c->disparos);
    c->salidas = GEN_PULSOS_SAL_OUT1;
    c->decae = GEN_PULSOS_DECAE_RESET;
}

static int validar(mca_bloque *b, const gen_pulsos_cfg_t *c)
{
    if (c == NULL)
        return MCA_EINVAL;
    TRY(gen_disparos_validar_en(b, &c->disparos));
    if (c->amp_aleat > 1)
        return bloque_fallar(b, MCA_EINVAL, "amp_aleat = %" PRIu32 ": es 0 o 1",
                             c->amp_aleat);
    if (c->salidas > (GEN_PULSOS_SAL_OUT1 | GEN_PULSOS_SAL_OUT2))
        return bloque_fallar(b, MCA_EINVAL, "salidas = %" PRIu32 ": es una m\xc3\xa1scara "
                             "de OUT1 (1) y OUT2 (2)", c->salidas);
    if (c->decae > GEN_PULSOS_DECAE_MAX)
        return bloque_fallar(b, MCA_EINVAL, "decae = %" PRIu32 ": DECAE tiene 16 bits "
                             "(hasta 65535)", c->decae);
    if (c->subida > GEN_PULSOS_SUBIDA_MAX)
        return bloque_fallar(b, MCA_EINVAL, "subida = %" PRIu32 ": SUBIDA tiene 3 bits "
                             "(hasta 7)", c->subida);
    if (c->amp_n > GEN_PULSOS_N_TABLA)
        return bloque_fallar(b, MCA_EINVAL, "amp_n = %" PRIu32 ": la tabla tiene 1024 "
                             "entradas", c->amp_n);
    if (c->base < GEN_PULSOS_AMP_MIN || c->base > GEN_PULSOS_AMP_MAX)
        return bloque_fallar(b, MCA_EINVAL, "base = %" PRId32 ": BASE tiene 14 bits con "
                             "signo (-8192..8191)", c->base);
    if (c->ruido > 1)
        return bloque_fallar(b, MCA_EINVAL, "ruido = %" PRIu32 ": es 0 o 1", c->ruido);
    if (c->ruido_sh > GEN_PULSOS_RUIDO_SH_MAX)
        return bloque_fallar(b, MCA_EINVAL, "ruido_sh = %" PRIu32 ": tiene 4 bits "
                             "(hasta 15)", c->ruido_sh);
    return MCA_OK;
}

int gen_pulsos_validar(const gen_pulsos_cfg_t *c)
{
    bloque_limpiar_apertura();
    return validar(NULL, c);
}

/* CTRL sin `en`: los bits de configuracion. */
static uint32_t ctrl_de(const gen_pulsos_cfg_t *c)
{
    return (c->disparos.aleatorio ? GEN_PULSOS_CTRL_ALEATORIO : 0u)
         | (c->amp_aleat ? GEN_PULSOS_CTRL_AMP_ALEAT : 0u)
         | ((c->salidas & GEN_PULSOS_SAL_OUT1) ? GEN_PULSOS_CTRL_OUT1 : 0u)
         | ((c->salidas & GEN_PULSOS_SAL_OUT2) ? GEN_PULSOS_CTRL_OUT2 : 0u);
}

int gen_pulsos_configurar(gen_pulsos_h *h, const gen_pulsos_cfg_t *c)
{
    INICIO(h);
    TRY(validar(&h->b, c));
    mca_bloque *b = &h->b;
    TRY(mca_bus_w32(b->bus, GEN_PULSOS_R_CTRL, 0));
    TRY(gen_disparos_escribir(b, GEN_PULSOS_R_CTRL, &c->disparos));
    TRY(gen_poner(b, GEN_PULSOS_R_DECAE, "DECAE", c->decae, c->decae));
    TRY(gen_poner(b, GEN_PULSOS_R_SUBIDA, "SUBIDA", c->subida, c->subida));
    const uint32_t amp_n = c->amp_n % GEN_PULSOS_N_TABLA;      /* 1024 se escribe 0 */
    TRY(gen_poner(b, GEN_PULSOS_R_AMP_N, "AMP_N", amp_n, amp_n));
    /* BASE se relee con el signo extendido a 32 bits. */
    TRY(gen_poner(b, GEN_PULSOS_R_BASE, "BASE", (uint32_t)c->base, (uint32_t)c->base));
    const uint32_t ruido = (c->ruido ? GEN_PULSOS_RUIDO_EN : 0u) | c->ruido_sh;
    TRY(gen_poner(b, GEN_PULSOS_R_RUIDO, "RUIDO", ruido, ruido));
    const uint32_t ctrl = ctrl_de(c);
    return gen_poner(b, GEN_PULSOS_R_CTRL, "CTRL", ctrl, ctrl);
}

int gen_pulsos_leer_config(gen_pulsos_h *h, gen_pulsos_cfg_t *c)
{
    INICIO(h);
    if (c == NULL)
        return MCA_EINVAL;
    mca_bus *bus = h->b.bus;
    uint32_t ctrl, amp_n, base, ruido;
    TRY(mca_bus_r32(bus, GEN_PULSOS_R_CTRL, &ctrl));
    TRY(gen_disparos_leer(&h->b, GEN_PULSOS_R_CTRL, &c->disparos));
    TRY(mca_bus_r32(bus, GEN_PULSOS_R_DECAE, &c->decae));
    TRY(mca_bus_r32(bus, GEN_PULSOS_R_SUBIDA, &c->subida));
    TRY(mca_bus_r32(bus, GEN_PULSOS_R_AMP_N, &amp_n));
    TRY(mca_bus_r32(bus, GEN_PULSOS_R_BASE, &base));
    TRY(mca_bus_r32(bus, GEN_PULSOS_R_RUIDO, &ruido));
    c->disparos.aleatorio = (ctrl & GEN_PULSOS_CTRL_ALEATORIO) != 0;
    c->amp_aleat = (ctrl & GEN_PULSOS_CTRL_AMP_ALEAT) != 0;
    c->salidas = ((ctrl & GEN_PULSOS_CTRL_OUT1) ? GEN_PULSOS_SAL_OUT1 : 0u)
               | ((ctrl & GEN_PULSOS_CTRL_OUT2) ? GEN_PULSOS_SAL_OUT2 : 0u);
    c->amp_n = amp_n ? amp_n : GEN_PULSOS_N_TABLA;
    c->base = (int32_t)base;
    c->ruido = (ruido & GEN_PULSOS_RUIDO_EN) != 0;
    c->ruido_sh = ruido & 0xFu;
    return MCA_OK;
}

int gen_pulsos_cargar_tabla(gen_pulsos_h *h, const int16_t *amp, uint32_t n)
{
    INICIO(h);
    if (n > GEN_PULSOS_N_TABLA)
        return fallar(h, MCA_EINVAL, "%" PRIu32 " amplitudes: la tabla tiene 1024", n);
    if (amp == NULL && n > 0)
        return MCA_EINVAL;
    for (uint32_t i = 0; i < n; i++)
        if (amp[i] < GEN_PULSOS_AMP_MIN || amp[i] > GEN_PULSOS_AMP_MAX)
            return fallar(h, MCA_EINVAL, "amp[%" PRIu32 "] = %d: no entra en 14 bits con "
                          "signo (-8192..8191)", i, amp[i]);
    mca_bus *bus = h->b.bus;
    for (uint32_t i = 0; i < GEN_PULSOS_N_TABLA; i++) {
        const int32_t v = i < n ? amp[i] : 0;
        TRY(mca_bus_w32(bus, GEN_PULSOS_R_TABLA + 4u * i, (uint32_t)v));
    }
    for (uint32_t i = 0; i < GEN_PULSOS_N_TABLA; i++) {
        const int32_t v = i < n ? amp[i] : 0;
        uint32_t r;
        TRY(mca_bus_r32(bus, GEN_PULSOS_R_TABLA + 4u * i, &r));
        if (r != (uint32_t)v)
            return fallar(h, MCA_EVERIFY, "TABLA[%" PRIu32 "]: se escribi\xc3\xb3 %" PRId32
                          " y se ley\xc3\xb3 %" PRId32, i, v, (int32_t)r);
    }
    return MCA_OK;
}

int gen_pulsos_leer_tabla(gen_pulsos_h *h, int16_t *amp, uint32_t n)
{
    INICIO(h);
    if (n > GEN_PULSOS_N_TABLA)
        return fallar(h, MCA_EINVAL, "%" PRIu32 " amplitudes: la tabla tiene 1024", n);
    if (amp == NULL && n > 0)
        return MCA_EINVAL;
    for (uint32_t i = 0; i < n; i++) {
        uint32_t r;
        TRY(mca_bus_r32(h->b.bus, GEN_PULSOS_R_TABLA + 4u * i, &r));
        amp[i] = (int16_t)(int32_t)r;
    }
    return MCA_OK;
}

/* =========================================================================
 * Control y estado
 * ========================================================================= */

int gen_pulsos_arrancar(gen_pulsos_h *h)
{
    INICIO(h);
    uint32_t ctrl;
    TRY(mca_bus_r32(h->b.bus, GEN_PULSOS_R_CTRL, &ctrl));
    /* Bajarlo primero: el estado se reinicia en el flanco de `en`. */
    TRY(mca_bus_w32(h->b.bus, GEN_PULSOS_R_CTRL, ctrl & ~GEN_PULSOS_CTRL_EN));
    return mca_bus_w32(h->b.bus, GEN_PULSOS_R_CTRL, ctrl | GEN_PULSOS_CTRL_EN);
}

int gen_pulsos_parar(gen_pulsos_h *h)
{
    INICIO(h);
    uint32_t ctrl;
    TRY(mca_bus_r32(h->b.bus, GEN_PULSOS_R_CTRL, &ctrl));
    return mca_bus_w32(h->b.bus, GEN_PULSOS_R_CTRL, ctrl & ~GEN_PULSOS_CTRL_EN);
}

int gen_pulsos_estado(gen_pulsos_h *h, gen_estado_t *e)
{
    INICIO(h);
    return gen_estado_leer(&h->b, GEN_PULSOS_R_CTRL, e);
}

int gen_pulsos_esperar(gen_pulsos_h *h, int64_t plazo_ns, gen_estado_t *e)
{
    INICIO(h);
    gen_estado_t local;
    if (e == NULL)
        e = &local;
    uint32_t n, ctrl;
    TRY(mca_bus_r32(h->b.bus, GEN_PULSOS_R_N, &n));
    if (n == 0)
        return fallar(h, MCA_EINVAL, "N = 0: el generador no termina nunca");
    TRY(gen_estado_leer(&h->b, GEN_PULSOS_R_CTRL, e));
    if (e->terminado)
        return MCA_OK;
    TRY(mca_bus_r32(h->b.bus, GEN_PULSOS_R_CTRL, &ctrl));
    if (!(ctrl & GEN_PULSOS_CTRL_EN))
        return fallar(h, MCA_EINVAL, "el generador est\xc3\xa1 apagado: no va a llegar a "
                      "N = %" PRIu32 " (GEN_CNT = %" PRIu32 ")", n, e->gen_cnt);
    /* Un sondeo cada 100 us: el bus es barato, pero no hace falta ocuparlo. */
    const struct timespec paso = { 0, 100000 };
    for (;;) {
        TRY(gen_estado_leer(&h->b, GEN_PULSOS_R_CTRL, e));
        if (e->terminado)
            return MCA_OK;
        if (osciloscope_ahora_ns() > plazo_ns)
            return fallar(h, MCA_ETIMEOUT, "el generador no lleg\xc3\xb3 a N = %" PRIu32
                          " a tiempo (GEN_CNT = %" PRIu32 ")", n, e->gen_cnt);
        nanosleep(&paso, NULL);
    }
}

int gen_pulsos_set_lazo(gen_pulsos_h *h, int32_t on)
{
    INICIO(h);
    if (h->hk == NULL)
        return fallar(h, MCA_ENOSYS, "este handle no tiene housekeeping: se abri\xc3\xb3 "
                      "sin el bus de HK");
    uint32_t v, r;
    TRY(mca_bus_r32(h->hk, GEN_PULSOS_HK_LAZO, &v));
    v = on ? (v | 1u) : (v & ~1u);
    TRY(mca_bus_w32(h->hk, GEN_PULSOS_HK_LAZO, v));
    TRY(mca_bus_r32(h->hk, GEN_PULSOS_HK_LAZO, &r));
    if ((r & 1u) != (v & 1u))
        return fallar(h, MCA_EVERIFY, "digital_loop: se escribi\xc3\xb3 0x%" PRIX32 " y se "
                      "ley\xc3\xb3 0x%" PRIX32, v, r);
    return MCA_OK;
}

int gen_pulsos_get_lazo(gen_pulsos_h *h, int32_t *on)
{
    INICIO(h);
    if (on == NULL)
        return MCA_EINVAL;
    if (h->hk == NULL)
        return fallar(h, MCA_ENOSYS, "este handle no tiene housekeeping: se abri\xc3\xb3 "
                      "sin el bus de HK");
    uint32_t v;
    TRY(mca_bus_r32(h->hk, GEN_PULSOS_HK_LAZO, &v));
    *on = (v & 1u) != 0;
    return MCA_OK;
}

/* =========================================================================
 * Las cuentas
 * ========================================================================= */

int gen_pulsos_decae_para(double tau_muestras, uint32_t *decae)
{
    bloque_limpiar_apertura();
    if (decae == NULL)
        return MCA_EINVAL;
    if (!(tau_muestras > 0.0))
        return bloque_fallar(NULL, MCA_EINVAL, "tau = %g muestras: tiene que ser > 0",
                             tau_muestras);
    /* e^x = 1 + expm1(x): exp() pide GLIBC_2.29 en el .so (ver check-bus). */
    const double v = nearbyint(65536.0 * (1.0 + expm1(-1.0 / tau_muestras)));
    *decae = v < 0.0 ? 0u : v > (double)GEN_PULSOS_DECAE_MAX ? GEN_PULSOS_DECAE_MAX
                                                             : (uint32_t)v;
    return MCA_OK;
}

int gen_pulsos_tau(uint32_t decae, double *tau_muestras)
{
    bloque_limpiar_apertura();
    if (tau_muestras == NULL)
        return MCA_EINVAL;
    if (decae > GEN_PULSOS_DECAE_MAX)
        return bloque_fallar(NULL, MCA_EINVAL, "decae = %" PRIu32 ": DECAE tiene 16 bits",
                             decae);
    /* ln(x) = log1p(x - 1), por lo mismo; x - 1 es exacto. DECAE 0 cae en una
     * muestra: tau 0. */
    *tau_muestras = decae == 0 ? 0.0 : -1.0 / log1p((double)decae / 65536.0 - 1.0);
    return MCA_OK;
}

int gen_pulsos_mq(uint32_t decae, uint32_t *mq)
{
    bloque_limpiar_apertura();
    if (mq == NULL)
        return MCA_EINVAL;
    if (decae > GEN_PULSOS_DECAE_MAX)
        return bloque_fallar(NULL, MCA_EINVAL, "decae = %" PRIu32 ": DECAE tiene 16 bits",
                             decae);
    /* round(16 d / (2^16 - d)) al par, en enteros. Nunca empata (2^16 no tiene
     * divisores impares), asi que da lo mismo que la cuenta en double del modelo. */
    const uint32_t num = 16u * decae, den = 65536u - decae;
    uint32_t q = num / den;
    const uint32_t r2 = 2u * (num % den);
    if (r2 > den || (r2 == den && (q & 1u)))
        q++;
    *mq = q;
    return MCA_OK;
}

int gen_pulsos_sigma_ruido(uint32_t sh, double *sigma)
{
    bloque_limpiar_apertura();
    if (sigma == NULL)
        return MCA_EINVAL;
    if (sh > GEN_PULSOS_RUIDO_SH_MAX)
        return bloque_fallar(NULL, MCA_EINVAL, "sh = %" PRIu32 ": tiene 4 bits (hasta 15)",
                             sh);
    /* Irwin-Hall de cuatro bytes: varianza 4 (256^2 - 1) / 12. */
    *sigma = ldexp(sqrt(4.0 * (65536.0 - 1.0) / 12.0), -(int)sh);
    return MCA_OK;
}

int gen_pulsos_tabla_cdf(const double *valores, const double *pesos, uint32_t n,
                         int16_t *tabla, uint32_t n_tabla)
{
    bloque_limpiar_apertura();
    if (valores == NULL || pesos == NULL || tabla == NULL)
        return MCA_EINVAL;
    if (n_tabla != GEN_PULSOS_N_TABLA)
        return bloque_fallar(NULL, MCA_EINVAL, "n_tabla = %" PRIu32 ": la tabla tiene "
                             "1024 entradas", n_tabla);
    if (n == 0)
        return bloque_fallar(NULL, MCA_EINVAL, "sin valores");
    double *cdf = malloc((size_t)n * sizeof(*cdf));
    if (cdf == NULL)
        return MCA_ENOMEM;
    int rc = MCA_OK;
    double acc = 0.0;
    for (uint32_t j = 0; j < n; j++) {
        if (!(pesos[j] >= 0.0) || !isfinite(pesos[j])) {
            rc = bloque_fallar(NULL, MCA_EINVAL, "pesos[%" PRIu32 "] = %g: tiene que ser "
                               "finito y >= 0", j, pesos[j]);
            goto fin;
        }
        acc += pesos[j];
        cdf[j] = acc;
    }
    if (!(acc > 0.0) || !isfinite(acc)) {
        rc = bloque_fallar(NULL, MCA_EINVAL, "los pesos suman %g", acc);
        goto fin;
    }
    for (uint32_t j = 0; j < n; j++)
        cdf[j] /= acc;
    /* searchsorted por izquierda: el primer j con cdf[j] >= u. u crece, asi que j
     * solo avanza. */
    uint32_t j = 0;
    for (uint32_t i = 0; i < n_tabla; i++) {
        const double u = ((double)i + 0.5) / (double)n_tabla;
        while (j < n && cdf[j] < u)
            j++;
        const double v = valores[j < n ? j : n - 1u];
        const double r = nearbyint(v);
        if (!isfinite(v) || r < (double)GEN_PULSOS_AMP_MIN || r > (double)GEN_PULSOS_AMP_MAX) {
            rc = bloque_fallar(NULL, MCA_EINVAL, "el valor %g no entra en 14 bits con "
                               "signo (-8192..8191)", v);
            goto fin;
        }
        tabla[i] = (int16_t)r;
    }
fin:
    free(cdf);
    return rc;
}

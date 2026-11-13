/* El osciloscopio en C: la region del slot 1.
 *
 * La referencia es API/ref_py/osciloscope2.py y la regla es la de mca.c: para cada
 * funcion publica, las dos hacen las MISMAS escrituras en el MISMO orden y devuelven
 * lo mismo, tambien en los casos de error, y con los mismos mensajes. Lo comprueba
 * API/tests/test_libmca_osciloscope.py contra un modelo de registros.
 *
 * Las excepciones deliberadas son dos: `ch` distinto de 0 y 1, que en la referencia
 * cae en el canal 1 en silencio, y un argumento invalido de acq_base, que aca no deja
 * nada escrito.
 *
 * Nada de este fichero toca memoria de dispositivo: todo pasa por mca_bus.
 */
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bloque.h"
#include "osciloscope.h"
#include "osciloscope_priv.h"

#define fallar(h, ...) bloque_fallar((mca_bloque *)(h), __VA_ARGS__)

/* Lo que se mapea para preguntar la geometria: el mapa canonico esta en 0x1000. */
#define SONDA 0x2000u

static int rd(osciloscope_h *h, uint32_t off, uint32_t *v)
{
    return mca_bus_r32(h->b.bus, off, v);
}

static int wr(osciloscope_h *h, uint32_t off, uint32_t v)
{
    return mca_bus_w32(h->b.bus, off, v);
}

/* =========================================================================
 * Tablas
 * ========================================================================= */

#define X_REG(n, off) { "R_" #n, off },
static const mca_reg_t REGS[] = { OSCILOSCOPE_REGS(X_REG) };
#undef X_REG

#define X_CAMPO(n, reg, sh, msk, sig) { #n, OSCILOSCOPE_R_##reg, sh, msk, sig },
static const mca_field_t CAMPOS[OSCILOSCOPE_N_FIELDS] = { OSCILOSCOPE_FIELDS(X_CAMPO) };
#undef X_CAMPO

int32_t osciloscope_reg_count(void)
{
    return (int32_t)(sizeof(REGS) / sizeof(REGS[0]));
}

const mca_reg_t *osciloscope_reg_info(int32_t i)
{
    return (i >= 0 && i < osciloscope_reg_count()) ? &REGS[i] : NULL;
}

int32_t osciloscope_field_count(void)
{
    return OSCILOSCOPE_N_FIELDS;
}

const mca_field_t *osciloscope_field_info(int32_t i)
{
    return (i >= 0 && i < OSCILOSCOPE_N_FIELDS) ? &CAMPOS[i] : NULL;
}

size_t osciloscope_sizeof(const char *tipo)
{
    static const struct { const char *n; size_t s; } t[] = {
        { "osciloscope_geometria_t", sizeof(osciloscope_geometria_t) },
        { "osciloscope_calib_t",     sizeof(osciloscope_calib_t) },
        { "osciloscope_status_t",    sizeof(osciloscope_status_t) },
        { "osciloscope_adc_cal_t",   sizeof(osciloscope_adc_cal_t) },
        { "osciloscope_lote_cfg_t",  sizeof(osciloscope_lote_cfg_t) },
        { "osciloscope_lote_estado_t", sizeof(osciloscope_lote_estado_t) },
        { "osciloscope_lote_t",      sizeof(osciloscope_lote_t) },
        { "osciloscope_lote_resultado_t", sizeof(osciloscope_lote_resultado_t) },
    };
    for (size_t i = 0; tipo != NULL && i < sizeof(t) / sizeof(t[0]); i++)
        if (strcmp(tipo, t[i].n) == 0)
            return t[i].s;
    return 0;
}

/* =========================================================================
 * Geometria
 * ========================================================================= */

/* `b` es donde queda el detalle del error: NULL durante una apertura. */
static int geometria_de(mca_bloque *b, int64_t rsz, int64_t n_ch, osciloscope_geometria_t *g)
{
    if (n_ch < 1 || n_ch > OSCILOSCOPE_N_APERTURAS)
        return bloque_fallar(b, MCA_EINVAL, "n_ch=%" PRId64 " fuera de 1..%d", n_ch,
                             OSCILOSCOPE_N_APERTURAS);
    if (rsz < 1 || rsz > 24)
        return bloque_fallar(b, MCA_EINVAL, "rsz=%" PRId64 " no es una profundidad "
                             "plausible", rsz);
    memset(g, 0, sizeof(*g));
    g->rsz = (uint32_t)rsz;
    g->n_ch = (uint32_t)n_ch;
    g->n_buf = 1u << rsz;
    for (uint32_t i = 0; i < g->n_ch; i++)
        g->aperturas[i] = OSCILOSCOPE_APERTURA_0 + i * OSCILOSCOPE_APERTURA_PASO;
    /* Una palabra de 32 b por muestra. */
    g->size = g->aperturas[g->n_ch - 1] + 4u * g->n_buf;
    return MCA_OK;
}

int osciloscope_geometria_de(int64_t rsz, int64_t n_ch, osciloscope_geometria_t *g)
{
    if (g == NULL)
        return MCA_EINVAL;
    bloque_limpiar_apertura();
    return geometria_de(NULL, rsz, n_ch, g);
}

/* Sale del mapa canonico, que imprime los mismos RSZ y N_CH con que se dimensiono la
 * BRAM de al lado. Un bitstream anterior a ese mapa lee otra cosa en el magic, y se
 * opera con los valores que ese bitstream justamente tiene: negarse seria peor. */
static int leer_geometria(mca_bus *bus, mca_bloque *b, osciloscope_geometria_t *g)
{
    uint32_t magic, caps;
    TRY(mca_bus_r32(bus, OSCILOSCOPE_R_CANON_MAGIC, &magic));
    if (magic != OSCILOSCOPE_MAGIC) {
        TRY(geometria_de(b, OSCILOSCOPE_RSZ_DEFECTO, OSCILOSCOPE_N_CH_DEFECTO, g));
        g->dw = OSCILOSCOPE_DW_DEFECTO;
        g->descubierta = 0;
        return MCA_OK;
    }
    TRY(mca_bus_r32(bus, OSCILOSCOPE_R_CANON_CAPS, &caps));
    TRY(geometria_de(b, (caps >> 16) & 0x3Fu, caps & 0xFu, g));
    g->dw = (caps >> 8) & 0x3Fu;
    g->descubierta = 1;
    return MCA_OK;
}

int osc_geometria(osciloscope_h *h, const osciloscope_geometria_t **g)
{
    if (!h->geo_leida) {
        TRY(leer_geometria(h->b.bus, &h->b, &h->geo));
        h->geo_leida = 1;
    }
    *g = &h->geo;
    return MCA_OK;
}

int osciloscope_get_geometria(osciloscope_h *h, osciloscope_geometria_t *g)
{
    INICIO(h);
    if (g == NULL)
        return MCA_EINVAL;
    const osciloscope_geometria_t *leida;
    TRY(osc_geometria(h, &leida));
    *g = *leida;
    return MCA_OK;
}

/* =========================================================================
 * Ciclo de vida
 * ========================================================================= */

int osciloscope_open_bus(osciloscope_h **h, mca_bus *bus, int propio)
{
    if (h == NULL || bus == NULL)
        return MCA_EINVAL;
    *h = NULL;
    bloque_limpiar_apertura();
    osciloscope_h *n = calloc(1, sizeof(*n));
    if (n == NULL)
        return MCA_ENOMEM;
    n->b.bus = bus;
    n->b.propio = propio;
    *h = n;
    return MCA_OK;
}

/* Lo comun al mapeo de /dev/mem y al de un fichero: `path` NULL es /dev/mem. */
static int abrir_mapeo(mca_bus **b, const char *path, uint32_t phys, uint32_t size)
{
    if (path == NULL)
        return bloque_abrir_devmem(b, phys, size);
    return mca_bus_open_file(b, path, phys, size);
}

static int abrir(osciloscope_h **h, const char *path, uint32_t phys, uint32_t size)
{
    if (h == NULL)
        return MCA_EINVAL;
    *h = NULL;
    bloque_limpiar_apertura();
    mca_bus *b;
    osciloscope_geometria_t geo;
    int con_geo = 0;
    if (size == 0) {
        TRY(abrir_mapeo(&b, path, phys, SONDA));
        int rc = leer_geometria(b, NULL, &geo);
        mca_bus_close(b);
        TRY(rc);
        size = geo.size;
        con_geo = 1;
    }
    TRY(abrir_mapeo(&b, path, phys, size));
    int rc = osciloscope_open_bus(h, b, 1);
    if (rc != MCA_OK) {
        mca_bus_close(b);
        return rc;
    }
    if (con_geo) {
        (*h)->geo = geo;
        (*h)->geo_leida = 1;
    }
    return MCA_OK;
}

int osciloscope_open(osciloscope_h **h, uint32_t phys, uint32_t size)
{
    return abrir(h, NULL, phys, size);
}

int osciloscope_open_file(osciloscope_h **h, const char *path, uint32_t phys, uint32_t size)
{
    if (path == NULL)
        return MCA_EINVAL;
    return abrir(h, path, phys, size);
}

void osciloscope_close(osciloscope_h *h)
{
    if (h == NULL)
        return;
    if (h->b.propio)
        mca_bus_close(h->b.bus);
    free(h);
}

const char *osciloscope_last_error(const osciloscope_h *h)
{
    return bloque_ultimo_error((const mca_bloque *)h);
}

/* =========================================================================
 * Acceso crudo
 * ========================================================================= */

int osciloscope_r32(osciloscope_h *h, uint32_t off, uint32_t *v)
{
    INICIO(h);
    return rd(h, off, v);
}

int osciloscope_w32(osciloscope_h *h, uint32_t off, uint32_t v)
{
    INICIO(h);
    return wr(h, off, v);
}

/* =========================================================================
 * Canales y conversiones
 * ========================================================================= */

static int exigir_canal(osciloscope_h *h, int64_t ch)
{
    if (ch != 0 && ch != 1)
        return fallar(h, MCA_EINVAL, "canal %" PRId64 " fuera de 0..1", ch);
    return MCA_OK;
}

static int exigir_set(osciloscope_h *h, int64_t ch)
{
    return ch == OSCILOSCOPE_AMBOS ? MCA_OK : exigir_canal(h, ch);
}

/* Un registro por canal, en uno o en los dos: el canal 0 primero. */
static int escribir(osciloscope_h *h, int64_t ch, uint32_t off0, uint32_t off1, uint32_t v)
{
    TRY(exigir_set(h, ch));
    if (ch != 1)
        TRY(wr(h, off0, v));
    if (ch != 0)
        TRY(wr(h, off1, v));
    return MCA_OK;
}

static int leer(osciloscope_h *h, int64_t ch, uint32_t off0, uint32_t off1, uint32_t *v)
{
    INICIO(h);
    if (v == NULL)
        return MCA_EINVAL;
    TRY(exigir_canal(h, ch));
    return rd(h, ch ? off1 : off0, v);
}

/* Los 32 bits bajos de un entero guardado en un double, en complemento a dos: lo que
 * da `int(x) & 0xFFFFFFFF` en Python, que tiene precision arbitraria. Convertir el
 * double directo seria indefinido desde 2^63. La resta es exacta: dividir y multiplicar
 * por una potencia de 2 solo mueve el exponente, y los dos terminos son multiplos del
 * bit mas bajo de x. */
static uint32_t bajos32(double x)
{
    const double m = 4294967296.0;
    return (uint32_t)(int64_t)(x - m * trunc(x / m));
}

/* Los mensajes son los de int() y round() de Python. */
static int exigir_finito(osciloscope_h *h, double x)
{
    if (isnan(x))
        return fallar(h, MCA_EINVAL, "cannot convert float NaN to integer");
    if (isinf(x))
        return fallar(h, MCA_EINVAL, "cannot convert float infinity to integer");
    return MCA_OK;
}

/* `round()` de Python redondea al par mas cercano, y rint() tambien con el modo de
 * redondeo por defecto, que nadie cambia en este proceso. */
static int cuentas_de_umbral(osciloscope_h *h, double volts, uint32_t *cnt)
{
    double x = volts * OSCILOSCOPE_CNT_PER_V;
    TRY(exigir_finito(h, x));
    *cnt = bajos32(rint(x)) & 0x3FFFu;
    return MCA_OK;
}

static int exigir_decim(osciloscope_h *h, int64_t v)
{
    if (v == 1 || v == 8 || v == 64 || v == 1024 || v == 8192 || v == 65536)
        return MCA_OK;
    return fallar(h, MCA_EINVAL, "decim %" PRId64 " no legal; usar "
                  "(1, 8, 64, 1024, 8192, 65536)", v);
}

/* =========================================================================
 * Configuracion por canal
 * ========================================================================= */

int osciloscope_get_thr(osciloscope_h *h, int64_t ch, double *volts)
{
    if (volts == NULL)
        return MCA_EINVAL;
    uint32_t v;
    TRY(leer(h, ch, OSCILOSCOPE_R_THR_CH0, OSCILOSCOPE_R_THR_CH1, &v));
    int32_t c = (int32_t)(v & 0x3FFFu);
    if (c & 0x2000)
        c -= 0x4000;
    *volts = (double)c / OSCILOSCOPE_CNT_PER_V;
    return MCA_OK;
}

int osciloscope_set_thr(osciloscope_h *h, double volts, int64_t ch)
{
    INICIO(h);
    uint32_t cnt;
    TRY(cuentas_de_umbral(h, volts, &cnt));
    return escribir(h, ch, OSCILOSCOPE_R_THR_CH0, OSCILOSCOPE_R_THR_CH1, cnt);
}

int osciloscope_get_decim(osciloscope_h *h, int64_t ch, uint32_t *v)
{
    return leer(h, ch, OSCILOSCOPE_R_DEC_CH0, OSCILOSCOPE_R_DEC_CH1, v);
}

int osciloscope_set_decim(osciloscope_h *h, int64_t v, int64_t ch)
{
    INICIO(h);
    TRY(exigir_decim(h, v));
    return escribir(h, ch, OSCILOSCOPE_R_DEC_CH0, OSCILOSCOPE_R_DEC_CH1, (uint32_t)v);
}

int osciloscope_get_delay(osciloscope_h *h, int64_t ch, uint32_t *v)
{
    return leer(h, ch, OSCILOSCOPE_R_DLY_CH0, OSCILOSCOPE_R_DLY_CH1, v);
}

int osciloscope_set_delay(osciloscope_h *h, uint32_t v, int64_t ch)
{
    INICIO(h);
    return escribir(h, ch, OSCILOSCOPE_R_DLY_CH0, OSCILOSCOPE_R_DLY_CH1, v);
}

int osciloscope_get_hysteresis(osciloscope_h *h, int64_t ch, double *volts)
{
    if (volts == NULL)
        return MCA_EINVAL;
    uint32_t v;
    TRY(leer(h, ch, OSCILOSCOPE_R_HYST_CH0, OSCILOSCOPE_R_HYST_CH1, &v));
    *volts = (double)v / OSCILOSCOPE_CNT_PER_V;
    return MCA_OK;
}

int osciloscope_set_hysteresis(osciloscope_h *h, double volts, int64_t ch)
{
    INICIO(h);
    double x = fabs(volts) * OSCILOSCOPE_CNT_PER_V;
    TRY(exigir_finito(h, x));
    /* El piso va antes de quedarse con los bits bajos: es lo que hace max(1, int(x)). */
    double c = trunc(x);
    uint32_t cnt = c < 1.0 ? 1u : bajos32(c);
    return escribir(h, ch, OSCILOSCOPE_R_HYST_CH0, OSCILOSCOPE_R_HYST_CH1, cnt);
}

int osciloscope_get_calibration(osciloscope_h *h, int64_t ch, osciloscope_calib_t *c)
{
    if (c == NULL)
        return MCA_EINVAL;
    TRY(leer(h, ch, OSCILOSCOPE_R_CALIB_OFF_CH0, OSCILOSCOPE_R_CALIB_OFF_CH1, &c->offset));
    return rd(h, ch ? OSCILOSCOPE_R_CALIB_GAIN_CH1 : OSCILOSCOPE_R_CALIB_GAIN_CH0, &c->gain);
}

/* Sin OSCILOSCOPE_AMBOS: la calibracion es de cada canal. */
int osciloscope_set_calib_offset(osciloscope_h *h, int64_t ch, uint32_t v)
{
    INICIO(h);
    TRY(exigir_canal(h, ch));
    return wr(h, ch ? OSCILOSCOPE_R_CALIB_OFF_CH1 : OSCILOSCOPE_R_CALIB_OFF_CH0, v);
}

int osciloscope_set_calib_gain(osciloscope_h *h, int64_t ch, uint32_t v)
{
    INICIO(h);
    TRY(exigir_canal(h, ch));
    return wr(h, ch ? OSCILOSCOPE_R_CALIB_GAIN_CH1 : OSCILOSCOPE_R_CALIB_GAIN_CH0, v);
}

/* =========================================================================
 * Configuracion global
 * ========================================================================= */

int osciloscope_get_avg(osciloscope_h *h, int32_t *en)
{
    INICIO(h);
    if (en == NULL)
        return MCA_EINVAL;
    uint32_t v;
    TRY(rd(h, OSCILOSCOPE_R_AVG_EN, &v));
    *en = (int32_t)(v & 1u);
    return MCA_OK;
}

int osciloscope_set_avg(osciloscope_h *h, int32_t en)
{
    INICIO(h);
    return wr(h, OSCILOSCOPE_R_AVG_EN, en ? 1u : 0u);
}

static int leer_global(osciloscope_h *h, uint32_t off, uint32_t *v)
{
    INICIO(h);
    if (v == NULL)
        return MCA_EINVAL;
    return rd(h, off, v);
}

int osciloscope_get_deb_len(osciloscope_h *h, uint32_t *v)
{
    return leer_global(h, OSCILOSCOPE_R_DEB_LEN, v);
}

int osciloscope_set_deb_len(osciloscope_h *h, uint32_t v)
{
    INICIO(h);
    return wr(h, OSCILOSCOPE_R_DEB_LEN, v);
}

int osciloscope_get_filter_bypass(osciloscope_h *h, uint32_t *v)
{
    return leer_global(h, OSCILOSCOPE_R_FILT_BYPASS, v);
}

int osciloscope_set_filter_bypass(osciloscope_h *h, uint32_t v)
{
    INICIO(h);
    return wr(h, OSCILOSCOPE_R_FILT_BYPASS, v);
}

/* =========================================================================
 * Configuracion en bloque
 * ========================================================================= */

int osciloscope_get_config(osciloscope_h *h, int64_t *vals, int32_t n)
{
    INICIO(h);
    if (vals == NULL || n != OSCILOSCOPE_N_FIELDS)
        return MCA_EINVAL;
    for (int32_t i = 0; i < OSCILOSCOPE_N_FIELDS; i++) {
        const mca_field_t *c = &CAMPOS[i];
        uint32_t w;
        TRY(rd(h, c->offset, &w));
        uint32_t v = (w >> c->shift) & c->mascara;
        vals[i] = v;
        /* Sin extender el signo, un umbral de -0.5 V se lee como +15792 cuentas y el
         * control de la GUI salta al tope. */
        if (c->bandera && (v & ((c->mascara + 1) >> 1)))
            vals[i] -= (int64_t)c->mascara + 1;
    }
    return MCA_OK;
}

int osciloscope_configure(osciloscope_h *h, const int32_t *campos, const uint32_t *valores,
                          int32_t n)
{
    INICIO(h);
    if (n < 0 || (n > 0 && (campos == NULL || valores == NULL)))
        return MCA_EINVAL;
    for (int32_t i = 0; i < n; i++)
        if (osciloscope_field_info(campos[i]) == NULL)
            return MCA_EINVAL;

    for (int32_t i = 0; i < n; i++) {
        uint32_t off = CAMPOS[campos[i]].offset;
        int ya_escrito = 0;
        for (int32_t j = 0; j < i; j++)
            ya_escrito |= CAMPOS[campos[j]].offset == off;
        if (ya_escrito)
            continue;
        uint32_t w;
        TRY(rd(h, off, &w));
        for (int32_t j = i; j < n; j++) {
            const mca_field_t *c = &CAMPOS[campos[j]];
            if (c->offset == off)
                w = (w & ~(c->mascara << c->shift))
                    | ((valores[j] & c->mascara) << c->shift);
        }
        TRY(wr(h, off, w));
    }
    return MCA_OK;
}

/* =========================================================================
 * Estado
 * ========================================================================= */

int osciloscope_get_adc_state(osciloscope_h *h, uint32_t *v)
{
    return leer_global(h, OSCILOSCOPE_R_CMD, v);
}

int osciloscope_get_trg_state(osciloscope_h *h, uint32_t *v)
{
    return leer_global(h, OSCILOSCOPE_R_SW_TRIG, v);
}

int osciloscope_get_wp_cur(osciloscope_h *h, int64_t ch, uint32_t *v)
{
    return leer(h, ch, OSCILOSCOPE_R_WP_CUR_CH0, OSCILOSCOPE_R_WP_CUR_CH1, v);
}

int osciloscope_get_wp_trig(osciloscope_h *h, int64_t ch, uint32_t *v)
{
    return leer(h, ch, OSCILOSCOPE_R_WP_TRIG_CH0, OSCILOSCOPE_R_WP_TRIG_CH1, v);
}

int osciloscope_get_we_cnt(osciloscope_h *h, int64_t ch, uint32_t *v)
{
    return leer(h, ch, OSCILOSCOPE_R_WE_CNT_CH0, OSCILOSCOPE_R_WE_CNT_CH1, v);
}

int osciloscope_get_status(osciloscope_h *h, osciloscope_status_t *st)
{
    INICIO(h);
    if (st == NULL)
        return MCA_EINVAL;
    TRY(rd(h, OSCILOSCOPE_R_CMD, &st->adc_state));
    TRY(rd(h, OSCILOSCOPE_R_SW_TRIG, &st->trg_state));
    TRY(rd(h, OSCILOSCOPE_R_WP_CUR_CH0, &st->wp_cur_ch0));
    TRY(rd(h, OSCILOSCOPE_R_WP_CUR_CH1, &st->wp_cur_ch1));
    TRY(rd(h, OSCILOSCOPE_R_WP_TRIG_CH0, &st->wp_trig_ch0));
    TRY(rd(h, OSCILOSCOPE_R_WP_TRIG_CH1, &st->wp_trig_ch1));
    TRY(rd(h, OSCILOSCOPE_R_WE_CNT_CH0, &st->we_cnt_ch0));
    return rd(h, OSCILOSCOPE_R_WE_CNT_CH1, &st->we_cnt_ch1);
}

/* =========================================================================
 * Comandos
 * ========================================================================= */

int osciloscope_reset(osciloscope_h *h)
{
    INICIO(h);
    TRY(wr(h, OSCILOSCOPE_R_CMD, 0x00000202u));
    return wr(h, OSCILOSCOPE_R_TRIG_DIS_CLR, 0x00000101u);
}

int osciloscope_sw_trigger(osciloscope_h *h)
{
    INICIO(h);
    return wr(h, OSCILOSCOPE_R_SW_TRIG, 0x00000001u);
}

int osciloscope_acq_base(osciloscope_h *h, double thr_volts, uint32_t delay, int64_t decim)
{
    INICIO(h);
    TRY(exigir_decim(h, decim));
    uint32_t cnt;
    TRY(cuentas_de_umbral(h, thr_volts, &cnt));
    /* Tras un disparo single-shot el HW deja adc_trg_dis latcheado y la mascara efectiva
     * en 0, y el reset de la FSM no lo limpia: sin el desbloqueo no vuelve a disparar. */
    TRY(osciloscope_reset(h));
    TRY(wr(h, OSCILOSCOPE_R_DEC_CH0, (uint32_t)decim));
    TRY(wr(h, OSCILOSCOPE_R_DEC_CH1, (uint32_t)decim));
    TRY(wr(h, OSCILOSCOPE_R_THR_CH0, cnt));
    TRY(wr(h, OSCILOSCOPE_R_THR_CH1, cnt));
    TRY(wr(h, OSCILOSCOPE_R_DLY_CH0, delay));
    return wr(h, OSCILOSCOPE_R_DLY_CH1, delay);
}

/* =========================================================================
 * La BRAM
 * ========================================================================= */

#define TRAMO 256u

static int leer_tramo(mca_bus *bus, uint32_t off, uint32_t n, uint32_t dw,
                      const osc_cal_t *cal, int16_t *dst)
{
    uint32_t w[TRAMO];
    while (n > 0) {
        uint32_t m = n < TRAMO ? n : TRAMO;
        TRY(mca_bus_read_words(bus, off, m, w));
        if (cal == NULL)
            for (uint32_t i = 0; i < m; i++)
                dst[i] = (int16_t)osc_muestra(w[i], dw);
        else
            for (uint32_t i = 0; i < m; i++)
                dst[i] = osc_calibrar(cal, osc_muestra(w[i], dw));
        off += 4u * m;
        dst += m;
        n -= m;
    }
    return MCA_OK;
}

int osc_leer(mca_bus *bus, const osciloscope_geometria_t *g, uint32_t ch, int64_t start,
             uint32_t n, const osc_cal_t *cal, int16_t *dst)
{
    /* n_buf es potencia de 2: la mascara da el modulo tambien con start negativo. */
    uint32_t pos = (uint32_t)((uint64_t)start & (g->n_buf - 1u));
    uint32_t base = g->aperturas[ch];
    uint32_t hasta_el_final = g->n_buf - pos;
    uint32_t n1 = n < hasta_el_final ? n : hasta_el_final;
    TRY(leer_tramo(bus, base + 4u * pos, n1, g->dw, cal, dst));
    return leer_tramo(bus, base, n - n1, g->dw, cal, dst + n1);
}

int osc_validar_lectura(osciloscope_h *h, const osciloscope_geometria_t *g, int64_t ch,
                        int64_t n)
{
    if (ch < 0 || ch >= (int64_t)g->n_ch)
        return fallar(h, MCA_EINVAL, "canal %" PRId64 " fuera de 0..%" PRIu32
                      ": este bitstream tiene %" PRIu32 " canales", ch, g->n_ch - 1, g->n_ch);
    if (n < 0 || n > (int64_t)g->n_buf)
        return fallar(h, MCA_EINVAL, "ventana de %" PRId64 " muestras sobre un anillo de "
                      "%" PRIu32 ": el hardware devolver\xc3\xad" "a el buffer repetido sin "
                      "avisar", n, g->n_buf);
    if (g->dw < 1 || g->dw > 16)
        return fallar(h, MCA_ENOSYS, "muestras de %" PRIu32 " bits: no entran en 16",
                      g->dw);
    return MCA_OK;
}

int osciloscope_read_bram(osciloscope_h *h, int64_t ch, int64_t start, int64_t n, int16_t *dst)
{
    INICIO(h);
    if (dst == NULL && n != 0)
        return MCA_EINVAL;
    const osciloscope_geometria_t *g;
    TRY(osc_geometria(h, &g));
    TRY(osc_validar_lectura(h, g, ch, n));
    return osc_leer(h->b.bus, g, (uint32_t)ch, start, (uint32_t)n, NULL, dst);
}

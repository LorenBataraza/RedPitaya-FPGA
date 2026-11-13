/* El lazo por evento del osciloscopio y la calibracion de librp. Ver
 * include/osciloscope_lote.h.
 *
 * La referencia del lazo es el que corria en Python (ReaderThread._loop sobre
 * BramSource, hasta la Parte 6 del plan de libmca): las mismas lecturas y escrituras,
 * en el mismo orden, por evento. La de la calibracion es cmn_CalibCntsSigned de
 * rp-api 2.00-35 (rp-api/api/src/common.c), comprobada contra una tabla generada
 * con esa funcion: API/tests/datos/calib_rp.npz.
 *
 * Nada de este fichero toca memoria de dispositivo: todo pasa por mca_bus.
 */
#define _DEFAULT_SOURCE         /* clock_gettime con -std=c11 */

#include <inttypes.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "bloque.h"
#include "osciloscope_lote.h"
#include "osciloscope_priv.h"

#define fallar(h, ...) bloque_fallar((mca_bloque *)(h), __VA_ARGS__)

/* Cada cuantas lecturas del estado se mira el reloj mientras se espera. Leer el
 * registro cuesta ~0.24 us en la placa y el reloj mas: mirarlo siempre haria mas
 * lento el sondeo, que es la latencia con que se ve el disparo. */
#define VUELTAS_POR_RELOJ 16u

int64_t osciloscope_ahora_ns(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (int64_t)t.tv_sec * 1000000000LL + (int64_t)t.tv_nsec;
}

/* =========================================================================
 * Calibracion
 * ========================================================================= */

int osc_cal_preparar(mca_bloque *b, const osciloscope_adc_cal_t *c, uint32_t dw,
                     osc_cal_t *p)
{
    if (c == NULL || p == NULL)
        return MCA_EINVAL;
    if (dw < 2 || dw > 16)
        return bloque_fallar(b, MCA_EINVAL, "muestras de %" PRIu32 " bits: la "
                             "calibraci\xc3\xb3n es para 2 a 16", dw);
    if (c->base == 0 || c->base > (uint32_t)INT32_MAX)
        return bloque_fallar(b, MCA_EINVAL, "base=%" PRIu32 " de la calibraci\xc3\xb3n: "
                             "tiene que ser de 1 a 2^31 - 1", c->base);
    /* Una calibracion en cero es la de un struct que nadie lleno (rp_CalibInit sin
     * llamar): guardar ceros seria guardar basura sin avisar. */
    if (c->gain == 0 || c->gain > (uint32_t)INT32_MAX)
        return bloque_fallar(b, MCA_EINVAL, "gain=%" PRIu32 " de la calibraci\xc3\xb3n: "
                             "tiene que ser de 1 a 2^31 - 1 (0 es una calibraci\xc3\xb3n "
                             "que no se ley\xc3\xb3)", c->gain);
    int64_t lim = (int64_t)1 << (dw - 1);
    int64_t peor = (lim + llabs((long long)c->offset)) * (int64_t)c->gain;
    if (c->offset == INT32_MIN || peor > INT32_MAX)
        return bloque_fallar(b, MCA_EINVAL, "gain=%" PRIu32 " y offset=%" PRId32
                             " desbordan los 32 bits de la cuenta de librp",
                             c->gain, c->offset);
    p->gain = (int32_t)c->gain;
    p->base = (int32_t)c->base;
    p->offset = c->offset;
    p->lim = (int32_t)lim;
    p->k = -1;
    if ((c->base & (c->base - 1u)) == 0) {
        p->k = 0;
        while ((1u << p->k) != c->base)
            p->k++;
    }
    return MCA_OK;
}

int osc_cal_canales(mca_bloque *b, const osciloscope_adc_cal_t *c, uint32_t n_ch,
                    uint32_t dw, osc_cal_t *p)
{
    for (uint32_t k = 0; k < n_ch; k++) {
        osc_cal_t q;
        int rc = osc_cal_preparar(b, &c[k], dw, p ? &p[k] : &q);
        if (rc != MCA_OK) {
            /* El mensaje de preparar, con el canal adelante. */
            char m[MCA_LARGO_ERROR];
            strncpy(m, bloque_ultimo_error(b), sizeof(m) - 1);
            m[sizeof(m) - 1] = '\0';
            return bloque_fallar(b, rc, "canal %" PRIu32 ": %s", k, m);
        }
    }
    return MCA_OK;
}

int osciloscope_calibrar(const osciloscope_adc_cal_t *cal, int64_t dw,
                         const uint32_t *crudo, int16_t *dst, int64_t n)
{
    bloque_limpiar_apertura();
    if (n < 0 || ((crudo == NULL || dst == NULL) && n != 0))
        return MCA_EINVAL;
    if (dw < 2 || dw > 16)
        return bloque_fallar(NULL, MCA_EINVAL, "muestras de %" PRId64 " bits: la "
                             "calibraci\xc3\xb3n es para 2 a 16", dw);
    osc_cal_t p;
    TRY(osc_cal_preparar(NULL, cal, (uint32_t)dw, &p));
    for (int64_t i = 0; i < n; i++)
        dst[i] = osc_calibrar(&p, osc_muestra(crudo[i], (uint32_t)dw));
    return MCA_OK;
}

int osciloscope_read_cal(osciloscope_h *h, int64_t ch, int64_t start, int64_t n,
                         const osciloscope_adc_cal_t *cal, int16_t *dst)
{
    INICIO(h);
    if (cal == NULL || (dst == NULL && n != 0))
        return MCA_EINVAL;
    const osciloscope_geometria_t *g;
    TRY(osc_geometria(h, &g));
    TRY(osc_validar_lectura(h, g, ch, n));
    osc_cal_t p;
    TRY(osc_cal_preparar(&h->b, cal, g->dw, &p));
    return osc_leer(h->b.bus, g, (uint32_t)ch, start, (uint32_t)n, &p, dst);
}

/* =========================================================================
 * El lazo
 * ========================================================================= */

/* La configuracion, contra la geometria. Prepara la calibracion de los canales que
 * se leen; `cal` puede ser NULL si solo se valida. */
static int validar(osciloscope_h *h, const osciloscope_lote_cfg_t *c,
                   const osciloscope_geometria_t *g, osc_cal_t *cal)
{
    if (c->n_ch > g->n_ch)
        return fallar(h, MCA_EINVAL, "n_ch=%" PRIu32 ": este bitstream tiene %" PRIu32
                      " canales", c->n_ch, g->n_ch);
    if (c->wp_off != OSCILOSCOPE_R_WP_TRIG_CH0 && c->wp_off != OSCILOSCOPE_R_WP_TRIG_CH1)
        return fallar(h, MCA_EINVAL, "wp_off=0x%03" PRIX32 ": wp_trig est\xc3\xa1 en "
                      "0x01C (canal 0) o en 0x11C (canal 1)", c->wp_off);
    if (c->n_ch > 0) {
        uint64_t s = (uint64_t)c->pre + c->post;
        if (s == 0 || s > g->n_buf)
            return fallar(h, MCA_EINVAL, "ventana de %" PRIu64 " muestras (pre=%" PRIu32
                          ", post=%" PRIu32 ") sobre un anillo de %" PRIu32, s, c->pre,
                          c->post, g->n_buf);
        if (g->dw < 2 || g->dw > 16)
            return fallar(h, MCA_ENOSYS, "muestras de %" PRIu32 " bits: no entran en 16",
                          g->dw);
    }
    return osc_cal_canales(&h->b, c->cal, c->n_ch, g->dw, cal);
}

int osciloscope_lote_iniciar(osciloscope_h *osc, const osciloscope_lote_cfg_t *cfg,
                             osciloscope_lote_estado_t *st)
{
    INICIO(osc);
    if (cfg == NULL || st == NULL)
        return MCA_EINVAL;
    const osciloscope_geometria_t *g;
    TRY(osc_geometria(osc, &g));
    TRY(validar(osc, cfg, g, NULL));
    uint32_t wp;
    TRY(mca_bus_r32(osc->b.bus, cfg->wp_off, &wp));
    memset(st, 0, sizeof(*st));
    st->wp_prev = wp;
    return MCA_OK;
}

/* 1 con un evento, 0 si vencio el plazo, o el error. En single-shot la senal es
 * adc_we == 0: la FSM completo el post-trigger y congelo el buffer. Es inequivoca, y
 * mirar cambios de wp_trig no: dos disparos pueden caer en la misma posicion. */
static int esperar(mca_bus *bus, const osciloscope_lote_cfg_t *c,
                   osciloscope_lote_estado_t *st, int64_t plazo, uint32_t *wp, int64_t *t)
{
    uint32_t v;
    for (uint32_t vueltas = 1;; vueltas++) {
        if (c->single_shot) {
            TRY(mca_bus_r32(bus, OSCILOSCOPE_R_CMD, &v));
            if (!(v & 1u)) {
                TRY(mca_bus_r32(bus, c->wp_off, wp));
                *t = osciloscope_ahora_ns();
                return 1;
            }
        } else {
            TRY(mca_bus_r32(bus, c->wp_off, &v));
            if (v != st->wp_prev) {
                st->wp_prev = v;
                *wp = v;
                *t = osciloscope_ahora_ns();
                return 1;
            }
        }
        if (vueltas % VUELTAS_POR_RELOJ == 0 && osciloscope_ahora_ns() > plazo)
            return 0;
    }
}

/* Primero arma la FSM (slot 1) y despues carga las mascaras (slot 3): al reves, un
 * flanco en el medio gasta la mascara con la FSM sin armar. No se pulsa 0x094: el
 * trigger_shield limpia adc_trg_dis solo. */
static int rearmar(mca_bus *osc, mca_bus *mt, const osciloscope_lote_cfg_t *c)
{
    if (!c->rearmar)
        return MCA_OK;
    TRY(mca_bus_w32(osc, OSCILOSCOPE_R_CMD, 0x00000101u));   /* arm ch0 + ch1 */
    TRY(mca_bus_w32(mt, MULTITRIGGER_R_OR_MASK_CH0, c->mascara));
    return mca_bus_w32(mt, MULTITRIGGER_R_OR_MASK_CH1, c->mascara);
}

int osciloscope_leer_lote(osciloscope_h *osc, multitrigger_h *mt,
                          const osciloscope_lote_cfg_t *cfg,
                          osciloscope_lote_estado_t *st,
                          const osciloscope_lote_t *lote, uint32_t n_max,
                          int64_t plazo_ns, osciloscope_lote_resultado_t *res)
{
    INICIO(osc);
    if (cfg == NULL || st == NULL || res == NULL)
        return MCA_EINVAL;
    memset(res, 0, sizeof(*res));
    if (mt == NULL && (cfg->rearmar || cfg->leer_snap))
        return fallar(osc, MCA_EINVAL, "sin el multitrigger no se puede re-armar ni leer "
                      "el snapshot");
    const osciloscope_geometria_t *g;
    TRY(osc_geometria(osc, &g));
    osc_cal_t cal[OSCILOSCOPE_N_APERTURAS];
    TRY(validar(osc, cfg, g, cal));

    mca_bus *bo = osc->b.bus;
    /* El primer miembro de todo handle es su mca_bloque (bloque.h). */
    mca_bus *bm = mt != NULL ? ((mca_bloque *)mt)->bus : NULL;
    const uint32_t S = cfg->pre + cfg->post;
    const int leer_ventana = lote != NULL && lote->wave != NULL && cfg->n_ch > 0;

    while ((lote != NULL ? (uint64_t)res->n : res->descartados) < n_max) {
        uint32_t wp = 0;
        int64_t t = 0;
        int r = esperar(bo, cfg, st, plazo_ns, &wp, &t);
        if (r < 0)
            return r;
        if (r == 0)
            break;

        if (lote == NULL) {
            /* Sin destino: se cuenta y se re-arma sin leer. Sin re-armar, el buffer
             * queda congelado y el mismo evento se vuelve a contar a la velocidad del
             * sondeo (medido en Python: 14996 "eventos" contra 10251 reales). */
            st->pendientes++;
            res->descartados++;
            TRY(rearmar(bo, bm, cfg));
        } else {
            uint32_t i = res->n;
            if (lote->gap != NULL)
                lote->gap[i] = st->pendientes < 255u ? (uint8_t)st->pendientes : 255u;
            res->asignados += st->pendientes;
            st->pendientes = 0;
            if (lote->t_ns != NULL)
                lote->t_ns[i] = t;
            if (lote->wp != NULL)
                lote->wp[i] = (int32_t)wp;
            if (lote->snap != NULL) {
                uint32_t s = 0;
                if (cfg->leer_snap)
                    TRY(mca_bus_r32(bm, MULTITRIGGER_R_TRIG_SNAP, &s));
                lote->snap[i] = s;
            }
            if (leer_ventana) {
                int16_t *fila = lote->wave + (size_t)i * cfg->n_ch * S;
                for (uint32_t k = 0; k < cfg->n_ch; k++)
                    TRY(osc_leer(bo, g, k, (int64_t)wp - cfg->pre, S, &cal[k],
                                 fila + (size_t)k * S));
            }
            /* Re-armar apenas la ventana esta copiada: hasta aca el scope estuvo
             * ciego, y ese hueco es el tiempo muerto del metodo. */
            TRY(rearmar(bo, bm, cfg));
            if (lote->dead_ns != NULL)
                lote->dead_ns[i] = osciloscope_ahora_ns() - t;
            res->n = i + 1;
        }
        /* Con eventos sin pausa el sondeo nunca vence: el plazo se mira tambien aca. */
        if (t > plazo_ns)
            break;
    }
    return MCA_OK;
}

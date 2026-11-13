/* El motor de disparos de los dos generadores: las cuentas y los registros
 * comunes. Ver include/gen_disparos.h y src/gen_priv.h.
 *
 * La referencia es gen_disparos.sv y su modelo, `disparos` y `umbral_para` de
 * modulos/gen_eventos/modelos/python_model/gen_eventos_model.py: el mismo orden de
 * operaciones en double y el mismo redondeo (nearbyint, al par, como round() de
 * Python). Nada de este fichero toca memoria de dispositivo.
 */
#include <inttypes.h>
#include <math.h>
#include <string.h>

#include "bloque.h"
#include "gen_priv.h"

#define fallar(b, ...) bloque_fallar((b), __VA_ARGS__)

void gen_disparos_default(gen_disparos_cfg_t *c)
{
    if (c == NULL)
        return;
    memset(c, 0, sizeof(*c));
    c->periodo = 1000;
    c->dt_min = GEN_DT_MIN_MIN;
}

int gen_disparos_validar_en(mca_bloque *b, const gen_disparos_cfg_t *c)
{
    if (c == NULL)
        return MCA_EINVAL;
    if (c->aleatorio > 1)
        return fallar(b, MCA_EINVAL, "aleatorio = %" PRIu32 ": es 0 (peri\xc3\xb3" "dico) o "
                      "1", c->aleatorio);
    if (c->dt_min > GEN_DT_MIN_MAX)
        return fallar(b, MCA_EINVAL, "dt_min = %" PRIu32 ": DT_MIN tiene 16 bits (hasta "
                      "65535)", c->dt_min);
    if (!c->aleatorio && c->periodo < GEN_PERIODO_MIN)
        return fallar(b, MCA_EINVAL, "periodo = %" PRIu32 ": el m\xc3\xadnimo es 2 (el "
                      "disparo se toma por flanco)", c->periodo);
    if (c->aleatorio && c->dt_min < GEN_DT_MIN_MIN)
        return fallar(b, MCA_EINVAL, "dt_min = %" PRIu32 ": el m\xc3\xadnimo es 2 (el "
                      "disparo se toma por flanco)", c->dt_min);
    if (c->aleatorio && c->umbral == 0)
        return fallar(b, MCA_EINVAL, "umbral = 0: el modo aleatorio no disparar\xc3\xad" "a "
                      "nunca");
    return MCA_OK;
}

int gen_disparos_validar(const gen_disparos_cfg_t *c)
{
    bloque_limpiar_apertura();
    return gen_disparos_validar_en(NULL, c);
}

const char *gen_disparos_last_error(void)
{
    return bloque_ultimo_error(NULL);
}

static uint32_t al_menos_2(uint32_t v)
{
    return v < 2u ? 2u : v;
}

int gen_disparos_umbral_para(double tasa_hz, uint32_t dt_min, uint32_t *umbral)
{
    bloque_limpiar_apertura();
    if (umbral == NULL)
        return MCA_EINVAL;
    if (!(tasa_hz > 0.0) || !isfinite(tasa_hz))
        return fallar(NULL, MCA_EINVAL, "tasa = %g Hz: tiene que ser > 0", tasa_hz);
    const uint32_t d = al_menos_2(dt_min);
    const double resto = GEN_FS_HZ / tasa_hz - (double)(d - 1u);
    if (resto < 1.0)
        return fallar(NULL, MCA_ERANGE, "%g Hz con dt_min = %" PRIu32 ": el m\xc3\xa1ximo "
                      "es %g", tasa_hz, dt_min, GEN_FS_HZ / (double)d);
    const double v = nearbyint(4294967296.0 / resto);
    *umbral = v > 4294967295.0 ? UINT32_MAX : (uint32_t)v;
    return MCA_OK;
}

int gen_disparos_periodo_para(double tasa_hz, uint32_t *periodo)
{
    bloque_limpiar_apertura();
    if (periodo == NULL)
        return MCA_EINVAL;
    if (!(tasa_hz > 0.0) || !isfinite(tasa_hz))
        return fallar(NULL, MCA_EINVAL, "tasa = %g Hz: tiene que ser > 0", tasa_hz);
    const double v = nearbyint(GEN_FS_HZ / tasa_hz);
    if (v < (double)GEN_PERIODO_MIN)
        return fallar(NULL, MCA_ERANGE, "%g Hz: el m\xc3\xa1ximo peri\xc3\xb3" "dico es %g "
                      "(un disparo cada 2 ciclos)", tasa_hz, GEN_FS_HZ / 2.0);
    if (v > 4294967295.0)
        return fallar(NULL, MCA_ERANGE, "%g Hz: el periodo no entra en 32 bits", tasa_hz);
    *periodo = (uint32_t)v;
    return MCA_OK;
}

int gen_disparos_tasa(const gen_disparos_cfg_t *c, double *tasa_hz)
{
    if (c == NULL || tasa_hz == NULL)
        return MCA_EINVAL;
    if (!c->aleatorio)
        *tasa_hz = GEN_FS_HZ / (double)al_menos_2(c->periodo);
    else if (c->umbral == 0)
        *tasa_hz = 0.0;
    else
        *tasa_hz = GEN_FS_HZ / ((double)(al_menos_2(c->dt_min) - 1u)
                                + 4294967296.0 / (double)c->umbral);
    return MCA_OK;
}

static uint32_t xorshift32(uint32_t x)
{
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    return x;
}

/* El motor de gen_disparos.sv mientras esta activo, ciclo por ciclo, como
 * `disparos` del modelo. Lo que el RTL hace fuera de activo (el xorshift quieto) no
 * importa: despues de N no hay mas disparos. */
int gen_disparos_predecir(const gen_disparos_cfg_t *c, uint64_t n_ciclos, uint32_t lat,
                          uint64_t *t, uint32_t n_max, uint32_t *n)
{
    if (c == NULL || n == NULL || (t == NULL && n_max > 0))
        return MCA_EINVAL;
    const uint32_t per = al_menos_2(c->periodo);
    const uint32_t dtm = al_menos_2(c->dt_min & 0xFFFFu);
    const uint32_t lim = (c->n != 0 && c->n < n_max) ? c->n : n_max;
    uint32_t x = c->semilla ? c->semilla : GEN_SEMILLA_0;
    uint32_t per_cnt = per - 1u, hold = 0, k = 0;
    for (uint64_t g = 0; g < n_ciclos && k < lim; g++) {
        int disp;
        if (c->aleatorio) {
            disp = hold == 0 && x < c->umbral;
            if (disp)
                hold = dtm - 1u;
            else if (hold)
                hold--;
        } else {
            disp = per_cnt == 0;
            per_cnt = per_cnt == 0 ? per - 1u : per_cnt - 1u;
        }
        if (disp)
            t[k++] = g + lat;
        x = xorshift32(x);
    }
    *n = k;
    return MCA_OK;
}

size_t gen_disparos_sizeof(const char *tipo)
{
    static const struct { const char *n; size_t s; } t[] = {
        { "gen_disparos_cfg_t", sizeof(gen_disparos_cfg_t) },
        { "gen_estado_t",       sizeof(gen_estado_t) },
    };
    for (size_t i = 0; tipo != NULL && i < sizeof(t) / sizeof(t[0]); i++)
        if (strcmp(t[i].n, tipo) == 0)
            return t[i].s;
    return 0;
}

/* =========================================================================
 * Los registros del motor, desde una base
 * ========================================================================= */

int gen_poner(mca_bloque *b, uint32_t off, const char *nombre, uint32_t v,
              uint32_t esperado)
{
    uint32_t r;
    TRY(mca_bus_w32(b->bus, off, v));
    TRY(mca_bus_r32(b->bus, off, &r));
    if (r != esperado)
        return fallar(b, MCA_EVERIFY, "%s: se escribi\xc3\xb3 0x%08" PRIX32 " y se "
                      "ley\xc3\xb3 0x%08" PRIX32, nombre, v, r);
    return MCA_OK;
}

int gen_disparos_escribir(mca_bloque *b, uint32_t base, const gen_disparos_cfg_t *c)
{
    TRY(gen_poner(b, base + GEN_OFF_PERIODO, "PERIODO", c->periodo, c->periodo));
    TRY(gen_poner(b, base + GEN_OFF_UMBRAL, "UMBRAL", c->umbral, c->umbral));
    TRY(gen_poner(b, base + GEN_OFF_DT_MIN, "DT_MIN", c->dt_min, c->dt_min));
    TRY(gen_poner(b, base + GEN_OFF_N, "N", c->n, c->n));
    return gen_poner(b, base + GEN_OFF_SEMILLA, "SEMILLA", c->semilla, c->semilla);
}

int gen_disparos_leer(mca_bloque *b, uint32_t base, gen_disparos_cfg_t *c)
{
    c->aleatorio = 0;
    TRY(mca_bus_r32(b->bus, base + GEN_OFF_PERIODO, &c->periodo));
    TRY(mca_bus_r32(b->bus, base + GEN_OFF_UMBRAL, &c->umbral));
    TRY(mca_bus_r32(b->bus, base + GEN_OFF_DT_MIN, &c->dt_min));
    TRY(mca_bus_r32(b->bus, base + GEN_OFF_N, &c->n));
    return mca_bus_r32(b->bus, base + GEN_OFF_SEMILLA, &c->semilla);
}

int gen_estado_leer(mca_bloque *b, uint32_t base, gen_estado_t *e)
{
    if (e == NULL)
        return MCA_EINVAL;
    /* ESTADO primero: si dice terminado, el GEN_CNT que se lee despues ya es N. Al
     * reves, un GEN_CNT de un ciclo antes podria acompaniar a un terminado. */
    TRY(mca_bus_r32(b->bus, base + GEN_OFF_ESTADO, &e->estado));
    TRY(mca_bus_r32(b->bus, base + GEN_OFF_GEN_CNT, &e->gen_cnt));
    e->generando = (e->estado & GEN_ST_GENERANDO) != 0;
    e->terminado = (e->estado & GEN_ST_TERMINADO) != 0;
    e->desborde = (e->estado & GEN_ST_DESBORDE) != 0;
    return MCA_OK;
}

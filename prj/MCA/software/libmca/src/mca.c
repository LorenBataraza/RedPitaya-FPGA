/* El MCA2 en C: el analizador con ranuras, funcion por funcion.
 *
 * La referencia es API/ref_py/mca2.py (la implementacion Python del mapa
 * "MCA2") y la regla es que, para cada funcion publica, las dos hagan las
 * MISMAS escrituras en el MISMO orden y devuelvan lo mismo. Lo comprueba
 * API/tests/test_libmca_equivalencia.py contra un modelo de registros.
 *
 * Eso incluye los casos de error: un argumento invalido se rechaza en el mismo
 * punto y con el mismo mensaje. mca_configure() valida todo ANTES de escribir,
 * asi que una configuracion mala no deja nada escrito.
 *
 * Las LECTURAS no tienen que coincidir una a una: no tienen efectos sobre la
 * PL, salvo la palabra baja de un reloj de 64 b, que congela la alta (r64 las
 * lee siempre en ese orden). Donde Python leia dos veces el mismo registro,
 * aca se lee una, y los campos derivados salen de la misma foto.
 *
 * Nada de este fichero toca memoria de dispositivo: todo pasa por mca_bus.
 */
#define _DEFAULT_SOURCE         /* nanosleep y clock_gettime con -std=c11 */

#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "bloque.h"
#include "mca.h"

struct mca_h {
    mca_bloque b;               /* primer miembro: ver bloque.h */
    uint32_t caps, h_aw, h2_aw, psd_aw;
};

#define fallar(h, ...) bloque_fallar((mca_bloque *)(h), __VA_ARGS__)

static int rd(mca_h *h, uint32_t off, uint32_t *v)
{
    return mca_bus_r32(h->b.bus, off, v);
}

static int wr(mca_h *h, uint32_t off, uint32_t v)
{
    return mca_bus_w32(h->b.bus, off, v);
}

/* El valor pedido, enmascarado como lo hace `v & mascara` en Python: sobre el
 * entero con signo, que en complemento a dos da lo mismo que sobre uint32. */
#define M(v, mascara) ((uint32_t)(v) & (uint32_t)(mascara))

static int32_t sign14(uint32_t v)
{
    v &= 0x3FFFu;
    return (v & 0x2000u) ? (int32_t)v - 0x4000 : (int32_t)v;
}

/* =========================================================================
 * Tablas
 * ========================================================================= */

#define TIPO_CAMPO   0
#define TIPO_BANDERA 1

#define X_TABLA(n, reg, sh, msk, tipo, set) \
    { #n, MCA_R_##reg, sh, msk, TIPO_##tipo },
static const mca_field_t CAMPOS[MCA_N_FIELDS] = { MCA_FIELDS(X_TABLA) };
#undef X_TABLA

#define X_REG(n, off) { "R_" #n, off },
static const mca_reg_t REGS[] = { MCA_REGS(X_REG) };
#undef X_REG

int32_t mca_field_count(void) { return MCA_N_FIELDS; }

const mca_field_t *mca_field_info(int32_t i)
{
    return (i >= 0 && i < MCA_N_FIELDS) ? &CAMPOS[i] : NULL;
}

int32_t mca_reg_count(void) { return (int32_t)(sizeof(REGS) / sizeof(REGS[0])); }

size_t mca_sizeof(const char *tipo)
{
    static const struct { const char *n; size_t s; } t[] = {
        { "mca_config_t",     sizeof(mca_config_t) },
        { "mca_counters_t",   sizeof(mca_counters_t) },
        { "mca_info_t",       sizeof(mca_info_t) },
        { "mca_last_event_t", sizeof(mca_last_event_t) },
        { "mca_field_t",      sizeof(mca_field_t) },
        { "mca_reg_t",        sizeof(mca_reg_t) },
    };
    for (size_t i = 0; tipo != NULL && i < sizeof(t) / sizeof(t[0]); i++)
        if (strcmp(tipo, t[i].n) == 0)
            return t[i].s;
    return 0;
}

const mca_reg_t *mca_reg_info(int32_t i)
{
    return (i >= 0 && i < mca_reg_count()) ? &REGS[i] : NULL;
}

/* El read-modify-write de _escribir_campo(): el RTL relee los registros
 * empaquetados enteros (mca_top.sv:340,346,351), asi que escribir un campo no
 * borra a sus vecinos. */
static int leer_campo(mca_h *h, int i, uint32_t *v)
{
    const mca_field_t *c = &CAMPOS[i];
    uint32_t w;
    TRY(rd(h, c->offset, &w));
    *v = (w >> c->shift) & c->mascara;
    return MCA_OK;
}

static int escribir_campo(mca_h *h, int i, uint32_t v)
{
    const mca_field_t *c = &CAMPOS[i];
    uint32_t w;
    if (c->bandera)
        v = (v != 0);
    TRY(rd(h, c->offset, &w));
    w = (w & ~(c->mascara << c->shift)) | ((v & c->mascara) << c->shift);
    return wr(h, c->offset, w);
}

int mca_get_field(mca_h *h, int32_t i, uint32_t *v)
{
    INICIO(h);
    if (v == NULL || mca_field_info(i) == NULL)
        return MCA_EINVAL;
    return leer_campo(h, i, v);
}

int mca_set_field(mca_h *h, int32_t i, uint32_t v)
{
    INICIO(h);
    if (mca_field_info(i) == NULL)
        return MCA_EINVAL;
    return escribir_campo(h, i, v);
}

int mca_get_config(mca_h *h, uint32_t *vals, int32_t n)
{
    INICIO(h);
    if (vals == NULL || n != MCA_N_FIELDS)
        return MCA_EINVAL;
    for (int i = 0; i < MCA_N_FIELDS; i++)
        TRY(leer_campo(h, i, &vals[i]));
    return MCA_OK;
}

/* Los get/set de la tabla. Los setters ESP estan mas abajo. */
#define X_GET(n, reg, sh, msk, tipo, set)                                   \
    int mca_get_##n(mca_h *h, uint32_t *v)                                  \
    {                                                                       \
        INICIO(h);                                                          \
        if (v == NULL)                                                      \
            return MCA_EINVAL;                                              \
        return leer_campo(h, MCA_FIELD_##n, v);                             \
    }
#define X_SET_GEN(n)                                                        \
    int mca_set_##n(mca_h *h, uint32_t v)                                   \
    {                                                                       \
        INICIO(h);                                                          \
        return escribir_campo(h, MCA_FIELD_##n, v);                         \
    }
#define X_SET_ESP(n)
#define X_SET(n, reg, sh, msk, tipo, set) X_SET_##set(n)
MCA_FIELDS(X_GET)
MCA_FIELDS(X_SET)
#undef X_GET
#undef X_SET_GEN
#undef X_SET_ESP
#undef X_SET

/* =========================================================================
 * Features
 * ========================================================================= */

static const char *const NOMBRES_F[MCA_N_FEATURES] = {
    "pico", "integral", "psd", "ancho_inv", "largo", "t_subida",
    "dt_anterior", "dt_siguiente", "solape", "trapecio", "forma",
};

/* Como `sorted(FEATURES)` y `sorted(FEATURES.values())` en los mensajes de
 * Python, para que el texto de la excepcion sea el mismo. */
#define NOMBRES_ORDENADOS \
    "['ancho_inv', 'dt_anterior', 'dt_siguiente', 'forma', 'integral', " \
    "'largo', 'pico', 'psd', 'solape', 't_subida', 'trapecio']"
#define INDICES_VALIDOS "[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]"

int mca_feature_from_name(const char *nombre, int32_t *idx)
{
    if (nombre == NULL || idx == NULL)
        return MCA_EINVAL;
    for (int32_t i = 0; i < MCA_N_FEATURES; i++)
        if (strcmp(nombre, NOMBRES_F[i]) == 0) {
            *idx = i;
            return MCA_OK;
        }
    return MCA_EINVAL;
}

const char *mca_feature_name(int32_t idx)
{
    return (idx >= 0 && idx < MCA_N_FEATURES) ? NOMBRES_F[idx] : NULL;
}

/* El _feat_idx() de Python: un indice fuera de rango apunta a una ranura
 * RESERVADA que vale cero, y el sintoma seria el espectro entero en el canal 0
 * sin ningun error. Lo mismo F_TRAP en un bitstream sin el trapecio. */
static int validar_feature(mca_h *h, int32_t f, int32_t por_defecto,
                           uint32_t *out)
{
    if (f == MCA_F_DEFAULT) {
        *out = (uint32_t)por_defecto;
        return MCA_OK;
    }
    if (f == MCA_F_DESCONOCIDA)
        return fallar(h, MCA_EINVAL, "feature desconocida; hay: %s",
                      NOMBRES_ORDENADOS);
    if (f < 0 || f >= MCA_N_FEATURES)
        return fallar(h, MCA_EINVAL,
                      "indice de feature %" PRId32 " sin productor: las ranuras "
                      "validas son " INDICES_VALIDOS " (" NOMBRES_ORDENADOS "). "
                      "Las demas estan reservadas y valen cero, asi que el "
                      "espectro caeria entero en el canal 0 sin avisar.", f);
    if ((f == MCA_F_TRAP || f == MCA_F_FORMA) && !(h->caps & MCA_CAP_TRAP))
        return fallar(h, MCA_EINVAL,
                      "la feature %s necesita el conformado trapezoidal "
                      "(CAPS bit 2) y el bitstream cargado no lo trae: vale cero, "
                      "asi que el espectro caeria entero en el canal 0 sin avisar.",
                      f == MCA_F_TRAP ? "trapecio" : "forma");
    if (f == MCA_F_FORMA) {
        /* Un bitstream con el trapecio pero sin el banco: 0x134 lee cero. */
        uint32_t w;
        TRY(rd(h, MCA_R_N_FORMAS, &w));
        if (((w >> 8) & 7u) == 0)
            return fallar(h, MCA_EINVAL,
                          "la feature forma necesita el banco de trapecios "
                          "(0x134, N_FORMAS) y el bitstream cargado no lo trae: "
                          "vale cero, asi que el espectro caeria entero en el "
                          "canal 0 sin avisar.");
    }
    *out = (uint32_t)f;
    return MCA_OK;
}

/* =========================================================================
 * Setters que validan o saturan
 * ========================================================================= */

/* Las validaciones de ref_py/mca2.py, con los mismos mensajes. Son los campos
 * que el RTL satura o envuelve en silencio. */
static int validar_dec(mca_h *h, int64_t v)
{
    if (v < 1)
        return fallar(h, MCA_EINVAL, "dec tiene que ser >= 1");
    return MCA_OK;
}

static int validar_n_acc(mca_h *h, int64_t v, uint32_t n_max)
{
    if (v < 1 || v > (int64_t)n_max)
        return fallar(h, MCA_EINVAL,
                      "n_acc=%" PRId64 ": tiene que estar entre 1 y %" PRIu32
                      ", las ranuras con que se sintetizo el MCA (el RTL toma 0 "
                      "como 1 y satura arriba sin avisar)", v, n_max);
    return MCA_OK;
}

static int validar_pre_dly(mca_h *h, int64_t v)
{
    if (v < 0 || v > MCA_PRE_DLY_MAX)
        return fallar(h, MCA_EINVAL, "pre_dly=%" PRId64 ": tiene que estar entre "
                      "0 y %d ciclos", v, MCA_PRE_DLY_MAX);
    return MCA_OK;
}

static int validar_trap_k(mca_h *h, int64_t v)
{
    if (v < 1 || v > MCA_TRAP_KL_MAX)
        return fallar(h, MCA_EINVAL, "trap_k=%" PRId64 ": tiene que estar entre "
                      "1 y %d muestras", v, MCA_TRAP_KL_MAX);
    return MCA_OK;
}

static int validar_trap_mq(mca_h *h, int64_t v)
{
    if (v < 0 || v > (int64_t)MCA_TRAP_MQ_MAX)
        return fallar(h, MCA_EINVAL, "trap_mq=%" PRId64 ": tiene que estar entre "
                      "0 y %u (M*16, con M hasta 65535.94 muestras)", v,
                      (unsigned)MCA_TRAP_MQ_MAX);
    return MCA_OK;
}

static int validar_n_formas(mca_h *h, int64_t v, uint32_t n_max)
{
    if (n_max == 0) {
        if (v != 1)
            return fallar(h, MCA_EINVAL, "n_formas=%" PRId64 ": el bitstream "
                          "cargado no tiene el banco de trapecios (0x134, "
                          "N_FORMAS = 0), usa una sola forma", v);
        return MCA_OK;
    }
    if (n_max > MCA_N_FORMAS_TOPE)
        n_max = MCA_N_FORMAS_TOPE;
    if (v < 1 || v > (int64_t)n_max)
        return fallar(h, MCA_EINVAL,
                      "n_formas=%" PRId64 ": tiene que estar entre 1 y %" PRIu32
                      ", las formas del banco (el RTL toma 0 como 1 y satura "
                      "arriba sin avisar)", v, n_max);
    return MCA_OK;
}

static int validar_forma_k(mca_h *h, int f, int64_t v)
{
    if (v < 1 || v > MCA_TRAP_KL_MAX)
        return fallar(h, MCA_EINVAL, "forma%d_k=%" PRId64 ": tiene que estar entre "
                      "1 y %d muestras", f, v, MCA_TRAP_KL_MAX);
    return MCA_OK;
}

/* La misma altura para el mismo pulso: k_f / 2^sh_f == k_0 / 2^sh_0. */
static int misma_ganancia(uint32_t k0, uint32_t sh0, uint32_t kf, uint32_t shf)
{
    int d = (int)sh0 - (int)shf;
    if (d >= 0)
        return d <= 10 && (kf << d) == k0;
    return -d <= 10 && (k0 << -d) == kf;
}

int mca_set_dec(mca_h *h, int64_t v)
{
    INICIO(h);
    TRY(validar_dec(h, v));
    return escribir_campo(h, MCA_FIELD_dec, (uint32_t)v);
}

int mca_set_n_acc(mca_h *h, int64_t v)
{
    INICIO(h);
    uint32_t n_max;
    TRY(rd(h, MCA_R_N_ACC_MAX, &n_max));
    TRY(validar_n_acc(h, v, n_max));
    return escribir_campo(h, MCA_FIELD_n_acc, (uint32_t)v);
}

int mca_set_pre_dly(mca_h *h, int64_t v)
{
    INICIO(h);
    TRY(validar_pre_dly(h, v));
    return escribir_campo(h, MCA_FIELD_pre_dly, (uint32_t)v);
}

int mca_set_trap_k(mca_h *h, int64_t v)
{
    INICIO(h);
    TRY(validar_trap_k(h, v));
    return escribir_campo(h, MCA_FIELD_trap_k, (uint32_t)v);
}

int mca_set_trap_mq(mca_h *h, int64_t v)
{
    INICIO(h);
    TRY(validar_trap_mq(h, v));
    return escribir_campo(h, MCA_FIELD_trap_mq, (uint32_t)v);
}

int mca_set_n_formas(mca_h *h, int64_t v)
{
    INICIO(h);
    uint32_t w;
    TRY(rd(h, MCA_R_N_FORMAS, &w));
    TRY(validar_n_formas(h, v, (w >> 8) & 7u));
    return escribir_campo(h, MCA_FIELD_n_formas, (uint32_t)v);
}

#define X_SET_FORMA_K(f)                                                    \
    int mca_set_forma##f##_k(mca_h *h, int64_t v)                           \
    {                                                                       \
        INICIO(h);                                                          \
        TRY(validar_forma_k(h, f, v));                                      \
        return escribir_campo(h, MCA_FIELD_forma##f##_k, (uint32_t)v);      \
    }
X_SET_FORMA_K(1)
X_SET_FORMA_K(2)
X_SET_FORMA_K(3)
#undef X_SET_FORMA_K

/* `mca_zoom.sv`: "z SE SATURA a FW-AW". Mas alla no quedan bits que rebanar. */
static int64_t z_max(uint32_t aw)
{
    return aw >= MCA_AMP_W ? 0 : (int64_t)MCA_AMP_W - (int64_t)aw;
}

static int set_zoom_z(mca_h *h, int campo, int64_t z, uint32_t aw)
{
    int64_t tope = z_max(aw);
    return escribir_campo(h, campo, (uint32_t)(z < tope ? z : tope));
}

int mca_set_zoom_1d_z(mca_h *h, int64_t z)
{
    INICIO(h);
    return set_zoom_z(h, MCA_FIELD_zoom_1d_z, z, h->h_aw);
}

int mca_set_zoom_2dx_z(mca_h *h, int64_t z)
{
    INICIO(h);
    return set_zoom_z(h, MCA_FIELD_zoom_2dx_z, z, h->h2_aw);
}

int mca_set_zoom_2dy_z(mca_h *h, int64_t z)
{
    INICIO(h);
    return set_zoom_z(h, MCA_FIELD_zoom_2dy_z, z, h->psd_aw);
}

static int set_sel(mca_h *h, int campo, int32_t f, int32_t por_defecto)
{
    uint32_t idx = 0;
    TRY(validar_feature(h, f, por_defecto, &idx));
    return escribir_campo(h, campo, idx);
}

int mca_set_sel_1d(mca_h *h, int32_t f)
{
    INICIO(h);
    return set_sel(h, MCA_FIELD_sel_1d, f, MCA_F_PEAK);
}

int mca_set_sel_2dx(mca_h *h, int32_t f)
{
    INICIO(h);
    return set_sel(h, MCA_FIELD_sel_2dx, f, MCA_F_PEAK);
}

int mca_set_sel_2dy(mca_h *h, int32_t f)
{
    INICIO(h);
    return set_sel(h, MCA_FIELD_sel_2dy, f, MCA_F_PSD);
}

int mca_set_discr_sel(mca_h *h, int32_t f)
{
    INICIO(h);
    return set_sel(h, MCA_FIELD_discr_sel, f, MCA_F_PEAK);
}

/* =========================================================================
 * Apertura
 * ========================================================================= */

int mca_wrap(mca_h **h, mca_bus *bus, int propio, uint32_t caps, uint32_t h_aw,
             uint32_t h2_aw, uint32_t psd_aw)
{
    if (h == NULL || bus == NULL)
        return MCA_EINVAL;
    *h = NULL;
    mca_h *n = calloc(1, sizeof(*n));
    if (n == NULL)
        return MCA_ENOMEM;
    n->b.bus = bus;
    n->b.propio = propio;
    n->caps = caps;
    n->h_aw = h_aw;
    n->h2_aw = h2_aw;
    n->psd_aw = psd_aw;
    *h = n;
    return MCA_OK;
}

/* `donde` es la base en hexa si se conoce, para el mensaje de magic malo. */
static int abrir_sobre(mca_h **h, mca_bus *bus, int propio, int check_magic,
                       const char *donde)
{
    if (h == NULL || bus == NULL)
        return MCA_EINVAL;
    *h = NULL;
    bloque_limpiar_apertura();

    uint32_t magic, caps, widths;
    TRY(mca_bus_r32(bus, MCA_R_MAGIC, &magic));
    if (check_magic && magic == MCA_MAGIC_MCA1)
        return fallar(NULL, MCA_ENOTPRESENT,
                      "el MCA en %s es el bitstream \"MCA1\" (magic 0x%08" PRIx32
                      ") y este software habla \"MCA2\". Para el MCA1: "
                      "mca_open(impl='py'), que usa la referencia congelada.",
                      donde, magic);
    if (check_magic && magic != MCA_MAGIC)
        return fallar(NULL, MCA_ENOTPRESENT,
                      "no hay MCA en %s: magic=0x%08" PRIx32 ", esperado "
                      "0x%08" PRIx32 ". En el bitstream del scope ese slot es un "
                      "sys_bus_stub. Carg\xc3\xa1 mca_red_pitaya.bit.",
                      donde, magic, MCA_MAGIC);
    TRY(mca_bus_r32(bus, MCA_R_CAPS, &caps));
    TRY(mca_bus_r32(bus, MCA_R_WIDTHS, &widths));
    return mca_wrap(h, bus, propio, caps, widths & 0xFFu, (widths >> 8) & 0xFFu,
                    (widths >> 16) & 0xFFu);
}

int mca_open_bus(mca_h **h, mca_bus *bus, int propio, int check_magic)
{
    return abrir_sobre(h, bus, propio, check_magic, "el bus");
}

int mca_open(mca_h **h, uint32_t phys, uint32_t size, int check_magic)
{
    if (h == NULL)
        return MCA_EINVAL;
    *h = NULL;
    mca_bus *b;
    TRY(bloque_abrir_devmem(&b, phys, size));
    char donde[16];
    snprintf(donde, sizeof(donde), "0x%" PRIx32, phys);
    int rc = abrir_sobre(h, b, 1, check_magic, donde);
    if (rc != MCA_OK)
        mca_bus_close(b);
    return rc;
}

void mca_close(mca_h *h)
{
    if (h == NULL)
        return;
    if (h->b.propio)
        mca_bus_close(h->b.bus);
    free(h);
}

const char *mca_last_error(const mca_h *h)
{
    return bloque_ultimo_error((const mca_bloque *)h);
}

int mca_get_geometry(const mca_h *h, uint32_t *caps, uint32_t *h_aw,
                     uint32_t *h2_aw, uint32_t *psd_aw)
{
    if (h == NULL)
        return MCA_EINVAL;
    if (caps)   *caps = h->caps;
    if (h_aw)   *h_aw = h->h_aw;
    if (h2_aw)  *h2_aw = h->h2_aw;
    if (psd_aw) *psd_aw = h->psd_aw;
    return MCA_OK;
}

/* =========================================================================
 * Acceso crudo
 * ========================================================================= */

int mca_r32(mca_h *h, uint32_t off, uint32_t *v)
{
    INICIO(h);
    return rd(h, off, v);
}

int mca_w32(mca_h *h, uint32_t off, uint32_t v)
{
    INICIO(h);
    return wr(h, off, v);
}

int mca_read_words(mca_h *h, uint32_t off, uint32_t n, uint32_t *dst)
{
    INICIO(h);
    return mca_bus_read_words(h->b.bus, off, n, dst);
}

static int r64(mca_h *h, uint32_t lo, uint32_t hi, uint64_t *v)
{
    uint32_t a, b;
    TRY(rd(h, lo, &a));         /* PRIMERO la baja: congela la alta */
    TRY(rd(h, hi, &b));
    *v = ((uint64_t)b << 32) | a;
    return MCA_OK;
}

int mca_r64(mca_h *h, uint32_t off_lo, uint32_t off_hi, uint64_t *v)
{
    INICIO(h);
    if (v == NULL)
        return MCA_EINVAL;
    return r64(h, off_lo, off_hi, v);
}

/* =========================================================================
 * Identificacion
 * ========================================================================= */

/* En el MCA2 el bus de features viene siempre: lo dice el magic. La sonda de
 * escribir y releer R_DISCR_MIN era para distinguir dos bitstreams "MCA1". */
static int sondear_features(mca_h *h, int32_t *si)
{
    uint32_t magic;
    TRY(rd(h, MCA_R_MAGIC, &magic));
    *si = magic == MCA_MAGIC;
    return MCA_OK;
}

int mca_tiene_features(mca_h *h, int32_t *si)
{
    INICIO(h);
    if (si == NULL)
        return MCA_EINVAL;
    return sondear_features(h, si);
}

int mca_exigir_features(mca_h *h)
{
    INICIO(h);
    uint32_t magic;
    TRY(rd(h, MCA_R_MAGIC, &magic));
    if (magic != MCA_MAGIC)
        return fallar(h, MCA_ENOTPRESENT, "el bitstream cargado no es el "
                      "\"MCA2\": magic 0x%08" PRIx32, magic);
    return MCA_OK;
}

int mca_identify(mca_h *h, mca_info_t *info)
{
    INICIO(h);
    if (info == NULL)
        return MCA_EINVAL;
    memset(info, 0, sizeof(*info));
    TRY(rd(h, MCA_R_MAGIC, &info->magic));
    info->hist_h = (h->caps & MCA_CAP_HIST_H) != 0;
    info->hist_h_psd = (h->caps & MCA_CAP_HIST_H_PSD) != 0;
    info->trap = (h->caps & MCA_CAP_TRAP) != 0;
    info->h_aw = h->h_aw;
    info->h2_aw = h->h2_aw;
    info->psd_aw = h->psd_aw;
    info->n_channels = 1u << h->h_aw;
    info->map2d_rows = 1u << h->h2_aw;
    info->map2d_cols = 1u << h->psd_aw;
    TRY(rd(h, MCA_R_N_ACC_MAX, &info->n_acc_max));
    uint32_t w;
    TRY(rd(h, MCA_R_N_FORMAS, &w));
    info->n_formas_max = (w >> 8) & 7u;
    return sondear_features(h, &info->features);
}

/* =========================================================================
 * Control
 * ========================================================================= */

static double ahora(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + 1e-9 * (double)t.tv_nsec;
}

/* El time.sleep() de Python, incluido su error con un negativo. */
static int dormir(mca_h *h, double s)
{
    if (!(s >= 0.0))
        return fallar(h, MCA_EINVAL, "sleep length must be non-negative");
    struct timespec ts;
    ts.tv_sec = (time_t)s;
    ts.tv_nsec = (long)((s - (double)ts.tv_sec) * 1e9);
    while (nanosleep(&ts, &ts) == -1 && errno == EINTR)
        ;
    return MCA_OK;
}

int mca_start(mca_h *h)
{
    INICIO(h);
    uint32_t c;
    TRY(rd(h, MCA_R_CTRL, &c));
    return wr(h, MCA_R_CTRL, c | 1u);
}

int mca_stop(mca_h *h)
{
    INICIO(h);
    uint32_t c;
    TRY(rd(h, MCA_R_CTRL, &c));
    return wr(h, MCA_R_CTRL, c & ~1u);
}

/* El barrido recorre 2^H_AW bins (66 us con 8192). Durante ese lapso el
 * puerto de lectura sigue vivo, asi que el bus no se cuelga, pero los eventos
 * que lleguen se descartan y se cuentan en cnt_dropped. El primer milisegundo
 * se sondea sin pausa (leer clear_busy cuesta 0.24 us y el barrido termina
 * antes); despues, cada 50 us, para no ocupar el bus si algo se trabo. Con la
 * pausa desde el principio, clear tardaba 176 us en la placa: el minimo de
 * nanosleep en el ARM, no el barrido. */
int mca_clear(mca_h *h, double timeout_s)
{
    INICIO(h);
    uint32_t c, st;
    TRY(rd(h, MCA_R_CTRL, &c));
    TRY(wr(h, MCA_R_CTRL, c | (1u << 1)));     /* clear autolimpiante */
    double t0 = ahora();
    for (;;) {
        TRY(rd(h, MCA_R_STATUS, &st));
        if (!(st & 1u))
            return MCA_OK;
        double t = ahora() - t0;
        if (t > timeout_s)
            return fallar(h, MCA_ETIMEOUT, "el barrido de borrado no termin\xc3\xb3");
        if (t > 1e-3) {
            struct timespec ts = { 0, 50000 };
            nanosleep(&ts, NULL);
        }
    }
}

/* =========================================================================
 * Estatus
 * ========================================================================= */

static int bit_de(mca_h *h, uint32_t off, int bit, uint32_t *v)
{
    uint32_t w;
    if (v == NULL)
        return MCA_EINVAL;
    TRY(rd(h, off, &w));
    *v = (w >> bit) & 1u;
    return MCA_OK;
}

int mca_get_status(mca_h *h, uint32_t *v)
{
    INICIO(h);
    if (v == NULL)
        return MCA_EINVAL;
    return rd(h, MCA_R_STATUS, v);
}

int mca_get_running(mca_h *h, uint32_t *v)
{
    INICIO(h);
    return bit_de(h, MCA_R_CTRL, 0, v);
}

int mca_get_clear_busy(mca_h *h, uint32_t *v)
{
    INICIO(h);
    return bit_de(h, MCA_R_STATUS, 0, v);
}

int mca_get_busy(mca_h *h, uint32_t *v)
{
    INICIO(h);
    return bit_de(h, MCA_R_STATUS, 1, v);
}

int mca_get_baseline_stale(mca_h *h, uint32_t *v)
{
    INICIO(h);
    return bit_de(h, MCA_R_STATUS, 2, v);
}

int mca_get_vetoed(mca_h *h, uint32_t *v)
{
    INICIO(h);
    return bit_de(h, MCA_R_STATUS, 3, v);
}

int mca_get_puede_abrir(mca_h *h, uint32_t *v)
{
    INICIO(h);
    return bit_de(h, MCA_R_STATUS, 5, v);
}

int mca_get_n_ocup(mca_h *h, uint32_t *v)
{
    INICIO(h);
    uint32_t w;
    if (v == NULL)
        return MCA_EINVAL;
    TRY(rd(h, MCA_R_STATUS, &w));
    *v = (w >> 8) & 0x7u;
    return MCA_OK;
}

int mca_get_n_acc_max(mca_h *h, uint32_t *v)
{
    INICIO(h);
    if (v == NULL)
        return MCA_EINVAL;
    return rd(h, MCA_R_N_ACC_MAX, v);
}

int mca_get_trap_ok(mca_h *h, uint32_t *v)
{
    INICIO(h);
    return bit_de(h, MCA_R_TRAP_MED, 31, v);
}

int mca_get_n_formas_max(mca_h *h, uint32_t *v)
{
    INICIO(h);
    uint32_t w;
    if (v == NULL)
        return MCA_EINVAL;
    TRY(rd(h, MCA_R_N_FORMAS, &w));
    *v = (w >> 8) & 7u;
    return MCA_OK;
}

int mca_get_umbr_ok(mca_h *h, uint32_t *v)
{
    INICIO(h);
    return bit_de(h, MCA_R_N_FORMAS, 31, v);
}

int mca_get_formas_ok(mca_h *h, uint32_t *mascara, uint32_t *n)
{
    INICIO(h);
    uint32_t w, m = 0, en_uso, tope;
    if (mascara == NULL || n == NULL)
        return MCA_EINVAL;
    TRY(rd(h, MCA_R_N_FORMAS, &w));
    /* El recorte de nf_hab en mca_top.sv: 0 es 1, y no mas que las del RTL. */
    tope = (w >> 8) & 7u;
    tope = tope > MCA_N_FORMAS_TOPE ? MCA_N_FORMAS_TOPE : (tope ? tope : 1u);
    en_uso = w & 7u;
    en_uso = en_uso == 0 ? 1u : (en_uso > tope ? tope : en_uso);
    for (uint32_t f = 0; f < en_uso; f++) {
        uint32_t ok;
        TRY(bit_de(h, f == 0 ? MCA_R_TRAP_MED : MCA_R_FORMA1_MED + 16u * (f - 1u),
                   31, &ok));
        m |= ok << f;
    }
    *mascara = m;
    *n = en_uso;
    return MCA_OK;
}

int mca_get_baseline_now(mca_h *h, int32_t *v)
{
    INICIO(h);
    uint32_t w;
    if (v == NULL)
        return MCA_EINVAL;
    TRY(rd(h, MCA_R_BASELINE_NOW, &w));
    *v = sign14(w);
    return MCA_OK;
}

int mca_get_caps(mca_h *h, uint32_t *v)
{
    INICIO(h);
    if (v == NULL)
        return MCA_EINVAL;
    return rd(h, MCA_R_CAPS, v);
}

int mca_get_widths(mca_h *h, uint32_t *h_aw, uint32_t *h2_aw, uint32_t *psd_aw)
{
    INICIO(h);
    uint32_t w;
    if (h_aw == NULL || h2_aw == NULL || psd_aw == NULL)
        return MCA_EINVAL;
    TRY(rd(h, MCA_R_WIDTHS, &w));
    *h_aw = w & 0xFFu;
    *h2_aw = (w >> 8) & 0xFFu;
    *psd_aw = (w >> 16) & 0xFFu;
    return MCA_OK;
}

/* =========================================================================
 * Configuracion en bloque
 * ========================================================================= */

void mca_config_default(mca_config_t *c)
{
    if (c == NULL)
        return;
    memset(c, 0, sizeof(*c));
    c->bl_k = 12;
    c->amp_max = 0xFFFF;
    c->dec = 1;
    c->gate_short = 32;
    c->gate_long = 384;
    c->n_acc = 1;
    c->pre_dly = 16;
    c->trap_k = 64;
    c->trap_m = 32;
    c->trap_off = 72;
    c->trap_lw = 4;
    c->trap_sh = 7;
    c->verify = 1;
    c->sel_1d = c->sel_2dx = c->sel_2dy = MCA_F_DEFAULT;
    c->discr_sel = MCA_F_DEFAULT;
    c->keep_if_full = 1;
    /* El reset del RTL: cada forma es la mitad de la anterior, con la ventana
     * en el centro de su meseta y la misma altura. Sin umbrales gana siempre la
     * forma 0, y con n_formas = 1 las otras no se miran. */
    c->n_formas = 1;
    c->forma[0] = (mca_forma_t){ .k = 32, .m = 16, .off = 40, .lw = 3, .sh = 6 };
    c->forma[1] = (mca_forma_t){ .k = 16, .m = 8,  .off = 22, .lw = 2, .sh = 5 };
    c->forma[2] = (mca_forma_t){ .k = 8,  .m = 4,  .off = 13, .lw = 1, .sh = 4 };
}

int mca_configure(mca_h *h, const mca_config_t *c)
{
    INICIO(h);
    if (c == NULL)
        return MCA_EINVAL;

    /* --- validacion: nada se escribe si algo esta mal --- */
    uint32_t n_max;
    TRY(validar_dec(h, c->dec));
    TRY(rd(h, MCA_R_N_ACC_MAX, &n_max));
    TRY(validar_n_acc(h, c->n_acc, n_max));
    TRY(validar_pre_dly(h, c->pre_dly));
    TRY(validar_trap_k(h, c->trap_k));
    if (c->trap_k + c->trap_m > MCA_TRAP_KL_MAX)
        return fallar(h, MCA_EINVAL,
                      "trap_k + trap_m = %" PRId64 ": la subida mas la meseta no "
                      "pueden pasar de %d muestras", c->trap_k + c->trap_m,
                      MCA_TRAP_KL_MAX);
    TRY(validar_trap_mq(h, c->trap_mq));
    /* Los defaults de los ejes de amplitud siguen al estimador que elige
     * amp_src; el Y del 2D es el factor de forma. */
    int32_t def = c->amp_src ? MCA_F_INT : MCA_F_PEAK;
    uint32_t s1 = 0, sx = 0, sy = 0, sd = 0;
    TRY(validar_feature(h, c->sel_1d, def, &s1));
    TRY(validar_feature(h, c->sel_2dx, def, &sx));
    TRY(validar_feature(h, c->sel_2dy, MCA_F_PSD, &sy));
    if (c->discr_en) {
        if (c->discr_min > c->discr_max && !c->discr_ext)
            return fallar(h, MCA_EINVAL,
                          "discr con min (%" PRId64 ") > max (%" PRId64 ") e "
                          "intervalo INTERNO: el conjunto es vacio y el MCA va "
                          "a rechazar TODOS los eventos. Si lo que querias es "
                          "cortar por fuera de un rango, pasa externo=True.",
                          c->discr_min, c->discr_max);
        TRY(validar_feature(h, c->discr_sel, MCA_F_PEAK, &sd));
    }
    /* El banco, con la compuerta. Se compara lo que el RTL va a ver: los valores
     * ya enmascarados. */
    uint32_t w_nf, nf_max;
    TRY(rd(h, MCA_R_N_FORMAS, &w_nf));
    nf_max = (w_nf >> 8) & 7u;
    TRY(validar_n_formas(h, c->n_formas, nf_max));
    for (int f = 1; f < MCA_N_FORMAS_TOPE; f++) {
        const mca_forma_t *fm = &c->forma[f - 1];
        TRY(validar_forma_k(h, f, fm->k));
        if (fm->k + fm->m > MCA_TRAP_KL_MAX)
            return fallar(h, MCA_EINVAL,
                          "forma%d_k + forma%d_m = %" PRId64 ": la subida mas la "
                          "meseta no pueden pasar de %d muestras", f, f,
                          fm->k + fm->m, MCA_TRAP_KL_MAX);
    }
    int usa_trap = s1 == MCA_F_TRAP || s1 == MCA_F_FORMA || sx == MCA_F_TRAP
                || sx == MCA_F_FORMA || sy == MCA_F_TRAP || sy == MCA_F_FORMA
                || (c->discr_en && (sd == MCA_F_TRAP || sd == MCA_F_FORMA));
    uint32_t gl = M(c->gate_long, 0xFFFF);
    for (int f = 0; f < c->n_formas; f++) {
        const mca_forma_t f0 = { c->trap_k, c->trap_m, c->trap_off, c->trap_lw,
                                 c->trap_sh, c->trap_antes, c->trap_despues };
        const mca_forma_t *fm = f == 0 ? &f0 : &c->forma[f - 1];
        uint32_t fin = M(fm->off, 0xFFFF) + MCA_TRAP_LAT + (1u << M(fm->lw, 7));
        if ((c->n_formas > 1 || usa_trap) && fin > gl)
            return fallar(h, MCA_EINVAL,
                          "forma %d: la ventana termina en %" PRIu32 " (off + %d + "
                          "2^lw) y la compuerta es de %" PRIu32 ": ninguna ranura "
                          "la completa y F_TRAP vale cero. Subir gate_long o bajar "
                          "off.", f, fin, MCA_TRAP_LAT, gl);
        if (M(fm->despues, 0xFFFF) > gl)
            return fallar(h, MCA_EINVAL,
                          "forma %d: despues = %" PRIu32 " y la compuerta es de %"
                          PRIu32 ": F_DTNEXT solo ve los disparos de adentro de la "
                          "ventana, asi que un vecino entre los dos no la "
                          "descartaria.", f, M(fm->despues, 0xFFFF), gl);
        if (f > 0 && !misma_ganancia(M(c->trap_k, 0x3FF), M(c->trap_sh, 0x3F),
                                     M(fm->k, 0x3FF), M(fm->sh, 0x3F)))
            return fallar(h, MCA_EINVAL,
                          "forma %d: k = %" PRIu32 " con sh = %" PRIu32 " no da la "
                          "ganancia de la forma 0 (k = %" PRIu32 ", sh = %" PRIu32
                          "): las formas con distinta ganancia parten el pico. k "
                          "tiene que ser k0 por una potencia de 2, y sh correrse "
                          "lo mismo.", f, M(fm->k, 0x3FF), M(fm->sh, 0x3F),
                          M(c->trap_k, 0x3FF), M(c->trap_sh, 0x3F));
    }

    /* --- escritura: primero se para (la ventana de amplitud y q_shift no se
     * pueden cambiar con una ranura midiendo) --- */
    TRY(wr(h, MCA_R_CTRL, c->channel ? (1u << 8) : 0u));     /* run=0, canal */
    TRY(wr(h, MCA_R_BASELINE, M(c->baseline, 0x3FFF)));
    TRY(wr(h, MCA_R_BL_CTRL,  (M(c->bl_holdoff, 0xFFFF) << 16)
                            | (M(c->bl_k, 0xF) << 4) | (c->bl_auto ? 1u : 0u)));
    TRY(wr(h, MCA_R_AMP_MIN,  M(c->amp_min, 0xFFFF)));
    TRY(wr(h, MCA_R_AMP_MAX,  M(c->amp_max, 0xFFFF)));
    TRY(wr(h, MCA_R_AMP_SRC,  (M(c->q_shift, 0x1F) << 8) | (c->amp_src ? 1u : 0u)));
    TRY(wr(h, MCA_R_DEC,      M(c->dec, 0xFFFF)));
    TRY(wr(h, MCA_R_GATE_LEN, (M(c->gate_long, 0xFFFF) << 16)
                            | M(c->gate_short, 0xFFFF)));
    TRY(wr(h, MCA_R_N_ACC,    M(c->n_acc, 0x7)));
    TRY(wr(h, MCA_R_PRE_DLY,  M(c->pre_dly, 0x7F)));
    TRY(wr(h, MCA_R_TRAP_KM,  (M(c->trap_m, 0x3FF) << 16) | M(c->trap_k, 0x3FF)));
    TRY(wr(h, MCA_R_TRAP_MQ,  M(c->trap_mq, MCA_TRAP_MQ_MAX)));
    TRY(wr(h, MCA_R_TRAP_MED, (M(c->trap_sh, 0x3F) << 24)
                            | (M(c->trap_lw, 0x7) << 16) | M(c->trap_off, 0xFFFF)));
    if (nf_max > 0) {
        TRY(wr(h, MCA_R_TRAP_UMBR, (M(c->trap_despues, 0xFFFF) << 16)
                                 | M(c->trap_antes, 0xFFFF)));
        for (uint32_t f = 1; f < nf_max && f < MCA_N_FORMAS_TOPE; f++) {
            const mca_forma_t *fm = &c->forma[f - 1];
            uint32_t base = MCA_R_FORMA1_KM + 16u * (f - 1u);
            TRY(wr(h, base,      (M(fm->m, 0x3FF) << 16) | M(fm->k, 0x3FF)));
            TRY(wr(h, base + 4u, (M(fm->sh, 0x3F) << 24)
                               | (M(fm->lw, 0x7) << 16) | M(fm->off, 0xFFFF)));
            TRY(wr(h, base + 8u, (M(fm->despues, 0xFFFF) << 16)
                               | M(fm->antes, 0xFFFF)));
        }
        TRY(wr(h, MCA_R_N_FORMAS, M(c->n_formas, 0x7)));
    }
    /* Despues de R_AMP_SRC, que mueve sel_1d/sel_2dx: este registro gana. */
    TRY(wr(h, MCA_R_HIST_SEL, (sy << 8) | (sx << 4) | s1));
    /* El zoom de configure() NO satura z (solo los setters sueltos lo hacen). */
    TRY(wr(h, MCA_R_ZOOM_1D,  (M(c->zoom_1d_k, 0xFF) << 8)  | M(c->zoom_1d_z, 0xF)));
    TRY(wr(h, MCA_R_ZOOM_2DX, (M(c->zoom_2dx_k, 0xFF) << 8) | M(c->zoom_2dx_z, 0xF)));
    TRY(wr(h, MCA_R_ZOOM_2DY, (M(c->zoom_2dy_k, 0xFF) << 8) | M(c->zoom_2dy_z, 0xF)));
    if (!c->discr_en) {
        TRY(wr(h, MCA_R_DISCR_CTRL, 0));
    } else {
        TRY(wr(h, MCA_R_DISCR_MIN, M(c->discr_min, 0xFFFF)));
        TRY(wr(h, MCA_R_DISCR_MAX, M(c->discr_max, 0xFFFF)));
        TRY(wr(h, MCA_R_DISCR_CTRL, (sd << 4) | (c->discr_ext ? 2u : 0u) | 1u));
    }
    TRY(wr(h, MCA_R_HIST_CTRL, c->keep_if_full ? 1u : 0u));

    if (c->verify) {
        struct {
            const char *n; uint32_t off; unsigned sh; int64_t esp; uint32_t m;
        } v[8] = {
            { "gate_short", MCA_R_GATE_LEN,  0, c->gate_short, 0xFFFF },
            { "gate_long",  MCA_R_GATE_LEN, 16, c->gate_long,  0xFFFF },
            { "n_acc",      MCA_R_N_ACC,     0, c->n_acc,      0x7    },
            { "pre_dly",    MCA_R_PRE_DLY,   0, c->pre_dly,    0x7F   },
            { "dec",        MCA_R_DEC,       0, c->dec,        0xFFFF },
            { "bl_k",       MCA_R_BL_CTRL,   4, c->bl_k,       0xF    },
        };
        size_t n_v = 6;
        /* Sin el trapecio o sin el banco, sus registros no existen y leen cero. */
        if (h->caps & MCA_CAP_TRAP) {
            v[n_v].n = "trap_k"; v[n_v].off = MCA_R_TRAP_KM; v[n_v].sh = 0;
            v[n_v].esp = c->trap_k; v[n_v].m = 0x3FF; n_v++;
        }
        if (nf_max > 0) {
            v[n_v].n = "n_formas"; v[n_v].off = MCA_R_N_FORMAS; v[n_v].sh = 0;
            v[n_v].esp = c->n_formas; v[n_v].m = 0x7; n_v++;
        }
        char det[MCA_LARGO_ERROR] = "";
        size_t largo = 0;
        for (size_t i = 0; i < n_v; i++) {
            uint32_t leido;
            TRY(rd(h, v[i].off, &leido));
            leido = (leido >> v[i].sh) & v[i].m;
            if (leido != M(v[i].esp, v[i].m) && largo < sizeof(det))
                largo += (size_t)snprintf(det + largo, sizeof(det) - largo,
                                          "%s%s: escribi %" PRId64 ", lei %" PRIu32,
                                          largo ? "; " : "", v[i].n, v[i].esp,
                                          leido);
        }
        if (largo)
            return fallar(h, MCA_EVERIFY,
                          "la relectura de config no coincide: %s", det);
    }
    return MCA_OK;
}

/* =========================================================================
 * Lectura
 * ========================================================================= */

/* t_win + t_div como double, sin desbordar. Dos relojes de 64 b suman hasta 65
 * bits, y Python los suma con precision arbitraria antes de pasar a float. En
 * la placa no se llega (2^64 ciclos son 4675 anios), pero un uint64 que da la
 * vuelta devolveria basura en silencio, y el arreglo es barato: con acarreo, el
 * valor se corre 2 bits conservando un bit pegajoso (que preserva el redondeo
 * al par mas cercano) y se reescala, que es exacto. El resultado es el float
 * correctamente redondeado de la suma, igual que en Python. */
static double suma_a_double(uint64_t a, uint64_t b)
{
    uint64_t t = a + b;
    unsigned acarreo = t < a;
    if (acarreo == 0)
        return (double)t;
    uint64_t w = ((uint64_t)acarreo << 62) | (t >> 2) | ((t & 3u) != 0);
    return (double)w * 4.0;
}

int mca_read_counters(mca_h *h, mca_counters_t *c)
{
    INICIO(h);
    if (c == NULL)
        return MCA_EINVAL;
    memset(c, 0, sizeof(*c));

    TRY(r64(h, MCA_R_REALTIME_LO, MCA_R_REALTIME_HI, &c->realtime));
    TRY(r64(h, MCA_R_LIVETIME_LO, MCA_R_LIVETIME_HI, &c->livetime));
    TRY(r64(h, MCA_R_DEADTIME_LO, MCA_R_DEADTIME_HI, &c->deadtime));
    TRY(r64(h, MCA_R_VETOTIME_LO, MCA_R_VETOTIME_HI, &c->vetotime));
    TRY(r64(h, MCA_R_T_WIN_LO,    MCA_R_T_WIN_HI,    &c->t_win));
    TRY(r64(h, MCA_R_T_DIV_LO,    MCA_R_T_DIV_HI,    &c->t_div));
    TRY(r64(h, MCA_R_T_CLEAR_LO,  MCA_R_T_CLEAR_HI,  &c->t_clear));
    TRY(rd(h, MCA_R_N_ACC_MAX, &c->n_acc_max));
    uint32_t n_t = (c->n_acc_max < MCA_N_ACC_TOPE ? c->n_acc_max : MCA_N_ACC_TOPE) + 1;
    for (uint32_t j = 0; j < n_t; j++) {
        uint32_t lo = MCA_R_T_OCUP + 8u * j;
        TRY(r64(h, lo, lo + 4u, &c->t_ocup[j]));
        c->t_ocup_s[j] = (double)c->t_ocup[j] / MCA_FS_HZ;
    }
    c->n_t_ocup = (int32_t)n_t;

    uint32_t st, periodos, pub_st, hs, w;
    TRY(rd(h, MCA_R_STATUS, &st));
    TRY(rd(h, MCA_R_DEAD_PERIODS, &periodos));
    TRY(rd(h, MCA_R_PUB_STATE, &pub_st));
    TRY(rd(h, MCA_R_HIST_STATUS, &hs));

    TRY(rd(h, MCA_R_CNT_TOTAL,     &c->total));
    TRY(rd(h, MCA_R_CNT_ACCEPTED,  &c->accepted));
    TRY(rd(h, MCA_R_CNT_REJ_AMP,   &c->rej_amp));
    TRY(rd(h, MCA_R_CNT_REJ_PSD,   &c->rej_psd));
    TRY(rd(h, MCA_R_CNT_PILEUP,    &c->pileup));
    TRY(rd(h, MCA_R_CNT_DROPPED,   &c->dropped));
    TRY(rd(h, MCA_R_CNT_REJ_DISCR, &c->rej_discr));
    TRY(rd(h, MCA_R_CNT_FULL_SUPP, &c->full_supp));

    c->realtime_s = (double)c->realtime / MCA_FS_HZ;
    c->livetime_s = (double)c->livetime / MCA_FS_HZ;
    c->deadtime_s = (double)c->deadtime / MCA_FS_HZ;   /* ocupacion */
    c->vetotime_s = (double)c->vetotime / MCA_FS_HZ;
    c->t_win_s    = (double)c->t_win    / MCA_FS_HZ;
    c->t_div_s    = (double)c->t_div    / MCA_FS_HZ;
    c->t_clear_s  = (double)c->t_clear  / MCA_FS_HZ;
    double muerto = suma_a_double(c->t_win, c->t_div);
    c->deadtime_real_s = muerto / MCA_FS_HZ;

    c->dead_periods = periodos;
    TRY(rd(h, MCA_R_DEAD_LEN_MAX, &w));
    c->dead_len_max_s = (double)w / MCA_FS_HZ;
    c->dead_len_mean_s = periodos ? muerto / (double)periodos / MCA_FS_HZ : 0.0;
    TRY(rd(h, MCA_R_DEAD_EXT, &c->dead_ext));
    c->dead_ext_frac = periodos ? (double)c->dead_ext / (double)periodos : 0.0;

    TRY(rd(h, MCA_R_CNT_CROSS,   &c->cross));
    TRY(rd(h, MCA_R_CNT_OPEN,    &c->open));
    TRY(rd(h, MCA_R_LOST_ACTIVE, &c->lost_active));
    TRY(rd(h, MCA_R_LOST_VETO,   &c->lost_veto));
    TRY(rd(h, MCA_R_CNT_WIN,     &c->windows));
    TRY(rd(h, MCA_R_CNT_TRIG,    &c->trig_edges));

    c->pub_occ = pub_st & 0xFFu;
    c->pub_occ_max = (pub_st >> 8) & 0xFFu;
    c->last_win_id = pub_st >> 16;
    TRY(rd(h, MCA_R_N_ACC, &w));
    c->n_acc = w & 0x7u;
    c->pub_saturada = c->pub_occ_max >= c->n_acc_max && c->n_acc_max > 0;

    c->clear_busy     = (st >> 0) & 1u;
    c->busy           = (st >> 1) & 1u;
    c->baseline_stale = (st >> 2) & 1u;
    c->vetoed         = (st >> 3) & 1u;
    c->puede_abrir    = (st >> 5) & 1u;
    c->n_ocup         = (st >> 8) & 0x7u;
    c->full_1d        = (hs >> 0) & 1u;
    c->full_2d        = (hs >> 1) & 1u;
    TRY(rd(h, MCA_R_TRAP_MED, &w));
    c->trap_ok        = (w >> 31) & 1u;
    return MCA_OK;
}

int mca_read_histogram(mca_h *h, uint32_t *dst, uint32_t n)
{
    INICIO(h);
    uint32_t esp = 1u << h->h_aw;
    if (dst == NULL || n != esp)
        return fallar(h, MCA_EINVAL, "el buffer tiene %" PRIu32 " canales y el "
                      "espectro %" PRIu32, n, esp);
    return mca_bus_read_words(h->b.bus, MCA_APERTURE_H, n, dst);
}

int mca_read_map2d(mca_h *h, uint32_t *dst, uint32_t n)
{
    INICIO(h);
    if (!(h->caps & MCA_CAP_HIST_H_PSD))
        return fallar(h, MCA_ENOSYS, "este bitstream no tiene el motor 2D "
                      "(CAPS sin CAP_HIST_H_PSD)");
    uint32_t esp = 1u << (h->h2_aw + h->psd_aw);
    if (dst == NULL || n != esp)
        return fallar(h, MCA_EINVAL, "el buffer tiene %" PRIu32 " celdas y el "
                      "mapa %" PRIu32, n, esp);
    return mca_bus_read_words(h->b.bus, MCA_APERTURE_2D, n, dst);
}

int mca_read_last_event(mca_h *h, mca_last_event_t *ev)
{
    INICIO(h);
    uint32_t w;
    if (ev == NULL)
        return MCA_EINVAL;
    TRY(rd(h, MCA_R_LAST_AMP, &w));
    ev->amp = w & 0xFFFFu;
    TRY(rd(h, MCA_R_LAST_PSD, &ev->psd));
    TRY(rd(h, MCA_R_LAST_QTOT, &ev->q_tot));
    TRY(rd(h, MCA_R_LAST_QTAIL, &ev->q_tail));
    TRY(rd(h, MCA_R_BASELINE_NOW, &w));
    ev->baseline = sign14(w);
    return MCA_OK;
}

/* Despues de parar, las ranuras abiertas cierran y publican igual: se espera a
 * que `busy` baje, con un tope de 10 ms (una ventana dura gate_long muestras y
 * la publicacion 18 ciclos). Si no baja, se sigue sin error, como en Python. */
static int esperar_vaciado(mca_h *h)
{
    uint32_t st;
    double t0 = ahora();
    for (;;) {
        TRY(rd(h, MCA_R_STATUS, &st));
        if (!(st & 2u))
            return MCA_OK;
        if (ahora() - t0 > 0.01)
            return MCA_OK;
    }
}

/* Lo que acquire y acquire_chunks leen al final, en el orden de Python: el
 * mapa se evalua antes que el `return spectrum(), m2d, counters()`. */
static int leer_resultado(mca_h *h, uint32_t *hist, uint32_t n_hist,
                          uint32_t *m2d, uint32_t n_m2d, mca_counters_t *cnt)
{
    if (m2d != NULL && (h->caps & MCA_CAP_HIST_H_PSD))
        TRY(mca_read_map2d(h, m2d, n_m2d));
    if (hist != NULL)
        TRY(mca_read_histogram(h, hist, n_hist));
    if (cnt != NULL)
        TRY(mca_read_counters(h, cnt));
    return MCA_OK;
}

int mca_read_acquire(mca_h *h, double seconds, int clear_first,
                     uint32_t *hist, uint32_t n_hist,
                     uint32_t *m2d, uint32_t n_m2d, mca_counters_t *cnt)
{
    INICIO(h);
    if (clear_first) {
        TRY(mca_stop(h));
        TRY(mca_clear(h, 1.0));
    }
    TRY(mca_start(h));
    TRY(dormir(h, seconds));
    TRY(mca_stop(h));
    TRY(esperar_vaciado(h));
    return leer_resultado(h, hist, n_hist, m2d, n_m2d, cnt);
}

/* El MCA queda PARADO (y con las ranuras vacias) durante on_chunk, asi que lo
 * que tarde el llamador en cambiar el estimulo no cuenta como tiempo vivo. */
int mca_read_acquire_chunks(mca_h *h, double seconds, double chunk_s,
                            mca_chunk_fn on_chunk, void *ctx,
                            uint32_t *hist, uint32_t n_hist,
                            uint32_t *m2d, uint32_t n_m2d, mca_counters_t *cnt)
{
    INICIO(h);
    TRY(mca_stop(h));
    TRY(mca_clear(h, 1.0));

    /* int(round(seconds / max(chunk_s, 1e-3))), con el redondeo de Python:
     * al par mas cercano (nearbyint en el modo por defecto). El max() de
     * Python devuelve el primero si el segundo no es mayor: con un NaN da NaN,
     * y eso se rechaza en vez de convertirlo en un entero cualquiera. */
    double div = (1e-3 > chunk_s) ? 1e-3 : chunk_s;
    double x = seconds / div;
    if (!isfinite(x))
        return fallar(h, MCA_EINVAL, "seconds / chunk_s no es finito");
    double r = nearbyint(x);
    int64_t n = r < 1.0 ? 1 : (int64_t)r;

    for (int64_t k = 0; k < n; k++) {
        TRY(mca_start(h));
        TRY(dormir(h, chunk_s));
        TRY(mca_stop(h));
        TRY(esperar_vaciado(h));
        if (on_chunk != NULL && k < n - 1) {
            int rc = on_chunk(ctx, (int32_t)k);
            if (rc != 0)
                return fallar(h, MCA_EBACKEND, "on_chunk(%" PRId64 ") devolvio %d",
                              k, rc);
        }
    }
    return leer_resultado(h, hist, n_hist, m2d, n_m2d, cnt);
}

static int32_t recortar(int32_t s)
{
    return s < 0 ? 0 : (s > 31 ? 31 : s);
}

/* round(log2(x)) sin log2(): con x = m * 2^e y m en [0.5, 1), sale exacto de
 * la mantisa. No es por velocidad: log2() de glibc
 * exporta el simbolo GLIBC_2.29, y un .so que lo pida no carga en una placa
 * con una glibc anterior (lo detecta `make check-bus`). frexp() es GLIBC_2.4.
 *
 * El redondeo no tiene empates: log2(x) = k + 1/2 exige x = 2^k * sqrt(2),
 * que no es representable. */
static int32_t round_log2(double x)             /* x > 0 */
{
    int e;
    double m = frexp(x, &e);
    return m >= M_SQRT1_2 ? e : e - 1;
}

/* Elige q_shift para que la INTEGRAL caiga cerca de target_channel, midiendo
 * Q_total de un evento real. Es la unica forma de comparar pico contra
 * integral en la misma escala de canales. */
int mca_autoscale_q_shift(mca_h *h, double target_channel, double seconds,
                          int32_t *shift)
{
    INICIO(h);
    if (shift == NULL)
        return MCA_EINVAL;
    TRY(mca_read_acquire(h, seconds, 1, NULL, 0, NULL, 0, NULL));
    mca_last_event_t ev;
    TRY(mca_read_last_event(h, &ev));
    if (ev.q_tot == 0) {
        *shift = -1;
        return MCA_OK;
    }
    double t = (1.0 > target_channel) ? 1.0 : target_channel;
    double x = (double)ev.q_tot / t;
    x = (1e-9 > x) ? 1e-9 : x;
    *shift = recortar(round_log2(x));
    return MCA_OK;
}

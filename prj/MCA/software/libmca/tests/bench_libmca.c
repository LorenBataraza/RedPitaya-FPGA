/* La columna c_puro de API/bench/bench_impl.py: las mismas operaciones, sin
 * interprete. La diferencia con la columna `c` (Python -> ctypes -> libmca) es
 * lo que cuesta ctypes por llamada; la diferencia con `py`, la del interprete
 * entero.
 *
 * Mismos nombres de operacion y mismo criterio de medicion que bench_impl.py:
 * una llamada de calentamiento que no se cuenta, despues al menos 5
 * repeticiones y hasta agotar el presupuesto (maximo 5000), y mediana, p5,
 * p95 y maximo en us, con la interpolacion lineal de np.percentile. Lo que
 * escribe (w32, set_campo) es el valor que el registro ya tenia.
 *
 * Imprime JSON en stdout: {"ops": {"<op>": {"mediana_us": ..., ...}}}.
 *
 *   build/armv7l/bench_libmca [--presupuesto S] [--destructivo]
 *
 * En la placa, como root. Sin --destructivo no borra ni reconfigura nada.
 */
#define _DEFAULT_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "integration.h"
#include "mca.h"
#include "multitrigger.h"
#include "osciloscope.h"

#define MAX_REPS 5000
#define MIN_REPS 5

static mca_h *h;
static uint32_t w_campo, campo0, *hist, *m2d, n_hist, n_m2d;

static double ahora_us(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec * 1e6 + (double)t.tv_nsec / 1e3;
}

/* ---- las operaciones ----------------------------------------------------- */

static int op_r32(void)        { uint32_t v; return mca_r32(h, MCA_R_MAGIC, &v); }
static int op_w32(void)        { return mca_w32(h, MCA_R_AMP_MAX, w_campo); }
static int op_rw_h(void)       { return mca_read_words(h, MCA_APERTURE_H, n_hist, hist); }
static int op_rw_2d(void)      { return mca_read_words(h, MCA_APERTURE_2D, n_m2d, m2d); }
static int op_get_campo(void)  { uint32_t v; return mca_get_amp_max(h, &v); }
static int op_set_campo(void)  { return mca_set_amp_max(h, campo0); }
static int op_get_config(void)
{
    uint32_t v[64];
    return mca_get_config(h, v, mca_field_count());
}
static int op_counters(void)   { mca_counters_t c; return mca_read_counters(h, &c); }
static int op_last_event(void) { mca_last_event_t e; return mca_read_last_event(h, &e); }
static int op_identify(void)   { mca_info_t i; return mca_identify(h, &i); }
static int op_spectrum(void)   { return mca_read_histogram(h, hist, n_hist); }
static int op_map2d(void)      { return mca_read_map2d(h, m2d, n_m2d); }
static int op_clear(void)      { return mca_clear(h, 1.0); }
static int op_configure(void)
{
    mca_config_t c;
    mca_config_default(&c);
    return mca_configure(h, &c);
}
static int op_acquire0(void)
{
    mca_counters_t c;
    return mca_read_acquire(h, 0.0, 1, hist, n_hist, m2d, n_m2d, &c);
}

/* La region de TOP. Lo que escribe (set_route) es lo que el registro ya tenia. */
static integration_h *ig;
static integration_route_t ruta0;

static int op_top_identify(void) { integration_info_t i; return integration_identify(ig, &i); }
static int op_top_slots(void)    { integration_slots_t s; return integration_get_slots(ig, &s); }
static int op_top_caps(void)     { integration_caps_t c; return integration_get_caps(ig, &c); }
static int op_top_routes(void)
{
    integration_route_t r[INTEGRATION_N_CONSUMIDORES];
    return integration_get_routes(ig, r, INTEGRATION_N_CONSUMIDORES);
}
static int op_top_status(void)   { integration_status_t st; return integration_get_status(ig, &st); }
static int op_top_get_run(void)  { int32_t on; return integration_get_run(ig, &on); }
static int op_top_set_route(void)
{
    return integration_set_route(ig, INTEGRATION_CONS_MCA, ruta0.tap, ruta0.enable, 1);
}

/* El multitrigger. Lo que escribe (set_shield) es lo que ya habia; la mascara no se
 * mide porque escribirla recarga la fuente activa aunque el valor sea el mismo. */
static multitrigger_h *mt;
static multitrigger_shield_t shield0;

static int op_mt_or_mask(void)  { uint32_t v; return multitrigger_get_or_mask(mt, 0, &v); }
static int op_mt_snapshot(void) { uint32_t v; return multitrigger_get_snapshot(mt, &v); }
static int op_mt_flags(void)    { uint32_t v; return multitrigger_get_flags(mt, &v); }
static int op_mt_slope(void)    { multitrigger_slope_t s; return multitrigger_get_slope(mt, 0, &s); }
static int op_mt_pz(void)       { multitrigger_pz_t p; return multitrigger_get_pz(mt, 0, &p); }
static int op_mt_config(void)
{
    uint32_t v[MULTITRIGGER_N_FIELDS];
    return multitrigger_get_config(mt, v, MULTITRIGGER_N_FIELDS);
}
static int op_mt_status(void)   { multitrigger_status_t st; return multitrigger_get_status(mt, &st); }
static int op_mt_set_shield(void)
{
    return multitrigger_set_shield(mt, shield0.src, shield0.dst, shield0.dur);
}

/* El osciloscopio. Lo que escribe (set_delay) es lo que ya habia. */
static osciloscope_h *osc;
static uint32_t delay0;

static int op_osc_thr(void)    { double v; return osciloscope_get_thr(osc, 0, &v); }
static int op_osc_decim(void)  { uint32_t v; return osciloscope_get_decim(osc, 0, &v); }
static int op_osc_wp(void)     { uint32_t v; return osciloscope_get_wp_trig(osc, 0, &v); }
static int op_osc_config(void)
{
    int64_t v[OSCILOSCOPE_N_FIELDS];
    return osciloscope_get_config(osc, v, OSCILOSCOPE_N_FIELDS);
}
static int op_osc_status(void) { osciloscope_status_t st; return osciloscope_get_status(osc, &st); }
static int op_osc_set_delay(void) { return osciloscope_set_delay(osc, delay0, 0); }
static int op_osc_bram(void)   { int16_t d[32]; return osciloscope_read_bram(osc, 0, 0, 32, d); }

/* ---- medicion ------------------------------------------------------------- */

static int cmp_d(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

/* np.percentile con interpolacion lineal, sobre un arreglo ya ordenado. */
static double percentil(const double *v, int n, double p)
{
    double pos = p / 100.0 * (double)(n - 1);
    int i = (int)pos;
    if (i >= n - 1)
        return v[n - 1];
    return v[i] + (pos - (double)i) * (v[i + 1] - v[i]);
}

static double ts[MAX_REPS];
static int primera = 1;

static int medir(const char *nombre, int (*fn)(void), double presupuesto_s)
{
    int rc = fn();                       /* calentamiento, no se cuenta */
    if (rc != MCA_OK) {
        fprintf(stderr, "%s: %s (%s)\n", nombre, mca_strerror(rc),
                mca_last_error(h));
        return rc;
    }
    int n = 0;
    double fin = ahora_us() + presupuesto_s * 1e6;
    while (n < MAX_REPS && (n < MIN_REPS || ahora_us() < fin)) {
        double t0 = ahora_us();
        rc = fn();
        ts[n++] = ahora_us() - t0;
        if (rc != MCA_OK)
            return rc;
    }
    qsort(ts, (size_t)n, sizeof(ts[0]), cmp_d);
    printf("%s\n    \"%s\": {\"mediana_us\": %.6f, \"p5_us\": %.6f, "
           "\"p95_us\": %.6f, \"max_us\": %.6f, \"reps\": %d}",
           primera ? "" : ",", nombre, percentil(ts, n, 50.0),
           percentil(ts, n, 5.0), percentil(ts, n, 95.0), ts[n - 1], n);
    primera = 0;
    return MCA_OK;
}

int main(int argc, char **argv)
{
    double presupuesto = 1.0;
    int destructivo = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--presupuesto") == 0 && i + 1 < argc)
            presupuesto = atof(argv[++i]);
        else if (strcmp(argv[i], "--destructivo") == 0)
            destructivo = 1;
        else {
            fprintf(stderr, "uso: %s [--presupuesto S] [--destructivo]\n", argv[0]);
            return 2;
        }
    }

    int rc = mca_open(&h, MCA_PHYS, MCA_SIZE, 1);
    if (rc != MCA_OK) {
        fprintf(stderr, "mca_open: %s (%s)\n", mca_strerror(rc), mca_last_error(NULL));
        return 1;
    }
    uint32_t caps, h_aw, h2_aw, psd_aw, corriendo;
    mca_get_geometry(h, &caps, &h_aw, &h2_aw, &psd_aw);
    n_hist = 1u << h_aw;
    n_m2d = 1u << (h2_aw + psd_aw);
    hist = calloc(n_hist, sizeof(*hist));
    m2d = calloc(n_m2d, sizeof(*m2d));
    mca_r32(h, MCA_R_AMP_MAX, &w_campo);
    mca_get_amp_max(h, &campo0);
    mca_get_running(h, &corriendo);
    if (destructivo && corriendo) {
        fprintf(stderr, "el MCA esta corriendo: --destructivo borraria una "
                        "adquisicion en curso\n");
        return 2;
    }

    struct { const char *n; int (*fn)(void); int necesita_2d, destruye; } ops[] = {
        { "bus.r32",           op_r32,        0, 0 },
        { "bus.w32",           op_w32,        0, 0 },
        { "bus.read_words_h",  op_rw_h,       0, 0 },
        { "bus.read_words_2d", op_rw_2d,      1, 0 },
        { "api.get_campo",     op_get_campo,  0, 0 },
        { "api.set_campo",     op_set_campo,  0, 0 },
        { "api.get_config",    op_get_config, 0, 0 },
        { "api.counters",      op_counters,   0, 0 },
        { "api.last_event",    op_last_event, 0, 0 },
        { "api.identify",      op_identify,   0, 0 },
        { "api.spectrum",      op_spectrum,   0, 0 },
        { "api.map2d",         op_map2d,      1, 0 },
        { "api.clear",         op_clear,      0, 1 },
        { "api.configure",     op_configure,  0, 1 },
        { "api.acquire0",      op_acquire0,   0, 1 },
    };

    /* Con --destructivo se guardan y restauran las palabras de configuracion,
     * igual que bench_impl.py (R_CTRL aparte: solo su campo channel). */
    uint32_t foto[64], canal = 0;
    int n_campos = mca_field_count();
    if (destructivo) {
        mca_get_channel(h, &canal);
        for (int i = 0; i < n_campos; i++)
            mca_r32(h, mca_field_info(i)->offset, &foto[i]);
    }

    printf("{\"ops\": {");
    int fallas = 0;
    for (size_t i = 0; i < sizeof(ops) / sizeof(ops[0]); i++) {
        if (ops[i].necesita_2d && !(caps & MCA_CAP_HIST_H_PSD))
            continue;
        if (ops[i].destruye && !destructivo)
            continue;
        fallas += medir(ops[i].n, ops[i].fn, presupuesto) != MCA_OK;
    }

    /* Puede faltar sin que nada este mal: un bitstream anterior al refactor de
     * registros no la trae. */
    static const struct { const char *n; int (*fn)(void); } ops_top[] = {
        { "top.identify",  op_top_identify },
        { "top.slots",     op_top_slots },
        { "top.caps",      op_top_caps },
        { "top.routes",    op_top_routes },
        { "top.status",    op_top_status },
        { "top.get_run",   op_top_get_run },
        { "top.set_route", op_top_set_route },
    };
    if (integration_open(&ig, INTEGRATION_PHYS, INTEGRATION_SIZE, 1) == MCA_OK
        && integration_get_route(ig, INTEGRATION_CONS_MCA, &ruta0) == MCA_OK) {
        for (size_t i = 0; i < sizeof(ops_top) / sizeof(ops_top[0]); i++)
            fallas += medir(ops_top[i].n, ops_top[i].fn, presupuesto) != MCA_OK;
    } else {
        fprintf(stderr, "sin region de TOP: %s\n", integration_last_error(ig));
    }
    integration_close(ig);

    static const struct { const char *n; int (*fn)(void); } ops_mt[] = {
        { "mt.get_or_mask", op_mt_or_mask },
        { "mt.snapshot",    op_mt_snapshot },
        { "mt.get_flags",   op_mt_flags },
        { "mt.get_slope",   op_mt_slope },
        { "mt.get_pz",      op_mt_pz },
        { "mt.get_config",  op_mt_config },
        { "mt.get_status",  op_mt_status },
        { "mt.set_shield",  op_mt_set_shield },
    };
    if (multitrigger_open(&mt, MULTITRIGGER_PHYS, MULTITRIGGER_SIZE, 1) == MCA_OK
        && multitrigger_get_shield(mt, &shield0) == MCA_OK) {
        for (size_t i = 0; i < sizeof(ops_mt) / sizeof(ops_mt[0]); i++)
            fallas += medir(ops_mt[i].n, ops_mt[i].fn, presupuesto) != MCA_OK;
    } else {
        fprintf(stderr, "sin multitrigger: %s\n", multitrigger_last_error(mt));
    }
    multitrigger_close(mt);

    static const struct { const char *n; int (*fn)(void); } ops_osc[] = {
        { "osc.get_thr",    op_osc_thr },
        { "osc.get_decim",  op_osc_decim },
        { "osc.get_wp",     op_osc_wp },
        { "osc.get_config", op_osc_config },
        { "osc.get_status", op_osc_status },
        { "osc.set_delay",  op_osc_set_delay },
        { "osc.read_bram",  op_osc_bram },
    };
    if (osciloscope_open(&osc, OSCILOSCOPE_PHYS, 0) == MCA_OK
        && osciloscope_get_delay(osc, 0, &delay0) == MCA_OK) {
        for (size_t i = 0; i < sizeof(ops_osc) / sizeof(ops_osc[0]); i++)
            fallas += medir(ops_osc[i].n, ops_osc[i].fn, presupuesto) != MCA_OK;
    } else {
        fprintf(stderr, "sin osciloscopio: %s\n", osciloscope_last_error(osc));
    }
    osciloscope_close(osc);
    printf("\n}}\n");

    if (destructivo) {
        for (int i = 0; i < n_campos; i++)
            if (mca_field_info(i)->offset != MCA_R_CTRL)
                mca_w32(h, mca_field_info(i)->offset, foto[i]);
        mca_set_channel(h, canal);
    }
    mca_close(h);
    free(hist);
    free(m2d);
    return fallas ? 1 : 0;
}

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

#include "mca.h"

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

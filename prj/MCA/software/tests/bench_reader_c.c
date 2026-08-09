/* Cuanto costaria el lazo del lector escrito en C, en vez de Python.
 *
 * El pipeline mca/ mide un ciclo de 252.7 us por evento, del cual la atribucion
 * por fase muestra que la mayor parte NO es bus sino overhead del interprete
 * (~10-50 us por operacion de Python/NumPy en este A9 a 667 MHz). Este programa
 * mide el piso real: las mismas transacciones AXI, sin interprete en el medio.
 *
 * Fases medidas (las mismas que instrumentamos en Python):
 *   poll    1 lectura de registro (adc_state @0x00)
 *   read    ventana de S muestras x N_CH, leida DIRECTO de la BRAM
 *   rearm   3 escrituras de registro (0x00, 0x240, 0x244)
 *   book    guardar los escalares del evento en el batch
 *
 * SEGURIDAD DE ACCESO (importante):
 *   El esclavo AXI de la PL solo atiende accesos de 32 bits ALINEADOS. Un
 *   memcpy sobre esta region emite loads multi-palabra (LDM/LDRD) que la PL no
 *   reconoce: la transaccion no completa, el core queda trabado en el bus y la
 *   placa se reinicia (verificado: pasó). Por eso aca se usa exclusivamente
 *   `volatile uint32_t *` de a una palabra, que es el MISMO acceso que hace
 *   struct.unpack_from desde Python y esta probado seguro.
 *   NO reemplazar por memcpy, NEON ni nada que agrupe accesos.
 *
 * Compilar y correr en la Pitaya:
 *   gcc -O2 -o bench_reader_c bench_reader_c.c && ./bench_reader_c
 */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define SCOPE_PHYS 0x40100000u
#define SCOPE_SIZE 0x30000u
#define N_BUF      16384
#define BRAM_CH0   0x10000u
#define BRAM_CH1   0x20000u
#define REG_STATE  0x00u
#define REG_WPTRIG 0x1Cu
#define REG_MASK0  0x240u
#define REG_MASK1  0x244u

#define S_REF   32          /* muestras por ventana  */
#define N_CH    2           /* canales               */
#define REPS    20000

static volatile uint32_t *g_map;

static inline uint32_t rd(uint32_t off) { return g_map[off >> 2]; }
static inline void     wr(uint32_t off, uint32_t v) { g_map[off >> 2] = v; }

static inline uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + ts.tv_nsec;
}

/* Ventana de `n` muestras del canal `ch` -> `out` (int16 con signo).
 * El readback trae {18'h0, dato[13:0]}: 14 bits sin extender el signo. */
static void read_window(int ch, uint32_t start, int n, int16_t *out) {
    const uint32_t base = (ch == 0 ? BRAM_CH0 : BRAM_CH1) >> 2;
    for (int i = 0; i < n; i++) {
        uint32_t idx = (start + (uint32_t)i) & (N_BUF - 1);
        uint32_t raw = g_map[base + idx];          /* 1 load de 32 b alineado */
        int16_t  v   = (int16_t)(raw & 0x3FFF);
        out[i] = (v & 0x2000) ? (int16_t)(v - 0x4000) : v;
    }
}

static int cmp_u64(const void *a, const void *b) {
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return (x > y) - (x < y);
}

static double median_us(uint64_t *v, int n) {
    qsort(v, n, sizeof(*v), cmp_u64);
    return v[n / 2] / 1000.0;
}

int main(void) {
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) { perror("/dev/mem"); return 1; }
    void *m = mmap(NULL, SCOPE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED,
                   fd, SCOPE_PHYS);
    if (m == MAP_FAILED) { perror("mmap"); return 1; }
    g_map = (volatile uint32_t *)m;

    /* sanity: el scope tiene que contestar (0x240 es R/W en el multitrigger) */
    wr(REG_MASK0, 0x2u);
    if (rd(REG_MASK0) != 0x2u) {
        fprintf(stderr, "no se lee un scope multitrigger en 0x%08x "
                        "(0x240 = 0x%08x). Cargar el bitstream.\n",
                SCOPE_PHYS, rd(REG_MASK0));
        return 1;
    }

    static int16_t wave[N_CH][S_REF];
    static uint64_t t_poll[REPS], t_read[REPS], t_rearm[REPS], t_book[REPS];
    struct { int64_t t_ns; int32_t wp; uint32_t snap; uint8_t gap; } ev;
    uint32_t wp = rd(REG_WPTRIG);

    for (int k = 0; k < REPS; k++) {
        uint64_t a = now_ns();
        (void)rd(REG_STATE);                                 /* poll  */
        uint64_t b = now_ns();
        uint32_t start = (wp - 8u) & (N_BUF - 1);
        for (int c = 0; c < N_CH; c++)
            read_window(c, start, S_REF, wave[c]);           /* read  */
        uint64_t c2 = now_ns();
        wr(REG_STATE, 0x00000101u);                          /* rearm */
        wr(REG_MASK0, 0x2u);
        wr(REG_MASK1, 0x2u);
        uint64_t d = now_ns();
        ev.t_ns = (int64_t)a; ev.wp = (int32_t)wp;
        ev.snap = rd(0x218u); ev.gap = 0;                    /* book + snap */
        uint64_t e = now_ns();

        t_poll[k] = b - a; t_read[k] = c2 - b;
        t_rearm[k] = d - c2; t_book[k] = e - d;
    }

    double p = median_us(t_poll, REPS), r = median_us(t_read, REPS);
    double a = median_us(t_rearm, REPS), bk = median_us(t_book, REPS);
    double tot = p + r + a + bk;

    printf("  lazo del lector en C  (%d canales x %d muestras, %d reps)\n\n",
           N_CH, S_REF, REPS);
    printf("  %-8s %8.2f us\n", "poll",  p);
    printf("  %-8s %8.2f us   (%.3f us/muestra)\n", "read", r,
           r / (N_CH * S_REF));
    printf("  %-8s %8.2f us\n", "rearm", a);
    printf("  %-8s %8.2f us   (incluye la lectura del snapshot)\n", "book", bk);
    printf("  %-8s %8.2f us   ->  techo %.1f kev/s\n", "CICLO", tot,
           1000.0 / tot);

    munmap(m, SCOPE_SIZE);
    close(fd);
    return 0;
}

/* Tests del nivel 2 en la PC: los dos backends del bus y la validacion comun, y la
 * region de DDR (mca_mem.h) con sus cuatro backends.
 *
 * devmem se prueba sobre un fichero comun (mca_bus_open_file): es el mismo
 * camino de open + mmap + calculo de pagina + accesos, solo que contra la
 * pagecache en vez de contra la PL. Lo que no se puede probar aca es la PL
 * misma; eso es API/tests/placa/diag_mca_hw.py.
 *
 *   make test
 */
#define _DEFAULT_SOURCE         /* ftruncate, pwrite, mkstemp con -std=c11 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "mca_bus.h"
#include "mca_mem.h"

static int fallas = 0;

#define CHECK(cond) do {                                                    \
    if (!(cond)) {                                                          \
        fprintf(stderr, "FALLA %s:%d: %s\n", __FILE__, __LINE__, #cond);    \
        fallas++;                                                           \
    }                                                                       \
} while (0)

/* ---- backend callback: un modelo de 64 registros que cuenta los accesos -- */

struct modelo {
    uint32_t reg[64];
    int n_r32, n_w32, n_bloque;
    int fallar;                 /* != 0: el proximo acceso devuelve este valor */
};

static int m_r32(void *ctx, uint32_t off, uint32_t *val)
{
    struct modelo *m = ctx;
    if (m->fallar) return m->fallar;
    *val = m->reg[off >> 2];
    m->n_r32++;
    return 0;
}

static int m_w32(void *ctx, uint32_t off, uint32_t val)
{
    struct modelo *m = ctx;
    if (m->fallar) return m->fallar;
    m->reg[off >> 2] = val;
    m->n_w32++;
    return 0;
}

static int m_bloque(void *ctx, uint32_t off, uint32_t n, uint32_t *dst)
{
    struct modelo *m = ctx;
    memcpy(dst, &m->reg[off >> 2], 4u * n);     /* memoria comun: no es la PL */
    m->n_bloque++;
    return 0;
}

static void test_callback(void)
{
    struct modelo m = {0};
    mca_bus_ops ops = { m_r32, m_w32, NULL, &m };
    mca_bus *b;
    uint32_t v, dst[4];

    CHECK(mca_bus_open_callback(&b, &ops, sizeof(m.reg)) == MCA_OK);
    CHECK(mca_bus_size(b) == sizeof(m.reg));

    CHECK(mca_bus_w32(b, 0x10, 0xDEADBEEF) == MCA_OK);
    CHECK(mca_bus_r32(b, 0x10, &v) == MCA_OK && v == 0xDEADBEEF);

    /* La validacion es del bus, no del backend: nunca llega al modelo. */
    int antes = m.n_r32 + m.n_w32;
    CHECK(mca_bus_r32(b, 0x11, &v) == MCA_EALIGN);
    CHECK(mca_bus_w32(b, 0x100, 1) == MCA_ERANGE);
    CHECK(mca_bus_read_words(b, 0xF8, 4, dst) == MCA_ERANGE);
    CHECK(m.n_r32 + m.n_w32 == antes);

    /* Sin read_words propio, el bloque son n lecturas sueltas. */
    m.reg[2] = 2; m.reg[3] = 3; m.reg[4] = 4; m.reg[5] = 5;
    m.n_r32 = 0;
    CHECK(mca_bus_read_words(b, 0x08, 4, dst) == MCA_OK);
    CHECK(dst[0] == 2 && dst[3] == 5 && m.n_r32 == 4);

    /* sondear: n lecturas del MISMO offset, validado una vez, sin el bloque. */
    m.reg[6] = 66;
    m.n_r32 = 0;
    uint32_t son[5] = { 0 };
    CHECK(mca_bus_sondear(b, 0x18, 5, son) == MCA_OK);
    CHECK(son[0] == 66 && son[4] == 66 && m.n_r32 == 5);
    antes = m.n_r32;
    CHECK(mca_bus_sondear(b, 0x19, 5, son) == MCA_EALIGN);
    CHECK(mca_bus_sondear(b, 0x100, 5, son) == MCA_ERANGE);
    CHECK(mca_bus_sondear(b, 0x18, 5, NULL) == MCA_EINVAL);
    CHECK(mca_bus_sondear(b, 0x18, 0, NULL) == MCA_OK);
    CHECK(m.n_r32 == antes);

    /* Los errores del backend se propagan: un codigo propio tal cual, otro
     * cualquiera como MCA_EBACKEND. */
    m.fallar = MCA_ETIMEOUT;
    CHECK(mca_bus_r32(b, 0, &v) == MCA_ETIMEOUT);
    m.fallar = 1;
    CHECK(mca_bus_w32(b, 0, 0) == MCA_EBACKEND);
    m.fallar = 0;
    mca_bus_close(b);

    /* Con read_words propio se usa ese, en UNA llamada. */
    ops.read_words = m_bloque;
    CHECK(mca_bus_open_callback(&b, &ops, 0) == MCA_OK);
    CHECK(mca_bus_size(b) == 0);
    m.n_r32 = 0;
    CHECK(mca_bus_read_words(b, 0x08, 4, dst) == MCA_OK);
    CHECK(dst[1] == 3 && m.n_bloque == 1 && m.n_r32 == 0);
    mca_bus_close(b);

    /* Argumentos invalidos. */
    mca_bus_ops sin_w32 = { m_r32, NULL, NULL, &m };
    CHECK(mca_bus_open_callback(&b, &sin_w32, 0) == MCA_EINVAL);
    CHECK(mca_bus_r32(NULL, 0, &v) == MCA_EINVAL);
}

/* ---- backend devmem, sobre un fichero ------------------------------------ */

static void test_fichero(void)
{
    char path[] = "/tmp/test_libmca_XXXXXX";
    int fd = mkstemp(path);
    CHECK(fd >= 0);
    if (fd < 0) return;

    /* 3 paginas. Se mapea desde la mitad de la primera para ejercitar el
     * calculo de offset dentro de la pagina. */
    long pag = sysconf(_SC_PAGESIZE);
    CHECK(ftruncate(fd, 3 * pag) == 0);
    uint32_t marca = 0x4D434131;            /* "MCA1" */
    CHECK(pwrite(fd, &marca, 4, pag / 2) == 4);
    close(fd);

    mca_bus *b;
    uint32_t v, dst[3];
    CHECK(mca_bus_open_file(&b, path, (uint32_t)(pag / 2), (uint32_t)pag) == MCA_OK);
    CHECK(mca_bus_r32(b, 0, &v) == MCA_OK && v == marca);

    CHECK(mca_bus_w32(b, 8, 7) == MCA_OK);
    CHECK(mca_bus_read_words(b, 0, 3, dst) == MCA_OK);
    CHECK(dst[0] == marca && dst[1] == 0 && dst[2] == 7);

    CHECK(mca_bus_r32(b, (uint32_t)pag, &v) == MCA_ERANGE);
    CHECK(mca_bus_r32(b, (uint32_t)pag - 4, &v) == MCA_OK);
    mca_bus_close(b);

    CHECK(mca_bus_open_file(&b, "/no/existe", 0, 4096) == MCA_EOPEN);
    CHECK(mca_bus_open_file(&b, path, 2, 4096) == MCA_EINVAL);
    unlink(path);
}

/* ---- la region de DDR ------------------------------------------------------ */

struct ddr_falsa {
    uint8_t m[64];
    int n_leer, n_escribir;
};

static int d_leer(void *ctx, uint32_t off, uint32_t n, void *dst)
{
    struct ddr_falsa *d = ctx;
    d->n_leer++;
    memcpy(dst, d->m + off, n);
    return 0;
}

static int d_escribir(void *ctx, uint32_t off, uint32_t n, const void *src)
{
    struct ddr_falsa *d = ctx;
    d->n_escribir++;
    memcpy(d->m + off, src, n);
    return off == 56 ? 1 : 0;   /* la ultima palabra: un error del backend */
}

static void test_mem(void)
{
    uint64_t buf[8] = { 0 }, dst[2];
    mca_mem *m;
    CHECK(mca_mem_open_ptr(&m, buf, 0x0A000000u, sizeof(buf)) == MCA_OK);
    CHECK(mca_mem_size(m) == sizeof(buf) && mca_mem_phys(m) == 0x0A000000u);
    buf[2] = 0x1122334455667788ull;
    CHECK(mca_mem_read(m, 16, 8, dst) == MCA_OK && dst[0] == buf[2]);
    uint64_t v = 0xFFFFFFFF00000000ull;
    CHECK(mca_mem_write(m, 56, 8, &v) == MCA_OK && buf[7] == v);
    /* palabras de 64 b, y dentro de la region */
    CHECK(mca_mem_read(m, 4, 8, dst) == MCA_EALIGN);
    CHECK(mca_mem_read(m, 8, 12, dst) == MCA_EALIGN);
    CHECK(mca_mem_read(m, 56, 16, dst) == MCA_ERANGE);
    CHECK(mca_mem_read(m, 64, 8, dst) == MCA_ERANGE);
    CHECK(mca_mem_read(m, 64, 0, dst) == MCA_OK);
    CHECK(mca_mem_write(m, 0xFFFFFFF8u, 8, &v) == MCA_ERANGE);
    CHECK(mca_mem_read(m, 0, 8, NULL) == MCA_EINVAL);
    mca_mem_close(m);

    CHECK(mca_mem_open_ptr(&m, NULL, 0, 64) == MCA_EINVAL);
    CHECK(mca_mem_open_ptr(&m, buf, 4, 64) == MCA_EINVAL);   /* phys sin alinear */
    CHECK(mca_mem_open_ptr(&m, buf, 0, 60) == MCA_EINVAL);   /* size sin alinear */
    CHECK(mca_mem_open_ptr(&m, buf, 0, 0) == MCA_EINVAL);

    struct ddr_falsa d = { .m = { 0 } };
    d.m[8] = 0x5A;
    CHECK(mca_mem_open_callback(&m, d_leer, d_escribir, &d, 0, sizeof(d.m)) == MCA_OK);
    CHECK(mca_mem_read(m, 8, 16, dst) == MCA_OK && (dst[0] & 0xFF) == 0x5A);
    CHECK(mca_mem_write(m, 0, 8, &v) == MCA_OK && d.n_escribir == 1);
    CHECK(mca_mem_write(m, 56, 8, &v) == MCA_EBACKEND);
    CHECK(mca_mem_read(m, 60, 8, dst) == MCA_EALIGN && d.n_leer == 1);  /* no llega */
    mca_mem_close(m);
    CHECK(mca_mem_open_callback(&m, d_leer, NULL, &d, 0, sizeof(d.m)) == MCA_OK);
    CHECK(mca_mem_write(m, 0, 8, &v) == MCA_ENOSYS);
    mca_mem_close(m);
    CHECK(mca_mem_open_callback(&m, NULL, NULL, &d, 0, 64) == MCA_EINVAL);

    /* devmem sobre un fichero: el mapeo con la pagina resuelta, como el bus */
    char path[] = "/tmp/test_libmca_mem_XXXXXX";
    int fd = mkstemp(path);
    CHECK(fd >= 0);
    if (fd < 0) return;
    long pag = sysconf(_SC_PAGESIZE);
    CHECK(ftruncate(fd, 2 * pag) == 0);
    uint64_t marca = 0x45564E5445564E54ull;
    CHECK(pwrite(fd, &marca, 8, pag + 8) == 8);
    close(fd);
    CHECK(mca_mem_open_file(&m, path, (uint32_t)pag, (uint32_t)pag) == MCA_OK);
    CHECK(mca_mem_read(m, 8, 8, dst) == MCA_OK && dst[0] == marca);
    CHECK(mca_mem_write(m, 16, 8, &marca) == MCA_OK);
    mca_mem_close(m);
    CHECK(mca_mem_open_file(&m, path, (uint32_t)pag + 16, 16) == MCA_OK);
    CHECK(mca_mem_read(m, 0, 8, dst) == MCA_OK && dst[0] == marca);   /* lo escrito */
    mca_mem_close(m);
    CHECK(mca_mem_open_file(&m, "/no/existe", 0, 4096) == MCA_EOPEN);
    mca_mem_close(NULL);
    unlink(path);
}

int main(void)
{
    test_callback();
    test_fichero();
    test_mem();
    printf("libmca %s  [%s]\n", mca_lib_version(), mca_lib_build());
    printf("test_bus: %s\n", fallas ? "FALLA" : "OK");
    return fallas ? 1 : 0;
}

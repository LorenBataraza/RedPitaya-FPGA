/* Tests del nivel 2 en la PC: los dos backends y la validacion comun.
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

int main(void)
{
    test_callback();
    test_fichero();
    printf("libmca %s  [%s]\n", mca_lib_version(), mca_lib_build());
    printf("test_bus: %s\n", fallas ? "FALLA" : "OK");
    return fallas ? 1 : 0;
}

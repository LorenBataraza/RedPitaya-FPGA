/* Lo privado del osciloscopio que comparten osciloscope.c, osciloscope_lote.c y
 * osciloscope_ring.c: el handle, la geometria, la lectura de la BRAM y la
 * calibracion. */
#ifndef OSCILOSCOPE_PRIV_H
#define OSCILOSCOPE_PRIV_H

#include <stdint.h>

#include "bloque.h"
#include "osciloscope.h"
#include "osciloscope_lote.h"

struct osciloscope_h {
    mca_bloque b;               /* primer miembro: ver bloque.h */
    osciloscope_geometria_t geo;
    int geo_leida;
};

/* La calibracion de un canal, lista para aplicar muestra por muestra. */
typedef struct {
    int32_t gain, base, offset;
    int32_t lim;                /* 2^(dw-1): el recorte de librp, en los dos sentidos */
    int32_t k;                  /* base = 2^k, o -1 si no es potencia de 2 */
} osc_cal_t;

/* La del bitstream, leida una vez y guardada en el handle. */
int osc_geometria(osciloscope_h *h, const osciloscope_geometria_t **g);

/* Valida la calibracion contra librp y la prepara. `b` recibe el detalle del error. */
int osc_cal_preparar(mca_bloque *b, const osciloscope_adc_cal_t *c, uint32_t dw,
                     osc_cal_t *p);

/* osc_cal_preparar para los n_ch primeros canales, con "canal k: " adelante del
 * error. `p` puede ser NULL si solo se valida. La usan la BRAM y el ring. */
int osc_cal_canales(mca_bloque *b, const osciloscope_adc_cal_t *c, uint32_t n_ch,
                    uint32_t dw, osc_cal_t *p);

/* Las reglas de osciloscope_read_bram: canal, largo contra el anillo y ancho de muestra. */
int osc_validar_lectura(osciloscope_h *h, const osciloscope_geometria_t *g, int64_t ch,
                        int64_t n);

/* n muestras del canal ch desde start (se reduce al anillo y da la vuelta). Con cal
 * NULL, cuentas con el signo extendido; si no, calibradas. Sin validar: ver arriba. */
int osc_leer(mca_bus *bus, const osciloscope_geometria_t *g, uint32_t ch, int64_t start,
             uint32_t n, const osc_cal_t *cal, int16_t *dst);

/* El readback trae el valor en los dw bits bajos, sin extender el signo. */
static inline int32_t osc_muestra(uint32_t w, uint32_t dw)
{
    uint32_t bit = 1u << (dw - 1);
    uint32_t v = w & ((bit << 1) - 1u);
    return (int32_t)(v ^ bit) - (int32_t)bit;
}

/* cmn_CalibCntsSigned sobre una cuenta ya extendida. La division de C trunca hacia
 * cero; el desplazamiento aritmetico, hacia abajo. Con base potencia de 2 se desplaza
 * el modulo y se le devuelve el signo: el A9 no tiene division por hardware. */
static inline int16_t osc_calibrar(const osc_cal_t *c, int32_t s)
{
    int32_t m = c->gain * (s - c->offset);
    if (c->k >= 0)
        m = m >= 0 ? (m >> c->k) : -((-m) >> c->k);
    else
        m = m / c->base;
    if (m < -c->lim)
        m = -c->lim;
    else if (m > c->lim)
        m = c->lim;
    return (int16_t)m;
}

#endif /* OSCILOSCOPE_PRIV_H */

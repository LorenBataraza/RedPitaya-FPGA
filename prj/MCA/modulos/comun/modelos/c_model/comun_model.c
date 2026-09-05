/* Modelo de referencia en C de comun.
 *
 * Se compila con -DDPI_MODE para engancharlo por DPI-C desde un scoreboard de
 * UVM, o sin el flag para correrlo suelto con el main de abajo.
 *
 * Ojo: para comun puede convenir mas el modelo en Python (modelos/python_model),
 * sobre todo si ya existe uno del lado del software. El de C rinde cuando hace
 * falta cerrar el lazo por DPI dentro de la simulacion.
 */
#include <stdio.h>
#include <stdint.h>

void comun_model_reset(void)
{
    /* TODO */
}

#ifndef DPI_MODE
int main(void)
{
    printf("=== modelo C: comun ===\n");
    comun_model_reset();
    printf("=== sin casos todavia ===\n");
    return 0;
}
#endif

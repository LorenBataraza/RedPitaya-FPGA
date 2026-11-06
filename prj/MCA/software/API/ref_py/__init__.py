"""La implementación Python de la API de hardware, congelada.

Son `mca.py`, `integration.py`, `multitrigger.py` y `osciloscope.py` tal como
estaban en el commit 06fffdd, antes de que la API pasara a `libmca` (C). La
única edición es una línea de import de `osciloscope.py`, para que use el
`multitrigger` de acá y no el de `API/`. Ese `mca.py` habla el mapa "MCA1":
es la única implementación que todavía lo abre (`mca_open(impl='py')` con ese
bitstream cargado).

`mca2.py` es la referencia del mapa "MCA2" (las ranuras), escrita para el port
de libmca a ese mapa y congelada cuando ese port cerró. El despacho `'py'` va
ahí por defecto; un handle del MCA1 lleva `_referencia` y va a `mca.py`.

Para qué existe:

  - **Benchmarks.** Es la columna `py` de `API/bench/bench_impl.py`: lo que se
    compara contra C tiene que ser siempre el mismo código, o una corrida de
    hoy y una de dentro de seis meses no son comparables.
  - **Equivalencia.** `API/tests/test_libmca_equivalencia.py` exige que esta
    implementación y la de C produzcan EXACTAMENTE la misma secuencia de
    accesos al bus para cada función pública.
  - **Selección explícita.** `mca_open(impl='py')` abre un handle de acá, y los
    testbenches de campaña lo eligen con `--impl py`.

Por eso **no se edita** y **no se le agregan funciones**. Si la API pública
cambia, la función nueva existe sólo en C y la equivalencia se prueba contra
lo que había.
"""

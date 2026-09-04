"""SHIM de compatibilidad — el generador vive en `API/rigol_dg4162.py`.

El módulo se movió tal cual, sin partirlo: es el driver de un instrumento
externo (Rigol DG4162), no un bloque de la PL, así que no le aplica la
nomenclatura de tres capas de `API/`.

Se mantiene el shim porque `import rigol_dg4162 as rg` aparece en los
testbenches, en `tests/pile-up/pileup.py` y en los notebooks. Código nuevo::

    from API.rigol_dg4162 import RigolDG4162, detector_pulse
"""

from API.rigol_dg4162 import *                                 # noqa: F401,F403
from API.rigol_dg4162 import (                                 # noqa: F401
    RigolDG4162,
    detector_pulse, two_population_wave, sliding_pulser_wave,
    pulse_train_wave, shaped_train_wave, poisson_train_wave,
    apply_poisson_train,
    forma_cr, forma_cr_rc, forma_cr_rc_n,
    forma_triangular, forma_trapezoidal, forma_bipolar,
    FORMAS_KNOLL, ARB_MAX_POINTS, ARB_MAX_SRATE, MIN_RISE_PTS,
)

# `import *` NO exporta nombres con guion bajo, y estos dos se usan desde fuera:
# `tests/pile-up/pileup.py` importa `_fwhm_pts` y llama `_escala_para_fwhm`, y
# tres tests más usan `rg._fwhm_pts`. Sin estas líneas el shim los pierde en
# silencio. `tests/gen_compat_baseline.py:privados_usados_fuera()` los detecta
# con ast, así que la lista se mantiene sola: si aparece otro, el test lo dice.
from API.rigol_dg4162 import _fwhm_pts, _escala_para_fwhm       # noqa: F401

"""SHIM de compatibilidad — el MCA vive en `API/mca.py` y `API/analisis.py`.

El refactor partió este fichero en dos: el driver y los registros a `API/mca.py`
(que además añade la API de funciones `mca_get_*` / `mca_set_*` / `mca_read_*` /
`mca_*_file_*`), y los helpers de análisis puros a `API/analisis.py`.

Se mantiene el shim para no tocar los ~40 importadores, los notebooks ni los
scripts que ya corren en la placa: `import mca_utils as mu` y todo `mu.loquesea`
siguen resolviendo igual. Código nuevo::

    from API.mca import mca_open, mca_set_thr, mca_read_histogram
    from API.analisis import gauss_fit_peak

Retirar el shim y migrar los call sites es un paso posterior, después de que
esto verifique en la placa.

Sin DeprecationWarning a propósito: saltaría en cada corrida en la Pitaya y
sería ruido en la salida de las campañas.
"""

from API.mca import *                                          # noqa: F401,F403
from API.mca import (                                          # noqa: F401
    MCA, MCANotPresent,
    MCA_PHYS, MCA_SIZE, MAGIC, APERTURE_H, APERTURE_2D,
    CAP_HIST_H, CAP_HIST_H_PSD, FS_HZ, ADC_CNT_PER_V,
    R_MAGIC, R_CAPS, R_WIDTHS, R_CTRL, R_STATUS,
    R_THR, R_HYST, R_BASELINE, R_BL_CTRL, R_BASELINE_NOW,
    R_MAXLEN, R_TAIL_DLY, R_AMP_MIN, R_AMP_MAX, R_AMP_SRC,
    R_H_SHIFT, R_H2_SHIFT, R_DEC, R_GATE_MODE, R_GATE_LEN,
    R_CNT_TOTAL, R_CNT_ACCEPTED, R_CNT_REJ_AMP, R_CNT_REJ_PSD,
    R_CNT_PILEUP, R_CNT_DROPPED,
    R_REALTIME_LO, R_REALTIME_HI, R_LIVETIME_LO, R_LIVETIME_HI,
    R_DEADTIME_LO, R_DEADTIME_HI,
    R_LAST_AMP, R_LAST_PSD, R_LAST_QTOT, R_LAST_QTAIL,
)
from API.analisis import *                                     # noqa: F401,F403
from API.analisis import (                                     # noqa: F401
    gauss_fit_peak, buscar_picos, energy_calibration, dnl, fom, deadtime_fit,
    counts_to_volts, axis_calibration, apply_calibration,
    linearize_spectrum, inl_residual_vs_knots,
    propagar_calibracion_muestra,
    tau_poisson, tau_periodico, error_cuantizacion, cv_residuo,
)

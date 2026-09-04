"""API del software de adquisición de la Red Pitaya.

Los nombres públicos llevan el prefijo completo del módulo al que pertenecen,
así que un script suelto se lee sin tener que saber de dónde vino cada función::

    from API.mca import mca_open, mca_set_thr, mca_read_histogram

    h = mca_open()
    mca_set_thr(h, 200)
    hist = mca_read_histogram(h)

Tres capas en el nombre — `<módulo>_<capa>_<campo>`:

    capa 1, módulo      a qué bloque del bus pega
                        mca_ · osciloscope_ · osciloscope_ring_ · multitrigger_
    capa 2, tipo        cfg/status sin infijo · read_ · write_file_ / save_file_
    capa 3, campo       el registro o la operación concreta

Módulos:

    API.mca                 analizador multicanal, slot 7 (0x4070_0000)
    API.osciloscope         osciloscopio clásico, slot 1 (0x4010_0000)
    API.osciloscope_ring    event_ring en DDR, slot 2 (0x4020_0000)
    API.osciloscope_store   guardado continuo del flujo de eventos (hilos+colas)
    API.multitrigger        máscaras OR, shield y snapshot del slot 1
    API.analisis            helpers PUROS de análisis, sin hardware
    API.fpga                bring-up de la PL (bitstream, puentes AXI)
    API.rigol_dg4162        driver del generador

`API.analisis` es la excepción deliberada a la nomenclatura: sus funciones
(`gauss_fit_peak`, `dnl`, `fom`, `axis_calibration`, …) no son cfg/read/store,
no tocan hardware y conservan los nombres que ya tenían. Las tres capas
gobiernan la API de *hardware*.

Este `__init__` no importa nada a propósito: así `from API import analisis`
funciona en la PC sin arrastrar los módulos que necesitan `rp` o /dev/mem.
"""

__version__ = '1.0'

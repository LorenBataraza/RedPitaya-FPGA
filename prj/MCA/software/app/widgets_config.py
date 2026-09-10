#!/usr/bin/env python3
"""Controles de configuración: la base común de las pestañas que escriben.

`panel_espectro.py` tenía un `_spin()` con un antirrebote de tres mecanismos.
Funciona, pero una pestaña de configuración del MCA tiene ~25 controles y de
tres tipos distintos, así que copiarlo 25 veces no era opción: acá está una vez,
con los tres tipos, y con la clasificación de cuándo se puede tocar cada cosa.

POR QUÉ TRES MECANISMOS Y NO UNO. Cada uno tapa un agujero distinto:

  `setKeyboardTracking(False)`  mientras se TIPEA "1234", Qt emitiría en 1, 12,
                                123 y 1234. Con esto emite recién al terminar.
  el temporizador de 250 ms     arrastrar la flecha del spinbox manda una
                                escritura por paso. Con esto se manda sólo el
                                valor con el que se quedó.
  la bandera `_cargando`        al repoblar los controles con lo que dice el
                                hardware, `setValue` dispara `valueChanged` y
                                eso REESCRIBIRÍA el mismo valor al hardware, en
                                un lazo que además pisa lo que el usuario esté
                                tipeando. Es el más difícil de ver de los tres.

Los dos primeros son comodidad; el tercero es corrección.
"""

from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QGroupBox, QLabel,
                             QSpinBox, QVBoxLayout, QWidget)

RETARDO_MS = 250

# =============================================================================
# Cuándo se puede tocar cada parámetro
# =============================================================================
#
# El usuario pidió que esto estuviera dicho, y que parar la adquisición un
# instante no fuera problema. Así que el criterio es AVISAR, no prohibir: la
# GUI escribe siempre y dice qué implica.

CALIENTE = 'caliente'    # no interrumpe nada
CORTA    = 'corta'       # reinicia la cuenta en curso
INVALIDA = 'invalida'    # el histograma YA acumulado deja de tener sentido
RIESGO   = 'riesgo'      # mal puesto, deja el sistema sin eventos

_EXPLICACION = {
    CALIENTE: 'Se puede cambiar con la medición corriendo.',
    CORTA:    'Cambiarlo REINICIA la cuenta en curso.',
    INVALIDA: ('Cambia el significado del eje: lo que ya está acumulado se '
               'mezcla con lo nuevo. Conviene borrar después de aplicar.'),
    RIESGO:   'Mal puesto puede dejar el sistema SIN EVENTOS.',
}

_MARCA = {CALIENTE: '', CORTA: ' ·', INVALIDA: ' ··', RIESGO: ' ⚠'}


def _tooltip(ayuda, cuando):
    partes = [ayuda] if ayuda else []
    partes.append(_EXPLICACION[cuando])
    return '\n\n'.join(partes)


class PanelCampos(QWidget):
    """Base de los paneles que escriben campos de configuración por nombre.

    El contrato con la ventana es el mismo que ya cumplen los otros paneles:
    emite `pedir_campo(campo, valor)` y `log(texto)`, y recibe `actualizar_config`
    y `set_conectado`. La ventana no necesita saber qué controles hay adentro.

    `campo` tiene que ser una clave del `_CAMPOS` del bloque al que pertenece
    el panel, que declara en `BLOQUE`. Para el MCA el trabajador despacha por
    `getattr(A, f'mca_set_{campo}')`, así que un campo sin setter falla en
    tiempo de ejecución y no de importación; para los demás bloques va por una
    operación `<bloque>.set` con un dict. En los dos casos un nombre mal escrito
    sólo se nota al tocar el control, así que `campos_desconocidos()` lo
    comprueba de una vez y hay un test que lo corre sobre los paneles reales.
    """

    # A qué bloque van los campos de este panel. La ventana lo mira para
    # decidir a qué operación mandarlos; el panel no sabe nada de la red.
    BLOQUE = 'mca'

    pedir_campo = pyqtSignal(str, int)
    log = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cargando = False
        self._controles = {}          # campo -> (widget, leer, escribir)
        self._cuando = {}             # campo -> CALIENTE/CORTA/...

    # ---------- construcción de controles ----------

    def _registrar(self, campo, w, leer, escribir, cuando, ayuda):
        w.setToolTip(_tooltip(ayuda, cuando))
        self._controles[campo] = (w, leer, escribir)
        self._cuando[campo] = cuando
        return w

    def _emitir(self, campo, valor):
        if self._cargando:
            return
        self.pedir_campo.emit(campo, int(valor))
        cuando = self._cuando.get(campo, CALIENTE)
        if cuando == INVALIDA:
            self.log.emit(f'{campo}: cambia el eje — lo acumulado antes de '
                          f'este punto ya no es comparable')
        elif cuando == RIESGO:
            self.log.emit(f'{campo} = {valor}: si el espectro se queda en cero, '
                          f'es esto')

    def _spin(self, campo, minimo, maximo, cuando=CALIENTE, ayuda='', paso=1):
        s = QSpinBox()
        s.setRange(minimo, maximo)
        s.setSingleStep(paso)
        s.setKeyboardTracking(False)
        t = QTimer(s, singleShot=True, interval=RETARDO_MS)
        t.timeout.connect(lambda: self._emitir(campo, s.value()))
        s.valueChanged.connect(lambda _v: None if self._cargando else t.start())
        return self._registrar(campo, s, s.value, s.setValue, cuando, ayuda)

    def _check(self, campo, texto, cuando=CALIENTE, ayuda=''):
        c = QCheckBox(texto + _MARCA[cuando])
        # Sin temporizador: una casilla no tiene estados intermedios, así que
        # el antirrebote no aporta y sí agregaría un retardo visible.
        c.toggled.connect(lambda v: self._emitir(campo, 1 if v else 0))
        return self._registrar(campo, c, lambda: int(c.isChecked()),
                               lambda v: c.setChecked(bool(v)), cuando, ayuda)

    def _combo(self, campo, opciones, cuando=CALIENTE, ayuda=''):
        """`opciones` es [(texto, valor)]. El valor va al hardware, no el índice."""
        cb = QComboBox()
        for texto, valor in opciones:
            cb.addItem(texto, valor)
        cb.currentIndexChanged.connect(
            lambda _i: self._emitir(campo, cb.currentData()))

        def escribir(v):
            i = cb.findData(int(v))
            # Un valor que no está en la lista es un registro que el bitstream
            # no implementa (lee 0) o una ranura reservada. Se muestra crudo en
            # vez de mentir eligiendo la primera opción.
            if i < 0:
                cb.setCurrentIndex(-1)
                cb.setEditText(f'({v})') if cb.isEditable() else None
            else:
                cb.setCurrentIndex(i)

        return self._registrar(campo, cb, cb.currentData, escribir, cuando, ayuda)

    # ---------- estado ----------

    def actualizar_config(self, cfg):
        """Repuebla los controles con lo que dice el hardware, sin reenviarlo."""
        self._cargando = True
        try:
            for campo, (_w, _leer, escribir) in self._controles.items():
                if campo in cfg:
                    escribir(cfg[campo])
        finally:
            self._cargando = False

    def set_conectado(self, conectado, running=False):
        for w, _l, _e in self._controles.values():
            w.setEnabled(conectado)

    def campos(self):
        return tuple(self._controles)


def campos_sin_setter(campos):
    """Los que NO tienen `mca_set_<campo>` en API/mca.py.

    El trabajador escribe por `getattr`, así que un campo mal escrito no falla
    al importar sino al tocarlo, y el usuario ve un error en el log en vez de
    un control que no anda. Esto lo convierte en algo comprobable de una vez.
    """
    from API import mca as A
    return tuple(c for c in campos if not hasattr(A, f'mca_set_{c}'))


def campos_desconocidos(campos, bloque='mca'):
    """Los que NO existen en el `_CAMPOS` del bloque que dice el panel.

    Generaliza `campos_sin_setter` a los bloques que no son el MCA: el OSC y el
    multitrigger no tienen un setter por campo, se configuran con un dict que el
    servidor valida contra su propia tabla. Un nombre mal escrito llegaría hasta
    allá y volvería como un error en el log; esto lo detecta en un test.
    """
    from API import mca as A
    from API import multitrigger as MT
    from API import osciloscope as O
    tablas = {'mca': A._CAMPOS, 'osc': O._CAMPOS, 'mtrg': MT._CAMPOS}
    if bloque not in tablas:
        raise ValueError(f'bloque desconocido: {bloque!r}; hay: {sorted(tablas)}')
    return tuple(c for c in campos if c not in tablas[bloque])


def grupo(titulo, *widgets_o_filas):
    """Un QGroupBox con una columna de widgets. Azúcar para armar los paneles."""
    g = QGroupBox(titulo)
    v = QVBoxLayout(g)
    for w in widgets_o_filas:
        v.addWidget(w if isinstance(w, QWidget) else QLabel(str(w)))
    return g

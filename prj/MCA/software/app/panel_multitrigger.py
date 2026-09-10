#!/usr/bin/env python3
"""Pestaña del multitrigger: qué puede disparar, qué disparó, y el shield.

Es el bloque que este proyecto **añadió** al scope original de RedPitaya, en los
registros 0x210-0x24C. Comparte el slot físico con el osciloscopio, y sin
embargo va en su propia pestaña: son dos APIs sobre la misma región y mezclarlas
esconde justamente eso. El osciloscopio clásico —umbral, decimación, delay,
calibración, BRAM— está en la pestaña de al lado.

Tres cosas se hacen desde acá:

  - **las máscaras OR**, que dicen qué fuentes pueden disparar cada canal. Van
    como casillas con nombre y no como un hexadecimal: los bits son 17 y
    escribir `0x2` a mano cuando se quería `0x4` no deja ningún rastro;
  - **el `trigger_shield`**, que re-arma el disparo por hardware. Es lo que
    permite tasas altas: sin él, el lazo de lectura tiene que pulsar 0x94
    después de cada evento y ese pulso es el tiempo muerto;
  - **el snapshot**, que dice qué fuente disparó de verdad. Es STICKY, así que
    acumula desde la última limpieza — y por eso lleva su botón.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QFormLayout, QGridLayout, QGroupBox,
                             QLabel, QPushButton, QScrollArea, QVBoxLayout,
                             QWidget)

from app.widgets_config import CORTA, PanelCampos

# Cuántas casillas por fila en la grilla de máscaras. Tres columnas dejan los
# 17 bits en seis filas, que entra sin scroll al lado de los otros grupos.
COLUMNAS = 3


class PanelMultitrigger(PanelCampos):
    """Máscaras, shield y snapshot del bloque multitrigger."""

    BLOQUE = 'mtrg'

    pedir_mascara = pyqtSignal(int, int)     # canal, máscara
    pedir_armar = pyqtSignal(bool)           # True = armar, False = desarmar
    pedir_refresco = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bits = ()                      # [(nombre, valor, ayuda)]
        self._casillas = {}                  # (canal, valor) -> QCheckBox
        self._mascaras = {0: 0, 1: 0}
        self._construir()
        self.set_conectado(False)

    # =========================================================================
    # Construcción
    # =========================================================================

    def _construir(self):
        interior = QWidget()
        self._v = QVBoxLayout(interior)
        self._grupo_mascaras = QGroupBox('Fuentes de disparo (máscara OR)')
        self._rejilla = QGridLayout(self._grupo_mascaras)
        # Una columna elástica al final: sin esto las tres columnas de casillas
        # se reparten todo el ancho y quedan separadas por medio panel.
        self._rejilla.setColumnStretch(COLUMNAS, 1)
        self._v.addWidget(self._grupo_mascaras)
        self._v.addWidget(self._grupo_shield())
        self._v.addWidget(self._grupo_snapshot())
        self._v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(interior)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(scroll)

    def _forma(self, g):
        f = QFormLayout(g)
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return f

    def _grupo_shield(self):
        g = QGroupBox('trigger_shield (re-armado por hardware)')
        f = self._forma(g)
        f.addRow('arman (src)',
                 self._spin('shield_src', 0, 0xF, CORTA,
                            'Máscara de canales cuyo disparo activa el shield. '
                            '0x3 = ch0 y ch1. Con 0 el shield está apagado y el '
                            're-armado vuelve a ser por software.'))
        f.addRow('limpian (dst)',
                 self._spin('shield_dst', 0, 0xF, CORTA,
                            'Máscara de canales cuyo adc_trg_dis se limpia. '
                            'Normalmente igual que src.'))
        f.addRow('holdoff (ciclos)',
                 self._spin('shield_dur', 0, 0xFFFF, CORTA,
                            'Ciclos de espera antes de limpiar. Con 0 la '
                            'limpieza sale en el MISMO ciclo del disparo, que '
                            'es lo que permite re-disparar a velocidad de HW.'))

        self.lbl_runtime = QLabel('—')
        f.addRow('runtime del shield', self.lbl_runtime)
        self.lbl_flags = QLabel('—')
        self.lbl_flags.setToolTip('dis_act / we_keep, tal como los publica 0x21C.')
        f.addRow('flags', self.lbl_flags)

        btn_armar = QPushButton('Armar disparo por ADC')
        btn_armar.setToolTip(
            'Secuencia completa de armado. Cruza registros del osciloscopio y '
            'del multitrigger, y su orden importa: por eso es una operación del '
            'servidor y no una escritura suelta desde acá.')
        btn_armar.clicked.connect(lambda: self.pedir_armar.emit(True))
        btn_desarmar = QPushButton('Desarmar')
        btn_desarmar.clicked.connect(lambda: self.pedir_armar.emit(False))
        f.addRow(btn_armar)
        f.addRow(btn_desarmar)
        return g

    def _grupo_snapshot(self):
        g = QGroupBox('Qué disparó (snapshot, sticky)')
        v = QVBoxLayout(g)
        self.lbl_snap = QLabel('—')
        self.lbl_snap.setWordWrap(True)
        self.lbl_snap.setToolTip(
            'El registro es STICKY: acumula todas las fuentes que dispararon '
            'desde la última limpieza, no la última. Ver dos fuentes acá no '
            'significa que hayan disparado juntas.')
        v.addWidget(self.lbl_snap)
        btn = QPushButton('Releer')
        btn.clicked.connect(self.pedir_refresco)
        v.addWidget(btn)
        return g

    # ---------- la grilla de máscaras, que depende del servidor ----------

    def construir_bits(self, bits):
        """Arma las casillas con los nombres que mandó el servidor.

        Los nombres viajan con el dato en vez de estar duplicados acá: una
        segunda copia de la lista de bits es exactamente cómo se desincroniza
        una interfaz de un RTL que cambió.
        """
        if tuple(tuple(b) for b in bits) == self._bits:
            return
        self._bits = tuple(tuple(b) for b in bits)

        while self._rejilla.count():
            it = self._rejilla.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self._casillas = {}

        for canal in (0, 1):
            base = canal * (len(self._bits) // COLUMNAS + 2)
            self._rejilla.addWidget(QLabel(f'<b>canal {canal}</b>'), base, 0, 1,
                                    COLUMNAS)
            for i, (nombre, valor, ayuda) in enumerate(self._bits):
                c = QCheckBox(nombre)
                c.setToolTip(ayuda)
                c.toggled.connect(
                    lambda marcado, ch=canal, v=valor: self._cambio(ch, v, marcado))
                self._casillas[(canal, valor)] = c
                self._rejilla.addWidget(c, base + 1 + i // COLUMNAS,
                                        i % COLUMNAS)

    def _cambio(self, canal, valor, marcado):
        if self._cargando:
            return
        nueva = (self._mascaras[canal] | valor) if marcado else \
                (self._mascaras[canal] & ~valor)
        self._mascaras[canal] = nueva & 0xFFFFFFFF
        self.pedir_mascara.emit(canal, self._mascaras[canal])

    # =========================================================================
    # Entradas
    # =========================================================================

    def actualizar_mtrg(self, info):
        """El `mtrg.get` del servidor."""
        self.construir_bits(info.get('bits', ()))
        cfg = info.get('config', {})
        self.actualizar_config(cfg)

        self._cargando = True
        try:
            for canal, clave in ((0, 'or_mask_ch0'), (1, 'or_mask_ch1')):
                m = int(cfg.get(clave, 0))
                self._mascaras[canal] = m
                for (ch, valor), casilla in self._casillas.items():
                    if ch == canal:
                        casilla.setChecked(bool(m & valor))
        finally:
            self._cargando = False

        est = info.get('status', {})
        fuentes = est.get('fuentes') or []
        crudo = est.get('snapshot', 0)
        self.lbl_snap.setText(
            f'{crudo:#07x} — ' + (', '.join(fuentes) if fuentes
                                  else 'ninguna fuente registrada'))
        self.lbl_runtime.setText(str(est.get('shield_runtime', '—')))
        self.lbl_flags.setText(f'{est.get("flags", 0):#010x}')

    def set_conectado(self, conectado, running=False):
        super().set_conectado(conectado, running)
        for c in self._casillas.values():
            c.setEnabled(conectado)

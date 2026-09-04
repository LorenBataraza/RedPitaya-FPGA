#!/usr/bin/env python3
"""Pestaña de mensajes: todo lo que hizo la aplicación, con hora.

Cuando algo sale mal en la placa el síntoma llega tarde y desfigurado (un
espectro vacío, una tasa que no sube). Tener el orden exacto de las operaciones
es lo que permite reconstruir qué pasó, así que acá se registra todo: cada
comando, cada error con su tipo, y las transiciones de conexión.
"""

import time

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QFileDialog, QHBoxLayout, QPlainTextEdit,
                             QPushButton, QVBoxLayout, QWidget)


class PanelLog(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.texto = QPlainTextEdit(readOnly=True)
        self.texto.setMaximumBlockCount(5000)
        self.texto.setFont(QFont('monospace', 9))

        limpiar = QPushButton('Limpiar')
        limpiar.clicked.connect(self.texto.clear)
        guardar = QPushButton('Guardar log…')
        guardar.clicked.connect(self._guardar)

        botones = QHBoxLayout()
        botones.addWidget(limpiar)
        botones.addWidget(guardar)
        botones.addStretch(1)

        caja = QVBoxLayout(self)
        caja.addWidget(self.texto)
        caja.addLayout(botones)

    def agregar(self, mensaje, nivel=''):
        marca = time.strftime('%H:%M:%S')
        prefijo = f'{marca} {nivel} ' if nivel else f'{marca} '
        self.texto.appendPlainText(prefijo + mensaje)

    def info(self, mensaje):
        self.agregar(mensaje)

    def error(self, mensaje):
        self.agregar(mensaje, nivel='ERROR')

    def _guardar(self):
        ruta, _ = QFileDialog.getSaveFileName(self, 'Guardar log',
                                              'mcamon.log', 'Texto (*.log *.txt)')
        if ruta:
            with open(ruta, 'w') as f:
                f.write(self.texto.toPlainText())
            self.info(f'log guardado en {ruta}')

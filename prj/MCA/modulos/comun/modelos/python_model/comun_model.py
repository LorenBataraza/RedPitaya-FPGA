"""Modelo de referencia en Python de comun.

Antes de escribir uno nuevo, mirar si ya existe del lado del software:
prj/MCA/software/API/modelo_rtl/ tiene los modelos que usa la API en produccion
(ring_format.py, estimadores.py). Esos NO se mueven aca — se importan, y este
modulo agrega solo lo especifico de verificacion.
"""
from __future__ import annotations


class ComunModel:
    """Modelo bit-exacto de comun."""

    def reset(self) -> None:
        raise NotImplementedError

    def step(self, **kwargs):
        raise NotImplementedError

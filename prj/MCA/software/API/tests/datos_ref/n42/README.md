# N42.42-2011: el esquema de NIST

Son de [N42.42-2011 en NIST](https://www.nist.gov/pml/radiation-physics/n42-2011), sin
modificar. `API/tests/test_n42.py` los usa como referencia: lo que importa es que otro
programa abra el archivo, y eso no lo decide este código.

| Archivo | Qué es | De dónde |
|---|---|---|
| `n42.xsd` | el esquema, versión 0.0.54 | <https://www.nist.gov/document/n42xsd> |
| `n42.sch` | las reglas que el XSD no puede expresar | <https://www.nist.gov/document/n42sch> |
| `annexb.n42` | el ejemplo del Anexo B | <https://www.nist.gov/document/annexbn42xml> |
| `correr_schematron.py` | corre `n42.sch` con Saxon, a mano | escrito acá |

`make verificar` valida contra el XSD con `lxml`, y se saltea si no está. Las reglas de
`n42.sch` están en XSLT 2, y `lxml` no las corre: si cambia lo que escribe `API/n42.py`,
hay que correr `correr_schematron.py`, que explica cómo.

Además se abrieron una vez con un lector independiente, `SpecUtils` de Sandia
(`pip install SandiaSpecUtils`, 0.0.11): da los mismos canales, cuentas, tiempos,
calibración e instrumento. Ojo al compararlo: `SpecUtils` ignora el desvío horario de
`annexb.n42` (`-07:00`). Lo que escribe `API/n42.py` va siempre en UTC (`Z`), y ahí no
hay ambigüedad.

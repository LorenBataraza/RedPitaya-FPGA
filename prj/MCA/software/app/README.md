# mcamon — la aplicación cliente/servidor del MCA

**Documentación completa:** [`prj/MCA/docs/APP/`](../../docs/APP/)

| Documento | Qué contiene |
|---|---|
| [README](../../docs/APP/README.md) | qué es la app, la arquitectura en corto, las pestañas, y las diferencias con `mcpha` |
| [Flujo de datos](../../docs/APP/flujo_de_datos.md) | el camino de control y el de datos, hilo por hilo |
| [Protocolo](../../docs/APP/protocolo.md) | las 15 operaciones, la trama, los errores |
| [Pruebas](../../docs/APP/pruebas.md) | qué demuestra cada test y qué no cubre ninguno |

---

## Arrancarlo

**Sin placa**, contra un MCA simulado — levanta servidor y GUI de una:

```bash
make -C .. gui-demo
```

**Contra la Pitaya** — levanta el servidor allá si no estaba y abre la GUI acá:

```bash
make -C .. gui-placa
```

**A mano**, si hace falta separarlo:

```bash
# en la placa (como root, por eso el 1001 anda)
python3 app/mca_server.py --port 1001
python3 app/mca_server.py --selftest    # comprueba el camino de lectura y sale

# en la PC
python3 app/mcamon.py --host 10.73.28.27 --port 1001 --conectar
```

> **En la PC hay que usar un puerto ≥ 1024.** El 1001 por defecto es el de
> `mcpha` y en la Pitaya anda porque ahí se corre como root; en una sesión de
> usuario, Linux reserva todo lo que está por debajo de 1024 y el `bind` falla
> con `PermissionError`. Los objetivos del Makefile ya usan 5001 en la PC.

---

## El árbol

```
app/
├── mca_server.py     ← corre en la Pitaya: expone API/mca.py por TCP
├── mcamon.py         ← corre en la PC: ventana, barra superior, hilo del socket
├── panel_espectro.py ← el histograma 1D y todo lo que se hace con él
├── panel_mapa2d.py   ← amplitud × forma, y la FOM
├── panel_log.py      ← la pestaña de mensajes
└── tests/
    ├── test_mca_remote.py    ← la superficie mca_* entera, por socket
    ├── test_mcamon_gui.py    ← la GUI de punta a punta, sin pantalla
    └── placa/
        └── e2e_rigol_app.py  ← (P,R) el lazo completo, con pulsos reales
```

El protocolo y el handle remoto viven en `API/`, no acá:
[`API/mca_net.py`](../API/mca_net.py) y [`API/mca_remote.py`](../API/mca_remote.py).
Es a propósito — son parte de la API del MCA, no de la aplicación: cualquier
script puede usarlos sin arrastrar PyQt5.

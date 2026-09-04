# Guía de uso

Recetas completas. La referencia función por función está en
[`referencia_api.md`](referencia_api.md).

Todo lo que toca `/dev/mem` corre **en la Pitaya**; lo que es análisis y
guardado corre igual en la PC. Cada receta dice cuál es cuál.

---

## 1. Arrancar la placa

**En la Pitaya.** Cargar el bitstream **antes** de mapear nada — típicamente la
primera celda del notebook.

```python
from API.fpga import load_bitstream, fpga_state, pl_bus_ready

load_bitstream('/root/mca_red_pitaya.bit.bin')
assert fpga_state() == 'operating'
assert pl_bus_ready()[0]
```

> Si venís de un kernel muerto por SIGBUS: **reiniciá la placa** y cargá el
> bitstream una sola vez, antes de mapear. Reconfigurar en caliente con mapeos
> abiertos puede dejar el puerto GP0 trabado, y de ese estado sólo se sale
> reiniciando.

---

## 2. Un espectro con el MCA

**En la Pitaya.**

```python
import time

from API.mca import (mca_open, mca_close, mca_configure, mca_clear, mca_start,
                     mca_stop, mca_read_histogram, mca_read_counters,
                     mca_get_metadata, mca_write_file_histogram)

h = mca_open()
mca_configure(h, thr=200, hyst=80, maxlen=1024, tail_dly=8,
              bl_auto=False, amp_src=0, h_shift=0, dec=1)

mca_clear(h)
mca_start(h)
time.sleep(10.0)
mca_stop(h)

hist = mca_read_histogram(h)          # ~110 ms para 16384 canales
cnt  = mca_read_counters(h)
print(f"{cnt['total']} eventos, livetime {cnt['livetime_s']:.3f} s")

mca_write_file_histogram(hist, 'espectro.csv', meta=mca_get_metadata(h))
mca_close(h)
```

Lo mismo en una línea, si no hace falta controlar el intervalo a mano:

```python
hist, mapa2d, cnt = mca_read_acquire(h, seconds=10.0)
```

### Ajustar campos sueltos

```python
from API.mca import mca_set_thr, mca_get_thr, mca_set_bl_k, mca_get_config

mca_set_thr(h, 317)
mca_set_bl_k(h, 13)        # no borra bl_holdoff ni bl_auto: hace read-modify-write
print(mca_get_config(h))   # los 19 campos, releídos del hardware
```

> **`bl_k` demasiado corto no da menos eventos: da CERO.** El seguidor de base
> persigue el pulso y lo borra antes de que cruce el umbral. Regla: τ = 2^k
> muestras ≥ 100× la duración del pulso. Ante la duda, `bl_auto=False`.

---

## 3. Capturar eventos con el osciloscopio

**En la Pitaya.** El osciloscopio y el multitrigger son dos handles sobre el
mismo bloque; `MultiTrigger.open(osc=...)` comparte el mapeo.

```python
from API.osciloscope import (Osciloscope, osciloscope_set_decim,
                             osciloscope_read_events)
from API.multitrigger import (MultiTrigger, multitrigger_arm,
                              multitrigger_disarm, BIT_ADC_P0)

osc = Osciloscope.open()
mt  = MultiTrigger.open(osc=osc)

osciloscope_set_decim(osc, 1)
multitrigger_arm(osc, mt, mask_ch0=BIT_ADC_P0, mask_ch1=BIT_ADC_P0,
                 thr=0.5, hyst=0.02, delay=1)

eventos, dur = osciloscope_read_events(osc, n=50, timeout_ms=2000)
print(mt.read_snapshot())          # qué fuentes dispararon

multitrigger_disarm(osc, mt)
osc.close()
```

> **No reordenar el armado.** `multitrigger_arm` arma la máquina (`0x00`) y
> **recién después** habilita la máscara OR (`0x240`/`0x244`). Al revés, con
> señal viva, un flanco puede disparar en la ventana pre-arm y dejar la máquina
> esperando un trigger que ya pasó. Si necesitás la secuencia a mano, copiala de
> ahí, no la reinventes.

Para una captura que no dependa de que haya señal:

```python
from API.osciloscope import osciloscope_read_capture_sw
datos = osciloscope_read_capture_sw(osc, thr=0.5)
```

---

## 4. Guardado continuo del flujo de eventos

**En la Pitaya.** Es la API de guardado: mientras la de lectura da una estructura
puntual, ésta escribe el flujo entero a disco, un `.npz` por chunk.

```python
from API.osciloscope import Osciloscope
from API.osciloscope_store import BramSource, AcquisitionSession

osc = Osciloscope.open()
src = BramSource(osc, pre=8, post=24, thr=0.5)

with AcquisitionSession(src, '/home/jupyter/DATOS/corrida_01') as s:
    s.wait(duration_s=30)
print(s.summary())
```

Con el event_ring en vez de la BRAM, el lector no cambia — `RingSource` expone la
misma interfaz:

```python
from API.osciloscope_ring import RingSource
src = RingSource(osc, ring_mem, ddr_mem, ddr_phys, ddr_size, pre=8, post=24)
```

**En la PC, sin placa**, para probar el pipeline entero:

```python
from API.osciloscope_store import FakeSource, AcquisitionSession
```

Releer un chunk:

```python
from API.osciloscope_store import load_chunk
arrays, meta = load_chunk('chunk_000000.npz')
```

---

## 5. Guardar y releer un espectro

**En la PC o en la placa.** Los tres formatos llevan el mismo par
(histograma, metadata), y `mca_load_file` los relee por extensión.

```python
from API.mca import (mca_write_file_histogram, mca_save_file_binary,
                     mca_save_file_json, mca_load_file)

mca_write_file_histogram(hist, 'esp.csv',  meta=meta)   # texto, por defecto
mca_save_file_binary    (hist, 'esp.npz',  meta=meta)   # compacto
mca_save_file_json      (hist, 'esp.json', meta=meta)   # sin numpy

hist2, meta2 = mca_load_file('esp.csv')   # y da lo mismo cuál de los tres
```

El csv lleva la metadata como comentarios de cabecera y sigue siendo un csv
normal para Excel u Origin:

```
# schema_version: 1
# thr: 317
# livetime_s: 10.0
canal,cuentas
0,0
1,3
```

Elegí csv cuando el fichero lo va a abrir una persona, `.npz` cuando lo va a
leer el resto del árbol, y `.json` cuando lo va a leer algo que no tiene numpy.

---

## 6. Analizar sin placa

**En la PC.** Los helpers de `API.analisis` no tocan hardware, así que trabajan
igual sobre un `.npz` guardado hace meses.

```python
from API.mca import mca_load_file
from API.analisis import gauss_fit_peak, energy_calibration, dnl, fom

hist, meta = mca_load_file('esp.npz')

pico = gauss_fit_peak(hist, 7700, 8300)
print(f"centroide {pico['centroid']:.1f}, resolución {pico['resolution_pct']:.2f} %")

a, b, resid, inl = energy_calibration(centroides, energias)
```

Linealizar el eje de amplitud:

```python
from API.analisis import axis_calibration, linearize_spectrum, inl_residual_vs_knots

cal = axis_calibration(ref, centroides_medidos)
if not cal['invertible']:
    raise RuntimeError('el eje se pliega: no se puede corregir')

corregido = linearize_spectrum(hist, cal)['spec']
print(inl_residual_vs_knots(cal, n_knots=(8, 16, 32, 64)))   # dimensiona la LUT del RTL
```

---

## 7. Generar señal de prueba

**En la Pitaya** (el generador va por USB/red).

```python
from API.rigol_dg4162 import RigolDG4162, detector_pulse, poisson_train_wave

g = RigolDG4162.usb()
onda = detector_pulse(128, t_rise=4, tau=16, amplitude=1.0)
g.load_arb(onda, ch=1)
g.set_arb(ch=1, freq_hz=2000.0, amp_vpp=0.6, offset_v=0.0)
g.output(1, True)
```

---

## 8. Correr los tests

**En la PC**, sin placa:

```bash
cd prj/MCA/software
python API/tests/test_compat_api.py     # nada público cambió respecto al baseline
python API/tests/test_api_mca.py        # accesores por campo y guardado
python -m pytest API/tests/test_api_mca.py API/tests/test_compat_api.py API/tests/placa/ -q
```

**En la placa**, tras el rsync habitual:

```bash
python API/tests/placa/diag_mca_hw.py         # identify + magic + un espectro completo
python API/tests/placa/test_mca_hw.py
python campanas/testbench_mca.py --list
python API/tests/placa/hw_ring_swtrig.py
```

`diag_mca_hw.py` es el chequeo que importa: si lee el espectro entero sin colgar
la placa, el camino de lectura palabra a palabra está intacto.

---

## Errores frecuentes

| Síntoma | Causa |
|---|---|
| `MCANotPresent` al abrir | está cargado el bitstream del scope, donde el slot 7 es un stub. Cargar `mca_red_pitaya.bit` |
| El proceso muere sin traceback | SIGBUS: la PL no está programada, o se mapeó antes de cargar el bitstream |
| **La placa se reinicia** al leer | alguien cambió la lectura palabra a palabra por un slice o un `np.frombuffer`. El esclavo AXI rechaza ráfagas |
| 0 eventos con señal buena | `bl_k` demasiado corto: el seguidor de base se come el pulso |
| Armado que nunca dispara | máscara OR habilitada antes del arm, o `delay=0` (caso degenerado del `bram_sm`) |
| `ImportError: No module named 'rp'` en la PC | se llamó a un camino que necesita placa. La configuración y el análisis sí importan sin ella |
| Dead-time de ~65 µs inexplicable | `auto_rearm=False`, o `delay` heredado de `rp_AcqSetTriggerDelay` |

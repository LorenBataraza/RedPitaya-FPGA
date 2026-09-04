# %% [markdown]
# # Intentando usar nueva funcion para lectura más rápida

# %%
import os
import time
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
import rp
from rp_overlay import overlay
import pathlib
import sys

# ------------------------------------------------------------
# Funciones auxiliares (iguales)
# ------------------------------------------------------------
def get_free_space_mb(path="/"):
    statvfs = os.statvfs(path)
    return (statvfs.f_bavail * statvfs.f_frsize) / (1024 * 1024)

def get_max_events_or_time(samples, channels):
    print("\n" + "="*70)
    print("Configuración de almacenamiento")
    print("="*70)
    free_mb = get_free_space_mb()
    avail_mb = free_mb - 200
    if avail_mb <= 0:
        print("Espacio insuficiente.")
        exit()
    per_event_bytes = channels * samples * 4
    max_events = int((avail_mb * 1024 * 1024) // per_event_bytes)
    print(f"Espacio disponible: {avail_mb:.1f} MB → máx eventos ≈ {max_events}")
    opt = input("¿Límite por eventos (E) o tiempo (T)? [E]: ").strip().lower()
    if opt == 't':
        mins = float(input("Minutos: "))
        return {'mode': 'time', 'duration_minutes': mins, 'max_events': max_events}
    else:
        num = int(input(f"Nº eventos (default 10, max {max_events}): ") or "10")
        num = min(num, max_events)
        return {'mode': 'events', 'num_events': num}

def select_channels(available=[1,2,3,4]):
    user = input("Canales (ej. 1,2,3 o Enter para todos): ").strip()
    if not user:
        return available
    try:
        chs = [int(c) for c in user.replace(',',' ').split() if c.isdigit()]
        return [c for c in chs if c in available] or available
    except:
        return available

def select_trigger_source():
    edge = input("Flanco (P=positivo, N=negativo) [N]: ").strip().upper()
    edge = edge if edge in ['P','N'] else 'N'
    ch = int(input("Canal trigger (1-4) [1]: ") or "1")
    ch = max(1, min(4, ch))
    letter = ['A','B','C','D'][ch-1]
    suffix = 'PE' if edge=='P' else 'NE'
    trig_src = getattr(rp, f'RP_TRIG_SRC_CH{letter}_{suffix}')
    trig_ch = getattr(rp, f'RP_CH_{ch}')
    print(f"Trigger: canal {ch}, flanco {edge}")
    return trig_src, trig_ch, ch, edge

def get_user_input(prompt, default, cast=float):
    val = input(f"{prompt} [default: {default}]: ").strip()
    return cast(val) if val else default

def generar_nombre_carpeta(set_time, channel, trig_lvl):
    day = set_time.strftime('%Y%m%d_%H%M')
    mv = int(round(trig_lvl * 1000))
    return f"Data_{day}_TCH{channel}_TL{mv:+04d}mV"

# ------------------------------------------------------------
# PROGRAMA PRINCIPAL (volt, salida en tabla cada 0.5 s)
# ------------------------------------------------------------
def main():
    print("="*100)
    print("\033[1m   Adquisición de pulsos - Modo volt, salida en tabla cada 0.5 s\033[0m")
    print("="*100 + "\n")

    TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")
    set_time = datetime.now(TZ_AR)
    print(f"Hora local: {set_time}\n")

    fpga = overlay()
    rp.rp_Init()

    dec = rp.RP_DEC_1
    fs = 125e6 / dec
    N = 16384

    trig_src, trig_ch, channel, flanco = select_trigger_source()
    default_level = 0.2 if flanco == 'P' else -0.05
    trig_lvl = get_user_input("Nivel de trigger (V)", default_level)
    samples = int(get_user_input("Muestras por evento [32 recomendado]", 32, int))
    samples_delay = int(get_user_input("Delay de muestras", 8, int))
    channels_to_acquire = select_channels()
    config = get_max_events_or_time(samples, len(channels_to_acquire))

    # Carpeta de salida
    folder = generar_nombre_carpeta(set_time, channel, trig_lvl)
    BASE_DIR = pathlib.Path("/home/jupyter/RedPitaya/DATOS").resolve()
    out_dir = BASE_DIR / folder
    out_dir.mkdir(exist_ok=True, parents=True)
    os.chdir(out_dir)
    print(f"\n📁 Datos en: {out_dir}\n")

    # Configurar hardware
    rp.rp_AcqSetTriggerSrc(trig_src)
    rp.rp_AcqSetTriggerLevel(trig_ch, trig_lvl)
    rp.rp_AcqSetTriggerDelay(0)

    # Ventana de datos
    trigger_pos_linear = N // 2
    start_linear = max(0, trigger_pos_linear - samples_delay)
    end_linear = start_linear + samples - 1
    if end_linear >= N:
        end_linear = N - 1
        start_linear = end_linear - samples + 1

    # Variables para tasa sobre ventana de tiempo (0.5 s)
    RATE_WINDOW = 0.5  # segundos
    timestamps_window = []  # lista de timestamps (segundos) de eventos en la ventana
    last_print_time = time.time()
    total_events = 0
    start_real = time.time()
    timeout_count = 0
    t_prev = None
    last_delta_us = 0.0

    # Variables para tasa instantánea (sin ventana fija)
    last_print_time = time.time()
    total_events = 0
    start_real = time.time()
    timeout_count = 0
    t_prev = None
    last_delta_us = 0.0
    current_rate = 0.0   # para mostrar

    # Almacenamiento de eventos (para guardar al final)
    events_data = []
    all_deltas_ns = []

    print("\n\n=================================================================")
    print("\033[1m PARÁMETROS DE ADQUISICIÓN SELECCIONADOS\033[0m")
    print("=================================================================\n")
    print(f"🔷 Hora del sistema: {set_time}")
    print(f"🔷 Frecuencia de muestreo = {fs/1e6:.2f} MHz")
    print(f"🔷 Canal de trigger: {channel}")
    print(f"🔷 Flanco = {flanco}")
    print(f"🔷 Nivel de trigger = {trig_lvl} V")
    print(f"🔷 Muestras por evento = {samples}")
    print(f"🔷 Delay de muestras = {samples_delay}")
    print(f"🔷 Canales seleccionados = {channels_to_acquire}")
    if config['mode'] == 'events':
        print(f"🔷 Eventos a adquirir: {config['num_events']}.\n")
    else:
        print(f"🔷 Adquisición durante {config['duration_minutes']} minutos.\n")
    
    day_time_of_first_pulse = set_time.strftime('%Y%m%d_%H%M')

    print("🟢 Iniciando adquisición...\n")
    print("="*80)
    print(f"{'Evento':>8} | {'Δt (ms)':>12} | {'Tasa prom (ev/s)':>16} | {'Fs (MHz)':>10}")
    print("="*80)

    rp.rp_AcqStart()

    try:
        while True:
            elapsed = time.time() - start_real
            if config['mode'] == 'events' and total_events >= config['num_events']:
                break
            if config['mode'] == 'time' and elapsed >= config['duration_minutes'] * 60:
                break

            # Rearmar trigger
            rp.rp_AcqSetTriggerSrc(trig_src)
            time.sleep(samples_delay / (fs / dec))

            # Esperar trigger (timeout 450 µs)
            t0 = time.perf_counter()
            triggered = False
            while (time.perf_counter() - t0) < 0.00045:
                if rp.rp_AcqGetTriggerState()[1] == rp.RP_TRIG_STATE_TRIGGERED:
                    ptr_trig = rp.rp_AcqGetWritePointerAtTrig()[1]
                    triggered = True
                    break
            if not triggered:
                timeout_count += 1
                continue

            t_detection = time.perf_counter()

            # Delta-t
            if t_prev is None:
                delta_sec = 0.0
                delta_ns = 0
                last_delta_us = 0.0
                last_delta_ms = 0.0
            else:
                delta_sec = t_detection - t_prev
                delta_ns = int(delta_sec * 1e9)
                last_delta_us = delta_ns / 1e3
                last_delta_ms = delta_ns / 1e6
            t_prev = t_detection

            # Ventana deslizante para tasa (basada en tiempo real)
            # Calcular tasa instantánea (basada en último intervalo)
            if delta_sec > 0:
                current_rate = 1.0 / delta_sec
            else:
                current_rate = 0.0   # primer evento

            # Calcular ventana circular
            offset = ptr_trig - (N // 2)
            start_circ = (start_linear + offset) % N
            end_circ = (end_linear + offset) % N

            # Leer datos (modo volt)
            data_evento = {}
            for ch in channels_to_acquire:
                rp_ch = getattr(rp, f'RP_CH_{ch}')
                if start_circ <= end_circ:
                    buf = np.empty(samples, dtype=np.float32)
                    rp.rp_AcqGetDataPosVNP(rp_ch, start_circ, end_circ, buf)
                else:
                    len1 = N - start_circ
                    len2 = end_circ + 1
                    buf1 = np.empty(len1, dtype=np.float32)
                    buf2 = np.empty(len2, dtype=np.float32)
                    rp.rp_AcqGetDataPosVNP(rp_ch, start_circ, N-1, buf1)
                    rp.rp_AcqGetDataPosVNP(rp_ch, 0, end_circ, buf2)
                    buf = np.concatenate([buf1, buf2])
                data_evento[f'ch{ch}'] = buf

            # Reiniciar adquisición
            rp.rp_AcqStop()
            rp.rp_AcqStart()

            # Guardar evento
            events_data.append({
                'timestamp_ns': int(t_detection * 1e9),
                'delta_ns': delta_ns,
                'ptr_trig': ptr_trig,
                'data': data_evento
            })
            all_deltas_ns.append(delta_ns)
            total_events += 1

            # Mostrar cada 0.5 segundos (con el último evento)
            now = time.time()
            if now - last_print_time >= 0.5:
                # Calcular tasa promedio hasta ahora
                elapsed_total = now - start_real
                if elapsed_total > 0 and total_events > 0:
                    avg_rate = total_events / elapsed_total
                else:
                    avg_rate = 0.0
                fs_mhz = fs / 1e6
                # Mostrar delta en ms (last_delta_ms ya se calculó)
                print(f"{total_events:8d} | {last_delta_ms:12.1f} | {avg_rate:16.1f} | {fs_mhz:10.0f}")
                last_print_time = now
            # # Depuración opcional (cada 100 eventos, se puede comentar)
            # if total_events % 100 == 0 and total_events > 0:
            #     espera_ms = (t_detection - t0) * 1000
            #     print(f"[DEBUG] Ev {total_events:6d} | Espera: {espera_ms:.3f} ms | Δt: {delta_ns/1e3:8.3f} µs | Timeouts: {timeout_count}", file=sys.stderr)

    except KeyboardInterrupt:
        print("\n[CTRL+C] Detenido.")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        rp.rp_AcqStop()
        rp.rp_Release()

    # Guardar datos al final
    if total_events == 0:
        print("No se capturaron eventos.")
        return

    print(f"\n[INFO] Capturados {total_events} eventos. Guardando archivo NPZ...")
    write_start = time.time()

    timestamps = np.array([e['timestamp_ns'] for e in events_data], dtype=np.int64)
    deltas = np.array([e['delta_ns'] for e in events_data], dtype=np.int64)
    ptrs = np.array([e['ptr_trig'] for e in events_data], dtype=np.int32)
    channel_arrays = {f'ch{ch}': np.zeros((total_events, samples), dtype=np.float32) for ch in channels_to_acquire}
    for i, ev in enumerate(events_data):
        for ch in channels_to_acquire:
            channel_arrays[f'ch{ch}'][i, :] = ev['data'][f'ch{ch}']

    # Calcular tasa real final (promedio)
    if total_events > 1:
        final_rate = (total_events - 1) / ((timestamps[-1] - timestamps[0]) / 1e9)
    else:
        final_rate = 0.0
    capture_rate = total_events / (time.time() - start_real)

    metadata = f"""sampling_rate_Hz: {fs}
trigger_channel: {channel}
trigger_level_V: {trig_lvl}
trigger_flank: {flanco}
samples_per_event: {samples}
samples_delay: {samples_delay}
channels: {channels_to_acquire}
total_events: {total_events}
timestamp_local_iso: {set_time.isoformat()}
acq_mode: volt_table_output
average_capture_rate_ev_per_s: {capture_rate:.2f}
average_real_pulse_rate_Hz: {final_rate:.2f}
total_timeouts: {timeout_count}
"""

    save_dict = {
        'timestamps_ns': timestamps,
        'deltas_ns': deltas,
        'ptr_trig': ptrs,
        'delta_list_ns': deltas[1:],
        'metadata': np.array([metadata], dtype=object)
    }
    for ch in channels_to_acquire:
        save_dict[f'channel_{ch}'] = channel_arrays[f'ch{ch}']

    day_time = set_time.strftime('%Y%m%d_%H%M')
    filename = f"Data_{day_time}_TCH{channel}_TL{int(trig_lvl*1000):+04d}mV.npz"
    np.savez_compressed(filename, **save_dict)

    write_elapsed = time.time() - write_start
    file_size = os.path.getsize(filename) / (1024 * 1024)
    print(f"✅ Archivo: {filename}")
    # print(f"   Tamaño: {file_size:.2f} MB | Escritura en {write_elapsed:.2f} s")
    print(f"   Tasa de captura promedio: {capture_rate:.1f} ev/s")
    # print(f"   Tasa real de pulsos (promedio): {final_rate:.1f} Hz")
    print("\n🎉 Proceso finalizado.")

if __name__ == "__main__":
    main()

# %%




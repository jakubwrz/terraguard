#!/usr/bin/env python3
"""
TerraGuard - Real-time Sensor & Hardware Diagnostic Tool
Reads and displays live telemetry from IMU, AHT10, GPS, and Encoders.
"""

import sys
import time
import os

# Ensure local imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import SocketRouterBridge


def test_sensors():
    bridge = SocketRouterBridge()
    if not bridge.sock:
        print("[!] Note: /var/run/arduino-router.sock not detected.")
        print("    Running in SIMULATION / MOCK mode for testing...")
        from main import MockBridge
        bridge = MockBridge()

    print("\n" + "=" * 65)
    print("   TERRAGUARD - LIVE SENSOR & HARDWARE DIAGNOSTIC DASHBOARD")
    print("=" * 65)
    print("Instructions:")
    print("  1. Spin each wheel by hand -> see encoder tick counters change.")
    print("  2. Turn the rover left/right -> see the IMU heading change.")
    print("  3. Blow on the AHT10 sensor -> see temp & humidity rise.")
    print("  4. Check GPS -> shows 'Searching' indoors, locks outdoors.")
    print("Press Ctrl+C to exit.\n")

    # Optional initial servo center check and IMU heading zero
    try:
        bridge.call("pan_servo", 0)
        bridge.call("reset_imu_heading")
    except Exception:
        pass

    DELAY = 0.03  # 30ms between RPC calls to avoid flooding the bridge
    rpc_ok = 0
    rpc_fail = 0

    try:
        while True:
            # --- Make RPC calls one at a time with small delays ---

            # 1. IMU Heading
            raw_head = bridge.call("get_imu_heading")
            time.sleep(DELAY)

            # 2. Temperature & Humidity (single delay between them)
            raw_temp = bridge.call("get_temperature")
            time.sleep(DELAY)
            raw_hum = bridge.call("get_humidity")
            time.sleep(DELAY)

            # 3. Encoders (just left+right averages to reduce calls)
            raw_enc_l = bridge.call("get_encoder_left")
            time.sleep(DELAY)
            raw_enc_r = bridge.call("get_encoder_right")
            time.sleep(DELAY)

            # 4. I2C Bus Status
            i2c_stat = bridge.call("get_i2c_status")

            # --- Track RPC health ---
            calls = [raw_head, raw_temp, raw_hum, raw_enc_l, raw_enc_r, i2c_stat]
            rpc_ok += sum(1 for c in calls if c is not None)
            rpc_fail += sum(1 for c in calls if c is None)
            total = rpc_ok + rpc_fail
            health_pct = int(100 * rpc_ok / total) if total > 0 else 0

            # --- Format display strings ---

            # Heading
            if raw_head is not None:
                hval = float(raw_head)
                if hval >= 0.0:
                    head_str = f"{hval:5.1f}°"
                elif hval <= -200:
                    head_str = f"RX_ERR({int(hval)})"
                elif hval <= -100:
                    head_str = f"TX_ERR({int(hval)})"
                else:
                    head_str = f"ERR({hval:.1f})"
            else:
                head_str = "OFFLINE"

            # Temperature: show value if we got a response (even 0.0 is a valid cached value)
            if raw_temp is not None:
                tval = float(raw_temp)
                temp_str = f"{tval:4.1f}°C" if tval != 0.0 else "0.0°C (Init)"
            else:
                temp_str = "OFFLINE"

            # Humidity
            if raw_hum is not None:
                hval = float(raw_hum)
                hum_str = f"{hval:4.1f}%" if hval != 0.0 else "0.0% (Init)"
            else:
                hum_str = "OFFLINE"

            # Encoders
            enc_l = int(raw_enc_l) if raw_enc_l is not None else 0
            enc_r = int(raw_enc_r) if raw_enc_r is not None else 0
            enc_str = f"L:{enc_l:6d} | R:{enc_r:6d}"

            # 5. BNO055 Diagnostic & Accelerometer
            time.sleep(DELAY)
            bno_diag = bridge.call("get_bno_diag")
            time.sleep(DELAY)
            bno_accel = bridge.call("get_bno_accel_z")

            # I2C Bus & BNO Diagnostic
            i2c_notes = []
            if i2c_stat is not None:
                i2c_notes.append("AHT10: OK" if (i2c_stat & 1) else "AHT10: MISSING")
                is_active = bool(i2c_stat & 8)
                if is_active:
                    addr_str = "0x29" if (i2c_stat & 4) else "0x28"
                    i2c_notes.append(f"BNO: ACTIVE ({addr_str})")
                else:
                    i2c_notes.append("BNO: NOT INIT")
            i2c_str = " | ".join(i2c_notes) if i2c_notes else "RPC: No Response"

            # BNO055 register diagnostic
            bno_str = ""
            if bno_diag is not None and bno_diag != -1:
                d = int(bno_diag)
                opr_mode = d & 0xFF
                calib = (d >> 8) & 0xFF
                sys_stat = (d >> 16) & 0xFF
                sys_err = (d >> 24) & 0xFF
                cal_sys = (calib >> 6) & 3
                cal_gyr = (calib >> 4) & 3
                cal_acc = (calib >> 2) & 3
                cal_mag = calib & 3
                mode_names = {0:"CONFIG",1:"ACCONLY",2:"MAGONLY",3:"GYROONLY",
                              4:"ACCMAG",5:"ACCGYRO",6:"MAGGYRO",7:"AMG",
                              8:"IMU",9:"COMPASS",0xA:"M4G",0xB:"NDOF_FMC",0xC:"NDOF"}
                mode_name = mode_names.get(opr_mode, f"0x{opr_mode:02X}")
                acc_val = (int(bno_accel) / 100.0) if bno_accel is not None else 0.0
                accel_str = f"AccZ:{acc_val:.2f}m/s²" if bno_accel is not None else "AccZ:?"
                bno_str = (f"Mode:{mode_name} Cal[S:{cal_sys} G:{cal_gyr} A:{cal_acc} M:{cal_mag}] "
                           f"Stat:{sys_stat} Err:{sys_err} {accel_str}")
            elif bno_diag == -1:
                bno_str = "BNO not initialized"
            else:
                bno_str = "RPC timeout"

            # Print updated dashboard (4 clean lines)
            output = (
                f"\r\033[K🧭 Heading: {head_str:<18} | 🌡️ Temp: {temp_str:<12} | 💧 Hum: {hum_str:<10}\n"
                f"\033[K   🛞 Encoders -> {enc_str:<25} | 🛰️ GPS: (run outdoors)\n"
                f"\033[K   🔌 I2C Bus  -> {i2c_str:<40} | 📡 RPC: {health_pct}% OK\n"
                f"\033[K   🔬 BNO055   -> {bno_str}\033[3F"
            )
            sys.stdout.write(output)
            sys.stdout.flush()
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n\n\n\n\n[+] Diagnostic ended. All sensors safely polled.")


if __name__ == "__main__":
    test_sensors()

#!/usr/bin/env python3
import time
import sys
from main import SocketRouterBridge

def main():
    print("=" * 60)
    print("   TerraGuard BNO055 - Non-Fusion Mode Test (ACCGYRO & GYROONLY)")
    print("=" * 60)

    bridge = SocketRouterBridge()
    time.sleep(0.2)

    def poke(reg, val=-1):
        res = bridge.call("bno_poke", reg, val)
        time.sleep(0.04)
        return res

    def read16(reg):
        res = bridge.call("bno_read16", reg)
        time.sleep(0.04)
        return res

    poke(0x07, 0x00) # Page 0
    poke(0x3E, 0x00) # Normal power
    poke(0x3F, 0x00) # Internal osc

    # Explicitly test Mode 0x05 (ACCGYRO) - NO FUSION ENGINE
    print("\n[+] Setting Mode 0x05: ACCGYRO (Raw Sensors, Bypasses Fusion Engine)...")
    poke(0x3D, 0x00)
    time.sleep(0.03)
    poke(0x3D, 0x05)
    time.sleep(0.05)

    r_mode = poke(0x3D)
    r_stat = poke(0x39)
    r_err = poke(0x3A)
    print(f"    Result -> OPR_MODE: 0x{r_mode:02X}, SysStat: {r_stat}, SysErr: {r_err}")

    # If 0x05 failed, try 0x03 (GYROONLY)
    if r_mode != 0x05:
        print("\n[+] Mode 0x05 rejected. Trying Mode 0x03: GYROONLY...")
        poke(0x3D, 0x00)
        time.sleep(0.03)
        poke(0x3D, 0x03)
        time.sleep(0.05)
        r_mode = poke(0x3D)
        r_stat = poke(0x39)
        r_err = poke(0x3A)
        print(f"    Result -> OPR_MODE: 0x{r_mode:02X}, SysStat: {r_stat}, SysErr: {r_err}")

    print("\n" + "=" * 60)
    print("   Live Raw Gyro & Accel Streaming - PLEASE ROTATE ROVER")
    print("=" * 60)

    yaw_accum = 0.0
    last_t = time.time()
    for i in range(25):
        now = time.time()
        dt = now - last_t
        last_t = now

        gyr_z = read16(0x18)
        gyr_x = read16(0x14)
        acc_z = read16(0x0C)

        g_dps = (gyr_z / 16.0) if (gyr_z is not None and gyr_z > -100) else 0.0
        gx_dps = (gyr_x / 16.0) if (gyr_x is not None and gyr_x > -100) else 0.0
        a_ms2 = (acc_z / 100.0) if (acc_z is not None and acc_z > -100) else 0.0

        if abs(g_dps) > 0.5:
            yaw_accum -= g_dps * dt
            while yaw_accum < 0: yaw_accum += 360.0
            while yaw_accum >= 360.0: yaw_accum -= 360.0

        print(f"  [{i+1:02d}/25] GyroZ: {g_dps:6.1f}°/s | GyroX: {gx_dps:6.1f}°/s | YawIntegrated: {yaw_accum:5.1f}° | AccZ: {a_ms2:5.2f} m/s²")
        time.sleep(0.4)

    print("\n[+] Test complete.")

if __name__ == "__main__":
    main()

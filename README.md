# TerraGuard

> **Autonomous Environmental Scout Rover for Wildfire Risk Monitoring**  
> Powered by the dual-core **Arduino Uno Q** (STM32 MCU + Linux Debian MPU), featuring real-time sensor fusion, Edge AI computer vision, BLE teleoperation, and offline GIS mapping.

---

## Overview

TerraGuard is an autonomous 4WD scout rover designed to patrol forest trails and clearings to detect ground-level wildfire fuel hazards before ignition occurs. Tree canopies frequently conceal dry combustible biomass (leaf litter, dead pine needles, dry brush) from satellites and high-altitude drones. TerraGuard navigates forest floors, fuses microclimate telemetry (temperature, relative humidity), captures ground imagery, and classifies wildfire risk in real time using an onboard Edge AI neural network.

---

## System Architecture

TerraGuard leverages the hybrid architecture of the **Arduino Uno Q**:

```
+-------------------------------------------------------------------------+
|                         ARDUINO UNO Q PLATFORM                          |
|                                                                         |
|  +-------------------------------------------------------------------+  |
|  |                 Real-Time Microcontroller (STM32)                 |  |
|  |  - 4WD motor PWM across 2x identical L298N dual H-bridge drivers   |  |
|  |  - Hardware interrupt handling for 4 wheel encoders (8 lines)      |  |
|  |  - BNO055 IMU polling and orientation integration (20 Hz)          |  |
|  |  - Environmental sensor acquisition (AHT10 on I2C)               |  |
|  |  - Onboard 12x8 LED Matrix status indicators (GPS fix, turns)    |  |
|  |  - Camera pan servo actuation (-60 deg to +60 deg)                |  |
|  +----------------------------------+--------------------------------+  |
|                                     |                                   |
|                        MessagePack RPC Socket Bridge                    |
|                                     |                                   |
|  +----------------------------------+--------------------------------+  |
|  |                   Linux Application MPU (Debian)                  |  |
|  |  - Sensor fusion: Dead-reckoning odometry (Encoders + Gyro)       |  |
|  |  - Path navigation: Curvature steering algorithm                  |  |
|  |  - BLE GATT Peripheral: Telemetry stream & command interface      |  |
|  |  - Vision pipeline: Frame acquisition & MobileNetV2 ONNX inference|  |
|  |  - Mission Logger: Structured JSON telemetry & GIS database        |  |
|  +-------------------------------------------------------------------+  |
+-------------------^---------------------------------^-------------------+
                    |                                 |
              Wi-Fi MJPEG                         BLE 5.0
                    |                                 |
+-------------------+-------------------+   +---------+-------------------+
|   Seeed Studio XIAO ESP32S3 Sense     |   |   Android Mobile Controller |
|   Camera on SG90 Pan Servo            |   |   Kotlin + Jetpack Compose  |
+---------------------------------------+   +-----------------------------+
```

---

## Repository Structure

```
.
|-- HACKSTER_DOCS.md           # Full Hackster.io submission story & technical documentation
|-- LICENSE                    # MIT License
|-- README.md                  # Project overview and setup guide
|-- deploy.bat                 # One-click deployment script to Arduino Uno Q
|-- deploy_to_arduino.ps1      # PowerShell deployment automation
|-- fetch_mission.bat          # Download mission logs and open interactive satellite map
|-- fetch_mission.ps1          # PowerShell mission sync script
|-- dataset/                   # Field-collected ground vegetation training dataset
|   |-- high_risk/             # Dry grass, combustible brush, dead pine needles
|   |-- medium_risk/           # Mixed foliage, partially dried ground cover
|   `-- low_risk/              # Fresh green vegetation, bare soil, damp ground
|-- models/                    # ONNX Runtime & PyTorch model artifacts
|   |-- best_wildfire_model.pth
|   |-- wildfire_model.onnx
|   |-- wildfire_model_int8.onnx
|   |-- wildfire_model_single.onnx
|   |-- training_history.json
|   `-- test_evaluation.json
|-- uno_q_linux/               # Linux Python application daemon
|   |-- main.py                # Main orchestration loop and RPC bridge
|   |-- sensor_fusion.py       # Encoder odometry and BNO055 heading fusion
|   |-- state_machine.py       # Operating modes (Teach, Waypoints, Drive replay)
|   |-- vision.py              # Frame capture and ONNX inference engine
|   |-- ble_server.py          # Bluetooth Low Energy GATT peripheral
|   |-- mission_logger.py      # Telemetry database and GeoJSON export
|   |-- visualize_mission.py   # Leaflet.js interactive satellite map generator
|   |-- test_sensors.py        # Sensor diagnostic script
|   `-- build_and_run.sh       # Rover startup script
|-- uno_q_stm32/               # STM32 real-time firmware (Zephyr / App Lab)
|   |-- sketch.ino             # Motor control, encoder ISR, I2C, servo control
|   |-- HardwareServo.*        # Hardware PWM servo library for Zephyr
|   `-- TinyGPS++.*            # NMEA sentence parsing library
|-- uno_q_motor_test/          # Standalone motor and encoder verification sketch
|-- xiao_esp32s3_camera/       # Seeed Studio XIAO ESP32S3 Sense camera firmware
|-- rover_controller_android/  # Native Android teleoperation app (Jetpack Compose)
`-- missions/                  # Field test telemetry logs and interactive HTML maps
```

---

## Hardware Bill of Materials

| Component | Function | Interface |
| :--- | :--- | :--- |
| **Arduino Uno Q** | Dual-core computing platform (STM32 MCU + Linux Debian MPU) with onboard 12x8 LED Matrix | Internal RPC |
| **Seeed Studio XIAO ESP32S3 Sense** | Ground inspection camera with Wi-Fi MJPEG streaming | Wi-Fi HTTP |
| **Bosch BNO055 9-DOF IMU** | Gyroscope and absolute heading orientation | I2C (0x29) |
| **AHT10 / AHT20 Sensor** | Ambient temperature and relative humidity | I2C (0x38) |
| **U-blox NEO-6M GPS** | Geographic coordinate logging | Serial1 UART (9600 baud) |
| **Quadrature Wheel Encoders (4x)** | 4x magnetic Hall quadrature encoders (Phase A & B) on 12.5 cm wheels | Digital / Analog Interrupts |
| **L298N Dual Motor Drivers (2x)** | Two identical dual H-bridge drivers (Driver 1: Left, Driver 2: Right) | PWM / Direction GPIOs |
| **SG90 Micro Servo** | Camera pan mechanism (-60° to +60°) | PWM (D9) |

---

## Pinout and Wiring

| Arduino Uno Q Pin | Peripheral Device | Connected Pin | Function / Description |
| :--- | :--- | :--- | :--- |
| **I2C SDA** | BNO055, AHT10 | SDA | Shared I2C data bus (4.7kΩ pull-up to 3.3V) |
| **I2C SCL** | BNO055, AHT10 | SCL | Shared I2C clock bus (4.7kΩ pull-up to 3.3V) |
| **Analog A0** | Front Left (FL) Encoder | Phase A | External interrupt tick counter (Yellow) |
| **Digital D12** | Front Left (FL) Encoder | Phase B | Direction sensing input (White) |
| **Digital D13** | Rear Left (RL) Encoder | Phase A | External interrupt tick counter (Yellow) |
| **Digital D11** | Rear Left (RL) Encoder | Phase B | Direction sensing input (White) |
| **Analog A1** | Front Right (FR) Encoder | Phase A | External interrupt tick counter (Yellow) |
| **Analog A2** | Front Right (FR) Encoder | Phase B | Direction sensing input (White) |
| **Analog A3** | Rear Right (RR) Encoder | Phase A | External interrupt tick counter (Yellow) |
| **Analog A4** | Rear Right (RR) Encoder | Phase B | Direction sensing input (White) |
| **Analog A5** | Left Driver (L298N #1) | FL DIR | Front Left motor direction control |
| **Digital D10 (PWM)**| Left Driver (L298N #1) | FL PWM | Front Left motor PWM speed modulation |
| **Digital D7** | Left Driver (L298N #1) | RL DIR | Rear Left motor direction control |
| **Digital D6 (PWM)**| Left Driver (L298N #1) | RL PWM | Rear Left motor PWM speed modulation |
| **Digital D4** | Right Driver (L298N #2) | FR DIR | Front Right motor direction control |
| **Digital D5 (PWM)**| Right Driver (L298N #2) | FR PWM | Front Right motor PWM speed modulation |
| **Digital D2** | Right Driver (L298N #2) | RR DIR | Rear Right motor direction control |
| **Digital D3 (PWM)**| Right Driver (L298N #2) | RR PWM | Rear Right motor PWM speed modulation |
| **Digital D9 (PWM)**| SG90 Micro Servo | Signal | Camera pan servo PWM pulse (-60° to +60°) |
| **Serial RX (D0)** | U-blox NEO-6M GPS | TX | GPS NMEA sentence input (9600 baud) |
| **Serial TX (D1)** | U-blox NEO-6M GPS | RX | GPS configuration commands |
| **3.3V Rail** | BNO055, AHT10 | VCC | 3.3V regulated power rail |
| **5V Rail** | Servo, GPS, Encoders, ESP32 | VCC | 5V buck regulator rail |
| **GND** | All Peripherals | GND | Common star ground reference |

---

## Getting Started

### 1. Flash the STM32 Firmware
Open `uno_q_stm32/sketch.ino` in the Arduino App Lab or Arduino IDE and upload it to the Arduino Uno Q's STM32 microcontroller.

### 2. Flash the Camera Firmware
Open `xiao_esp32s3_camera/xiao_esp32s3_camera.ino` in the Arduino IDE and flash it to the Seeed Studio XIAO ESP32S3 Sense. The camera will launch an access point streaming frames over HTTP.

### 3. Deploy the Linux Application
From your computer connected to the same local network:
```bash
./deploy.bat
```
This transfers the Python stack, ONNX models, and configuration files to the Uno Q.

### 4. Run the Rover Service
SSH into the Linux system on the Uno Q:
```bash
ssh arduino@[YOURIP]
python3 ~/terraguard/python/main.py
```

### 5. Connect the Android App
1. Open the project in `rover_controller_android` in Android Studio and install the app on your phone.
2. Open the app, scan for Bluetooth Low Energy devices, and connect to `TerraGuardRover`.
3. Use the onscreen joystick to explore. Switch between **TEACH**, **WAYPOINTS**, and **DRIVE** modes.

### 6. View Mission Maps
After a patrol session, download the telemetry database and view the interactive satellite map:
```bash
./fetch_mission.bat
```
This generates and opens `missions/latest_mission_map.html` with your route, sensor plots, and geotagged inspection photos.

---

## License

This project is licensed under the [MIT License](LICENSE).

/**
 * TerraGuard - Outdoor Autonomous Rover
 * STM32 Real-Time Core Sketch
 * 
 * Hardware Layout:
 * - IMU: BNO055 on I2C
 * - GPS: Standard GPS module on Serial1 (Rx/Tx)
 * - Panning Servo: Connected to PWM Pin (D9)
 * - Encoders: Left/Right encoders connected to Interrupt Pins
 * - Drive Motors: 4 DC Motors driven by two Dual Motor Drivers (Left: ZK-BM1, Right: L298N)
 */

#include <Wire.h>
#include "Arduino_HardwareServo.h"
#include "Arduino_LED_Matrix.h"
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>
#include <Adafruit_AS7341.h>
#include <Adafruit_AHTX0.h>
#include "TinyGPS++.h"
#include <Arduino_RouterBridge.h>

// --- PIN DEFINITIONS ---
// Panning Servo
#define SERVO_PIN 9

// Motor Driver 1 (Left Side: D6, D7, D8, D10) & Driver 2 (Right Side: D2, D3, D4, D5)
// Left Driver (Driver 1): Motor B (IN3=D8, IN4=D10) = Front Left (FL), Motor A (IN1=D7, IN2=D6) = Rear Left (RL)
// Right Driver (Driver 2): Motor B (IN3=D4, IN4=D5) = Front Right (FR), Motor A (IN1=D2, IN2=D3) = Rear Right (RR)

// --- LEFT SIDE MOTORS (Driver 1: D6, D7, A5, D10) ---
#define FL_DIR A5  // Reassigned from D8 to pristine Pin A5
#define FL_PWM 10
#define RL_DIR 7
#define RL_PWM 6

// --- RIGHT SIDE MOTORS (Driver 2: D2, D3, D4, D5) ---
#define FR_DIR 4
#define FR_PWM 5
#define RR_DIR 2
#define RR_PWM 3

// Encoders (4x Quadrature Encoders)
// --- Left Side Motors ---
#define ENC1_A A0  // Front Left (FL) Phase A (Yellow) -> A0
#define ENC1_B 12  // Front Left (FL) Phase B (White)  -> D12
#define ENC3_A 13  // Rear Left (RL) Phase A (Yellow)  -> D13
#define ENC3_B 11  // Rear Left (RL) Phase B (White)   -> D11

// --- Right Side Motors ---
#define ENC2_A A1  // Front Right (FR) Phase A (Yellow) -> A1
#define ENC2_B A2  // Front Right (FR) Phase B (White)  -> A2
#define ENC4_A A3  // Rear Right (RR) Phase A (Yellow)  -> A3
#define ENC4_B A4  // Rear Right (RR) Phase B (White)   -> A4

// --- GLOBAL INSTANCES ---
ArduinoLEDMatrix matrix;
HardwareServo panServo;
Adafruit_BNO055 bno = Adafruit_BNO055(55, 0x29, &Wire);
Adafruit_AS7341 as7341;
Adafruit_AHTX0 aht;
TinyGPSPlus gps;

// --- 12x8 LED MATRIX VISUAL BITMAPS (Physically Aligned for Rover Mounting) ---
// Smile Face (Original physically-aligned bitmap - Solid when GPS fix acquired!)
const uint32_t FRAME_SMILE[4]    = { 0x0001860c, 0x48024012, 0x1890c300, 0x00000000 };
const uint32_t FRAME_OFF[4]      = { 0x00000000, 0x00000000, 0x00000000, 0x00000000 };
// Forward Arrow (Physically points forward toward front nose of rover)
const uint32_t FRAME_FORWARD[4]  = { 0x0080061f, 0xf8ffe7ff, 0x3ff00300, 0x10000000 };
// Backward Arrow (Physically points backward toward rear USB-C)
const uint32_t FRAME_BACKWARD[4] = { 0x0800c00f, 0xfcffe7ff, 0x1ff86001, 0x00000000 };
// Left Arrow (Physically points to true left)
const uint32_t FRAME_LEFT[4]     = { 0x0700fe0f, 0xf8ffefff, 0x87c03e01, 0xf0000000 };
// Right Arrow (Physically points to true right)
const uint32_t FRAME_RIGHT[4]    = { 0x0f807c03, 0xe1fff7ff, 0x1ff07f00, 0xe0000000 };

bool bno_initialized = false;
bool as7341_initialized = false;
bool aht_initialized = false;

// Encoder Tick Counters (volatile for ISR access, signed for forward/reverse tracking)
volatile long fl_ticks = 0;
volatile long fr_ticks = 0;
volatile long rl_ticks = 0;
volatile long rr_ticks = 0;

// Last GPS read variables
double gpsLat = 0.0;
double gpsLng = 0.0;
bool gpsHasFix = false;
float gpsSpeed = 0.0; // in meters per second

// --- INTERRUPT SERVICE ROUTINES ---
// Configured so driving FORWARD increases (+) all encoder counts
void countFL() {
    if (digitalRead(ENC1_B) == LOW) {
        fl_ticks--;
    } else {
        fl_ticks++;
    }
}

void countFR() {
    if (digitalRead(ENC2_B) == LOW) {
        fr_ticks++;
    } else {
        fr_ticks--;
    }
}

void countRL() {
    if (digitalRead(ENC3_B) == LOW) {
        rl_ticks--;
    } else {
        rl_ticks++;
    }
}

void countRR() {
    if (digitalRead(ENC4_B) == LOW) {
        rr_ticks++;
    } else {
        rr_ticks--;
    }
}

// --- MOTOR DRIVE LOGIC ---
/**
 * Helper to drive a single dual-pin H-Bridge channel safely and symmetrically.
 * Logic:
 *  - Speed == 0: pinDir = LOW, analogWrite(pinPWM, 0) (Guarantees hardware PWM timer stops completely)
 *  - Speed > 0:  pinDir = LOW, pinPWM = PWM (Forward)
 *  - Speed < 0:  pinDir = HIGH, pinPWM = (255 - PWM) (Reverse on dedicated PWM timer)
 */
void drive_hbridge_channel(int pinDir, int pinPWM, int speed) {
    if (speed == 0) {
        digitalWrite(pinDir, LOW);
        analogWrite(pinPWM, 0);
        digitalWrite(pinPWM, LOW);
        return;
    }

    int mag = abs(speed);
    int pwm_val = map(mag, 1, 255, 70, 255);
    pwm_val = constrain(pwm_val, 0, 255);

    if (speed > 0) {
        digitalWrite(pinDir, LOW);
        analogWrite(pinPWM, pwm_val);
    } else {
        digitalWrite(pinDir, HIGH);
        analogWrite(pinPWM, 255 - pwm_val);
    }
}

int current_left_speed = 0;
int current_right_speed = 0;

void set_motor_speeds(int left_speed, int right_speed) {
    left_speed = constrain(left_speed, -255, 255);
    right_speed = constrain(right_speed, -255, 255);
    current_left_speed = left_speed;
    current_right_speed = right_speed;

    // --- LEFT WHEELS (Driver 1 - ZK-BM1) ---
    drive_hbridge_channel(FL_DIR, FL_PWM, left_speed);
    drive_hbridge_channel(RL_DIR, RL_PWM, left_speed);

    // --- RIGHT WHEELS (Driver 2 - L298N) ---
    drive_hbridge_channel(FR_DIR, FR_PWM, right_speed);
    drive_hbridge_channel(RR_DIR, RR_PWM, right_speed);

    // --- UPDATE 12x8 LED MATRIX FEEDBACK ---
    if (left_speed > 25 && right_speed > 25) {
        matrix.loadFrame(FRAME_FORWARD);
    } else if (left_speed < -25 && right_speed < -25) {
        matrix.loadFrame(FRAME_BACKWARD);
    } else if (left_speed < right_speed && right_speed > 25) {
        matrix.loadFrame(FRAME_LEFT);
    } else if (right_speed < left_speed && left_speed > 25) {
        matrix.loadFrame(FRAME_RIGHT);
    } else {
        if (gpsHasFix) {
            matrix.loadFrame(FRAME_SMILE);
        } else {
            matrix.loadFrame(FRAME_OFF);
        }
    }
}

// --- SERVO PAN CONTROL (Smooth & Inverted Direction, Limit: -60° to +60°) ---
int current_servo_angle = 0; // Tracks angle from -60 (Left) to +60 (Right)

void pan_servo(int targetAngle) {
    int constrainedTarget = constrain(targetAngle, -60, 60);
    int step = (constrainedTarget > current_servo_angle) ? 1 : -1;
    
    while (current_servo_angle != constrainedTarget) {
        current_servo_angle += step;
        // Inverted map: -60° (Left) -> 150° pulse, 0° -> 90° pulse, +60° (Right) -> 30° pulse
        int pulseAngle = map(current_servo_angle, -90, 90, 180, 0);
        panServo.write(pulseAngle);
        delay(8); // 8ms per degree = smooth, gentle, quiet panning
    }
}

// --- SENSOR GETTERS FOR RPC ---
int get_encoder_left() {
    return (int)((fl_ticks + rl_ticks) / 2);
}

int get_encoder_right() {
    return (int)((fr_ticks + rr_ticks) / 2);
}

int get_encoder_fl() { return (int)fl_ticks; }
int get_encoder_fr() { return (int)fr_ticks; }
int get_encoder_rl() { return (int)rl_ticks; }
int get_encoder_rr() { return (int)rr_ticks; }

void reset_encoders() {
    fl_ticks = 0;
    fr_ticks = 0;
    rl_ticks = 0;
    rr_ticks = 0;
}

float cached_heading = 0.0f;
float cached_temp = 0.0f;
float cached_hum = 0.0f;
int cached_i2c_status = 0;
float gyro_yaw = 0.0f;
float gyro_bias_z = 0.0f;
bool gyro_calibrated = false;
float gyro_calib_sum = 0.0f;
int gyro_calib_samples = 0;

float get_imu_heading() {
    return cached_heading;
}

void reset_imu_heading() {
    gyro_yaw = 0.0f;
    cached_heading = 0.0f;
}

unsigned long bno_ready_time = 0;

void calibrate_gyro() {
    gyro_calibrated = false;
    gyro_calib_sum = 0.0f;
    gyro_calib_samples = 0;
    gyro_yaw = 0.0f;
    cached_heading = 0.0f;
}

double get_gps_lat() { return gpsLat; }
double get_gps_lng() { return gpsLng; }
bool get_gps_has_fix() { return gpsHasFix; }
float get_gps_speed() { return gpsSpeed; }

float get_temperature() {
    return cached_temp;
}

float get_humidity() {
    return cached_hum;
}

int get_i2c_status() {
    return cached_i2c_status;
}

int get_spectral_f1() { if (!as7341_initialized) return 0; return as7341.getChannel(AS7341_CHANNEL_415nm_F1); }
int get_spectral_f2() { if (!as7341_initialized) return 0; return as7341.getChannel(AS7341_CHANNEL_445nm_F2); }
int get_spectral_f3() { if (!as7341_initialized) return 0; return as7341.getChannel(AS7341_CHANNEL_480nm_F3); }
int get_spectral_f4() { if (!as7341_initialized) return 0; return as7341.getChannel(AS7341_CHANNEL_515nm_F4); }
int get_spectral_f5() { if (!as7341_initialized) return 0; return as7341.getChannel(AS7341_CHANNEL_555nm_F5); }
int get_spectral_f6() { if (!as7341_initialized) return 0; return as7341.getChannel(AS7341_CHANNEL_590nm_F6); }
int get_spectral_f7() { if (!as7341_initialized) return 0; return as7341.getChannel(AS7341_CHANNEL_630nm_F7); }
int get_spectral_f8() { if (!as7341_initialized) return 0; return as7341.getChannel(AS7341_CHANNEL_680nm_F8); }
int get_spectral_clear() { if (!as7341_initialized) return 0; return as7341.getChannel(AS7341_CHANNEL_CLEAR); }
int get_spectral_nir() { if (!as7341_initialized) return 0; return as7341.getChannel(AS7341_CHANNEL_NIR); }

// --- DIRECT BNO055 HARDWARE DRIVER (Bypasses third-party library overhead) ---
uint8_t bno_addr = 0;
uint8_t chip_id_29 = 0;
uint8_t chip_id_28 = 0;

uint8_t bno_read_reg(uint8_t addr, uint8_t reg) {
    Wire.beginTransmission(addr);
    Wire.write(reg);
    if (Wire.endTransmission() != 0) return 0xFF;
    if (Wire.requestFrom(addr, (uint8_t)1) != 1) return 0xFF;
    return Wire.read();
}

int last_write_err = 0;

bool bno_write_reg(uint8_t addr, uint8_t reg, uint8_t val) {
    Wire.beginTransmission(addr);
    Wire.write(reg);
    Wire.write(val);
    int err = Wire.endTransmission();
    if (reg == 0x3D) last_write_err = err;
    return (err == 0);
}

bool init_bno_hardware(uint8_t addr) {
    uint8_t id = bno_read_reg(addr, 0x00);
    if (id != 0xA0) return false;

    // 1. Force Page 0
    bno_write_reg(addr, 0x07, 0x00);
    delay(15);

    // 2. Set power mode to NORMAL (0x00)
    bno_write_reg(addr, 0x3E, 0x00);
    delay(15);

    // 3. Use internal oscillator (SYS_TRIGGER = 0x00)
    bno_write_reg(addr, 0x3F, 0x00);
    delay(20);

    // 4. Set units: degrees, Celsius, m/s² (0x00)
    bno_write_reg(addr, 0x3B, 0x00);
    delay(10);

    // 5. Switch to CONFIG mode first
    bno_write_reg(addr, 0x3D, 0x00);
    delay(30);

    // 6. Switch DIRECTLY to ACCGYRO mode (0x05: Raw Accel + Gyro, Bypasses Fusion Engine)
    bno_write_reg(addr, 0x3D, 0x05);
    delay(50);

    uint8_t mode = bno_read_reg(addr, 0x3D);
    if (mode == 0x05) return true;

    // Fallback: try GYROONLY (0x03)
    bno_write_reg(addr, 0x3D, 0x00);
    delay(25);
    bno_write_reg(addr, 0x3D, 0x03);
    delay(50);
    mode = bno_read_reg(addr, 0x3D);
    return (mode == 0x03);
}

float read_bno_yaw(uint8_t addr) {
    Wire.beginTransmission(addr);
    Wire.write(0x1A); // EUL_DATA_X_LSB
    if (Wire.endTransmission() != 0) return -101.0f;
    if (Wire.requestFrom(addr, (uint8_t)2) != 2) return -201.0f;
    uint8_t lsb = Wire.read();
    uint8_t msb = Wire.read();
    int16_t raw_yaw = (int16_t)((msb << 8) | lsb);
    float h = raw_yaw / 16.0f;
    if (h < 0.0f) h += 360.0f;
    return h;
}

int16_t read_bno_gyro_z(uint8_t addr) {
    Wire.beginTransmission(addr);
    Wire.write(0x18); // GYR_DATA_Z_LSB
    if (Wire.endTransmission() != 0) return 0;
    if (Wire.requestFrom(addr, (uint8_t)2) != 2) return 0;
    uint8_t lsb = Wire.read();
    uint8_t msb = Wire.read();
    return (int16_t)((msb << 8) | lsb);
}

// BNO055 deep diagnostic: reads critical registers live
// Returns packed int: byte0=OPR_MODE(0x3D), byte1=CALIB_STAT(0x35),
//                     byte2=SYS_STATUS(0x39), byte3=SYS_ERR(0x3A)
int get_bno_diag() {
    if (!bno_initialized || bno_addr == 0) return -1;
    uint8_t opr = bno_read_reg(bno_addr, 0x3D);
    uint8_t cal = bno_read_reg(bno_addr, 0x35);
    uint8_t sts = bno_read_reg(bno_addr, 0x39);
    uint8_t err = bno_read_reg(bno_addr, 0x3A);
    return (int)opr | ((int)cal << 8) | ((int)sts << 16) | ((int)err << 24);
}

// BNO055 raw accel Z — should read ~980 (= 9.80 m/s² × 100) from gravity alone
int get_bno_accel_z() {
    if (!bno_initialized || bno_addr == 0) return -9999;
    Wire.beginTransmission(bno_addr);
    Wire.write(0x0C); // ACC_DATA_Z_LSB
    if (Wire.endTransmission() != 0) return -8888;
    if (Wire.requestFrom(bno_addr, (uint8_t)2) != 2) return -7777;
    uint8_t lsb = Wire.read();
    uint8_t msb = Wire.read();
    return (int)((int16_t)((msb << 8) | lsb));
}

// Returns packed internal sensor IDs and self-test result:
// byte 0: ACC_ID (reg 0x01, expected 0xFB)
// byte 1: MAG_ID (reg 0x02, expected 0x32)
// byte 2: GYR_ID (reg 0x03, expected 0x0F)
// byte 3: ST_RESULT (reg 0x36, expected 0x0F)
int get_bno_internal_ids() {
    if (bno_addr == 0) return -1;
    bno_write_reg(bno_addr, 0x07, 0x00); // Ensure Page 0
    uint8_t acc = bno_read_reg(bno_addr, 0x01);
    uint8_t mag = bno_read_reg(bno_addr, 0x02);
    uint8_t gyr = bno_read_reg(bno_addr, 0x03);
    uint8_t st  = bno_read_reg(bno_addr, 0x36);
    return (int)acc | ((int)mag << 8) | ((int)gyr << 16) | ((int)st << 24);
}

int get_bno_write_err() {
    return last_write_err;
}

// Low-level BNO register probe:
// If val >= 0: writes val to reg, waits 30ms, then reads back reg.
// If val < 0: reads reg directly.
int bno_poke(int reg, int val) {
    uint8_t addr = (bno_addr != 0) ? bno_addr : 0x29;
    if (val >= 0) {
        Wire.beginTransmission(addr);
        Wire.write((uint8_t)reg);
        Wire.write((uint8_t)val);
        int tx_err = Wire.endTransmission();
        if (tx_err != 0) return -100 - tx_err;
        delay(40);
    }
    Wire.beginTransmission(addr);
    Wire.write((uint8_t)reg);
    int tx_err = Wire.endTransmission();
    if (tx_err != 0) return -200 - tx_err;
    if (Wire.requestFrom(addr, (uint8_t)1) != 1) return -300;
    return (int)Wire.read();
}

// Reads 16-bit signed register (e.g. 0x1A=Euler Yaw, 0x18=Gyro Z, 0x0C=Accel Z)
int bno_read16(int reg) {
    uint8_t addr = (bno_addr != 0) ? bno_addr : 0x29;
    Wire.beginTransmission(addr);
    Wire.write((uint8_t)reg);
    if (Wire.endTransmission() != 0) return -100;
    if (Wire.requestFrom(addr, (uint8_t)2) != 2) return -200;
    uint8_t lsb = Wire.read();
    uint8_t msb = Wire.read();
    return (int)((int16_t)((msb << 8) | lsb));
}

void setup() {
    // 1. CRITICAL SAFETY: Immediately clamp all motor pins to 0V before anything else
    pinMode(FL_DIR, OUTPUT);
    pinMode(FL_PWM, OUTPUT);
    pinMode(FR_DIR, OUTPUT);
    pinMode(FR_PWM, OUTPUT);
    pinMode(RL_DIR, OUTPUT);
    pinMode(RL_PWM, OUTPUT);
    pinMode(RR_DIR, OUTPUT);
    pinMode(RR_PWM, OUTPUT);

    digitalWrite(FL_DIR, LOW);
    digitalWrite(FR_DIR, LOW);
    digitalWrite(RL_DIR, LOW);
    digitalWrite(RR_DIR, LOW);

    analogWrite(FL_PWM, 0);
    analogWrite(FR_PWM, 0);
    analogWrite(RL_PWM, 0);
    analogWrite(RR_PWM, 0);

    digitalWrite(FL_PWM, LOW);
    digitalWrite(FR_PWM, LOW);
    digitalWrite(RL_PWM, LOW);
    digitalWrite(RR_PWM, LOW);

    Serial.begin(115200);
    Serial1.begin(9600);

    // 2. Initialize 12x8 LED Matrix Display FIRST for instant visual boot feedback
    matrix.begin();
    matrix.loadFrame(FRAME_SMILE);

    // 3. Initialize Servo
    panServo.attach(SERVO_PIN);
    pan_servo(0); // Center position

    // 4. Initialize Encoders
    pinMode(ENC1_A, INPUT_PULLUP);
    pinMode(ENC1_B, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(ENC1_A), countFL, RISING);

    pinMode(ENC2_A, INPUT_PULLUP);
    pinMode(ENC2_B, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(ENC2_A), countFR, RISING);

    pinMode(ENC3_A, INPUT_PULLUP);
    pinMode(ENC3_B, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(ENC3_A), countRL, RISING);

    pinMode(ENC4_A, INPUT_PULLUP);
    pinMode(ENC4_B, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(ENC4_A), countRR, RISING);

    // 5. Initialize RouterBridge RPC
    Bridge.begin();
    Bridge.provide("set_motor_speeds", set_motor_speeds);
    Bridge.provide("pan_servo", pan_servo);
    Bridge.provide("get_encoder_left", get_encoder_left);
    Bridge.provide("get_encoder_right", get_encoder_right);
    Bridge.provide("get_encoder_fl", get_encoder_fl);
    Bridge.provide("get_encoder_fr", get_encoder_fr);
    Bridge.provide("get_encoder_rl", get_encoder_rl);
    Bridge.provide("get_encoder_rr", get_encoder_rr);
    Bridge.provide("reset_encoders", reset_encoders);
    Bridge.provide("get_imu_heading", get_imu_heading);
    Bridge.provide("reset_imu_heading", reset_imu_heading);
    Bridge.provide("calibrate_gyro", calibrate_gyro);
    Bridge.provide("get_gps_lat", get_gps_lat);
    Bridge.provide("get_gps_lng", get_gps_lng);
    Bridge.provide("get_gps_has_fix", get_gps_has_fix);
    Bridge.provide("get_gps_speed", get_gps_speed);
    Bridge.provide("get_temperature", get_temperature);
    Bridge.provide("get_humidity", get_humidity);
    Bridge.provide("get_spectral_f1", get_spectral_f1);
    Bridge.provide("get_spectral_f2", get_spectral_f2);
    Bridge.provide("get_spectral_f3", get_spectral_f3);
    Bridge.provide("get_spectral_f4", get_spectral_f4);
    Bridge.provide("get_spectral_f5", get_spectral_f5);
    Bridge.provide("get_spectral_f6", get_spectral_f6);
    Bridge.provide("get_spectral_f7", get_spectral_f7);
    Bridge.provide("get_spectral_f8", get_spectral_f8);
    Bridge.provide("get_spectral_clear", get_spectral_clear);
    Bridge.provide("get_spectral_nir", get_spectral_nir);
    Bridge.provide("get_i2c_status", get_i2c_status);
    Bridge.provide("get_bno_diag", get_bno_diag);
    Bridge.provide("get_bno_accel_z", get_bno_accel_z);
    Bridge.provide("get_bno_internal_ids", get_bno_internal_ids);
    Bridge.provide("get_bno_write_err", get_bno_write_err);
    Bridge.provide("bno_poke", bno_poke);
    Bridge.provide("bno_read16", bno_read16);

    // 6. Initialize I2C Bus & Sensors (Safe Non-blocking check)
    Wire.begin();
    Wire.setClock(100000);
    delay(50);

    // Initialize AHT10 (Fast startup < 20ms)
    Wire.beginTransmission(0x38);
    if (Wire.endTransmission() == 0) {
        if (aht.begin()) {
            aht_initialized = true;
            cached_i2c_status |= 1;
            sensors_event_t humidity, temp;
            if (aht.getEvent(&humidity, &temp)) {
                cached_temp = temp.temperature;
                cached_hum = humidity.relative_humidity;
            }
        }
    }

    // Initialize BNO055: Probe 0x29 first (default for GY-BNO055 modules), then 0x28
    delay(700);
    chip_id_29 = bno_read_reg(0x29, 0x00);
    chip_id_28 = bno_read_reg(0x28, 0x00);

    if (chip_id_29 == 0xA0) {
        bno_addr = 0x29;
        if (init_bno_hardware(bno_addr)) bno_initialized = true;
    } else if (chip_id_28 == 0xA0) {
        bno_addr = 0x28;
        if (init_bno_hardware(bno_addr)) bno_initialized = true;
    }

    if (bno_initialized) {
        cached_i2c_status |= 8;
        bno_ready_time = millis() + 1500; // Allow full 1.5s for hardware stabilization
        gyro_calibrated = false;
        gyro_calib_sum = 0.0f;
        gyro_calib_samples = 0;
        gyro_bias_z = 0.0f;
        gyro_yaw = 0.0f;
        cached_heading = 0.0f;
    }
}

unsigned long last_bno_poll = 0;
int bno_retry_count = 0;
unsigned long last_aht_poll = 0;
unsigned long last_i2c_poll = 0;
unsigned long last_gyro_ms = 0;

void loop() {
    unsigned long now = millis();

    // 1. Process incoming GPS NMEA sentences on Serial1
    while (Serial1.available() > 0) {
        if (gps.encode(Serial1.read())) {
            if (gps.location.isValid()) {
                gpsLat = gps.location.lat();
                gpsLng = gps.location.lng();
                bool hadFix = gpsHasFix;
                gpsHasFix = true;
                if (!hadFix && abs(current_left_speed) <= 25 && abs(current_right_speed) <= 25) {
                    // Instant SOLID glowing smiling face the exact moment GPS satellites lock!
                    matrix.loadFrame(FRAME_SMILE);
                }
            }
            if (gps.speed.isValid()) {
                gpsSpeed = gps.speed.mps();
            }
        }
    }

    // 1b. GPS Searching beacon: When stopped and NO GPS fix yet, pulse smile (500ms ON, 1500ms OFF)
    static unsigned long last_gps_beacon_ms = 0;
    static bool gps_beacon_on = false;
    if (!gpsHasFix && abs(current_left_speed) <= 25 && abs(current_right_speed) <= 25) {
        unsigned long interval = gps_beacon_on ? 500 : 1500;
        if (now - last_gps_beacon_ms >= interval) {
            last_gps_beacon_ms = now;
            gps_beacon_on = !gps_beacon_on;
            if (gps_beacon_on) {
                matrix.loadFrame(FRAME_SMILE);
            } else {
                matrix.loadFrame(FRAME_OFF);
            }
        }
    }

    // 2. Poll BNO055 IMU in background (~20Hz = every 50ms)
    // Continuous non-blocking ACCGYRO poll & real-time Gyroscope Z integration with ZUPT
    if (now - last_bno_poll >= 50) {
        last_bno_poll = now;
        uint8_t addr = (bno_addr != 0) ? bno_addr : 0x29;

        // Ensure mode 0x05 (ACCGYRO) is active; if dropped to CONFIG mode (0x00), immediately restore!
        static unsigned long last_mode_check = 0;
        if (now - last_mode_check >= 1000) {
            last_mode_check = now;
            uint8_t cur_mode = bno_read_reg(addr, 0x3D);
            if (cur_mode != 0x05 && cur_mode != 0xFF) {
                init_bno_hardware(addr);
                bno_ready_time = millis() + 500;
            }
        }

        // Wait 1.5s after boot for internal gyro PLL to stabilize
        if (now >= bno_ready_time) {
            float dt = (last_gyro_ms == 0) ? 0.05f : ((float)(now - last_gyro_ms) / 1000.0f);
            if (dt > 0.2f) dt = 0.05f;
            last_gyro_ms = now;

            int16_t gz_raw = read_bno_gyro_z(addr);
            float raw_dps = gz_raw / 16.0f;

            // Physical Sanity Guard: If Accel Z is < 300 (< 3 m/s²), sensor is in CONFIG mode or offline!
            // On Earth, Accel Z is ~980 (~9.8 m/s²). If Accel Z is 0, freeze integration and re-init!
            int acc_z = get_bno_accel_z();
            if (acc_z < 300) {
                init_bno_hardware(addr);
                bno_ready_time = millis() + 500;
                cached_heading = gyro_yaw;
                return;
            }

            // Initial 40-sample baseline calibration (40 * 50ms = 2.0s)
            if (!gyro_calibrated) {
                gyro_calib_sum += raw_dps;
                gyro_calib_samples++;
                if (gyro_calib_samples >= 40) {
                    gyro_bias_z = gyro_calib_sum / 40.0f;
                    gyro_calibrated = true;
                    gyro_yaw = 0.0f;
                    cached_heading = 0.0f;
                }
            } else {
                float true_rate = raw_dps - gyro_bias_z;

                // Determine if the rover is physically stationary vs moving/rotating
                bool motors_active = (abs(current_left_speed) > 15 || abs(current_right_speed) > 15);
                bool hand_rotating = (abs(true_rate) > 3.0f); // Human hand turns are > 3.0 deg/sec

                if (!motors_active && !hand_rotating) {
                    // STATIONARY ON TABLE OR STOPPED AT WAYPOINT:
                    // 1. Rate is clamped to EXACT 0.0f -> 100% mathematically ZERO drift!
                    true_rate = 0.0f;

                    // 2. Continuous adaptive bias tracking to absorb thermal shift
                    gyro_bias_z = (gyro_bias_z * 0.995f) + (raw_dps * 0.005f);
                } else if (abs(true_rate) < 0.4f) {
                    // Noise floor deadband while driving
                    true_rate = 0.0f;
                }

                // Integrate only when true rotation occurs
                if (true_rate != 0.0f) {
                    gyro_yaw -= true_rate * dt;
                    while (gyro_yaw < 0.0f) gyro_yaw += 360.0f;
                    while (gyro_yaw >= 360.0f) gyro_yaw -= 360.0f;
                }
            }

            cached_heading = gyro_yaw;
        }
    }

    // 3. Poll AHT10 in background every 5 seconds (5000ms)
    if (aht_initialized && (now - last_aht_poll >= 5000)) {
        last_aht_poll = now;
        sensors_event_t humidity, temp;
        if (aht.getEvent(&humidity, &temp)) {
            cached_temp = temp.temperature;
            cached_hum = humidity.relative_humidity;
        }
    }
}


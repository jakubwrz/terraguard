/**
 * TerraGuard - Safe Low-Power Motor & Driver Diagnostic Tool
 * 
 * Specifically designed to safely test dual H-Bridge motor drivers
 * at gentle, low-power settings (25% - 35% PWM) with safety auto-shutoff.
 * 
 * Pins tested:
 * Driver Channel A: IN1 = D2, IN2 = D3
 * Driver Channel B: IN3 = D4, IN4 = D5
 */

#include <Arduino.h>

// Driver 1 / Left Side Pins
#define CH_A_PIN1 2  // D2
#define CH_A_PIN2 3  // D3
#define CH_B_PIN1 4  // D4
#define CH_B_PIN2 5  // D5

// Safe Low-Power PWM Speed (65 out of 255 = ~25% power)
const int GENTLE_SPEED = 70;
const int TEST_DURATION_MS = 2000; // 2 seconds run time per test

void stop_all_motors() {
    digitalWrite(CH_A_PIN1, LOW);
    digitalWrite(CH_A_PIN2, LOW);
    digitalWrite(CH_B_PIN1, LOW);
    digitalWrite(CH_B_PIN2, LOW);
}

void setup() {
    Serial.begin(115200);
    
    // Set all motor pins as OUTPUT and immediately drive LOW (Coast / 0V)
    pinMode(CH_A_PIN1, OUTPUT);
    pinMode(CH_A_PIN2, OUTPUT);
    pinMode(CH_B_PIN1, OUTPUT);
    pinMode(CH_B_PIN2, OUTPUT);
    stop_all_motors();

    delay(1000);
    Serial.println("\n=======================================================");
    Serial.println("   TERRAGUARD - SAFE MOTOR & DRIVER DIAGNOSTIC TOOL");
    Serial.println("=======================================================");
    Serial.println("Safety Mode: Active (Speed capped at gentle ~27% PWM)");
    Serial.println("Channels configured:");
    Serial.println("  - Channel A: IN1 (D2), IN2 (D3)");
    Serial.println("  - Channel B: IN3 (D4), IN4 (D5)");
    Serial.println("\nType a command in Serial monitor or wait for Auto-Test:");
    Serial.println("  [1] - Test Channel A FORWARD (2 sec)");
    Serial.println("  [2] - Test Channel A REVERSE (2 sec)");
    Serial.println("  [3] - Test Channel B FORWARD (2 sec)");
    Serial.println("  [4] - Test Channel B REVERSE (2 sec)");
    Serial.println("  [a] - Run Complete Automated Gentle Test");
    Serial.println("  [s] - EMERGENCY ALL STOP");
    Serial.println("=======================================================\n");
}

void test_channel(const char* name, int pin1, int pin2, bool forward, int speed, int duration_ms) {
    Serial.print(">> TESTING: ");
    Serial.print(name);
    Serial.print(forward ? " [FORWARD] " : " [REVERSE] ");
    Serial.print("at gentle PWM = ");
    Serial.print(speed);
    Serial.println(" (27% power)...");

    if (forward) {
        digitalWrite(pin1, LOW);
        analogWrite(pin2, speed);
    } else {
        digitalWrite(pin2, LOW);
        analogWrite(pin1, speed);
    }

    delay(duration_ms);

    stop_all_motors();
    Serial.println("   -> STOPPED. Motor released.\n");
    delay(500);
}

void run_automated_test() {
    Serial.println(">>> STARTING AUTOMATED LOW-POWER TEST SEQUENCE <<<\n");

    // 1. Channel A Forward
    test_channel("Channel A (D2/D3)", CH_A_PIN1, CH_A_PIN2, true, GENTLE_SPEED, TEST_DURATION_MS);
    delay(1000);

    // 2. Channel A Reverse
    test_channel("Channel A (D2/D3)", CH_A_PIN1, CH_A_PIN2, false, GENTLE_SPEED, TEST_DURATION_MS);
    delay(1000);

    // 3. Channel B Forward
    test_channel("Channel B (D4/D5)", CH_B_PIN1, CH_B_PIN2, true, GENTLE_SPEED, TEST_DURATION_MS);
    delay(1000);

    // 4. Channel B Reverse
    test_channel("Channel B (D4/D5)", CH_B_PIN1, CH_B_PIN2, false, GENTLE_SPEED, TEST_DURATION_MS);
    
    Serial.println(">>> AUTOMATED TEST COMPLETE! All motors stopped. <<<\n");
}

void loop() {
    if (Serial.available() > 0) {
        char cmd = Serial.read();
        if (cmd == '1') {
            test_channel("Channel A (D2/D3)", CH_A_PIN1, CH_A_PIN2, true, GENTLE_SPEED, TEST_DURATION_MS);
        } else if (cmd == '2') {
            test_channel("Channel A (D2/D3)", CH_A_PIN1, CH_A_PIN2, false, GENTLE_SPEED, TEST_DURATION_MS);
        } else if (cmd == '3') {
            test_channel("Channel B (D4/D5)", CH_B_PIN1, CH_B_PIN2, true, GENTLE_SPEED, TEST_DURATION_MS);
        } else if (cmd == '4') {
            test_channel("Channel B (D4/D5)", CH_B_PIN1, CH_B_PIN2, false, GENTLE_SPEED, TEST_DURATION_MS);
        } else if (cmd == 'a' || cmd == 'A') {
            run_automated_test();
        } else if (cmd == 's' || cmd == 'S') {
            stop_all_motors();
            Serial.println("[!] ALL MOTORS FORCED STOPPED.");
        }
    }
}

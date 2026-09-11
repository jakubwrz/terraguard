/*
    This file is part of the Arduino_HardwareServo library.

    Copyright (C) Arduino s.r.l. and/or its affiliated companies

    This Source Code Form is subject to the terms of the Mozilla Public
    License, v. 2.0. If a copy of the MPL was not distributed with this
    file, You can obtain one at http://mozilla.org/MPL/2.0/.

*/

#include "HardwareServo.h"
#include "HardwareServo_api.h"

HardwareServo::HardwareServo() {
    servoIndex = INVALID_SERVO;
    min = SERVO_MIN_US;
    max = SERVO_MAX_US;
}

uint8_t HardwareServo::attach(int pin, int min, int max) {
    servoIndex = _hwservo_get_pwm_index(pin);
    if (servoIndex == INVALID_SERVO) {return INVALID_SERVO;}

    analogWrite(pin, 0);
    this->min = constrain(min, 0, SERVO_PERIOD_US);
    this->max = constrain(max, 0, SERVO_PERIOD_US);

    return servoIndex;
}

void HardwareServo::detach() {
    if (!this->attached()) {
        return;
    }
    servoIndex = INVALID_SERVO;
}

void HardwareServo::write(int value) {
    if (!this->attached()) {return;}
    value = constrain(value, 0, 180);
    pulseWidth = map(static_cast<uint32_t>(value), 0, 180, min, max);
    _hwservo_pwm_set_pulse_us(servoIndex, SERVO_PERIOD_US, pulseWidth);
}

void HardwareServo::writeMicroseconds(int value) {
    if (!this->attached()) {return;}
    value = constrain(value, min, max);
    pulseWidth = value;
    _hwservo_pwm_set_pulse_us(servoIndex, SERVO_PERIOD_US, pulseWidth);
}

int HardwareServo::read() {
    if (!this->attached()) {
        return -1;
    }
    return map(pulseWidth, min, max, 0, 180);
}

int HardwareServo::readMicroseconds() {
    if (!this->attached()) {
        return -1;
    }
    return pulseWidth;
}

bool HardwareServo::attached() {
    return this->servoIndex != INVALID_SERVO;
}

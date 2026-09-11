/*
    This file is part of the Arduino_HardwareServo library.

    Copyright (C) Arduino s.r.l. and/or its affiliated companies

    This Source Code Form is subject to the terms of the Mozilla Public
    License, v. 2.0. If a copy of the MPL was not distributed with this
    file, You can obtain one at http://mozilla.org/MPL/2.0/.

*/

#ifdef __ZEPHYR__

#include <Arduino.h>
#include <zephyr/drivers/pwm.h>
#include <zephyr/sys/util.h>

#include "HardwareServo.h"
#include "HardwareServo_api.h"

#define PWM_DT_SPEC(n, p, i) PWM_DT_SPEC_GET_BY_IDX(n, i),

#define PWM_PINS(n, p, i)                                                                          \
DIGITAL_PIN_GPIOS_FIND_PIN(DT_REG_ADDR(DT_PHANDLE_BY_IDX(DT_PATH(zephyr_user), p, i)),         \
DT_PHA_BY_IDX(DT_PATH(zephyr_user), p, i, pin)),

static const struct pwm_dt_spec _arduino_pwm[] = {
    DT_FOREACH_PROP_ELEM(DT_PATH(zephyr_user), pwms, PWM_DT_SPEC)
};

static const pin_size_t _arduino_pwm_pins[] = {
    DT_FOREACH_PROP_ELEM(DT_PATH(zephyr_user), pwm_pin_gpios, PWM_PINS)
};

static_assert(ARRAY_SIZE(_arduino_pwm_pins) < INVALID_SERVO, "Too many PWM pins defined in the device tree for this board");

uint8_t _hwservo_get_pwm_index(pin_size_t pinNumber) {
    for (size_t i = 0; i < ARRAY_SIZE(_arduino_pwm_pins); i++) {
        if (_arduino_pwm_pins[i] == pinNumber) {
            return i;
        }
    }
    return INVALID_SERVO;
}

int _hwservo_pwm_set_pulse_us(uint8_t index, uint32_t period_us, uint32_t pulse_us) {
    return pwm_set_dt(&_arduino_pwm[index], period_us * 1000, pulse_us * 1000);
}

#endif

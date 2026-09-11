#ifndef HARDWARESERVO_API_H
#define HARDWARESERVO_API_H

#include <Arduino.h>

uint8_t _hwservo_get_pwm_index(pin_size_t pinNumber);

int _hwservo_pwm_set_pulse_us(uint8_t index, uint32_t period_us, uint32_t pulse_us);

#if !defined(__ZEPHYR__)
#error "Currently this library supports Zephyr boards only"
#endif

#endif // HARDWARESERVO_API_H

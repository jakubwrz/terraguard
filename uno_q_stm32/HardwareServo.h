/*
    This file is part of the Arduino_HardwareServo library.

    Copyright (C) Arduino s.r.l. and/or its affiliated companies

    This Source Code Form is subject to the terms of the Mozilla Public
    License, v. 2.0. If a copy of the MPL was not distributed with this
    file, You can obtain one at http://mozilla.org/MPL/2.0/.

*/

/* HardwareServo conforms to the same interface as arduino-libraries/Servo */


#ifndef HARDWARESERVO_H
#define HARDWARESERVO_H

#include <Arduino.h>

#define SERVO_PERIOD_US   20000    /* 20 ms = 50 Hz */
#define SERVO_MIN_US      500      /* 0.5 ms = 0 deg   (full range 500-2500 us) */
#define SERVO_MAX_US      2500     /* 2.5 ms = 180 deg (full range 500-2500 us) */

#define INVALID_SERVO         255     // flag indicating an invalid servo index

class HardwareServo {
public:
    HardwareServo();

    /**
     * @brief Attaches the given pin to the next free channel.
     * * This method sets the appropriate pinMode and configures the minimum
     * and maximum pulse width values.
     * * @param pin The GPIO pin number the servo is connected to.
     * @param min The minimum pulse width in microseconds (defaults to SERVO_MIN_US). Corresponds to 0deg
     * @param max The maximum pulse width in microseconds (defaults to SERVO_MAX_US). Corresponds to 180deg
     * @return uint8_t The channel number assigned, or INVALID_SERVO on failure.
     */
    uint8_t attach(int pin, int min = SERVO_MIN_US, int max = SERVO_MAX_US);

    /**
     * @brief Detaches the servo from its pin and frees the PWM channel.
     */
    void detach();

    /**
     * @brief Sets the servo to a specific angle.
     * * @param value The desired angle in degrees (0 to 180). Out-of-bound
     * values are automatically clamped to this range.
     */
    void write(int value);

    /**
     * @brief Sets the servo pulse width directly in microseconds.
     * * @param value The desired pulse width in microseconds. The value is
     */
    void writeMicroseconds(int value);

    /**
     * @brief Reads the current position of the servo as an angle.
     * * @return int The current angle in degrees, between 0 and 180.
     */
    int read();

    /**
     * @brief Reads the current pulse width sent to the servo.
     * * @return int The current pulse width in microseconds.
     */
    int readMicroseconds();

    /**
     * @brief Checks if the servo is currently attached to a pin.
     * * @return true If the servo is successfully attached.
     * @return false If the servo is not attached.
     */
    bool attached();

private:

    uint8_t servoIndex;    /**< Index into the channel data for this servo. */
    uint32_t min;          /**< Pulse width in microseconds corresponding to 0 degrees. */
    uint32_t max;          /**< Pulse width in microseconds corresponding to 180 degrees. */
    uint32_t pulseWidth=0; /**< Current pulse width in microseconds. */
};

#endif //HARDWARESERVO_H

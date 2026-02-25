/**
 * Minimal RUI3 LoRaWAN OTAA example.
 *
 * This sketch initializes the serial port and prints a message,
 * serving as a build-system smoke test for the RUI3 PlatformIO platform.
 */

#include "Arduino.h"

void setup()
{
    Serial.begin(115200);
    delay(2000);
    Serial.println("RAK3172 RUI3 — LoRaWAN OTAA Example");
    Serial.println("Build OK");
}

void loop()
{
    delay(5000);
    Serial.println("loop");
}

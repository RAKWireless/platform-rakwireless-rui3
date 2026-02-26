/**
 * RUI3 System Info Example
 *
 * Reads and prints device information available through the RUI3 API:
 * API version, firmware version, AT command version, model ID, chip ID,
 * and battery voltage. Refreshes every 10 seconds.
 *
 * Works on any RUI3 board (RAK3172, RAK4631, ...).
 */

#include "Arduino.h"

void printSystemInfo()
{
    Serial.println("========================================");
    Serial.println("           RUI3 System Info             ");
    Serial.println("========================================");

    Serial.print("API Version  : ");
    Serial.println(api.system.apiVersion.get());

    Serial.print("FW Version   : ");
    Serial.println(api.system.firmwareVersion.get());

    Serial.print("AT Version   : ");
    Serial.println(api.system.cliVersion.get());

    Serial.print("Model ID     : ");
    Serial.println(api.system.modelId.get());

    Serial.print("Chip ID      : ");
    Serial.println(api.system.chipId.get());

    Serial.print("Battery (V)  : ");
    Serial.println(api.system.bat.get(), 3);

    Serial.println("========================================");
    Serial.println();
}

void setup()
{
    Serial.begin(115200);
    delay(2000);
    printSystemInfo();
}

void loop()
{
    delay(10000);
    printSystemInfo();
}

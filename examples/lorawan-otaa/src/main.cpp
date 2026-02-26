/**
 * RUI3 LoRaWAN OTAA Example
 *
 * Joins a LoRaWAN network via OTAA, then sends a 2-byte uplink counter
 * every TX_INTERVAL_MS milliseconds. Received downlinks are printed to
 * Serial with FPort, RSSI, SNR and hex payload.
 *
 * Before flashing:
 *   1. Fill in your OTAA credentials (DevEUI, AppEUI, AppKey) below.
 *   2. Set LORAWAN_BAND to match your region (see table in the #define).
 *
 * Tested on: RAK3172 (EU868), RAK4631 (EU868)
 */

#include "Arduino.h"

// ---------------------------------------------------------------------------
// OTAA credentials — replace with values from your LNS console
// ---------------------------------------------------------------------------

// DevEUI — 8 bytes, MSB first
static uint8_t node_dev_eui[8] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};

// AppEUI / JoinEUI — 8 bytes, MSB first
static uint8_t node_app_eui[8] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};

// AppKey — 16 bytes, MSB first
static uint8_t node_app_key[16] = {
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// Region / band index:
//   0=EU433  1=CN470  2=RU864  3=IN865  4=EU868  5=US915
//   6=AU915  7=KR920  8=AS923-1  9=AS923-2  10=AS923-3  11=AS923-4  12=LA915
#define LORAWAN_BAND         4       // EU868

// Data rate (region-dependent; DR3 = SF9/125 kHz on EU868)
#define LORAWAN_DR           3

// FPort for uplinks (1–223)
#define LORAWAN_FPORT        1

// Uplink interval in milliseconds
#define TX_INTERVAL_MS       60000UL

// ---------------------------------------------------------------------------
// Callbacks
// ---------------------------------------------------------------------------

void joinCallback(int32_t status)
{
    if (status == 0) {
        Serial.println("[LoRaWAN] Joined!");
    } else {
        Serial.printf("[LoRaWAN] Join failed (status %d), retrying...\r\n", status);
    }
}

void sendCallback(int32_t status)
{
    if (status == 0) {
        Serial.println("[LoRaWAN] Uplink confirmed by network");
    } else {
        Serial.printf("[LoRaWAN] Uplink TX done (status %d)\r\n", status);
    }
}

void recvCallback(SERVICE_LORA_RECEIVE_T *data)
{
    Serial.printf("[LoRaWAN] Downlink  FPort=%u  RSSI=%d  SNR=%d  len=%u  payload:",
                  data->Port, data->Rssi, data->Snr, data->BufferSize);
    for (uint8_t i = 0; i < data->BufferSize; i++) {
        Serial.printf(" %02X", data->Buffer[i]);
    }
    Serial.println();
}

// ---------------------------------------------------------------------------
// Sketch
// ---------------------------------------------------------------------------

static uint16_t uplink_count = 0;

void sendUplink()
{
    uint8_t payload[2] = {
        (uint8_t)(uplink_count >> 8),
        (uint8_t)(uplink_count & 0xFF)
    };

    Serial.printf("[LoRaWAN] Sending uplink #%u (count=0x%04X)\r\n",
                  uplink_count, uplink_count);

    if (!api.lorawan.send(sizeof(payload), payload, LORAWAN_FPORT, false)) {
        Serial.println("[LoRaWAN] send() returned false");
    }

    uplink_count++;
}

void setup()
{
    Serial.begin(115200);
    delay(2000);

    Serial.println("=== RUI3 LoRaWAN OTAA Example ===");
    Serial.printf("  Model  : %s\r\n", api.system.modelId.get().c_str());
    Serial.printf("  Chip ID: %s\r\n", api.system.chipId.get().c_str());
    Serial.printf("  FW     : %s\r\n", api.system.firmwareVersion.get().c_str());
    Serial.println();

    // --- Credentials ---
    api.lorawan.deui.set(node_dev_eui, 8);
    api.lorawan.appeui.set(node_app_eui, 8);
    api.lorawan.appkey.set(node_app_key, 16);

    // --- Radio / MAC settings ---
    api.lorawan.band.set(LORAWAN_BAND);
    api.lorawan.njm.set(RAK_LORA_OTAA);
    api.lorawan.dr.set(LORAWAN_DR);
    api.lorawan.adr.set(false);
    api.lorawan.cfm.set(false);  // unconfirmed uplinks by default

    // --- Callbacks ---
    api.lorawan.registerJoinCallback(joinCallback);
    api.lorawan.registerSendCallback(sendCallback);
    api.lorawan.registerRecvCallback(recvCallback);

    // --- Start joining ---
    // join(start, auto_retry, retry_period_s, max_retries)
    // max_retries=0 means retry indefinitely
    Serial.println("[LoRaWAN] Starting OTAA join...");
    api.lorawan.join(1, 1, 10, 0);
}

void loop()
{
    static uint32_t last_tx = 0;

    if (!api.lorawan.njs.get()) {
        return;  // not joined yet — join callback will fire when ready
    }

    uint32_t now = millis();
    if (last_tx == 0 || (now - last_tx) >= TX_INTERVAL_MS) {
        last_tx = now;
        sendUplink();
    }
}

#pragma once
#include <Arduino.h>

namespace wifi_setup {

// Connects to Wi-Fi using stored credentials. Opens the WiFiManager captive portal
// (AP "SoundShare-XXXX") when no credentials are stored, when the connection fails,
// or when forcePortal is true. Custom fields: backend host, port, deviceId, token.
// Blocks until connected; restarts the ESP32 if the portal times out.
void connect(bool forcePortal);

// True when the BOOT button is held for ~3 s right after power-up.
bool bootButtonHeld();

String apName();

}  // namespace wifi_setup

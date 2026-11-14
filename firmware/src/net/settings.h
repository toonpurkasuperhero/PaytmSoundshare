#pragma once
#include <Arduino.h>

// Persistent device settings (NVS via Preferences).
struct DeviceSettings {
  String host;
  uint16_t port;
  String deviceId;
  String token;
  String merchantName;  // cached from hello_ack so Idle shows it while offline
};

namespace settings {

void load();
void save();
DeviceSettings& get();
void setMerchantName(const String& name);

}  // namespace settings

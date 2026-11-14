// Paytm SoundShare Soundbox firmware (ESP32-S3 + TFT + MAX98357A [+ INMP441]).
//
// Task layout:
//   core 1 (Arduino loop) : WebSocket client, protocol, LVGL
//   core 0                : audio decode task, ad-cache downloader, mic meter, Wi-Fi stack

#include <Arduino.h>
#include <LittleFS.h>
#include <WiFi.h>
#include <time.h>

#include "app_config.h"
#include "audio/ad_cache.h"
#include "audio/audio_player.h"
#include "display/display.h"
#include "net/settings.h"
#include "net/wifi_setup.h"
#include "net/ws_client.h"
#include "protocol/protocol.h"
#include "ui/ui.h"

namespace {

void logClipInventory() {
  for (const char* lang : {"en", "hi"}) {
    String dirPath = String(CLIPS_DIR) + "/" + lang;
    File dir = LittleFS.open(dirPath);
    int n = 0;
    if (dir && dir.isDirectory()) {
      for (File f = dir.openNextFile(); f; f = dir.openNextFile()) ++n;
    }
    Serial.printf("[fs] %s: %d clips\n", dirPath.c_str(), n);
  }
  Serial.printf("[fs] LittleFS used %u / %u KB\n", (unsigned)(LittleFS.usedBytes() / 1024),
                (unsigned)(LittleFS.totalBytes() / 1024));
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.printf("\nSoundShare Soundbox fw %s, PSRAM %u KB\n", FW_VERSION, (unsigned)(ESP.getPsramSize() / 1024));

  settings::load();
  display::begin();
  ui::begin();
  ui::setMerchant(settings::get().merchantName);
  ui::showBoot("Starting...");
  display::refreshNow();

  if (!LittleFS.begin(true)) {
    Serial.println("[fs] LittleFS mount failed");
    ui::showBoot("Storage error. Flash clips with: pio run -t uploadfs");
    display::refreshNow();
    delay(1500);
  } else {
    logClipInventory();
  }
  ad_cache::begin();
  audio_player::begin();

  const bool forcePortal = wifi_setup::bootButtonHeld();
  wifi_setup::connect(forcePortal);
  configTime(0, 0, "pool.ntp.org", "time.google.com");  // fallback clock for QR expiry

  const DeviceSettings& s = settings::get();
  ui::setDeviceInfo(s.deviceId, s.host, s.port);
  ui::showBoot("Connecting to server...");
  ws_client::begin(s.host, s.port, s.deviceId, s.token, protocol::onConnected, protocol::onDisconnected,
                   protocol::onText);
  ui::showIdle();
}

void loop() {
  ws_client::loop();
  protocol::loop();
  display::loop();
  delay(1);
}

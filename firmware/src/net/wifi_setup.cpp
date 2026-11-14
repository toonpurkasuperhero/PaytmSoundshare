#include "wifi_setup.h"

#include <WiFi.h>
#include <WiFiManager.h>

#include "app_config.h"
#include "board_pins.h"
#include "display/display.h"
#include "settings.h"
#include "ui/ui.h"

namespace {

void onPortalStarted(WiFiManager* wm) {
  Serial.printf("[wifi] setup portal started: %s\n", wm->getConfigPortalSSID().c_str());
  ui::showSetupPortal(wm->getConfigPortalSSID().c_str());
  display::refreshNow();
}

}  // namespace

namespace wifi_setup {

String apName() {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char buf[32];
  snprintf(buf, sizeof(buf), "%s%02X%02X", SETUP_AP_PREFIX, mac[4], mac[5]);
  return String(buf);
}

bool bootButtonHeld() {
  pinMode(PIN_BTN_BOOT, INPUT_PULLUP);
  if (digitalRead(PIN_BTN_BOOT) != LOW) return false;
  ui::showBoot("Keep holding BOOT to open Wi-Fi setup...");
  display::refreshNow();
  const uint32_t start = millis();
  while (millis() - start < 3000) {
    if (digitalRead(PIN_BTN_BOOT) != LOW) return false;
    delay(20);
  }
  return true;
}

void connect(bool forcePortal) {
  DeviceSettings& s = settings::get();
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);

  char portBuf[8];
  snprintf(portBuf, sizeof(portBuf), "%u", s.port);

  WiFiManagerParameter pHost("host", "Backend host / IP", s.host.c_str(), 63);
  WiFiManagerParameter pPort("port", "Backend port", portBuf, 6);
  WiFiManagerParameter pDev("devid", "Device ID", s.deviceId.c_str(), 31);
  WiFiManagerParameter pTok("token", "Device token", s.token.c_str(), 95);

  WiFiManager wm;
  wm.addParameter(&pHost);
  wm.addParameter(&pPort);
  wm.addParameter(&pDev);
  wm.addParameter(&pTok);
  wm.setTitle("SoundShare Soundbox");
  wm.setConfigPortalTimeout(SETUP_PORTAL_TIMEOUT_S);
  wm.setConnectTimeout(20);
  wm.setAPCallback(onPortalStarted);

  const String ap = apName();
  bool ok;
  if (forcePortal) {
    ok = wm.startConfigPortal(ap.c_str());
  } else {
    ui::showBoot("Connecting to Wi-Fi...");
    display::refreshNow();
    ok = wm.autoConnect(ap.c_str());
  }

  // Persist any values the user typed in the portal (no-op when unchanged).
  bool changed = false;
  auto take = [&changed](String& dst, const char* v) {
    String nv(v);
    nv.trim();
    if (nv.length() && nv != dst) {
      dst = nv;
      changed = true;
    }
  };
  take(s.host, pHost.getValue());
  take(s.deviceId, pDev.getValue());
  take(s.token, pTok.getValue());
  const long port = atol(pPort.getValue());
  if (port > 0 && port < 65536 && port != s.port) {
    s.port = static_cast<uint16_t>(port);
    changed = true;
  }
  if (changed) {
    Serial.println("[wifi] backend settings updated from portal");
    settings::save();
  }

  if (!ok) {
    Serial.println("[wifi] not connected, restarting");
    ui::showBoot("Wi-Fi setup timed out. Restarting...");
    display::refreshNow();
    delay(2000);
    ESP.restart();
  }
  Serial.printf("[wifi] connected, IP %s RSSI %d\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
}

}  // namespace wifi_setup

#include "settings.h"

#include <Preferences.h>

#include "app_config.h"

namespace {
DeviceSettings g_settings;
constexpr const char* kNs = "zmdr";
}  // namespace

namespace settings {

void load() {
  Preferences p;
  p.begin(kNs, true);
  g_settings.host = p.getString("host", DEFAULT_BACKEND_HOST);
  g_settings.port = p.getUShort("port", DEFAULT_BACKEND_PORT);
  g_settings.deviceId = p.getString("devid", DEFAULT_DEVICE_ID);
  g_settings.token = p.getString("token", DEFAULT_DEVICE_TOKEN);
  g_settings.merchantName = p.getString("mname", "");
  p.end();
  if (g_settings.port == 0) g_settings.port = DEFAULT_BACKEND_PORT;
  Serial.printf("[settings] host=%s port=%u device=%s\n", g_settings.host.c_str(), g_settings.port,
                g_settings.deviceId.c_str());
}

void save() {
  Preferences p;
  p.begin(kNs, false);
  p.putString("host", g_settings.host);
  p.putUShort("port", g_settings.port);
  p.putString("devid", g_settings.deviceId);
  p.putString("token", g_settings.token);
  p.putString("mname", g_settings.merchantName);
  p.end();
}

DeviceSettings& get() { return g_settings; }

void setMerchantName(const String& name) {
  if (name.length() == 0 || name == g_settings.merchantName) return;
  g_settings.merchantName = name;
  Preferences p;
  p.begin(kNs, false);
  p.putString("mname", name);
  p.end();
}

}  // namespace settings

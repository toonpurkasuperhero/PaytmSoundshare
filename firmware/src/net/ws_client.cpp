#include "ws_client.h"

#include <WebSocketsClient.h>

#include "app_config.h"

namespace {

WebSocketsClient g_ws;
ws_client::ConnectedFn g_onConnected = nullptr;
ws_client::DisconnectedFn g_onDisconnected = nullptr;
ws_client::TextFn g_onText = nullptr;
bool g_connected = false;

String urlEncode(const String& in) {
  static const char* hex = "0123456789ABCDEF";
  String out;
  out.reserve(in.length() * 3);
  for (size_t i = 0; i < in.length(); ++i) {
    const uint8_t c = static_cast<uint8_t>(in[i]);
    if (isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') {
      out += static_cast<char>(c);
    } else {
      out += '%';
      out += hex[c >> 4];
      out += hex[c & 0x0F];
    }
  }
  return out;
}

void onEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      g_connected = true;
      Serial.printf("[ws] connected: %.*s\n", (int)length, payload ? (const char*)payload : "");
      if (g_onConnected) g_onConnected();
      break;
    case WStype_DISCONNECTED:
      if (g_connected) Serial.println("[ws] disconnected");
      g_connected = false;
      if (g_onDisconnected) g_onDisconnected();
      break;
    case WStype_TEXT:
      if (g_onText) g_onText(reinterpret_cast<const char*>(payload), length);
      break;
    case WStype_ERROR:
      Serial.printf("[ws] error: %.*s\n", (int)length, payload ? (const char*)payload : "");
      break;
    default:
      break;  // binary frames, fragments and WS-level ping/pong need no handling
  }
}

}  // namespace

namespace ws_client {

void begin(const String& host, uint16_t port, const String& deviceId, const String& token,
           ConnectedFn onConnected, DisconnectedFn onDisconnected, TextFn onText) {
  g_onConnected = onConnected;
  g_onDisconnected = onDisconnected;
  g_onText = onText;

  String path = String(WS_PATH_PREFIX) + urlEncode(deviceId) + "?token=" + urlEncode(token);
  Serial.printf("[ws] ws://%s:%u%s\n", host.c_str(), port, path.c_str());

  g_ws.begin(host, port, path);
  g_ws.onEvent(onEvent);
  g_ws.setReconnectInterval(WS_RECONNECT_MS);
  // Transport-level keepalive detects half-open TCP links faster than the
  // application ping (20 s) would.
  g_ws.enableHeartbeat(15000, 5000, 2);
}

void loop() { g_ws.loop(); }

bool connected() { return g_connected; }

bool sendText(const String& text) {
  if (!g_connected) return false;
  String copy = text;  // sendTXT takes a non-const reference
  return g_ws.sendTXT(copy);
}

}  // namespace ws_client

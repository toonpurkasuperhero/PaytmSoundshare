#pragma once
#include <Arduino.h>
#include <stddef.h>

// Thin wrapper around links2004 WebSocketsClient for
//   ws://<host>:<port>/ws/device/{deviceId}?token=<token>
// Reconnects automatically. Only call from the Arduino loop task.
namespace ws_client {

using ConnectedFn = void (*)();
using DisconnectedFn = void (*)();
using TextFn = void (*)(const char* payload, size_t len);

void begin(const String& host, uint16_t port, const String& deviceId, const String& token,
           ConnectedFn onConnected, DisconnectedFn onDisconnected, TextFn onText);
void loop();
bool connected();
bool sendText(const String& text);

}  // namespace ws_client

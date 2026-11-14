#pragma once
#include <stddef.h>

// Device WebSocket protocol (docs/API_CONTRACT.md section 2): parses server frames,
// drives the UI/audio, and emits hello / heartbeat / pong / play_ack / cache_ok.
namespace protocol {

// WebSocket callbacks (wired up in main.cpp)
void onConnected();
void onDisconnected();
void onText(const char* payload, size_t len);

// Heartbeat, connection status and queued acks. Call from loop().
void loop();

}  // namespace protocol

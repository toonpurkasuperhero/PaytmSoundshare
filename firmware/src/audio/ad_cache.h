#pragma once
#include <Arduino.h>

#include <vector>

// Ad audio cache on LittleFS: /ads/<hash>.mp3.
// Downloads run on a background task; completions are drained by the main loop
// (which sends cache_ok over the WebSocket).
namespace ad_cache {

void begin();

// Accepts only [0-9a-fA-F], 8..64 chars, so it is safe to use in a path.
bool isValidHash(const String& hash);

String pathFor(const String& hash);
bool has(const String& hash);

// Queues a background download (no-op + immediate completion if already cached).
void request(const String& hash, const String& url);

// Pops one finished download; returns false when none is pending.
bool pollDone(String& hashOut);

void list(std::vector<String>& hashesOut);

// Makes a relative URL ("/media/audio/x.mp3") absolute against the backend.
String absoluteUrl(const String& url);

}  // namespace ad_cache

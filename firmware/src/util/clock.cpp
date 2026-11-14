#include "clock.h"

#include <Arduino.h>
#include <time.h>

namespace {
int64_t g_offset = 0;  // epoch seconds at millis() == 0
bool g_valid = false;
}  // namespace

namespace clock_sync {

void setServerTime(int64_t epochSeconds) {
  if (epochSeconds <= 0) return;
  g_offset = epochSeconds - static_cast<int64_t>(millis() / 1000);
  g_valid = true;
}

int64_t now() {
  if (g_valid) return g_offset + static_cast<int64_t>(millis() / 1000);
  const time_t t = time(nullptr);
  if (t > 1600000000) return static_cast<int64_t>(t);  // SNTP has synced
  return 0;
}

}  // namespace clock_sync

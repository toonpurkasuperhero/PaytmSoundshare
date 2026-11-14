#pragma once
#include <stdint.h>

// Wall clock derived from the backend's hello_ack.serverTime (epoch seconds),
// with SNTP as a fallback. Used for the QR expiry countdown.
namespace clock_sync {

void setServerTime(int64_t epochSeconds);

// Returns current epoch seconds, or 0 when the time is not known yet.
int64_t now();

}  // namespace clock_sync

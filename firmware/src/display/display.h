#pragma once
#include <stdint.h>

namespace display {

// Initialises the TFT (LovyanGFX), LVGL, the flush/touch drivers and the tick source.
void begin();

// Runs lv_timer_handler(); call from loop().
void loop();

// Forces an immediate full redraw (used before blocking calls such as the Wi-Fi portal).
void refreshNow();

void setBrightness(uint8_t level);

int width();
int height();

}  // namespace display

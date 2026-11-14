#include "display.h"

#include <Arduino.h>
#include <esp_heap_caps.h>
#include <lvgl.h>

#include "lgfx_panel.h"

namespace {

LGFX tft;
lv_display_t* lvDisp = nullptr;
lv_indev_t* lvTouch = nullptr;

constexpr int kBufLines = 40;

uint32_t tickCb() { return millis(); }

void flushCb(lv_display_t* disp, const lv_area_t* area, uint8_t* px) {
  const int32_t w = lv_area_get_width(area);
  const int32_t h = lv_area_get_height(area);
  // LVGL renders native-endian RGB565; LovyanGFX converts to the panel format
  // (RGB666 for the ILI9488) while pushing.
  tft.pushImage(area->x1, area->y1, w, h, reinterpret_cast<lgfx::rgb565_t*>(px));
  lv_display_flush_ready(disp);
}

void touchReadCb(lv_indev_t* indev, lv_indev_data_t* data) {
  (void)indev;
  uint16_t x = 0, y = 0;
  if (tft.getTouch(&x, &y)) {
    data->state = LV_INDEV_STATE_PRESSED;
    data->point.x = x;
    data->point.y = y;
  } else {
    data->state = LV_INDEV_STATE_RELEASED;
  }
}

void* allocDrawBuf(size_t bytes) {
  // Prefer internal DMA-capable RAM (fastest for SPI), fall back to PSRAM.
  void* p = heap_caps_malloc(bytes, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
  if (!p) p = heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM);
  return p;
}

}  // namespace

namespace display {

void begin() {
  tft.init();
  tft.setRotation(TFT_ROTATION);
  tft.setBrightness(200);
  tft.fillScreen(TFT_BLACK);

  lv_init();
  lv_tick_set_cb(tickCb);

  const int32_t w = tft.width();
  const int32_t h = tft.height();
  lvDisp = lv_display_create(w, h);
  lv_display_set_color_format(lvDisp, LV_COLOR_FORMAT_RGB565);
  lv_display_set_flush_cb(lvDisp, flushCb);

  const size_t bufBytes = static_cast<size_t>(w) * kBufLines * sizeof(uint16_t);
  void* buf1 = allocDrawBuf(bufBytes);
  void* buf2 = allocDrawBuf(bufBytes);
  lv_display_set_buffers(lvDisp, buf1, buf2, bufBytes, LV_DISPLAY_RENDER_MODE_PARTIAL);

  lvTouch = lv_indev_create();
  lv_indev_set_type(lvTouch, LV_INDEV_TYPE_POINTER);
  lv_indev_set_read_cb(lvTouch, touchReadCb);

  Serial.printf("[display] %ldx%ld, draw buffers 2 x %u bytes\n", (long)w, (long)h, (unsigned)bufBytes);
}

void loop() { lv_timer_handler(); }

void refreshNow() {
  lv_timer_handler();
  lv_refr_now(lvDisp);
}

void setBrightness(uint8_t level) { tft.setBrightness(level); }

int width() { return tft.width(); }
int height() { return tft.height(); }

}  // namespace display

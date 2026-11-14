#include "mic.h"

#include "app_config.h"  // may define HAS_MIC

#ifdef HAS_MIC

#include <Arduino.h>
#include <driver/i2s.h>
#include <math.h>

#include "board_pins.h"

namespace {

constexpr i2s_port_t kPort = I2S_NUM_1;
constexpr uint32_t kSampleRate = 16000;
constexpr int kFrame = 256;

volatile bool g_measuring = false;
portMUX_TYPE g_mux = portMUX_INITIALIZER_UNLOCKED;
double g_sumSq = 0;
uint64_t g_count = 0;
int32_t g_peak = 0;
float g_dc = 0;  // running DC estimate (INMP441 has a small offset)

void task(void*) {
  int32_t buf[kFrame];
  for (;;) {
    size_t bytes = 0;
    if (i2s_read(kPort, buf, sizeof(buf), &bytes, pdMS_TO_TICKS(100)) != ESP_OK || bytes == 0) continue;
    if (!g_measuring) continue;
    const int n = bytes / sizeof(int32_t);
    double sum = 0;
    int32_t peak = 0;
    for (int i = 0; i < n; ++i) {
      // 24-bit sample, left-justified in a 32-bit slot.
      const float s = static_cast<float>(buf[i] >> 8);
      g_dc += 0.001f * (s - g_dc);
      const float v = s - g_dc;
      sum += static_cast<double>(v) * v;
      const int32_t a = static_cast<int32_t>(fabsf(v));
      if (a > peak) peak = a;
    }
    portENTER_CRITICAL(&g_mux);
    g_sumSq += sum;
    g_count += n;
    if (peak > g_peak) g_peak = peak;
    portEXIT_CRITICAL(&g_mux);
  }
}

float toDbfs(double amplitude) {
  constexpr double kFullScale = 8388608.0;  // 2^23
  if (amplitude < 1.0) return -120.0f;
  return static_cast<float>(20.0 * log10(amplitude / kFullScale));
}

}  // namespace

namespace mic {

void begin() {
  i2s_config_t cfg = {};
  cfg.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX);
  cfg.sample_rate = kSampleRate;
  cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  cfg.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count = 4;
  cfg.dma_buf_len = kFrame;
  cfg.use_apll = false;

  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = PIN_I2S_MIC_SCK;
  pins.ws_io_num = PIN_I2S_MIC_WS;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  pins.data_in_num = PIN_I2S_MIC_SD;

  if (i2s_driver_install(kPort, &cfg, 0, nullptr) != ESP_OK || i2s_set_pin(kPort, &pins) != ESP_OK) {
    Serial.println("[mic] I2S init failed");
    return;
  }
  xTaskCreatePinnedToCore(task, "mic", 4096, nullptr, 3, nullptr, 0);
  Serial.println("[mic] INMP441 ready on I2S1");
}

void startMeasuring() {
  portENTER_CRITICAL(&g_mux);
  g_sumSq = 0;
  g_count = 0;
  g_peak = 0;
  portEXIT_CRITICAL(&g_mux);
  g_measuring = true;
}

Levels stopMeasuring() {
  g_measuring = false;
  Levels l;
  portENTER_CRITICAL(&g_mux);
  const double sumSq = g_sumSq;
  const uint64_t count = g_count;
  const int32_t peak = g_peak;
  portEXIT_CRITICAL(&g_mux);
  if (count == 0) return l;
  l.valid = true;
  l.peakDb = toDbfs(peak);
  l.rmsDb = toDbfs(sqrt(sumSq / static_cast<double>(count)));
  return l;
}

}  // namespace mic

#else  // !HAS_MIC

namespace mic {
void begin() {}
void startMeasuring() {}
Levels stopMeasuring() { return Levels{}; }
}  // namespace mic

#endif

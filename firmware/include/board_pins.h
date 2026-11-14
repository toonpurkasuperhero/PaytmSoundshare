#pragma once
// ---------------------------------------------------------------------------
// Pin map for ESP32-S3-DevKitC-1 N16R8.
//
// Pins to AVOID on N16R8:
//   GPIO 26-32  : quad SPI flash
//   GPIO 33-37  : octal PSRAM (OPI) - unusable when PSRAM is enabled
//   GPIO 19/20  : native USB D-/D+
//   GPIO 43/44  : UART0 TX/RX (USB-UART bridge, serial monitor)
//   GPIO 0/3/45/46 : strapping pins (GPIO0 is used only as the BOOT button input)
//   GPIO 48     : on-board RGB LED (fine to leave alone)
// ---------------------------------------------------------------------------

// ---- TFT (ILI9488 3.5" or ILI9341 2.8") on SPI2 / FSPI ---------------------
#define PIN_TFT_SCLK   12   // SCK
#define PIN_TFT_MOSI   11   // SDI (MOSI)
#define PIN_TFT_MISO   13   // SDO (MISO). Shared with touch T_DO. ILI9488 modules often do
                            // NOT tri-state SDO: if touch misbehaves, leave the TFT SDO pin
                            // unconnected and only wire T_DO to GPIO13.
#define PIN_TFT_CS     10
#define PIN_TFT_DC      9   // D/C (RS)
#define PIN_TFT_RST    14
#define PIN_TFT_BL     21   // LED / backlight (driven by PWM). Tie to 3V3 if the module has no BL pin.

// ---- XPT2046 touch (shares SCLK/MOSI/MISO with the TFT) ---------------------
#define PIN_TOUCH_CS    8   // T_CS
#define PIN_TOUCH_IRQ  18   // T_IRQ (optional, -1 to disable)

// ---- MAX98357A I2S amplifier (I2S port 0) -----------------------------------
#define PIN_I2S_SPK_BCLK  4   // BCLK
#define PIN_I2S_SPK_LRC   5   // LRC (WS)
#define PIN_I2S_SPK_DOUT  6   // DIN on the amp
// MAX98357A SD pin: leave floating/pull-up to VIN for (L+R)/2 mono mix. GAIN: floating = 9 dB.

// ---- INMP441 I2S MEMS mic (I2S port 1, optional, enable with -DHAS_MIC) -----
#define PIN_I2S_MIC_SCK  15   // SCK
#define PIN_I2S_MIC_WS   16   // WS
#define PIN_I2S_MIC_SD   17   // SD (data out of the mic)
// INMP441 L/R pin -> GND (left channel). VDD -> 3V3.

// ---- Buttons ----------------------------------------------------------------
#define PIN_BTN_BOOT     0    // On-board BOOT button. Hold during power-up (~3 s) to open the
                              // Wi-Fi / backend setup portal.

// ---- Display geometry (panel native orientation is portrait) ----------------
#if defined(PANEL_ILI9341)
  #define TFT_NATIVE_W   240
  #define TFT_NATIVE_H   320
  #define TFT_SPI_FREQ   40000000
#else  // PANEL_ILI9488 (default)
  #ifndef PANEL_ILI9488
    #define PANEL_ILI9488
  #endif
  #define TFT_NATIVE_W   320
  #define TFT_NATIVE_H   480
  #define TFT_SPI_FREQ   40000000   // drop to 27 MHz if you see noise with long jumper wires
#endif
#define TFT_ROTATION     1          // landscape (USB on the right). Use 3 to flip 180 degrees.

// XPT2046 raw calibration (typical values; adjust if taps land in the wrong place)
#define TOUCH_RAW_X_MIN  300
#define TOUCH_RAW_X_MAX  3900
#define TOUCH_RAW_Y_MIN  200
#define TOUCH_RAW_Y_MAX  3900
#define TOUCH_SPI_FREQ   1000000

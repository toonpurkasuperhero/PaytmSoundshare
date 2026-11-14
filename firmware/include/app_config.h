#pragma once
// Build-time configuration for the Soundbox firmware.

#define FW_VERSION "0.1.0"

// ---- Provisioning defaults (overridable via the WiFiManager portal, stored in NVS) ----
#define DEFAULT_BACKEND_HOST "192.168.1.100"
#define DEFAULT_BACKEND_PORT 8000
#define DEFAULT_DEVICE_ID    "DEV1"
#define DEFAULT_DEVICE_TOKEN "dev-token-DEV1"
#define SETUP_AP_PREFIX      "SoundShare-"
#define SETUP_PORTAL_TIMEOUT_S 300

// ---- WebSocket ----
#define WS_PATH_PREFIX         "/ws/device/"
#define WS_RECONNECT_MS        3000
#define HEARTBEAT_INTERVAL_MS  30000

// ---- UI timing ----
#define SUCCESS_RETURN_MS      20000   // success screen -> idle
#define FAILED_RETURN_MS       10000
#define CANCELLED_RETURN_MS    5000
#define BANNER_ROTATE_MS       6000
#define LEG_TOAST_MS           3500

// ---- Audio ----
#define AUDIO_VOLUME           18      // 0..21 (ESP32-audioI2S scale)
#define CLIP_FALLBACK_LANG     "en"    // used when /clips/<lang>/<token>.mp3 is missing
#define AD_MAX_EXTRA_MS        3000    // ad playback is cut at durationMs + this
#define AD_DEFAULT_MAX_MS      5000    // cap when durationMs is unknown
#define ADS_DIR                "/ads"
#define CLIPS_DIR              "/clips"
#define ADS_MIN_FREE_BYTES     (512 * 1024)

// ---- Money display ----
// Montserrat (LVGL built-in) has no U+20B9 glyph, so amounts are shown as "Rs.6,500".
#define CURRENCY_PREFIX        "Rs."

// ---- Optional INMP441 mic (proof of play). Enable here or with -DHAS_MIC in platformio.ini ----
// #define HAS_MIC

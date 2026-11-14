# Paytm SoundShare Soundbox firmware

ESP32-S3 firmware for the customer-facing Soundbox: TFT bill, split, and per-leg payment QR,
success screen with settlement details and an ad banner, a spoken "Rs.X received"
announcement, and a 2 to 3 s ad clip with proof of play.

It talks to the FastAPI backend over a plain WebSocket. The protocol is in
`docs/API_CONTRACT.md`, sections 2 and 3.

## Hardware

| Part | Notes |
|---|---|
| ESP32-S3-DevKitC-1 **N16R8** | 16 MB QIO flash, 8 MB OPI PSRAM |
| 3.5" 480x320 **ILI9488** SPI TFT + XPT2046 touch | default env `s3_ili9488` |
| 2.8" 320x240 **ILI9341** SPI TFT + XPT2046 touch | alternative env `s3_ili9341` |
| **MAX98357A** I2S amp + 4 ohm 3 W speaker | I2S port 0 |
| **INMP441** I2S MEMS mic (optional) | I2S port 1, build with `-DHAS_MIC` |

### Wiring

All pins are in `include/board_pins.h`. GPIO 26 to 37 are taken by the OPI flash and PSRAM on
the N16R8, and GPIO 19/20 (USB) and 43/44 (UART0) are not used either.

| Signal | ESP32-S3 GPIO | Module pin |
|---|---|---|
| TFT SCK | 12 | SCK |
| TFT MOSI | 11 | SDI (MOSI) |
| TFT MISO | 13 | SDO (MISO) (see note) |
| TFT CS | 10 | CS |
| TFT DC | 9 | DC / RS |
| TFT RST | 14 | RESET |
| TFT backlight | 21 | LED (PWM) |
| Touch CLK / DIN / DO | 12 / 11 / 13 | T_CLK / T_DIN / T_DO (shared SPI bus) |
| Touch CS | 8 | T_CS |
| Touch IRQ | 18 | T_IRQ |
| Amp BCLK | 4 | MAX98357A BCLK |
| Amp LRC | 5 | MAX98357A LRC |
| Amp DIN | 6 | MAX98357A DIN |
| Mic SCK | 15 | INMP441 SCK |
| Mic WS | 16 | INMP441 WS |
| Mic SD | 17 | INMP441 SD |
| BOOT button | 0 | on-board (hold at power-up to open the setup portal) |

Power: TFT VCC goes to 3V3 (or to 5 V if the module has its own regulator), MAX98357A VIN to 5 V,
INMP441 VDD to 3V3, INMP441 L/R to GND. Leave MAX98357A SD floating or pulled up so it plays a
(L+R)/2 mono mix, and leave GAIN floating for 9 dB.

> **ILI9488 MISO note:** many ILI9488 boards do not release SDO, which breaks touch reads on the
> shared bus. The firmware never reads from the panel (`readable = false`), so if touch acts up,
> disconnect the TFT's SDO and wire only T_DO to GPIO 13.

## Build, flash, upload clips

PlatformIO, Arduino-ESP32 2.0.17 (`espressif32@6.9.0`). Library versions are pinned in
`platformio.ini`: LVGL 9.2.2, LovyanGFX 1.2.7, WebSockets 2.6.1, WiFiManager 2.0.17,
ArduinoJson 7.2.1, ESP32-audioI2S 2.0.6.

```bash
cd firmware
pio run                                  # builds both panels
pio run -e s3_ili9488 -t upload          # or -e s3_ili9341 for the 2.8" panel
pio run -e s3_ili9488 -t uploadfs        # flashes firmware/data/ -> LittleFS
pio device monitor                       # 115200 baud
```

Use the board's **UART** USB port (the one labelled `UART`/`COM`). If you use the native `USB` port
instead, change `-DARDUINO_USB_CDC_ON_BOOT=0` to `1`.

### Partitions (`partitions_16MB_littlefs.csv`)

There are two 3 MB app slots (OTA-ready) and a ~9.9 MB LittleFS partition, which holds the
number clips and the cached ads. The partition is labelled `spiffs` because that is the label
Arduino's `LittleFS.begin()` and `pio run -t uploadfs` look for.

### Filesystem layout

```
data/                      (uploaded by `pio run -t uploadfs`)
  clips/en/<token>.mp3     n0..n99, hundred, thousand, lakh, crore, rupees, received
  clips/hi/<token>.mp3
/ads/<sha1>.mp3            created at runtime by cache_audio
```

`tools/gen_clips.py` generates the clip MP3s into `firmware/data/clips/{en,hi}/`. Clips should be
mono MP3, 22.05 to 44.1 kHz. A clip missing from `/clips/<lang>/` falls back to `/clips/en/`, and
a token with no clip at all is skipped (and logged on serial). **Running `uploadfs` rewrites the
whole partition, so it also wipes the cached ads.** The device downloads them again when the
backend sends `cache_audio`, or streams them the next time they play.

## Provisioning

1. On first boot (or when the stored Wi-Fi fails), the device opens a captive portal with the
   AP **`SoundShare-XXXX`**. The screen shows the AP name and a Wi-Fi QR code you can scan to join it.
2. Join the AP. Open http://192.168.4.1 if the portal page doesn't pop up by itself.
3. Pick the shop Wi-Fi, then fill in **Backend host / IP**, **port** (default 8000),
   **Device ID** (default `DEV1`) and **Device token** (default `dev-token-DEV1`).
4. Save. The values go into NVS (`Preferences`, namespace `zmdr`) and the device connects to
   `ws://<host>:<port>/ws/device/<deviceId>?token=<token>`.

To change the settings later, **hold BOOT for ~3 s while powering up** (or pressing RESET).
A long press on the idle screen shows device ID, IP, server, connection state and free memory.
The status dot in the top-right corner is green when online, amber when Wi-Fi is up but the
server is not, and red when there is no Wi-Fi.

## Font choice: "Rs." instead of the rupee sign

LVGL's built-in Montserrat fonts have no U+20B9 (₹) glyph. Rather than ship a custom font
generated with `lv_font_conv`, the firmware prints amounts as **`Rs.6,50,000`**. This is the
common convention on POS terminals and needs no extra toolchain. The prefix is the single
define `CURRENCY_PREFIX` in `include/app_config.h`. To switch to ₹ later, generate Montserrat at
the sizes in `include/lv_conf.h` with the range `0x20-0x7F,0x20B9` plus the LVGL symbol range,
then point the `Fonts` table in `src/ui/ui.cpp` at those fonts.

Amounts arrive as integer paise and use Indian digit grouping: `650000` paise is `Rs.6,500`,
`65000000` is `Rs.6,50,000`, and `9983` is `Rs.99.83`. Paise are shown only when they are not
zero. The same fonts cover only ASCII, so non-Latin merchant or banner text (for example
Devanagari) renders as blank glyphs.

## Source layout

```
include/
  board_pins.h        all GPIOs + panel geometry + touch calibration
  app_config.h        defaults, timings, volume, currency prefix, HAS_MIC
  lv_conf.h           LVGL 9.2 config (fonts 12-48, QR code widget)
src/
  main.cpp            boot sequence + loop
  display/            LovyanGFX panel class (ILI9488 / ILI9341 + XPT2046) and LVGL glue
  ui/                 LVGL screen state machine (Boot, Setup, Idle, Bill, Split, Pay, Success, Failed, Cancelled)
  net/                settings (NVS), WiFiManager provisioning, WebSocket client
  protocol/           JSON message structs + dispatch (ArduinoJson 7)
  audio/              audio task (announce + ad), ad cache downloader, INMP441 meter
  util/               Indian-grouped money formatting, server-synced clock
```

Threads: the Arduino loop on core 1 runs the WebSocket, the protocol and LVGL. The audio
decoder, the ad downloader and the mic meter are FreeRTOS tasks on core 0, so screen redraws
never cause audio dropouts. These tasks talk to the loop only through queues.

## Protocol behaviour

| Server message | Device behaviour |
|---|---|
| `hello_ack` | Stores the merchant name (cached in NVS for offline idle) and syncs the clock from `serverTime`. SNTP is the fallback. |
| `idle` | Replaces the rotating idle banners (6 s each). Switches to Idle unless the Success screen is up. |
| `show_bill` / `show_split` | Bill list with total / leg cards with the note. |
| `show_qr` | QR (about 254 px on 480x320, about 190 px on 320x240) on a white quiet zone, plus amount, "Leg n of m", and an `expiresAt` countdown. |
| `leg_paid` | Green toast over the current screen with the amount and the rail. |
| `payment_success` | Plays the `announce` tokens in order, then the ad (`/ads/<hash>.mp3` if cached, else streamed from `url` and cached in the background). Shows the amount, the settlement block ("Fee Rs.99.83 covered 100% by Havells, FitZone Gym" / "Merchant receives Rs.6,500"), the banner in its colours, and the offer QR. Returns to Idle after 20 s. |
| `payment_failed` / `cancelled` | Red / grey screen. Returns to Idle after 10 s / 5 s, or on a tap. |
| `cache_audio` | Downloads to `/ads/<hash>.mp3` (via `.tmp`, then rename), then sends `cache_ok`. Sends `cache_ok` right away if the file is already cached. |
| `ping` | `pong` |

Device to server: `hello` (with the cached hashes) on every (re)connect, `heartbeat` every 30 s,
and `play_ack` when the ad ends. `ms` is the measured play time. Playback is cut at
`durationMs + 3 s`. `peakDb`/`rmsDb` are dBFS from the INMP441, or `null` without `HAS_MIC`.
If an ad can't start, `ms: 0` is sent at once so the backend can release the reservation early.
The WebSocket reconnects every 3 s and also uses a WS-level keepalive ping (15 s).

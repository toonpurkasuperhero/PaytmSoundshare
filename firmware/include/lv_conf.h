/**
 * LVGL 9.2 configuration for the SoundShare Soundbox.
 * Only non-default values are set here; lv_conf_internal.h fills in the rest.
 * Picked up via -DLV_CONF_INCLUDE_SIMPLE -I include (see platformio.ini).
 */
#ifndef LV_CONF_H
#define LV_CONF_H

/* ---- Color ---- */
#define LV_COLOR_DEPTH 16

/* ---- Memory / stdlib: use the C library so big allocations can land in PSRAM ---- */
#define LV_USE_STDLIB_MALLOC   LV_STDLIB_CLIB
#define LV_USE_STDLIB_STRING   LV_STDLIB_CLIB
#define LV_USE_STDLIB_SPRINTF  LV_STDLIB_CLIB

/* ---- OS: LVGL is only touched from the Arduino loop task ---- */
#define LV_USE_OS LV_OS_NONE

/* ---- Rendering ---- */
#define LV_DEF_REFR_PERIOD 30
#define LV_DPI_DEF 130
#define LV_DRAW_SW_COMPLEX 1
#define LV_USE_DRAW_SW 1

/* ---- Logging / asserts ---- */
#define LV_USE_LOG 0
#define LV_USE_ASSERT_NULL 1
#define LV_USE_ASSERT_MALLOC 1
#define LV_USE_ASSERT_STYLE 0

/* ---- Fonts (Montserrat has no U+20B9, see app_config.h CURRENCY_PREFIX) ---- */
#define LV_FONT_MONTSERRAT_12 1
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_16 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_MONTSERRAT_24 1
#define LV_FONT_MONTSERRAT_28 1
#define LV_FONT_MONTSERRAT_36 1
#define LV_FONT_MONTSERRAT_48 1
#define LV_FONT_DEFAULT &lv_font_montserrat_16

/* ---- Widgets / extras ---- */
#define LV_USE_QRCODE 1
#define LV_USE_FLEX 1
#define LV_USE_GRID 0
#define LV_USE_THEME_DEFAULT 1
#define LV_THEME_DEFAULT_DARK 0

/* Not needed on this device */
#define LV_USE_CALENDAR 0
#define LV_USE_CHART 0
#define LV_USE_KEYBOARD 0
#define LV_USE_TABVIEW 0
#define LV_USE_TILEVIEW 0
#define LV_USE_WIN 0
#define LV_USE_SPINBOX 0
#define LV_USE_MENU 0
#define LV_USE_MSGBOX 0
#define LV_USE_LIST 0
#define LV_USE_ROLLER 0
#define LV_USE_DROPDOWN 0
#define LV_USE_TEXTAREA 0
#define LV_USE_IMAGEBUTTON 0
#define LV_USE_ANIMIMG 0
#define LV_USE_SCALE 0
#define LV_USE_LED 0

#define LV_BUILD_EXAMPLES 0
#define LV_USE_DEMO_WIDGETS 0
#define LV_USE_DEMO_BENCHMARK 0

#endif /* LV_CONF_H */

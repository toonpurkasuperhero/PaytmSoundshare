#include "ui.h"

#include <WiFi.h>
#include <lvgl.h>

#include <initializer_list>

#include "app_config.h"
#include "display/display.h"
#include "util/clock.h"
#include "util/money.h"

namespace {

using ui::Screen;

// ---- Palette -----------------------------------------------------------------
constexpr uint32_t kNavy = 0x002E6E;
constexpr uint32_t kSky = 0x00BAF2;
constexpr uint32_t kBg = 0xF3F6FA;
constexpr uint32_t kText = 0x0F172A;
constexpr uint32_t kMuted = 0x64748B;
constexpr uint32_t kLine = 0xE2E8F0;
constexpr uint32_t kGreen = 0x12B76A;
constexpr uint32_t kRed = 0xE5484D;
constexpr uint32_t kAmber = 0xF59E0B;
constexpr uint32_t kGrey = 0x475569;
constexpr uint32_t kWhite = 0xFFFFFF;

struct Fonts {
  const lv_font_t* xxl;
  const lv_font_t* xl;
  const lv_font_t* lg;
  const lv_font_t* md;
  const lv_font_t* sm;
  const lv_font_t* xs;
};

Fonts F;
int W = 480;
int H = 320;
bool g_small = false;
int M = 8;        // outer margin
int HDR_H = 44;   // header height

Screen g_screen = Screen::None;
lv_timer_t* g_tick = nullptr;    // per-screen repeating timer (countdown / banner rotation)
lv_timer_t* g_return = nullptr;  // per-screen one-shot "back to idle"

// Persistent overlays on lv_layer_top()
lv_obj_t* g_dot = nullptr;
lv_obj_t* g_toast = nullptr;
lv_obj_t* g_info = nullptr;

// Per-screen widgets (reset on every screen change)
lv_obj_t* g_bootMsg = nullptr;
lv_obj_t* g_idleFooter = nullptr;
lv_obj_t* g_bannerHost = nullptr;
lv_obj_t* g_countdown = nullptr;
int64_t g_expiresAt = 0;

std::vector<Banner> g_banners;
size_t g_bannerIdx = 0;
String g_merchant;
String g_deviceId;
String g_host;
uint16_t g_port = 0;
bool g_wifiUp = false;
bool g_serverUp = false;

// ---- Small helpers -------------------------------------------------------------
lv_color_t C(uint32_t hex) { return lv_color_hex(hex); }

lv_color_t parseColor(const String& s, uint32_t fallback) {
  const char* p = s.c_str();
  if (*p == '#') ++p;
  if (strlen(p) != 6) return C(fallback);
  char* end = nullptr;
  const unsigned long v = strtoul(p, &end, 16);
  if (!end || *end) return C(fallback);
  return C(static_cast<uint32_t>(v));
}

lv_obj_t* plain(lv_obj_t* parent) {
  lv_obj_t* o = lv_obj_create(parent);
  lv_obj_remove_style_all(o);
  lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_remove_flag(o, LV_OBJ_FLAG_CLICKABLE);
  return o;
}

lv_obj_t* panel(lv_obj_t* parent, uint32_t bg, int32_t radius) {
  lv_obj_t* o = plain(parent);
  lv_obj_set_style_bg_color(o, C(bg), 0);
  lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
  lv_obj_set_style_radius(o, radius, 0);
  return o;
}

void column(lv_obj_t* o, lv_flex_align_t main, lv_flex_align_t cross, int32_t gap) {
  lv_obj_set_flex_flow(o, LV_FLEX_FLOW_COLUMN);
  lv_obj_set_flex_align(o, main, cross, cross);
  lv_obj_set_style_pad_row(o, gap, 0);
}

void row(lv_obj_t* o, lv_flex_align_t main, lv_flex_align_t cross, int32_t gap) {
  lv_obj_set_flex_flow(o, LV_FLEX_FLOW_ROW);
  lv_obj_set_flex_align(o, main, cross, cross);
  lv_obj_set_style_pad_column(o, gap, 0);
}

lv_obj_t* text(lv_obj_t* parent, const char* s, const lv_font_t* f, lv_color_t color) {
  lv_obj_t* l = lv_label_create(parent);
  lv_label_set_text(l, s);
  lv_obj_set_style_text_font(l, f, 0);
  lv_obj_set_style_text_color(l, color, 0);
  return l;
}

lv_obj_t* text(lv_obj_t* parent, const char* s, const lv_font_t* f, uint32_t color) {
  return text(parent, s, f, C(color));
}

lv_obj_t* text(lv_obj_t* parent, const String& s, const lv_font_t* f, uint32_t color) {
  return text(parent, s.c_str(), f, C(color));
}

void wrapTo(lv_obj_t* label, int32_t width, lv_text_align_t align = LV_TEXT_ALIGN_LEFT) {
  lv_label_set_long_mode(label, LV_LABEL_LONG_WRAP);
  lv_obj_set_width(label, width);
  lv_obj_set_style_text_align(label, align, 0);
}

int32_t textWidth(const char* s, const lv_font_t* f) {
  int32_t w = 0;
  for (const char* p = s; *p; ++p) {
    w += lv_font_get_glyph_width(f, static_cast<uint8_t>(p[0]), static_cast<uint8_t>(p[1]));
  }
  return w;
}

const lv_font_t* fitFont(const char* s, int32_t maxW, std::initializer_list<const lv_font_t*> fonts) {
  const lv_font_t* last = nullptr;
  for (const lv_font_t* f : fonts) {
    last = f;
    if (textWidth(s, f) <= maxW) return f;
  }
  return last;
}

String merchantTitle() { return g_merchant.length() ? g_merchant : String("SoundShare Soundbox"); }

const char* railName(const String& rail) {
  if (rail == "UPI_BANK") return "UPI";
  if (rail == "UPI_RUPAY_CC") return "RuPay credit card on UPI";
  if (rail == "UPI_PPI") return "UPI wallet";
  if (rail == "DEBIT_CARD") return "Debit card";
  if (rail == "CREDIT_CARD") return "Credit card";
  if (rail == "NET_BANKING") return "Net banking";
  return "";
}

String pctText(float pct) {
  char buf[16];
  if (fabsf(pct - roundf(pct)) < 0.05f) {
    snprintf(buf, sizeof(buf), "%d%%", static_cast<int>(roundf(pct)));
  } else {
    snprintf(buf, sizeof(buf), "%.1f%%", pct);
  }
  return String(buf);
}

void killTimers() {
  if (g_tick) {
    lv_timer_delete(g_tick);
    g_tick = nullptr;
  }
  if (g_return) {
    lv_timer_delete(g_return);
    g_return = nullptr;
  }
}

lv_obj_t* newScreen(Screen s, uint32_t bg) {
  killTimers();
  g_bootMsg = g_idleFooter = g_bannerHost = g_countdown = nullptr;
  lv_obj_t* scr = lv_screen_active();
  lv_obj_clean(scr);
  lv_obj_set_style_bg_color(scr, C(bg), 0);
  lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
  lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_t* root = plain(scr);
  lv_obj_set_size(root, W, H);
  lv_obj_add_flag(root, LV_OBJ_FLAG_CLICKABLE);
  g_screen = s;
  return root;
}

void returnToIdleIn(uint32_t ms) {
  g_return = lv_timer_create(
      [](lv_timer_t* t) {
        lv_timer_delete(t);
        g_return = nullptr;
        ui::showIdle();
      },
      ms, nullptr);
}

lv_obj_t* header(lv_obj_t* parent, const String& title, const String& sub) {
  lv_obj_t* bar = panel(parent, kNavy, 0);
  lv_obj_set_size(bar, W, HDR_H);
  lv_obj_set_style_pad_left(bar, M + 2, 0);
  lv_obj_set_style_pad_right(bar, 28, 0);  // room for the status dot
  row(bar, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER, 8);
  lv_obj_t* t = text(bar, title, F.md, kWhite);
  lv_label_set_long_mode(t, LV_LABEL_LONG_DOT);
  lv_obj_set_flex_grow(t, 1);
  if (sub.length()) {
    lv_obj_t* s = text(bar, sub, F.xs, kSky);
    lv_label_set_long_mode(s, LV_LABEL_LONG_CLIP);
  }
  return bar;
}

lv_obj_t* makeQr(lv_obj_t* parent, const String& data, int32_t qrSize, int32_t quiet) {
  lv_obj_t* card = panel(parent, kWhite, 6);
  lv_obj_set_size(card, qrSize + 2 * quiet, qrSize + 2 * quiet);
  lv_obj_t* qr = lv_qrcode_create(card);
  lv_qrcode_set_size(qr, qrSize);
  lv_qrcode_set_dark_color(qr, lv_color_black());
  lv_qrcode_set_light_color(qr, lv_color_white());
  if (lv_qrcode_update(qr, data.c_str(), data.length()) != LV_RESULT_OK) {
    Serial.printf("[ui] QR encode failed (%u bytes)\n", (unsigned)data.length());
  }
  lv_obj_center(qr);
  return card;
}

Banner defaultBanner() {
  Banner b;
  b.title = "Scan & pay with any UPI app";
  b.subtitle = "Instant voice confirmation on every payment";
  b.cta = "Ads pay your fees";
  b.bg = "#0B1F3A";
  b.fg = "#FFFFFF";
  b.accent = "#00BAF2";
  return b;
}

// Fills `host` (already sized) with a banner. qrSize > 0 adds the offer QR on the right.
void renderBanner(lv_obj_t* host, const Banner& b, const String& offerQr, int32_t qrSize) {
  lv_obj_clean(host);
  const int32_t pad = g_small ? 8 : 12;
  lv_obj_set_style_bg_color(host, parseColor(b.bg, 0x0B1F3A), 0);
  lv_obj_set_style_bg_opa(host, LV_OPA_COVER, 0);
  lv_obj_set_style_radius(host, 12, 0);
  lv_obj_set_style_pad_all(host, pad, 0);
  row(host, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, pad);

  const lv_color_t fg = parseColor(b.fg, kWhite);
  const lv_color_t accent = parseColor(b.accent, 0x00E5A8);

  lv_obj_t* col = plain(host);
  lv_obj_set_flex_grow(col, 1);
  lv_obj_set_height(col, LV_SIZE_CONTENT);
  column(col, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_START, g_small ? 2 : 4);

  if (b.title.length()) {
    lv_obj_t* t = text(col, b.title.c_str(), F.lg, fg);
    wrapTo(t, lv_pct(100));
  }
  if (b.subtitle.length()) {
    lv_obj_t* s = text(col, b.subtitle.c_str(), F.sm, fg);
    wrapTo(s, lv_pct(100));
  }
  if (b.cta.length()) {
    String cta = String(b.cta) + " " LV_SYMBOL_RIGHT;
    lv_obj_t* c = text(col, cta.c_str(), F.sm, accent);
    wrapTo(c, lv_pct(100));
  }

  if (offerQr.length() && qrSize >= 48) {
    const int32_t quiet = g_small ? 4 : 6;
    makeQr(host, offerQr, qrSize - 2 * quiet, quiet);
  }
}

// Screen changes triggered from an object's own event callback must not delete that
// object synchronously, so they are deferred to the next lv_timer_handler() pass.
void goIdleAsync() {
  lv_async_call([](void*) { ui::showIdle(); }, nullptr);
}

void showNextIdleBanner() {
  if (!g_bannerHost) return;
  if (g_banners.empty()) {
    renderBanner(g_bannerHost, defaultBanner(), String(), 0);
    return;
  }
  g_bannerIdx %= g_banners.size();
  renderBanner(g_bannerHost, g_banners[g_bannerIdx], String(), 0);
}

void updateIdleFooter() {
  if (!g_idleFooter) return;
  String s = g_deviceId.length() ? g_deviceId : String("Soundbox");
  if (!g_wifiUp) {
    s += "  |  Wi-Fi offline";
  } else if (!g_serverUp) {
    s += "  |  Connecting to server...";
  } else {
    s += "  |  Online";
  }
  lv_label_set_text(g_idleFooter, s.c_str());
}

void updateCountdown() {
  if (!g_countdown) return;
  const int64_t now = clock_sync::now();
  if (g_expiresAt <= 0 || now <= 0) {
    lv_label_set_text(g_countdown, "");
    return;
  }
  const int64_t rem = g_expiresAt - now;
  if (rem <= 0) {
    lv_label_set_text(g_countdown, "QR expired");
    lv_obj_set_style_text_color(g_countdown, C(kRed), 0);
    return;
  }
  lv_label_set_text_fmt(g_countdown, "Expires in %02d:%02d", static_cast<int>(rem / 60), static_cast<int>(rem % 60));
  lv_obj_set_style_text_color(g_countdown, C(rem < 60 ? kRed : kText), 0);
}

void showDeviceInfo() {
  if (g_info) lv_obj_delete(g_info);
  g_info = panel(lv_layer_top(), kWhite, 12);
  lv_obj_set_size(g_info, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
  lv_obj_set_style_pad_all(g_info, M * 2, 0);
  lv_obj_set_style_border_color(g_info, C(kNavy), 0);
  lv_obj_set_style_border_width(g_info, 2, 0);
  column(g_info, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, 4);
  lv_obj_center(g_info);
  lv_obj_add_flag(g_info, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(
      g_info, [](lv_event_t* e) { lv_obj_delete_async(lv_event_get_target_obj(e)); }, LV_EVENT_CLICKED, nullptr);
  lv_obj_add_event_cb(g_info, [](lv_event_t*) { g_info = nullptr; }, LV_EVENT_DELETE, nullptr);

  char buf[96];
  text(g_info, "Device info", F.md, kNavy);
  snprintf(buf, sizeof(buf), "Device: %s", g_deviceId.c_str());
  text(g_info, buf, F.sm, kText);
  snprintf(buf, sizeof(buf), "IP: %s  RSSI %d", WiFi.localIP().toString().c_str(), WiFi.RSSI());
  text(g_info, buf, F.sm, kText);
  snprintf(buf, sizeof(buf), "Server: %s:%u (%s)", g_host.c_str(), g_port, g_serverUp ? "online" : "offline");
  text(g_info, buf, F.sm, kText);
  snprintf(buf, sizeof(buf), "FW %s  heap %u KB  PSRAM %u KB", FW_VERSION, (unsigned)(ESP.getFreeHeap() / 1024),
           (unsigned)(ESP.getFreePsram() / 1024));
  text(g_info, buf, F.xs, kMuted);
  text(g_info, "Hold BOOT at power-up to change settings", F.xs, kMuted);
  lv_obj_delete_delayed(g_info, 8000);
}

void toast(const String& msg, uint32_t bg, uint32_t ms) {
  if (g_toast) lv_obj_delete(g_toast);
  g_toast = panel(lv_layer_top(), bg, 12);
  lv_obj_set_size(g_toast, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
  lv_obj_set_style_max_width(g_toast, W - 2 * M, 0);
  lv_obj_set_style_pad_hor(g_toast, M * 2, 0);
  lv_obj_set_style_pad_ver(g_toast, M, 0);
  lv_obj_t* l = text(g_toast, msg, F.md, kWhite);
  lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
  lv_obj_set_style_max_width(l, W - 6 * M, 0);
  lv_obj_align(g_toast, LV_ALIGN_BOTTOM_MID, 0, -M * 2);
  lv_obj_add_event_cb(g_toast, [](lv_event_t*) { g_toast = nullptr; }, LV_EVENT_DELETE, nullptr);
  lv_obj_delete_delayed(g_toast, ms);
}

void updateDot() {
  if (!g_dot) return;
  const uint32_t c = !g_wifiUp ? kRed : (!g_serverUp ? kAmber : kGreen);
  lv_obj_set_style_bg_color(g_dot, C(c), 0);
}

}  // namespace

namespace ui {

void begin() {
  W = display::width();
  H = display::height();
  g_small = W < 480;
  if (g_small) {
    F = {&lv_font_montserrat_36, &lv_font_montserrat_28, &lv_font_montserrat_20,
         &lv_font_montserrat_16, &lv_font_montserrat_14, &lv_font_montserrat_12};
    M = 6;
    HDR_H = 32;
  } else {
    F = {&lv_font_montserrat_48, &lv_font_montserrat_36, &lv_font_montserrat_24,
         &lv_font_montserrat_20, &lv_font_montserrat_16, &lv_font_montserrat_14};
    M = 8;
    HDR_H = 44;
  }

  g_dot = panel(lv_layer_top(), kRed, LV_RADIUS_CIRCLE);
  lv_obj_set_size(g_dot, 10, 10);
  lv_obj_set_style_border_color(g_dot, C(kWhite), 0);
  lv_obj_set_style_border_width(g_dot, 1, 0);
  lv_obj_align(g_dot, LV_ALIGN_TOP_RIGHT, -9, (HDR_H - 10) / 2);
}

Screen current() { return g_screen; }

void setConnectionState(bool wifiUp, bool serverUp) {
  if (wifiUp == g_wifiUp && serverUp == g_serverUp) return;
  g_wifiUp = wifiUp;
  g_serverUp = serverUp;
  updateDot();
  updateIdleFooter();
}

void setMerchant(const String& name) {
  if (name == g_merchant) return;
  g_merchant = name;
  if (g_screen == Screen::Idle) showIdle();
}

void setDeviceInfo(const String& deviceId, const String& host, uint16_t port) {
  g_deviceId = deviceId;
  g_host = host;
  g_port = port;
  updateIdleFooter();
}

void setIdleBanners(const std::vector<Banner>& banners) {
  g_banners = banners;
  g_bannerIdx = 0;
  if (g_screen == Screen::Idle) showIdle();
}

// ---- Boot / setup ---------------------------------------------------------------------
void showBoot(const char* message) {
  if (g_screen == Screen::Boot && g_bootMsg) {
    lv_label_set_text(g_bootMsg, message);
    return;
  }
  lv_obj_t* root = newScreen(Screen::Boot, kNavy);
  column(root, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, 6);
  text(root, "SoundShare", F.xl, kWhite);
  text(root, "Paytm Soundbox + AdPulse", F.sm, kSky);
  lv_obj_t* spacer = plain(root);
  lv_obj_set_size(spacer, 1, M * 2);
  g_bootMsg = text(root, message, F.sm, kWhite);
  wrapTo(g_bootMsg, W - 4 * M, LV_TEXT_ALIGN_CENTER);
  text(root, "fw " FW_VERSION, F.xs, kMuted);
}

void showSetupPortal(const char* apName) {
  lv_obj_t* root = newScreen(Screen::Setup, kNavy);
  lv_obj_set_style_pad_all(root, M * 2, 0);
  row(root, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, M * 2);

  const int32_t qr = g_small ? 120 : 170;
  String wifiQr = String("WIFI:T:nopass;S:") + apName + ";;";
  makeQr(root, wifiQr, qr, 8);

  lv_obj_t* col = plain(root);
  lv_obj_set_flex_grow(col, 1);
  lv_obj_set_height(col, LV_SIZE_CONTENT);
  column(col, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_START, 6);
  text(col, "Wi-Fi setup", F.lg, kWhite);
  text(col, "1. Join this Wi-Fi network:", F.xs, kSky);
  text(col, apName, F.md, kWhite);
  lv_obj_t* l2 = text(col, "2. Open http://192.168.4.1", F.xs, kWhite);
  wrapTo(l2, lv_pct(100));
  lv_obj_t* l3 = text(col, "3. Pick your Wi-Fi, then set backend host, port, device ID and token.", F.xs, kWhite);
  wrapTo(l3, lv_pct(100));
}

// ---- Idle ------------------------------------------------------------------------------
void showIdle() {
  lv_obj_t* root = newScreen(Screen::Idle, kBg);
  column(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, M);
  lv_obj_set_style_pad_bottom(root, M / 2, 0);
  header(root, merchantTitle(), "Scan & pay");

  g_bannerHost = panel(root, kNavy, 12);
  lv_obj_set_width(g_bannerHost, W - 2 * M);
  lv_obj_set_flex_grow(g_bannerHost, 1);

  g_idleFooter = text(root, "", F.xs, kMuted);
  updateIdleFooter();

  showNextIdleBanner();
  if (g_banners.size() > 1) {
    g_tick = lv_timer_create(
        [](lv_timer_t*) {
          ++g_bannerIdx;
          showNextIdleBanner();
        },
        BANNER_ROTATE_MS, nullptr);
  }

  lv_obj_add_event_cb(root, [](lv_event_t*) { showDeviceInfo(); }, LV_EVENT_LONG_PRESSED, nullptr);
}

// ---- Bill ------------------------------------------------------------------------------
void showBill(const BillMsg& m) {
  lv_obj_t* root = newScreen(Screen::Bill, kBg);
  column(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, 0);
  header(root, "Your bill", m.orderId);

  lv_obj_t* list = plain(root);
  lv_obj_set_width(list, W);
  lv_obj_set_flex_grow(list, 1);
  lv_obj_add_flag(list, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_scrollbar_mode(list, LV_SCROLLBAR_MODE_AUTO);
  lv_obj_set_style_pad_hor(list, M * 2, 0);
  lv_obj_set_style_pad_ver(list, M / 2, 0);
  column(list, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, 0);

  for (const BillItem& it : m.items) {
    lv_obj_t* r = plain(list);
    lv_obj_set_size(r, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_set_style_pad_ver(r, g_small ? 4 : 7, 0);
    lv_obj_set_style_border_side(r, LV_BORDER_SIDE_BOTTOM, 0);
    lv_obj_set_style_border_width(r, 1, 0);
    lv_obj_set_style_border_color(r, C(kLine), 0);
    row(r, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, M);

    lv_obj_t* name = text(r, it.name, F.sm, kText);
    lv_label_set_long_mode(name, LV_LABEL_LONG_WRAP);
    lv_obj_set_flex_grow(name, 1);
    char qty[16];
    snprintf(qty, sizeof(qty), "x%ld", static_cast<long>(it.qty));
    text(r, qty, F.xs, kMuted);
    text(r, money::formatPaise(it.amount), F.md, kText);
  }

  lv_obj_t* totalBar = panel(root, kWhite, 0);
  lv_obj_set_size(totalBar, W, LV_SIZE_CONTENT);
  lv_obj_set_style_pad_hor(totalBar, M * 2, 0);
  lv_obj_set_style_pad_ver(totalBar, M, 0);
  lv_obj_set_style_border_side(totalBar, LV_BORDER_SIDE_TOP, 0);
  lv_obj_set_style_border_width(totalBar, 2, 0);
  lv_obj_set_style_border_color(totalBar, C(kLine), 0);
  row(totalBar, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER, M);
  char items[24];
  snprintf(items, sizeof(items), "Total (%u item%s)", (unsigned)m.items.size(), m.items.size() == 1 ? "" : "s");
  text(totalBar, items, F.sm, kMuted);
  text(totalBar, money::formatPaise(m.total), F.xl, kNavy);
}

// ---- Split -----------------------------------------------------------------------------
void showSplit(const SplitMsg& m) {
  lv_obj_t* root = newScreen(Screen::Split, kBg);
  column(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, 0);
  header(root, "Split payment", String("Total ") + money::formatPaise(m.total));

  lv_obj_t* body = plain(root);
  lv_obj_set_width(body, W);
  lv_obj_set_flex_grow(body, 1);
  lv_obj_add_flag(body, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_style_pad_all(body, M, 0);
  column(body, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, M);

  char intro[64];
  snprintf(intro, sizeof(intro), "This bill is paid in %u parts", (unsigned)m.legs.size());
  lv_obj_t* in = text(body, intro, F.sm, kMuted);
  wrapTo(in, lv_pct(100));

  const int32_t badge = g_small ? 26 : 34;
  for (const SplitLeg& leg : m.legs) {
    lv_obj_t* card = panel(body, kWhite, 10);
    lv_obj_set_size(card, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_set_style_pad_all(card, g_small ? M : M + 4, 0);
    row(card, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, M + 2);

    lv_obj_t* b = panel(card, kSky, LV_RADIUS_CIRCLE);
    lv_obj_set_size(b, badge, badge);
    char seq[8];
    snprintf(seq, sizeof(seq), "%d", leg.seq);
    lv_obj_center(text(b, seq, F.md, kWhite));

    lv_obj_t* label = text(card, leg.label, F.md, kText);
    lv_label_set_long_mode(label, LV_LABEL_LONG_WRAP);
    lv_obj_set_flex_grow(label, 1);
    text(card, money::formatPaise(leg.amount), F.lg, kNavy);
  }

  if (m.note.length()) {
    lv_obj_t* note = text(body, m.note, F.xs, kMuted);
    wrapTo(note, lv_pct(100));
  }
}

// ---- Pay (QR) --------------------------------------------------------------------------
void showQr(const QrMsg& m) {
  lv_obj_t* root = newScreen(Screen::Pay, kBg);
  lv_obj_set_style_pad_all(root, M, 0);
  row(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, M);

  // QR card: as large as the height allows, white quiet zone around it.
  const int32_t quiet = g_small ? 8 : 12;
  int32_t card = H - 2 * M;
  const int32_t maxCard = (W * (g_small ? 66 : 60)) / 100;
  if (card > maxCard) card = maxCard;
  makeQr(root, m.qrData, card - 2 * quiet, quiet);

  const int32_t rightW = W - card - 3 * M;
  lv_obj_t* col = plain(root);
  lv_obj_set_size(col, rightW, H - 2 * M);
  column(col, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, g_small ? 4 : 10);

  if (m.of > 1) {
    lv_obj_t* pill = panel(col, kSky, 12);
    lv_obj_set_size(pill, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_style_pad_hor(pill, g_small ? 6 : 12, 0);
    lv_obj_set_style_pad_ver(pill, 4, 0);
    char legTxt[24];
    snprintf(legTxt, sizeof(legTxt), "Leg %d of %d", m.seq, m.of);
    text(pill, legTxt, F.sm, kWhite);
  } else {
    text(col, "Scan to pay", F.sm, kMuted);
  }

  const String amount = money::formatPaise(m.amount);
  const lv_font_t* af = fitFont(amount.c_str(), rightW, {F.xl, F.lg, F.md, F.sm, F.xs});
  text(col, amount, af, kNavy);

  lv_obj_t* hint = text(col, "Scan with any UPI app", F.xs, kMuted);
  wrapTo(hint, rightW, LV_TEXT_ALIGN_CENTER);

  g_countdown = text(col, "", g_small ? F.xs : F.sm, kText);
  wrapTo(g_countdown, rightW, LV_TEXT_ALIGN_CENTER);
  g_expiresAt = m.expiresAt;
  updateCountdown();
  g_tick = lv_timer_create([](lv_timer_t*) { updateCountdown(); }, 1000, nullptr);

  lv_obj_t* mer = text(col, merchantTitle(), F.xs, kMuted);
  wrapTo(mer, rightW, LV_TEXT_ALIGN_CENTER);
}

void showLegPaid(const LegPaidMsg& m) {
  String s = String(LV_SYMBOL_OK " ");
  if (m.of > 1) {
    s += "Leg " + String(m.seq) + " of " + String(m.of) + " paid  ";
  } else {
    s += "Paid  ";
  }
  s += money::formatPaise(m.amount);
  const char* rail = railName(m.rail);
  if (*rail) {
    s += "\n";
    s += rail;
  }
  toast(s, kGreen, LEG_TOAST_MS);
}

// ---- Success ---------------------------------------------------------------------------
void showSuccess(const SuccessMsg& m) {
  if (g_toast) lv_obj_delete(g_toast);
  lv_obj_t* root = newScreen(Screen::Success, kBg);
  column(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, M);
  lv_obj_set_style_pad_bottom(root, M, 0);

  // Top: big check + amount
  const int32_t topH = g_small ? 78 : 112;
  lv_obj_t* top = panel(root, kGreen, 0);
  lv_obj_set_size(top, W, topH);
  row(top, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, g_small ? 10 : 16);
  const int32_t circle = g_small ? 50 : 72;
  lv_obj_t* ok = panel(top, kWhite, LV_RADIUS_CIRCLE);
  lv_obj_set_size(ok, circle, circle);
  lv_obj_center(text(ok, LV_SYMBOL_OK, F.xl, kGreen));
  lv_obj_t* amtCol = plain(top);
  lv_obj_set_size(amtCol, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
  column(amtCol, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_START, 0);
  const String amount = money::formatPaise(m.amount);
  text(amtCol, amount, fitFont(amount.c_str(), W - circle - 5 * M, {F.xxl, F.xl, F.lg}), kWhite);
  text(amtCol, "Payment received", F.sm, kWhite);

  // Settlement block
  if (m.settlement.present) {
    const Settlement& st = m.settlement;
    lv_obj_t* card = panel(root, kWhite, 10);
    lv_obj_set_size(card, W - 2 * M, LV_SIZE_CONTENT);
    lv_obj_set_style_pad_hor(card, M + 4, 0);
    lv_obj_set_style_pad_ver(card, g_small ? 4 : M, 0);
    column(card, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, 2);

    String line1;
    if (st.mdr <= 0) {
      line1 = "No fee on this payment";
    } else {
      line1 = "Fee " + money::formatPaise(st.mdr);
      if (!st.coveredBy.empty()) {
        line1 += " covered " + pctText(st.coveragePct) + " by ";
        for (size_t i = 0; i < st.coveredBy.size(); ++i) {
          if (i) line1 += ", ";
          line1 += st.coveredBy[i].name;
        }
      } else if (st.coveragePct > 0) {
        line1 += " (" + pctText(st.coveragePct) + " covered)";
      }
    }
    lv_obj_t* l1 = text(card, line1, F.xs, kMuted);
    wrapTo(l1, lv_pct(100));
    text(card, String("Merchant receives ") + money::formatPaise(st.merchantReceives), F.md, kNavy);
  }

  // Banner (+ offer QR)
  lv_obj_t* host = panel(root, kNavy, 12);
  lv_obj_set_width(host, W - 2 * M);
  lv_obj_set_flex_grow(host, 1);
  lv_obj_update_layout(root);
  const int32_t pad = g_small ? 8 : 12;
  const int32_t qrSize = lv_obj_get_height(host) - 2 * pad;

  Banner b;
  if (m.hasBanner) {
    b = m.banner;
  } else if (m.offerQr.length()) {
    b = defaultBanner();
    b.title = m.ad.present && m.ad.advertiser.length() ? m.ad.advertiser : String("Special offer");
    b.subtitle = "Scan the code to claim your offer";
    b.cta = "Scan to claim";
  } else {
    b = defaultBanner();
    b.title = "Thank you for shopping";
    b.subtitle = merchantTitle();
    b.cta = "";
  }
  renderBanner(host, b, m.offerQr, qrSize);

  returnToIdleIn(SUCCESS_RETURN_MS);
}

// ---- Failed / cancelled ----------------------------------------------------------------
void showFailed(const FailedMsg& m) {
  lv_obj_t* root = newScreen(Screen::Failed, kRed);
  column(root, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, M);
  const int32_t circle = g_small ? 56 : 80;
  lv_obj_t* c = panel(root, kWhite, LV_RADIUS_CIRCLE);
  lv_obj_set_size(c, circle, circle);
  lv_obj_center(text(c, LV_SYMBOL_CLOSE, F.xl, kRed));

  const char* title = "Payment failed";
  if (m.reason == "expired") title = "QR code expired";
  text(root, title, F.xl, kWhite);
  String sub = "Please ask the cashier to try again.";
  if (m.reason.length() && m.reason != "expired") sub = "Reason: " + m.reason + "\n" + sub;
  lv_obj_t* s = text(root, sub, F.sm, kWhite);
  wrapTo(s, W - 4 * M, LV_TEXT_ALIGN_CENTER);
  returnToIdleIn(FAILED_RETURN_MS);
  lv_obj_add_event_cb(root, [](lv_event_t*) { goIdleAsync(); }, LV_EVENT_CLICKED, nullptr);
}

void showCancelled(const String& orderId) {
  lv_obj_t* root = newScreen(Screen::Cancelled, kGrey);
  column(root, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, M);
  const int32_t circle = g_small ? 56 : 80;
  lv_obj_t* c = panel(root, kWhite, LV_RADIUS_CIRCLE);
  lv_obj_set_size(c, circle, circle);
  lv_obj_center(text(c, LV_SYMBOL_CLOSE, F.xl, kGrey));
  text(root, "Bill cancelled", F.xl, kWhite);
  if (orderId.length()) text(root, orderId, F.sm, kWhite);
  returnToIdleIn(CANCELLED_RETURN_MS);
  lv_obj_add_event_cb(root, [](lv_event_t*) { goIdleAsync(); }, LV_EVENT_CLICKED, nullptr);
}

}  // namespace ui

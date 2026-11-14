#include "protocol.h"

#include <ArduinoJson.h>
#include <WiFi.h>
#include <math.h>

#include "app_config.h"
#include "audio/ad_cache.h"
#include "audio/audio_player.h"
#include "messages.h"
#include "net/settings.h"
#include "net/ws_client.h"
#include "ui/ui.h"
#include "util/clock.h"

namespace {

uint32_t g_lastHeartbeat = 0;
uint32_t g_lastStatusPoll = 0;

// ---- JSON helpers ------------------------------------------------------------------
String str(JsonVariantConst v, const char* def = "") {
  const char* s = v.as<const char*>();
  return String(s ? s : def);
}

int64_t i64(JsonVariantConst v) { return v.is<int64_t>() || v.is<double>() ? v.as<int64_t>() : 0; }

bool parseBanner(JsonVariantConst v, Banner& b) {
  if (!v.is<JsonObjectConst>()) return false;
  b.title = str(v["title"]);
  b.subtitle = str(v["subtitle"]);
  b.cta = str(v["cta"]);
  b.bg = str(v["bg"], "#0B1F3A");
  b.fg = str(v["fg"], "#FFFFFF");
  b.accent = str(v["accent"], "#00E5A8");
  return true;
}

void send(const JsonDocument& doc) {
  String out;
  serializeJson(doc, out);
  if (!ws_client::sendText(out)) Serial.printf("[proto] drop (offline): %s\n", out.c_str());
}

float round1(float v) { return roundf(v * 10.0f) / 10.0f; }

// ---- Device -> server ----------------------------------------------------------------
void sendHello() {
  JsonDocument doc;
  doc["type"] = "hello";
  doc["fw"] = FW_VERSION;
  JsonArray cache = doc["cache"].to<JsonArray>();
  std::vector<String> hashes;
  ad_cache::list(hashes);
  for (const String& h : hashes) cache.add(h);
  send(doc);
}

void sendHeartbeat() {
  JsonDocument doc;
  doc["type"] = "heartbeat";
  doc["fw"] = FW_VERSION;
  doc["rssi"] = WiFi.RSSI();
  doc["heap"] = ESP.getFreeHeap();
  send(doc);
}

void sendPong() {
  JsonDocument doc;
  doc["type"] = "pong";
  send(doc);
}

void sendCacheOk(const String& hash) {
  JsonDocument doc;
  doc["type"] = "cache_ok";
  doc["hash"] = hash;
  send(doc);
}

void sendPlayAck(const audio_player::PlayAck& a) {
  JsonDocument doc;
  doc["type"] = "play_ack";
  doc["playId"] = a.playId;
  doc["ms"] = a.ms;
  if (a.hasLevels) {
    doc["peakDb"] = round1(a.peakDb);
    doc["rmsDb"] = round1(a.rmsDb);
  } else {
    doc["peakDb"] = nullptr;
    doc["rmsDb"] = nullptr;
  }
  send(doc);
}

// ---- Server -> device ----------------------------------------------------------------
void handleHelloAck(JsonDocument& doc) {
  JsonVariantConst merchant = doc["merchant"];
  const String name = str(merchant["name"]);
  if (name.length()) {
    settings::setMerchantName(name);
    ui::setMerchant(name);
  }
  clock_sync::setServerTime(i64(doc["serverTime"]));
  Serial.printf("[proto] hello_ack merchant=%s\n", name.c_str());
}

void handleIdle(JsonDocument& doc) {
  std::vector<Banner> banners;
  for (JsonVariantConst v : doc["banners"].as<JsonArrayConst>()) {
    Banner b;
    if (parseBanner(v, b)) banners.push_back(b);
  }
  ui::setIdleBanners(banners);
  // The server is authoritative: leave any order screen, but let the success
  // screen (ad banner + offer QR) finish its own countdown.
  if (ui::current() != ui::Screen::Idle && ui::current() != ui::Screen::Success) ui::showIdle();
}

void handleShowBill(JsonDocument& doc) {
  BillMsg m;
  m.orderId = str(doc["orderId"]);
  m.total = i64(doc["total"]);
  for (JsonVariantConst v : doc["items"].as<JsonArrayConst>()) {
    BillItem it;
    it.name = str(v["name"]);
    it.qty = v["qty"] | 1;
    it.amount = i64(v["amount"]);
    m.items.push_back(it);
  }
  ui::showBill(m);
}

void handleShowSplit(JsonDocument& doc) {
  SplitMsg m;
  m.orderId = str(doc["orderId"]);
  m.total = i64(doc["total"]);
  m.note = str(doc["note"]);
  for (JsonVariantConst v : doc["legs"].as<JsonArrayConst>()) {
    SplitLeg leg;
    leg.seq = v["seq"] | 0;
    leg.label = str(v["label"]);
    leg.amount = i64(v["amount"]);
    m.legs.push_back(leg);
  }
  ui::showSplit(m);
}

void handleShowQr(JsonDocument& doc) {
  QrMsg m;
  m.orderId = str(doc["orderId"]);
  m.legId = str(doc["legId"]);
  m.seq = doc["seq"] | 1;
  m.of = doc["of"] | 1;
  m.qrData = str(doc["qrData"]);
  m.amount = i64(doc["amount"]);
  m.expiresAt = i64(doc["expiresAt"]);
  if (m.qrData.length() == 0) {
    Serial.println("[proto] show_qr without qrData");
    return;
  }
  ui::showQr(m);
}

void handleLegPaid(JsonDocument& doc) {
  LegPaidMsg m;
  m.orderId = str(doc["orderId"]);
  m.legId = str(doc["legId"]);
  m.seq = doc["seq"] | 1;
  m.of = doc["of"] | 1;
  m.amount = i64(doc["amount"]);
  m.rail = str(doc["rail"]);
  ui::showLegPaid(m);
}

void handlePaymentSuccess(JsonDocument& doc) {
  SuccessMsg m;
  m.orderId = str(doc["orderId"]);
  m.amount = i64(doc["amount"]);
  m.lang = str(doc["lang"], "en");
  m.announceText = str(doc["announceText"]);
  m.announceUrl = str(doc["announceUrl"]);
  m.playId = str(doc["playId"]);
  for (JsonVariantConst t : doc["announce"].as<JsonArrayConst>()) {
    const char* s = t.as<const char*>();
    if (s) m.announce.push_back(String(s));
  }

  JsonVariantConst ad = doc["ad"];
  if (ad.is<JsonObjectConst>()) {
    m.ad.hash = str(ad["hash"]);
    m.ad.url = str(ad["url"]);
    m.ad.durationMs = ad["durationMs"] | 0;
    m.ad.advertiser = str(ad["advertiser"]);
    m.ad.present = ad_cache::isValidHash(m.ad.hash) || m.ad.url.length() > 0;
  }

  m.hasBanner = parseBanner(doc["banner"], m.banner);
  m.offerQr = str(doc["offerQr"]);

  JsonVariantConst st = doc["settlement"];
  if (st.is<JsonObjectConst>()) {
    m.settlement.present = true;
    m.settlement.mdr = i64(st["mdr"]);
    m.settlement.merchantReceives = i64(st["merchantReceives"]);
    m.settlement.coveragePct = st["coveragePct"] | 0.0f;
    for (JsonVariantConst s : st["coveredBy"].as<JsonArrayConst>()) {
      Sponsor sp;
      sp.name = str(s["name"]);
      sp.amount = i64(s["amount"]);
      if (sp.name.length()) m.settlement.coveredBy.push_back(sp);
    }
  }

  Serial.printf("[proto] payment_success %s: \"%s\" ad=%s\n", m.orderId.c_str(), m.announceText.c_str(),
                m.ad.present ? m.ad.hash.c_str() : "none");
  // Start audio first: the UI build takes a few frames and the announcement should not wait.
  audio_player::playPayment(m);
  ui::showSuccess(m);
}

// The counter ad: plays as the QR goes up, while the customer pays. The payment message that
// follows waits for it to finish (see audio_player).
void handlePlayAd(JsonDocument& doc) {
  SuccessMsg m;  // reuse the payment job shape: no announcement, just the ad
  m.orderId = str(doc["orderId"]);
  m.playId = str(doc["playId"]);
  JsonVariantConst ad = doc["ad"];
  if (!ad.is<JsonObjectConst>()) return;
  m.ad.hash = str(ad["hash"]);
  m.ad.url = str(ad["url"]);
  m.ad.durationMs = ad["durationMs"] | 0;
  m.ad.advertiser = str(ad["advertiser"]);
  m.ad.present = ad_cache::isValidHash(m.ad.hash) || m.ad.url.length() > 0;
  Serial.printf("[proto] play_ad %s: %s\n", m.orderId.c_str(), m.ad.advertiser.c_str());
  if (m.ad.present) audio_player::playPayment(m);
}

void handlePaymentFailed(JsonDocument& doc) {
  FailedMsg m;
  m.orderId = str(doc["orderId"]);
  m.legId = str(doc["legId"]);
  m.reason = str(doc["reason"]);
  ui::showFailed(m);
}

void handleCancelled(JsonDocument& doc) { ui::showCancelled(str(doc["orderId"])); }

void handleCacheAudio(JsonDocument& doc) {
  const String hash = str(doc["hash"]);
  const String url = str(doc["url"]);
  if (!ad_cache::isValidHash(hash)) {
    Serial.printf("[proto] cache_audio: bad hash '%s'\n", hash.c_str());
    return;
  }
  if (ad_cache::has(hash)) {
    sendCacheOk(hash);
  } else {
    ad_cache::request(hash, url);
  }
}

}  // namespace

namespace protocol {

void onConnected() {
  sendHello();
  g_lastHeartbeat = millis();
  ui::setConnectionState(WiFi.status() == WL_CONNECTED, true);
}

void onDisconnected() { ui::setConnectionState(WiFi.status() == WL_CONNECTED, false); }

void onText(const char* payload, size_t len) {
  JsonDocument doc;
  const DeserializationError err = deserializeJson(doc, payload, len);
  if (err) {
    Serial.printf("[proto] bad JSON (%s): %.*s\n", err.c_str(), (int)(len > 120 ? 120 : len), payload);
    return;
  }
  const char* type = doc["type"] | "";

  if (!strcmp(type, "ping")) {
    sendPong();
  } else if (!strcmp(type, "hello_ack")) {
    handleHelloAck(doc);
  } else if (!strcmp(type, "idle")) {
    handleIdle(doc);
  } else if (!strcmp(type, "show_bill")) {
    handleShowBill(doc);
  } else if (!strcmp(type, "show_split")) {
    handleShowSplit(doc);
  } else if (!strcmp(type, "show_qr")) {
    handleShowQr(doc);
  } else if (!strcmp(type, "leg_paid")) {
    handleLegPaid(doc);
  } else if (!strcmp(type, "payment_success")) {
    handlePaymentSuccess(doc);
  } else if (!strcmp(type, "play_ad")) {
    handlePlayAd(doc);
  } else if (!strcmp(type, "payment_failed")) {
    handlePaymentFailed(doc);
  } else if (!strcmp(type, "cancelled")) {
    handleCancelled(doc);
  } else if (!strcmp(type, "cache_audio")) {
    handleCacheAudio(doc);
  } else {
    Serial.printf("[proto] unknown type '%s'\n", type);
  }
}

void loop() {
  const uint32_t now = millis();

  if (ws_client::connected() && now - g_lastHeartbeat >= HEARTBEAT_INTERVAL_MS) {
    g_lastHeartbeat = now;
    sendHeartbeat();
  }

  if (now - g_lastStatusPoll >= 1000) {
    g_lastStatusPoll = now;
    ui::setConnectionState(WiFi.status() == WL_CONNECTED, ws_client::connected());
  }

  audio_player::PlayAck ack;
  while (audio_player::pollAck(ack)) sendPlayAck(ack);

  String hash;
  while (ad_cache::pollDone(hash)) sendCacheOk(hash);
}

}  // namespace protocol

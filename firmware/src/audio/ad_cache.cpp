#include "ad_cache.h"

#include <HTTPClient.h>
#include <LittleFS.h>
#include <WiFi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

#include "app_config.h"
#include "net/settings.h"

namespace {

struct Job {
  char hash[65];
  char url[256];
};

struct Done {
  char hash[65];
};

QueueHandle_t g_jobs = nullptr;
QueueHandle_t g_done = nullptr;

void pushDone(const String& hash) {
  Done d{};
  strlcpy(d.hash, hash.c_str(), sizeof(d.hash));
  xQueueSend(g_done, &d, 0);
}

size_t freeBytes() { return LittleFS.totalBytes() - LittleFS.usedBytes(); }

// Very small eviction policy: delete cached ads until there is room.
void makeRoom(size_t need) {
  if (freeBytes() >= need) return;
  File dir = LittleFS.open(ADS_DIR);
  if (!dir || !dir.isDirectory()) return;
  std::vector<String> victims;
  for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
    victims.push_back(String(ADS_DIR) + "/" + String(f.name()).substring(String(f.name()).lastIndexOf('/') + 1));
  }
  dir.close();
  for (const String& v : victims) {
    if (freeBytes() >= need) break;
    Serial.printf("[cache] evicting %s\n", v.c_str());
    LittleFS.remove(v);
  }
}

bool download(const Job& job) {
  if (WiFi.status() != WL_CONNECTED) return false;
  const String finalPath = ad_cache::pathFor(job.hash);
  const String tmpPath = finalPath + ".tmp";

  HTTPClient http;
  http.setTimeout(10000);
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
  if (!http.begin(job.url)) {
    Serial.printf("[cache] bad url %s\n", job.url);
    return false;
  }
  const int code = http.GET();
  if (code != HTTP_CODE_OK) {
    Serial.printf("[cache] GET %s -> %d\n", job.url, code);
    http.end();
    return false;
  }
  const int len = http.getSize();
  makeRoom((len > 0 ? static_cast<size_t>(len) : 256 * 1024) + ADS_MIN_FREE_BYTES);

  File f = LittleFS.open(tmpPath, FILE_WRITE);
  if (!f) {
    http.end();
    return false;
  }
  const int written = http.writeToStream(&f);
  f.close();
  http.end();
  if (written <= 0 || (len > 0 && written != len)) {
    Serial.printf("[cache] short write %d/%d for %s\n", written, len, job.hash);
    LittleFS.remove(tmpPath);
    return false;
  }
  LittleFS.remove(finalPath);
  if (!LittleFS.rename(tmpPath, finalPath)) {
    LittleFS.remove(tmpPath);
    return false;
  }
  Serial.printf("[cache] stored %s (%d bytes)\n", finalPath.c_str(), written);
  return true;
}

void task(void*) {
  Job job;
  for (;;) {
    if (xQueueReceive(g_jobs, &job, portMAX_DELAY) != pdTRUE) continue;
    if (ad_cache::has(job.hash)) {
      pushDone(job.hash);
      continue;
    }
    bool ok = false;
    for (int attempt = 0; attempt < 3 && !ok; ++attempt) {
      ok = download(job);
      if (!ok) vTaskDelay(pdMS_TO_TICKS(1500));
    }
    if (ok) pushDone(job.hash);
  }
}

}  // namespace

namespace ad_cache {

void begin() {
  if (!LittleFS.exists(ADS_DIR)) LittleFS.mkdir(ADS_DIR);
  // Remove partial downloads left by a reset.
  File dir = LittleFS.open(ADS_DIR);
  if (dir && dir.isDirectory()) {
    std::vector<String> stale;
    for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
      String n = f.name();
      if (n.endsWith(".tmp")) stale.push_back(String(ADS_DIR) + "/" + n.substring(n.lastIndexOf('/') + 1));
    }
    dir.close();
    for (const String& s : stale) LittleFS.remove(s);
  }
  g_jobs = xQueueCreate(8, sizeof(Job));
  g_done = xQueueCreate(8, sizeof(Done));
  xTaskCreatePinnedToCore(task, "adcache", 8192, nullptr, 2, nullptr, 0);
}

bool isValidHash(const String& hash) {
  if (hash.length() < 8 || hash.length() > 64) return false;
  for (size_t i = 0; i < hash.length(); ++i) {
    if (!isxdigit(static_cast<unsigned char>(hash[i]))) return false;
  }
  return true;
}

String pathFor(const String& hash) { return String(ADS_DIR) + "/" + hash + ".mp3"; }

bool has(const String& hash) { return isValidHash(hash) && LittleFS.exists(pathFor(hash)); }

void request(const String& hash, const String& url) {
  if (!isValidHash(hash) || url.length() == 0 || !g_jobs) return;
  Job job{};
  strlcpy(job.hash, hash.c_str(), sizeof(job.hash));
  strlcpy(job.url, absoluteUrl(url).c_str(), sizeof(job.url));
  if (xQueueSend(g_jobs, &job, 0) != pdTRUE) Serial.println("[cache] job queue full");
}

bool pollDone(String& hashOut) {
  if (!g_done) return false;
  Done d;
  if (xQueueReceive(g_done, &d, 0) != pdTRUE) return false;
  hashOut = d.hash;
  return true;
}

void list(std::vector<String>& out) {
  File dir = LittleFS.open(ADS_DIR);
  if (!dir || !dir.isDirectory()) return;
  for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
    String n = f.name();
    n = n.substring(n.lastIndexOf('/') + 1);
    if (!n.endsWith(".mp3")) continue;
    n.remove(n.length() - 4);
    if (isValidHash(n)) out.push_back(n);
  }
  dir.close();
}

String absoluteUrl(const String& url) {
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  const DeviceSettings& s = settings::get();
  String base = "http://" + s.host + ":" + String(s.port);
  return url.startsWith("/") ? base + url : base + "/" + url;
}

}  // namespace ad_cache

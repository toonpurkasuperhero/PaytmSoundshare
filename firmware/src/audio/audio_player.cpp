#include "audio_player.h"

#include <Audio.h>
#include <LittleFS.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

#include <vector>

#include "ad_cache.h"
#include "app_config.h"
#include "board_pins.h"
#include "mic.h"

namespace {

struct Job {
  String announceUrl;         // full-sentence announcement streamed from the backend (preferred)
  std::vector<String> clips;  // resolved LittleFS paths, in play order (fallback)
  bool hasAd = false;
  String adPath;  // non-empty when cached on LittleFS
  String adUrl;   // used when adPath is empty
  uint32_t adDurationMs = 0;
  String playId;
  bool adOnly = false;  // counter ad (play_ad): no announcement in this job
};

enum class CmdType : uint8_t { Play, Stop };
struct Cmd {
  CmdType type;
  Job* job;
};

struct AckRaw {
  char playId[64];
  uint32_t ms;
  bool hasLevels;
  float peakDb;
  float rmsDb;
};

enum class Phase : uint8_t { Idle, Announce, Clips, Ad };

Audio* g_audio = nullptr;
QueueHandle_t g_cmds = nullptr;
QueueHandle_t g_acks = nullptr;
volatile bool g_eof = false;
volatile Phase g_phase = Phase::Idle;

// Audio-task-only state
Job* g_job = nullptr;
Job* g_pending = nullptr;  // payment job waiting for the counter ad to finish
void startJob();
size_t g_clipIdx = 0;
uint32_t g_adStart = 0;
uint32_t g_annStart = 0;
constexpr uint32_t ANNOUNCE_MAX_MS = 9000;     // hard cap for the streamed announcement
constexpr uint32_t ANNOUNCE_MIN_OK_MS = 400;   // shorter than this = the stream failed
uint32_t g_adCapMs = 0;
bool g_adStarted = false;

bool validToken(const String& t) {
  if (t.length() == 0 || t.length() > 24) return false;
  for (size_t i = 0; i < t.length(); ++i) {
    const char c = t[i];
    if (!(isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '-')) return false;
  }
  return true;
}

bool validLang(const String& l) {
  if (l.length() == 0 || l.length() > 8) return false;
  for (size_t i = 0; i < l.length(); ++i) {
    if (!isalpha(static_cast<unsigned char>(l[i])) && l[i] != '-' && l[i] != '_') return false;
  }
  return true;
}

// Clips are WAV (gapless stitching: MP3 adds encoder padding at both ends of every clip);
// .mp3 is still accepted for older filesystem images.
String resolveClip(const String& lang, const String& token) {
  static const char* const kExts[] = {".wav", ".mp3"};
  for (const char* dir : {lang.c_str(), CLIP_FALLBACK_LANG}) {
    for (const char* ext : kExts) {
      String p = String(CLIPS_DIR) + "/" + dir + "/" + token + ext;
      if (LittleFS.exists(p)) return p;
    }
  }
  return String();
}

void finishJob() {
  delete g_job;
  g_job = nullptr;
  g_phase = Phase::Idle;
  if (g_pending) {  // the payment message that arrived while the counter ad was playing
    g_job = g_pending;
    g_pending = nullptr;
    g_clipIdx = 0;
    startJob();
  }
}

void finishAd() {
  const uint32_t ms = g_adStarted ? millis() - g_adStart : 0;
  g_audio->stopSong();
  const mic::Levels lv = mic::stopMeasuring();

  AckRaw a{};
  strlcpy(a.playId, g_job->playId.c_str(), sizeof(a.playId));
  a.ms = ms;
  a.hasLevels = lv.valid;
  a.peakDb = lv.peakDb;
  a.rmsDb = lv.rmsDb;
  if (a.playId[0]) xQueueSend(g_acks, &a, 0);
  Serial.printf("[audio] ad finished: %u ms (playId=%s)\n", (unsigned)ms, a.playId);
  finishJob();
}

void startAd() {
  if (!g_job->hasAd) {
    finishJob();
    return;
  }
  g_eof = false;
  g_adCapMs = g_job->adDurationMs ? g_job->adDurationMs + AD_MAX_EXTRA_MS : AD_DEFAULT_MAX_MS;
  mic::startMeasuring();
  g_adStart = millis();
  bool ok;
  if (g_job->adPath.length()) {
    ok = g_audio->connecttoFS(LittleFS, g_job->adPath.c_str());
  } else {
    Serial.printf("[audio] ad not cached, streaming %s\n", g_job->adUrl.c_str());
    ok = g_audio->connecttohost(g_job->adUrl.c_str());
  }
  g_adStarted = ok;
  g_phase = Phase::Ad;
  if (!ok) {
    Serial.println("[audio] ad playback failed to start");
    finishAd();
  }
}

void startNextClip() {
  g_eof = false;
  while (g_clipIdx < g_job->clips.size()) {
    const String& path = g_job->clips[g_clipIdx++];
    if (g_audio->connecttoFS(LittleFS, path.c_str())) {
      g_phase = Phase::Clips;
      return;
    }
    Serial.printf("[audio] cannot play %s\n", path.c_str());
  }
  startAd();
}

// Prefer the server's full-sentence announcement; fall back to local clips if it can't start.
void startJob() {
  g_eof = false;
  if (g_job->announceUrl.length() && g_audio->connecttohost(g_job->announceUrl.c_str())) {
    g_annStart = millis();
    g_phase = Phase::Announce;
    return;
  }
  if (g_job->announceUrl.length()) Serial.println("[audio] announcement stream failed, using local clips");
  startNextClip();
}

void finishAnnounce() {
  const uint32_t ms = millis() - g_annStart;
  g_audio->stopSong();
  if (ms < ANNOUNCE_MIN_OK_MS) {
    Serial.printf("[audio] announcement ended after %u ms, using local clips\n", (unsigned)ms);
    startNextClip();
  } else {
    g_clipIdx = g_job->clips.size();  // spoken already: skip the clip fallback
    startAd();
  }
}

void abortCurrent() {
  if (!g_job) return;
  if (g_phase == Phase::Ad) {
    finishAd();  // still report how long the ad actually played
  } else {
    g_audio->stopSong();
    finishJob();
  }
}

void audioTask(void*) {
  for (;;) {
    Cmd cmd;
    const TickType_t wait = (g_phase == Phase::Idle) ? pdMS_TO_TICKS(20) : 0;
    while (xQueueReceive(g_cmds, &cmd, wait) == pdTRUE) {
      if (cmd.type == CmdType::Play && cmd.job && g_job && g_job->adOnly && g_phase == Phase::Ad &&
          !cmd.job->adOnly) {
        delete g_pending;  // the customer hears the whole ad, then "payment received"
        g_pending = cmd.job;
        continue;
      }
      abortCurrent();
      if (cmd.type == CmdType::Play && cmd.job) {
        g_job = cmd.job;
        g_clipIdx = 0;
        startJob();
      }
      if (g_phase != Phase::Idle) break;
    }

    if (g_phase != Phase::Idle) {
      g_audio->loop();
      if (g_phase == Phase::Announce) {
        if (g_eof || !g_audio->isRunning() || millis() - g_annStart > ANNOUNCE_MAX_MS) finishAnnounce();
      } else if (g_phase == Phase::Clips) {
        if (g_eof || !g_audio->isRunning()) startNextClip();
      } else if (g_phase == Phase::Ad) {
        if (g_eof || !g_audio->isRunning() || millis() - g_adStart > g_adCapMs) finishAd();
      }
    }
    vTaskDelay(1);
  }
}

}  // namespace

// ---- ESP32-audioI2S callbacks (weak symbols in the library) ----
void audio_eof_mp3(const char* info) {
  (void)info;
  g_eof = true;
}
void audio_eof_stream(const char* info) {
  (void)info;
  g_eof = true;
}
void audio_info(const char* info) { log_d("[audio] %s", info); }

namespace audio_player {

void begin() {
  g_audio = new Audio(false, 3, I2S_NUM_0);
  g_audio->setPinout(PIN_I2S_SPK_BCLK, PIN_I2S_SPK_LRC, PIN_I2S_SPK_DOUT);
  g_audio->setVolume(AUDIO_VOLUME);
  g_audio->setConnectionTimeout(2000, 4000);
  mic::begin();

  g_cmds = xQueueCreate(4, sizeof(Cmd));
  g_acks = xQueueCreate(4, sizeof(AckRaw));
  // Core 0 alongside Wi-Fi; LVGL + WebSocket run on core 1 (Arduino loop).
  xTaskCreatePinnedToCore(audioTask, "audio", 8192, nullptr, 5, nullptr, 0);
}

void playPayment(const SuccessMsg& msg) {
  Job* job = new Job();
  job->adOnly = msg.announce.empty() && msg.announceUrl.length() == 0;
  if (msg.announceUrl.length()) job->announceUrl = ad_cache::absoluteUrl(msg.announceUrl);
  const String lang = validLang(msg.lang) ? msg.lang : String(CLIP_FALLBACK_LANG);
  for (const String& tok : msg.announce) {
    if (!validToken(tok)) continue;
    const String p = resolveClip(lang, tok);
    if (p.length()) {
      job->clips.push_back(p);
    } else {
      Serial.printf("[audio] missing clip for token '%s'\n", tok.c_str());
    }
  }

  if (msg.ad.present) {
    job->hasAd = true;
    job->playId = msg.playId;
    job->adDurationMs = msg.ad.durationMs;
    if (ad_cache::has(msg.ad.hash)) {
      job->adPath = ad_cache::pathFor(msg.ad.hash);
    } else {
      job->adUrl = ad_cache::absoluteUrl(msg.ad.url);
      // Cache it for next time (sends cache_ok when done).
      ad_cache::request(msg.ad.hash, msg.ad.url);
    }
  }

  Cmd cmd{CmdType::Play, job};
  if (xQueueSend(g_cmds, &cmd, pdMS_TO_TICKS(50)) != pdTRUE) {
    Serial.println("[audio] command queue full");
    delete job;
  }
}

void stop() {
  Cmd cmd{CmdType::Stop, nullptr};
  xQueueSend(g_cmds, &cmd, pdMS_TO_TICKS(50));
}

bool busy() { return g_phase != Phase::Idle; }

bool pollAck(PlayAck& out) {
  if (!g_acks) return false;
  AckRaw a;
  if (xQueueReceive(g_acks, &a, 0) != pdTRUE) return false;
  out.playId = a.playId;
  out.ms = a.ms;
  out.hasLevels = a.hasLevels;
  out.peakDb = a.peakDb;
  out.rmsDb = a.rmsDb;
  return true;
}

}  // namespace audio_player

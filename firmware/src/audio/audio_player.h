#pragma once
#include <Arduino.h>

#include "protocol/messages.h"

// Owns the MAX98357A (I2S0) through ESP32-audioI2S on a dedicated FreeRTOS task,
// so LVGL redraws never starve the decoder.
//
// playPayment() streams announceUrl (full-sentence announcement, any language) or, if that
// fails, plays /clips/<lang>/<token>.wav for every announce token; then the ad
// (/ads/<hash>.mp3 if cached, otherwise streamed from its URL). When the ad ends a
// PlayAck is queued for the main loop to send as play_ack.
namespace audio_player {

struct PlayAck {
  String playId;
  uint32_t ms = 0;
  bool hasLevels = false;  // false -> peakDb/rmsDb are sent as null
  float peakDb = 0;
  float rmsDb = 0;
};

void begin();

// Interrupts anything that is playing (an interrupted ad still gets its ack).
void playPayment(const SuccessMsg& msg);
void stop();

bool busy();
bool pollAck(PlayAck& out);

}  // namespace audio_player

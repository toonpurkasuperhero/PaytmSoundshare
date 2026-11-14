#pragma once
// INMP441 proof-of-play level meter on I2S port 1. Compiled to no-ops without -DHAS_MIC.
namespace mic {

struct Levels {
  bool valid = false;   // false when there is no mic or no samples were captured
  float peakDb = -120;  // dBFS
  float rmsDb = -120;   // dBFS
};

void begin();
void startMeasuring();
Levels stopMeasuring();

}  // namespace mic

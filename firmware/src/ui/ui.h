#pragma once
#include <Arduino.h>

#include <vector>

#include "protocol/messages.h"

// LVGL screen state machine. All functions must be called from the Arduino loop task.
//
//   Boot -> (Setup portal) -> Idle -> Bill -> Split -> Pay (per leg, leg_paid toast)
//        -> Success (auto-return to Idle after 20 s) | Failed | Cancelled
namespace ui {

enum class Screen { None, Boot, Setup, Idle, Bill, Split, Pay, Success, Failed, Cancelled };

void begin();
Screen current();

// Status / data that persists across screens
void setConnectionState(bool wifiUp, bool serverUp);
void setMerchant(const String& name);
void setDeviceInfo(const String& deviceId, const String& host, uint16_t port);
void setIdleBanners(const std::vector<Banner>& banners);

// Screens
void showBoot(const char* message);
void showSetupPortal(const char* apName);
void showIdle();
void showBill(const BillMsg& m);
void showSplit(const SplitMsg& m);
void showQr(const QrMsg& m);
void showLegPaid(const LegPaidMsg& m);  // toast over the current screen
void showSuccess(const SuccessMsg& m);
void showFailed(const FailedMsg& m);
void showCancelled(const String& orderId);

}  // namespace ui

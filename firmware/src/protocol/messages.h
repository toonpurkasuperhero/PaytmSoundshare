#pragma once
// Plain C++ views of the server -> device messages (docs/API_CONTRACT.md section 2).
// All money fields are integer paise.
#include <Arduino.h>
#include <stdint.h>

#include <vector>

struct Banner {
  String title;
  String subtitle;
  String cta;
  String bg = "#0B1F3A";
  String fg = "#FFFFFF";
  String accent = "#00E5A8";
};

struct BillItem {
  String name;
  int32_t qty = 1;
  int64_t amount = 0;
};

struct BillMsg {
  String orderId;
  std::vector<BillItem> items;
  int64_t total = 0;
};

struct SplitLeg {
  int seq = 0;
  String label;
  int64_t amount = 0;
};

struct SplitMsg {
  String orderId;
  int64_t total = 0;
  std::vector<SplitLeg> legs;
  String note;
};

struct QrMsg {
  String orderId;
  String legId;
  int seq = 1;
  int of = 1;
  String qrData;
  int64_t amount = 0;
  int64_t expiresAt = 0;  // epoch seconds, 0 = unknown
};

struct LegPaidMsg {
  String orderId;
  String legId;
  int seq = 1;
  int of = 1;
  int64_t amount = 0;
  String rail;
};

struct Sponsor {
  String name;
  int64_t amount = 0;
};

struct Settlement {
  bool present = false;
  int64_t mdr = 0;
  int64_t merchantReceives = 0;
  float coveragePct = 0.0f;
  std::vector<Sponsor> coveredBy;
};

struct AdInfo {
  bool present = false;
  String hash;
  String url;
  uint32_t durationMs = 0;
  String advertiser;
};

struct SuccessMsg {
  String orderId;
  int64_t amount = 0;
  String lang = "en";
  std::vector<String> announce;  // local clip tokens: offline fallback
  String announceText;
  String announceUrl;            // full-sentence announcement (any language); preferred when present
  String playId;
  AdInfo ad;
  bool hasBanner = false;
  Banner banner;
  String offerQr;  // empty when null
  Settlement settlement;
};

struct FailedMsg {
  String orderId;
  String legId;
  String reason;
};

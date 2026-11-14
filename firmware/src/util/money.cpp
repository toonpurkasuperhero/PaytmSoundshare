#include "money.h"

#include "app_config.h"

namespace money {

String groupIndian(uint64_t rupees) {
  char digits[24];
  snprintf(digits, sizeof(digits), "%llu", static_cast<unsigned long long>(rupees));
  const int n = strlen(digits);
  if (n <= 3) return String(digits);

  // Last three digits form one group, every group before that has two digits.
  char out[40];
  int o = 0;
  const int head = n - 3;  // digits before the final group of 3
  for (int i = 0; i < head; ++i) {
    out[o++] = digits[i];
    const int remaining = head - 1 - i;  // digits left in the head after this one
    if (remaining > 0 && remaining % 2 == 0) out[o++] = ',';
  }
  out[o++] = ',';
  for (int i = head; i < n; ++i) out[o++] = digits[i];
  out[o] = '\0';
  return String(out);
}

String formatPaise(int64_t paise, bool alwaysPaise) {
  const bool negative = paise < 0;
  const uint64_t abs = negative ? static_cast<uint64_t>(-paise) : static_cast<uint64_t>(paise);
  const uint64_t rupees = abs / 100;
  const unsigned frac = static_cast<unsigned>(abs % 100);

  String s;
  if (negative) s += '-';
  s += CURRENCY_PREFIX;
  s += groupIndian(rupees);
  if (frac != 0 || alwaysPaise) {
    char buf[5];
    snprintf(buf, sizeof(buf), ".%02u", frac);
    s += buf;
  }
  return s;
}

}  // namespace money

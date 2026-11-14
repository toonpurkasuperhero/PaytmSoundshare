#pragma once
#include <Arduino.h>
#include <stdint.h>

namespace money {

// Formats integer paise with Indian digit grouping and the currency prefix.
//   650000  -> "Rs.6,500"        (paise part dropped when it is zero)
//   9983    -> "Rs.99.83"
//   65000000000 -> "Rs.65,00,00,000"
// alwaysPaise=true forces the ".00" suffix.
String formatPaise(int64_t paise, bool alwaysPaise = false);

// Indian-grouped integer without prefix: 1234567 -> "12,34,567".
String groupIndian(uint64_t rupees);

}  // namespace money

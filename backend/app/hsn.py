"""Keyword HSN/SAC lookup: the FALLBACK classifier, used only when the Gemini
classification call fails. The primary path is factorizer.classify (AI)."""
from __future__ import annotations

# (keywords, code, category)
_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("warranty", "extended warranty", "protection plan"), "9987", "services"),
    (("installation", "install", "repair", "service charge", "servicing"), "9987", "services"),
    (("delivery", "shipping", "courier"), "9968", "services"),
    (("consultation", "checkup", "cleaning", "dental"), "9993", "services"),
    (("membership", "subscription", "gym"), "9996", "services"),
    (("mixer", "grinder", "juicer", "blender"), "8509", "appliance"),
    (("fan",), "8414", "appliance"),
    (("induction", "cooktop", "oven", "microwave", "kettle", "toaster", "iron"), "8516", "appliance"),
    (("bulb", "led", "tubelight", "lamp"), "8539", "lighting"),
    (("cable", "wire", "charger", "adapter"), "8544", "electronics"),
    (("phone", "mobile", "smartphone"), "8517", "electronics"),
    (("tv", "television", "speaker", "headphone", "earphone"), "8528", "electronics"),
    (("refrigerator", "fridge"), "8418", "appliance"),
    (("washing machine",), "8450", "appliance"),
    (("cake", "bread", "pastry", "cookie", "biscuit"), "1905", "bakery"),
    (("milk", "curd", "paneer"), "0401", "grocery"),
    (("rice", "atta", "flour", "dal"), "1006", "grocery"),
]

KNOWN_BRANDS = ["havells", "philips", "bajaj", "prestige", "usha", "crompton", "lg", "samsung",
                "sony", "boat", "orient", "pigeon", "butterfly", "syska", "wipro"]


def is_service_code(code: str | None) -> bool:
    return bool(code) and code.strip().startswith("99")


def classify(name: str) -> tuple[str, str]:
    """Return (hsn_sac, category) for an item name."""
    n = name.lower()
    for keys, code, cat in _RULES:
        if any(k in n for k in keys):
            return code, cat
    return "9999" if "service" in n else "8543", "general"


def detect_brand(name: str) -> str | None:
    n = name.lower()
    for b in KNOWN_BRANDS:
        if b in n.split() or n.startswith(b + " ") or f" {b} " in f" {n} ":
            return b
    return None

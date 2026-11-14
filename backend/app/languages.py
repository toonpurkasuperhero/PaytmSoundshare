"""Languages supported for ads and payment announcements (Sarvam Bulbul's 11)."""
from __future__ import annotations

LANGS: dict[str, dict] = {
    "en": {"name": "English", "native": "English", "bcp47": "en-IN", "script": "Latin"},
    "hi": {"name": "Hindi", "native": "हिन्दी", "bcp47": "hi-IN", "script": "Devanagari"},
    "bn": {"name": "Bengali", "native": "বাংলা", "bcp47": "bn-IN", "script": "Bengali"},
    "ta": {"name": "Tamil", "native": "தமிழ்", "bcp47": "ta-IN", "script": "Tamil"},
    "te": {"name": "Telugu", "native": "తెలుగు", "bcp47": "te-IN", "script": "Telugu"},
    "kn": {"name": "Kannada", "native": "ಕನ್ನಡ", "bcp47": "kn-IN", "script": "Kannada"},
    "ml": {"name": "Malayalam", "native": "മലയാളം", "bcp47": "ml-IN", "script": "Malayalam"},
    "mr": {"name": "Marathi", "native": "मराठी", "bcp47": "mr-IN", "script": "Devanagari"},
    "gu": {"name": "Gujarati", "native": "ગુજરાતી", "bcp47": "gu-IN", "script": "Gujarati"},
    "pa": {"name": "Punjabi", "native": "ਪੰਜਾਬੀ", "bcp47": "pa-IN", "script": "Gurmukhi"},
    "od": {"name": "Odia", "native": "ଓଡ଼ିଆ", "bcp47": "od-IN", "script": "Odia"},
}
CODES = list(LANGS)
PATTERN = "^(" + "|".join(CODES) + ")$"


def bcp47(code: str) -> str:
    return LANGS.get(code, LANGS["en"])["bcp47"]


def describe(code: str) -> str:
    """For prompts: 'Tamil (Tamil script)', 'Indian English'."""
    if code == "en" or code not in LANGS:
        return "Indian English"
    l = LANGS[code]
    return f"{l['name']} in {l['script']} script"


def public() -> list[dict]:
    return [{"code": c, "name": v["name"], "native": v["native"]} for c, v in LANGS.items()]

"""Runtime settings, loaded from environment / backend/.env."""
from __future__ import annotations

import socket
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
MEDIA_DIR = BACKEND_DIR / "media"
AUDIO_DIR = MEDIA_DIR / "audio"
SIM_DIR = BACKEND_DIR / "sim"
CONFIG_DIR = BACKEND_DIR / "config"
WEB_DIST_DIR = BACKEND_DIR.parent / "web" / "dist"


def _detect_lan_ip() -> str:
    """Best-effort LAN IP so ESP32 devices can reach media URLs."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packets are sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_DIR / ".env"), extra="ignore")

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'zeromdr.db').as_posix()}"
    public_base_url: str = ""
    port: int = 8000

    # Accounts
    admin_phone: str = ""
    admin_password: str = ""
    session_ttl_days: int = 30

    # Payments
    payment_provider: str = "mock"  # mock (test mode) | paytm | razorpay

    paytm_mid: str = ""
    paytm_merchant_key: str = ""
    paytm_base_url: str = "https://securegw-stage.paytm.in"
    paytm_client_id: str = "C11"
    paytm_store_id: str = "STORE1"

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_mode: str = "payment_link"  # payment_link | upi_qr

    # AI (Google Gemini): primary path for ad copy, voice, bill parsing and division
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    # Other Gemini models tried (in order) when the main one is out of quota / overloaded
    gemini_fallback_models: str = "gemini-3.5-flash-lite"
    gemini_tts_model: str = "gemini-3.8-flash-lite-tts"
    gemini_tts_voice: str = "Kore"
    gemini_timeout_s: float = 30.0
    # Voice fallback used ONLY when the AI voices fail: edge | none
    tts_fallback: str = "edge"

    # Sarvam AI: Indian-language voices (11 languages) + translation
    sarvam_api_key: str = ""
    sarvam_announce_model: str = "bulbul:v3"
    sarvam_announce_speaker: str = "priya"
    sarvam_announce_pace: float = 1.1
    sarvam_ad_model: str = "bulbul:v3"       # en/hi ads use bulbul:v4-flash "ads" personas
    sarvam_ad_speaker: str = "priya"
    # Which AI voices ads first: sarvam | gemini (the other one is the AI backup)
    ad_voice_primary: str = "sarvam"

    # Share of a sale's ad surplus (ad money beyond that sale's MDR) kept by the platform. The rest
    # pays the merchant's own Soundbox rental for the month, then goes to the shared SoundShare pool.
    platform_surplus_take_pct: float = 25.0
    # Max a single merchant can draw from the shared pool per day (so no one shop drains it).
    shared_pool_daily_cap_paise: int = 50000
    # The shared pool pays other merchants' rentals only above this balance (fees come first).
    shared_pool_fee_reserve_paise: int = 50000

    poll_interval_s: float = 3.0
    play_ack_timeout_s: float = 15.0
    qr_expiry_min: int = 10

    @property
    def base_url(self) -> str:
        if self.public_base_url:
            return self.public_base_url.rstrip("/")
        return f"http://{_detect_lan_ip()}:{self.port}"

    @property
    def provider_mode(self) -> str:
        if self.payment_provider == "mock":
            return "test"
        if self.payment_provider == "razorpay":
            return "test" if self.razorpay_key_id.startswith("rzp_test_") else "live"
        if self.payment_provider == "paytm":
            return "test" if "stage" in self.paytm_base_url else "live"
        return "test"


settings = Settings()

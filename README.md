# Paytm SoundShare

**Team Yottaminds · Track 1 (Merchant Growth AI)**

Small merchants pay a monthly rental for their Paytm Soundbox, but it sits idle between "payment received" messages. SoundShare turns it into an income source. The customer pays the full bill with one QR, with no fee and no price split. As soon as the payment message plays, the Soundbox plays a short AI-generated ad from a nearby business. Advertisers pay only for verified plays on paid bills. That money first pays the merchant's Soundbox rental for the month, and everything after that is the merchant's own earnings, shown on a live earnings tracker.

Advertisers write a one-line brief in English (or speak it). AI writes the ad in any of 11 Indian languages, voices it with Sarvam or Gemini, and designs the counter-screen banner. Payment announcements play in the merchant's own language.

## How a sale works

1. The merchant builds the bill (catalog taps, typed rows, pasted text or a photo) and presses **Create bill & show QR**.
2. The Soundbox shows the QR for the **full amount**.
3. The customer pays. The Soundbox announces the payment, then plays the ad.
4. **Busy hour** (a switch on the merchant page): no full ad. Only a one-second "Sponsored by …" line plays after the payment message, priced lower than a full ad (75% by default).
5. The advertiser is charged only if the bill was paid **and** the Soundbox confirmed the ad played (at least 80% of it). Self-payments earn no ad money.

## Where the ad money goes

For every paid bill with a verified ad:

1. **Paytm's share:** 25% (`PLATFORM_SURPLUS_TAKE_PCT`).
2. **Soundbox rental:** the rest pays this merchant's rental for the month (₹125 by default) until it is fully paid.
3. **Merchant earnings:** everything after that goes to the merchant.

The merchant's **Earnings** tab shows today / 7 days / month / lifetime earnings, how much of this month's rental ads have paid (and how many more plays clear it), a 30-day chart, earnings by advertiser, and per-bill detail. All of it comes from the double-entry ledger (`merchant_earnings:<id>`, `soundbox_rental`).

## Advertiser trust

- GSTIN is mandatory at sign-up (format and check digit are validated).
- Ads go live only after admin KYC approval **and** a ₹200 minimum wallet deposit.
- AI rejects health-cure claims, guaranteed returns and copy that sounds like a payment confirmation.

```
backend/    FastAPI: accounts, payments (Paytm / Razorpay / test mode), ad exchange, metering,
            earnings waterfall, double-entry ledger, AI creatives, KYC, device WebSocket hub
web/        React + Tailwind app (Stitch designs): /merchant, /advertiser, /admin
firmware/   ESP32-S3 Soundbox: TFT + LVGL QR screens, I2S audio, optional mic proof-of-play
backend/sim Browser Soundbox simulator (same protocol as the ESP32)
tools/      gen_clips.py: amount-announcement voice clips for the device
docs/       API_CONTRACT.md: REST + device protocol
```

## How AI is used

AI is the **primary path**. Fallbacks run **only when every AI call fails**, and each result records which path produced it (shown in the UI as an "AI" or "Fallback: reason" badge).

| Feature | Primary (AI) | Fallback, only on AI failure |
|---|---|---|
| Ad copy, translation and compliance check | Gemini writes the script in the chosen language from an English (or spoken) brief, plus the banner | Template from the brief, translated to the ad language by Sarvam |
| Ad voice-over | Sarvam `bulbul` voices (11 languages), then Gemini TTS | Microsoft Edge neural voice (`TTS_FALLBACK=edge`) |
| Payment announcement | Sarvam, in the merchant's language | Pre-recorded clips |
| Voice-note brief | Gemini transcription | Browser speech recognition |
| Bill text / photo → items | Gemini extraction | Regex parser (text only; photos need AI) |

## Setup (Windows, no Docker needed)

```powershell
# Backend
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # then fill in GEMINI_API_KEY, SARVAM_API_KEY, ADMIN_PHONE, ADMIN_PASSWORD, PUBLIC_BASE_URL
.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Web app (served by the backend at http://localhost:8000 once built)
cd ..\web
npm install
npm run build               # or `npm run dev` on :5173 (proxies to :8000)
```

Accounts:

1. **Admin:** created on start-up from `ADMIN_PHONE` / `ADMIN_PASSWORD`, or with `.\.venv\Scripts\python -m app.cli create-admin --phone 98XXXXXXXX`.
2. **Merchants** sign up at `/register` (business name, GSTIN, UPI ID, location), add their catalog and pair a Soundbox under **Soundboxes**. Pairing gives a device ID, a token (shown once) and a simulator link.
3. **Advertisers** sign up at `/register` with their GSTIN, deposit at least ₹200, wait for KYC approval, and create ads.
4. **Demo accounts** (optional): `python -m app.cli seed-demo`; remove them with `python -m app.cli remove-demo`.

| URL | Who |
|---|---|
| http://localhost:8000/login | Everyone |
| /merchant | Terminal (bill → QR + ad on the Soundbox), orders, catalog, Soundboxes, **Earnings**, busy-hour switch |
| /advertiser | Create an ad in 30 s (type in English or hold to talk), wallet, geofence, campaigns |
| /admin | Money-flow Sankey, ledger, KYC queue, Sentinel flags, system and AI health |
| /docs | OpenAPI |

## Payments

Set `PAYMENT_PROVIDER` in `backend/.env`:

| Value | Use |
|---|---|
| `mock` | **Test mode.** No real money moves. Every screen says so, and payments are simulated from the merchant terminal or the paired simulator. |
| `paytm` | Paytm PG Dynamic QR. Needs `PAYTM_MID`, `PAYTM_MERCHANT_KEY`, and Dynamic QR enabled on the MID. |
| `razorpay` | Needs `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET`. `RAZORPAY_MODE=payment_link` (default) works with `rzp_test_` keys; pay with UPI ID `success@razorpay`. |

Payment status is polled every 3 s. For webhooks, expose port 8000 (e.g. with `cloudflared tunnel --url http://localhost:8000`) and register `/api/webhooks/razorpay` or `/api/webhooks/paytm`.

**Keys live only in `backend/.env` (git-ignored). Never on the device, never in the web app.**

## ESP32 Soundbox

See [firmware/README.md](firmware/README.md) for wiring and flashing.

1. Set `PUBLIC_BASE_URL=http://<laptop-LAN-IP>:8000` in `backend/.env`.
2. Pair the device in **Merchant → Soundboxes**.
3. Enter the host, port, device ID and token it shows into the device's `SoundShare-XXXX` Wi-Fi setup portal.

The laptop and the ESP32 must be on the same network, with port 8000 allowed through the firewall.

## Tests

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q
```

The tests replace Gemini and Sarvam with deterministic fakes. They cover:
- one full-price QR per bill and the ad → payment message order on the device;
- the earnings waterfall (Paytm share → rental → merchant earnings) and the earnings tracker;
- an English brief becoming a Hindi ad, even when Gemini is down;
- a full AI outage, where each fallback must report its reason;
- busy-hour sponsor lines, unverified plays released without charge, and self-payments earning nothing;
- advertiser GSTIN, KYC and deposit gates, auth and ownership, and test-mode payment permissions.

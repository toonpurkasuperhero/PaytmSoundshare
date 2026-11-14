# Paytm SoundShare

**Team Yottaminds · Track 1 (Merchant Growth AI)**

Paytm Soundboxes and QR displays play short AI-generated local ads after each payment, announced in the merchant's language. The ad money, plus brand sponsorship bids, pays merchants' payment fees (MDR) and Soundbox rentals. Busy small vendors earn more ad money than they need, and they share the surplus with nearby shops whose big-ticket sales carry fees. The acquirer always gets its full MDR. AI also splits each bill into legal GST invoices (goods vs services), so less MDR is charged in the first place.

## Where the ad money goes

For every settled sale:

1. **This sale's fee.** The sale's own ad and sponsor money pays its MDR first.
2. **Shortfall.** Any fee left uncovered is paid from the **SoundShare pool**, up to ₹500 per merchant per day so one shop can't drain it.
3. **Surplus.** Money left after the fee goes, in order:
   - Paytm's cut (25%);
   - this merchant's own **Soundbox rental** for the month (₹125);
   - everything else to the **SoundShare pool**.
4. **Pool beyond fees.** The pool also pays other merchants' unpaid rentals, but only above a ₹500 reserve kept for fees.

Each merchant's Savings page shows their rental paid by ads, what they gave to the pool, and what the pool paid for them. The limits are set in `backend/.env` (`PLATFORM_SURPLUS_TAKE_PCT`, `SHARED_POOL_DAILY_CAP_PAISE`, `SHARED_POOL_FEE_RESERVE_PAISE`).

```
backend/    FastAPI: accounts, payments (Paytm / Razorpay / test mode), MDR engine, AI factorizer,
            Sentinel, ad exchange, metering, double-entry ledger, AI creatives, device WebSocket hub
web/        React + Tailwind app (Stitch designs): /merchant, /advertiser, /admin
firmware/   ESP32-S3 Soundbox: TFT + LVGL QR screens, I2S audio, optional mic proof-of-play
backend/sim Browser Soundbox simulator (same protocol as the ESP32)
tools/      gen_clips.py: amount-announcement voice clips for the device
docs/       API_CONTRACT.md: REST + device protocol (v2)
```

## How AI is used

Google Gemini is the **primary path**. Fallbacks run **only when an AI call fails**, and every result records which path produced it (shown in the UI as an "AI" or "Fallback: reason" badge).

| Feature | Primary (Gemini) | Fallback, only on AI failure |
|---|---|---|
| Ad copy and compliance check | `gemini-3.8-flash` writes the script and banner, and rejects health-cure or guaranteed-return claims | Template from the brief |
| Ad voice-over | `gemini-3.8-flash-lite-tts`, then trimmed, normalised and encoded to MP3 for the ESP32 | Microsoft Edge neural voice (`TTS_FALLBACK=edge`) |
| Voice-note brief | Gemini transcription | Browser speech recognition |
| Bill text / photo → items | Gemini extraction | Regex parser (text only; photos need AI) |
| HSN/SAC classification | Gemini | Keyword table |
| Bill division into legs | Gemini proposes legs with reasons. The proposal is accepted only if the Sentinel finds it legal and it costs no more MDR than the boundary split. | Rule engine: one invoice per supplier GSTIN × goods/services |

## Setup (Windows, no Docker needed)

```powershell
# Backend
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # then fill in GEMINI_API_KEY, ADMIN_PHONE, ADMIN_PASSWORD, PUBLIC_BASE_URL
.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Web app (served by the backend at http://localhost:8000 once built)
cd ..\web
npm install
npm run build               # or `npm run dev` on :5173 (proxies to :8000)
```

There is **no seeded data**. Everything is created by real users:

1. **Admin:** created on start-up from `ADMIN_PHONE` / `ADMIN_PASSWORD`, or with `.\.venv\Scripts\python -m app.cli create-admin --phone 98XXXXXXXX`.
2. **Merchants** sign up at `/register`: business name, GSTIN, UPI ID, location. Then they:
   - add their catalog (AI fills in HSN/SAC);
   - pair a Soundbox under **Soundboxes**, which gives a device ID, a token (shown once) and a simulator link.
3. **Advertisers** sign up at `/register` (local business or brand), top up their wallet, and create ads.

| URL | Who |
|---|---|
| http://localhost:8000/login | Everyone |
| /merchant | Merchant terminal: bill → AI split → QR on the Soundbox → settlement |
| /advertiser | Create an ad in 30 s, wallet, geofence, campaigns |
| /admin | Money-flow Sankey, ledger, Sentinel flags, system and AI health |
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

The tests replace Gemini with a deterministic fake. They cover:
- the AI path, an illegal AI split that the Sentinel rejects, and a full AI outage, where each fallback must report its reason;
- AI compliance rejection, drafts, and catalog codes taken from the server;
- the golden ₹6,500 walkthrough: ₹138.06 → ₹99.83 MDR, merchant ₹6,500, acquirer ₹99.83, Paytm ₹6.37, ledger Σ = 0;
- auth and ownership, structuring blocks, self-dealing, and test-mode payment permissions.

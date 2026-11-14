# SoundShare: API & Device Protocol Contract (v3)

The backend (FastAPI) runs at `http://<host>:8000`. All REST routes are under `/api`.
**Money is always an integer in paise** (₹6,500.00 = `650000`). Timestamps are ISO-8601 with a UTC offset.
Errors use the shape `{"detail": "...", "error": "<code>"?, "reasons": [...]?}`.

**Product rules (v3):**
- **One bill, one QR, full price.** There is no payment fee and no price split. Every order has exactly one leg for the whole amount.
- **The ad plays right after the payment message.** Ad money for a paid bill with a verified play goes: Paytm share (`PLATFORM_SURPLUS_TAKE_PCT`, default 25%), then this merchant's Soundbox rental for the month, then the merchant's earnings.
- **AI is the primary path** for ad creation (Gemini copy, Sarvam/Gemini voices, 11 languages) and bill reading. Deterministic fallbacks run **only when every AI call fails**. Every AI-produced object says which path produced it: `"source": "ai" | "fallback"` plus `"fallback_reason"`.
- Real users sign up themselves; the admin account comes from env vars. Optional demo accounts come from `python -m app.cli seed-demo` and are removed with `remove-demo`.

Payment methods (`rail`, used by the test-mode simulator): `UPI_BANK`, `UPI_RUPAY_CC`, `UPI_PPI`, `DEBIT_CARD`, `CREDIT_CARD`, `NET_BANKING`.

---

## 0. Auth

Phone + password. Send the session token as `Authorization: Bearer <token>`. WebSockets use `?token=` instead.
Roles: `merchant`, `advertiser`, `admin`. Each merchant or advertiser account owns exactly one business profile.

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/auth/register/merchant` | `{phone, password, name, category, gstin, vpa, lat, lng, address?, lang?}` | `201 Session` |
| POST | `/api/auth/register/advertiser` | `{phone, password, name, type:"local"\|"brand", category, gstin, lat?, lng?, address?}` | `201 Session`. GSTIN is mandatory (format + check digit) and unique. |
| POST | `/api/auth/login` | `{phone, password}` | `Session` (`401` on bad credentials, `429` after too many attempts) |
| GET | `/api/auth/me` | – | `User` |
| POST | `/api/auth/logout` | – | `{ok:true}` |

```jsonc
Session = {"token":"<opaque>", "user": User}
User = {"id":"U-..","phone":"9876543210","role":"merchant","name":"Sharma Electronics",
        "merchant_id":"M-..."|null, "advertiser_id":"A-..."|null}
```
- Phone: Indian mobile, 10 digits starting 6–9. A `+91` prefix is accepted and stripped.
- Password: at least 8 characters.
- GSTIN: 15-character format and check-digit validation. VPA: `name@bank` format.

Access: a merchant sees only its own merchant, catalog, devices and orders. An advertiser sees only its own advertiser, campaigns and top-ups. Admin sees everything, plus ledger, sentinel and system data.
`401` = not logged in. `403` = logged in but not allowed.

---

## 1. REST API

### Public
| Method | Path | Returns |
|---|---|---|
| GET | `/api/config` | `{provider, provider_mode:"test"\|"live", rails, base_url, ai:{configured:bool, text_model, tts_model}, sarvam:{configured}, languages:[{code,label,...}]}` |
| GET | `/api/qr.svg?data=&scale=8` | SVG QR |
| GET | `/api/offers/{creative_id}/claim?d=<deviceId>` | HTML page. Records a claim. |
| POST | `/api/webhooks/paytm`, `/api/webhooks/razorpay` | Payment provider webhooks (signature-verified) |

### System (admin)
| GET | `/api/system/status` | `{provider:{name, mode, ok, detail}, ai:{configured, text_model, tts_model, last_ok_at, last_error, last_error_at, calls, failures}, devices:{total, online}, db:"ok"}` |
|---|---|---|

### Merchants
| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/merchants` | admin | – | `Merchant[]` |
| GET | `/api/merchants/{id}` | owner/admin | – | `Merchant` with `stats` |
| PATCH | `/api/merchants/{id}` | owner | `{name?, blocked_categories?, busy_mode?, lang?, vpa?, lat?, lng?, address?}` | `Merchant` |
| GET | `/api/merchants/{id}/earnings?days=30` | owner/admin | – | `EarningsTracker` |
| GET | `/api/merchants/{id}/catalog` | owner/admin | – | `CatalogItem[]` |
| POST | `/api/merchants/{id}/catalog` | owner | `{name, unit_price, hsn_sac?, category?, brand?}` | `201 CatalogItem` (stored as entered, `source:"manual"`) |
| PATCH | `/api/merchants/{id}/catalog/{item_id}` | owner | same fields, all optional | `CatalogItem` |
| DELETE | `/api/merchants/{id}/catalog/{item_id}` | owner | – | `204` |

```jsonc
Merchant = {"id":"M-..","name":"..","category":"electronics","gstin":"..","vpa":"..","lat":..,"lng":..,"address":"..",
  "lang":"en","busy_mode":false,"blocked_categories":[],"device_ids":["SB-.."],
  "stats": {"tx_count":0,"gross_paise":0,"ad_revenue_paise":0,
            "earnings_lifetime_paise":0,"ad_income_per_play_paise":120|null,"platform_share_pct":25.0,
            "rental":{"monthly_fee_paise":12500,"paid_this_month_paise":0,"due_paise":12500,"plays_to_cover":139|null}}}
EarningsTracker = {...Merchant.stats (without tx/gross),
  "totals":{"today_paise","week_paise","month_paise","lifetime_paise",
            "rental_paid_lifetime_paise","ad_revenue_lifetime_paise","plays_month","plays_lifetime"},
  "daily":[{"date":"2026-11-14","earnings_paise","rental_paise","plays"}],      // IST days, oldest first
  "by_advertiser":[{"advertiser_id","name","plays","tags","ad_revenue_paise"}],
  "recent":[{"order_id","settled_at","bill_paise","advertisers":["FitZone Gym"],
             "ad_revenue_paise","rental_paid_paise","earnings_paise"}]}
CatalogItem = {"id":"C-..","name":"..","unit_price":470000,"hsn_sac":"8509","category":"appliance","brand":"havells"|null,
               "supply_type":"goods"|"services","source":"ai"|"fallback"|"manual"}
```

### Bills and orders
| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| POST | `/api/bills/parse` | merchant | `{text}`, or multipart `image` (bill photo: jpeg/png/webp, ≤ 8 MB) | `{items: ItemIn[], source, fallback_reason?, model?}` |
| POST | `/api/orders` | merchant | `{device_id, items: ItemIn[]}` | `201 Order`. One QR for the full total. The ad is reserved now and plays after the payment message. |
| GET | `/api/orders?limit=20` | merchant (own) / admin (all, optional `merchant_id`) | – | `Order[]` |
| GET | `/api/orders/{id}` | owner/admin | – | `Order` |
| POST | `/api/orders/{id}/cancel` | owner | – | `Order` |
| POST | `/api/orders/{id}/refresh` | owner | – | `Order` (polls the provider now) |
| POST | `/api/mock/pay` | merchant owner, or device token | `{leg_id, rail, payer?, device_token?}` | `Order`. **Only when provider is `mock` (test mode)**, otherwise `409`. `rail` is required. |
| GET | `/api/announce/{order_id}.mp3` | device | – | Payment announcement in the merchant's language (Sarvam) |

```jsonc
ItemIn = {"name":"..","qty":1,"unit_price":470000,"hsn_sac":".."?,"category":".."?,"brand":".."?,"catalog_item_id":"C-.."?}
Order = {"id","merchant_id","device_id","status","total_paise","created_at","paid_at","settled_at",
         "items":[...], "legs":[Leg],          // always exactly one leg = the full bill
         "settlement":Settlement|null}
Leg = {"id","seq":1,"of":1,"amount_paise","status":"active"|"paid"|..,"qr_data","qr_image_url","checkout_url","expires_at","rail","paid_at"}
Settlement = {"status":"pending_ack"|"settled",
  "merchant_receives_paise":650000,     // the full bill
  "ad_revenue_paise":120,               // committed ad money for this bill
  "platform_paise":30, "rental_paid_paise":90, "earnings_paise":0,
  "rental_due_after_paise":12410,       // rental still unpaid this month after this bill
  "sponsors":[{"advertiser_id","name","kind":"audio"|"tag","amount_paise","status":"committed"|"released","release_reason"}]}
```
Self-payments (payer VPA = merchant's VPA) earn no ad money. A play is charged only if the bill is paid **and** the play is verified.

### Devices (Soundboxes)
| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/devices` | merchant (own) / admin (all) | – | `Device[]` |
| POST | `/api/devices` | merchant | `{name}` | `201 Device & {token, provisioning:{host, port, device_id, token, sim_url}}`. The token is shown only once. |
| POST | `/api/devices/{id}/rotate-token` | owner | – | same as create |
| DELETE | `/api/devices/{id}` | owner | – | `204` |

`Device = {id:"SB-XXXX", merchant_id, merchant_name, name, online, last_seen, fw, rssi}`

### Advertisers, wallet, campaigns
| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| GET | `/api/advertisers` | admin | – | `Advertiser[]` |
| GET | `/api/advertisers/{id}` | owner/admin | – | `Advertiser` with `wallet` and `stats` |
| PATCH | `/api/advertisers/{id}` | owner | `{name?, category?, gstin?, lat?, lng?, address?}` | `Advertiser`. A changed GSTIN goes back to verification. |
| POST | `/api/advertisers/{id}/topup` | owner | `{amount_paise}` | `TopUp`. With a real provider, show `qr_data`/`checkout_url` and poll. |
| GET | `/api/topups/{id}` | owner/admin | – | `TopUp` |
| GET | `/api/advertisers/{id}/topups` | owner/admin | – | `TopUp[]` |
| POST | `/api/ai/transcribe` | advertiser/merchant | multipart `audio` (webm/ogg/wav/mp3, ≤ 2 MB), `lang` | `{text, source:"ai"}`. `502` if AI fails, and then the client falls back to browser speech recognition. |
| GET | `/api/geo/soundboxes?lat=&lng=&radius_m=` | advertiser/admin | – | `{count, online, soundboxes:[{device_id, merchant_name, category, lat, lng, distance_m, online}]}` |
| GET | `/api/campaigns` | advertiser (own) / admin (all) | – | `Campaign[]` |
| POST | `/api/campaigns` | advertiser | `CampaignCreate` | `201 Campaign` (`status:"generating"`). AI writes the copy in `lang` (the brief may be English or any language) and voices it. Goes live only once KYC is verified and ₹200 is deposited. |
| GET | `/api/campaigns/{id}` | owner/admin | – | `Campaign` |
| PATCH | `/api/campaigns/{id}` | owner | `{status?:"active"\|"paused", bid_paise?, daily_cap_paise?, radius_m?, lat?, lng?, name?}` | `Campaign`. Setting `active` on a draft deploys it. |
| POST | `/api/campaigns/{id}/regenerate` | owner | `{prompt?, lang?}` | `Campaign` |

```jsonc
Advertiser = {"id":"A-..","name":"FitZone Gym","type":"local","category":"fitness","lat":..,"lng":..,"address":"..",
  "balance_paise":29880,                      // available = ledger balance minus reserved holds
  "wallet":{"balance_paise":29880,"reserved_paise":0,"spent_today_paise":120,"daily_cap_total_paise":5000,
            "burn_per_play_paise":120|null,   // average committed audio charge
            "est_plays_remaining":249|null,   // balance ÷ weighted active bid
            "lifetime_topup_paise":30000,"lifetime_spend_paise":120},
  "gstin":"..","kyc":{"status":"pending"|"verified"|"rejected","note","method","verified_at",
                      "deposit_paise","min_deposit_paise":20000,"blockers":[".."],"can_go_live":false},
  "stats":{"plays":1,"spend_paise":120,"claims":0,"tag_plays":0,"released_plays":0}}
CampaignCreate = {"kind":"audio","name":"3-day promo",
  "prompt":"20% off all mixer grinders this week",   // brief, typically English
  "lang":"hi",                                       // ad language: en hi bn ta te kn ml mr gu pa or
  "lat":..?,"lng":..?,"radius_m":500,"target_categories":[],
  "bid_paise":120,                                   // full ad, per verified play
  "tag_bid_paise":90?,                               // busy-hour sponsor line; must be < bid; default 75%
  "daily_cap_paise":5000,"deploy":true}              // deploy:false = Save Draft
Campaign = {...CampaignCreate, "id":"CMP-..","advertiser_id","advertiser_name",
  "status":"generating"|"draft"|"active"|"paused"|"failed"|"exhausted", "error":null|"..",
  "creative": null | {"id","lang","script","banner":{title,subtitle,cta,bg,fg,accent},
     "audio_url","audio_hash","duration_ms","offer_url",
     "source":"ai"|"fallback","fallback_reason":null|"..",           // copywriting path
     "voice_source":"ai"|"fallback"|null,"voice_fallback_reason":null|"..",
     "model":"gemini-3.8-flash","voice":"Kore"},
  "stats":{"plays":0,"tag_plays":0,"spend_paise":0,"spent_today_paise":0,"claims":0}}
```

### Ledger, sentinel, admin (admin only)
| Method | Path | Returns |
|---|---|---|
| GET | `/api/ledger/balances` | `[{account,label,balance_paise}]` plus `invariant_paise` (sum, must be 0) via `/api/admin/stats` |
| GET | `/api/ledger/entries?ref=&limit=` | `[{txn_id,ref,memo,account,label,amount_paise,ts}]` |
| GET | `/api/ledger/flows?order_id=` | `{nodes:[{id,label}],links:[{source,target,amount_paise}]}` |
| GET | `/api/sentinel/flags?limit=` | `[{id,ref,rule,severity,action,detail,ts}]` |
| GET | `/api/admin/stats` | see below |
| GET | `/api/admin/kyc?status=pending\|verified\|rejected\|all` | `Advertiser[]` awaiting or past verification |
| POST | `/api/admin/advertisers/{id}/kyc` | `{action:"approve"\|"reject", note?}` → `Advertiser` |

```jsonc
AdminStats = {"orders":n,"settled_orders":n,"gross_paise":..,"avg_ticket_paise":..,
  "ad_revenue_paise":..,"merchant_earnings_paise":..,"rental_paid_by_ads_paise":..,"platform_paise":..,
  "plays":n,"tag_plays":n,"plays_released":n,"play_verification_pct":100.0,
  "devices_total":n,"devices_online":n,"merchants":n,"advertisers":n,
  "ledger_invariant_paise":0,
  "latency":{"p50_ms","p95_ms","last_ms","samples"}}
Ledger accounts: customer, merchant:<id>, merchant_earnings:<id>, soundbox_rental, adv:<id>,
  sponsor_pool (per-bill clearing), platform, funding.
```

### WebSocket `/ws/admin?token=<admin session token>`
Events: `{type:"order_update"|"ledger_post"|"device_status"|"play_ack"|"sentinel_flag"|"campaign_update"|"topup"|"offer_claim"|"device_msg", ...}`. Treat these as refresh signals.

---

## 2. Device WebSocket protocol (ESP32 + browser simulator)

Device ids and tokens come from `POST /api/devices` (e.g. `SB-7F3A`). One live connection per device: a new connection gets the device and the old one receives `replaced`. Connect to `ws://<host>:8000/ws/device/{deviceId}?token=<token>`.

Every frame is one JSON text message with a `type` field. The server sends `ping` every 20 s, and the device answers `pong`.
Times are epoch **seconds**. Media URLs are **http**. Banner text is ASCII.

### Server → device
```jsonc
{"type":"hello_ack","deviceId":"SB-7F3A","merchant":{"id":"M-..","name":"Sharma Electronics","lang":"en"},"serverTime":1731400000}
{"type":"idle","banners":[Banner,...]}
{"type":"show_bill","orderId":"O-1","items":[{"name":"Havells Mixer Grinder","qty":1,"amount":470000}],"total":650000}
{"type":"show_qr","orderId":"O-1","legId":"L-1","seq":1,"of":1,"qrData":"upi://pay?...","amount":650000,"expiresAt":1731400600}
{"type":"payment_success","orderId":"O-1","amount":650000,"lang":"en",
 "announce":["n6","thousand","n5","hundred","rupees","received"],"announceText":"Six thousand five hundred rupees received",
 "announceUrl":null|"http://host:8000/api/announce/O-1.mp3",   // play this instead of clips when present
 "playId":"P-2"|null,"ad":null|{"kind":"ad"|"tag","hash":"<sha1>","url":"...","durationMs":3500,"advertiser":"FitZone Gym"},
   // played right AFTER the announcement, then play_ack. Normal hours: kind "ad" (full ad, Campaign.bid_paise).
   // Busy hour (merchant busy_mode): kind "tag" (about 1 s "Sponsored by ...", Campaign.tag_bid_paise, default 75%).
 "banner":null|Banner,"offerQr":null|"http://host:8000/api/offers/CR-1/claim?d=SB-7F3A",
 "settlement":null}
{"type":"payment_failed","orderId":"O-1","legId":"L-1","reason":"expired"}
{"type":"cancelled","orderId":"O-1"}
{"type":"cache_audio","hash":"<sha1>","url":"http://host:8000/media/audio/<sha1>.mp3"}
{"type":"ping"}

Banner = {"title":"FitZone Gym","subtitle":"1 month FREE on annual plan","cta":"Scan to claim",
          "bg":"#0B1F3A","fg":"#FFFFFF","accent":"#00E5A8"}
```

### Device → server
```jsonc
{"type":"hello","fw":"0.1.0","cache":["<sha1>",...]}
{"type":"heartbeat","fw":"0.1.0","rssi":-61,"heap":123456}
{"type":"play_ack","playId":"P-1","ms":2400,"peakDb":-12.3,"rmsDb":-24.1}   // peakDb null without a mic; ms 0 if the ad could not play
{"type":"cache_ok","hash":"<sha1>"}                                          // may be unsolicited
{"type":"pong"}
```
A play is verified when `ms >= 0.8 * durationMs` and (`peakDb` is null or `peakDb > -50 dB`). If no `play_ack` arrives within 15 s, the reservation is released.

## 3. Announcement clip tokens
`announce` is a list of clip tokens played back to back from `/clips/<lang>/<token>.wav`. Clips are WAV, because MP3 padding makes stitched clips gappy; `.mp3` is accepted as a fallback.
- English: `chime` · `pre` ("Received") · amount · `rupees` · `received` ("on Paytm").
- Hindi: `chime` · `pre` ("पेटीएम पर") · amount · `rupees` ("रुपये") · `received` ("प्राप्त हुए").
- Amount tokens: `n0`…`n99`, `hundred`, `thousand`, `lakh`, `crore`, in Indian grouping. A zero group is skipped and paise are ignored.

`tools/gen_clips.py` creates the clips into `backend/media/clips/` (used by the simulator) and `firmware/data/clips/` (flashed to the device with `pio run -t uploadfs`).
Media URLs sent to a device use the host and port that device connected on.

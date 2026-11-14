# SoundShare: API & Device Protocol Contract (v2)

The backend (FastAPI) runs at `http://<host>:8000`. All REST routes are under `/api`.
**Money is always an integer in paise** (₹6,500.00 = `650000`). Timestamps are ISO-8601 with a UTC offset.
Errors use the shape `{"detail": "...", "error": "<code>"?, "reasons": [...]?}`.

**Product rules (v2):**
- **There is no seeded or demo data.** Merchants and advertisers sign up themselves, and the admin account comes from env vars.
- **AI is the primary path** for ad creation and bill division, using Google Gemini. Deterministic fallbacks run **only when the AI call fails**. Every AI-produced object says which path produced it: `"source": "ai" | "fallback"` plus `"fallback_reason"`.

Rails: `UPI_BANK`, `UPI_RUPAY_CC`, `UPI_PPI`, `DEBIT_CARD`, `CREDIT_CARD`, `NET_BANKING`, `UNKNOWN`.

---

## 0. Auth

Phone + password. Send the session token as `Authorization: Bearer <token>`. WebSockets use `?token=` instead.
Roles: `merchant`, `advertiser`, `admin`. Each merchant or advertiser account owns exactly one business profile.

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/auth/register/merchant` | `{phone, password, name, category, gstin, vpa, lat, lng, address?, lang?}` | `201 Session` |
| POST | `/api/auth/register/advertiser` | `{phone, password, name, type:"local"\|"brand", category, lat?, lng?, address?}` | `201 Session` |
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
- GSTIN: 15-character format check. VPA: `name@bank` format.

Access: a merchant sees only its own merchant, catalog, devices and orders. An advertiser sees only its own advertiser, campaigns and top-ups. Admin sees everything, plus ledger, sentinel and system data.
`401` = not logged in. `403` = logged in but not allowed.

---

## 1. REST API

### Public
| Method | Path | Returns |
|---|---|---|
| GET | `/api/config` | `{provider, provider_mode:"test"\|"live", rails, mdr_rates, gst_rate, base_url, ai:{configured:bool, text_model, tts_model}}` |
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
| PATCH | `/api/merchants/{id}` | owner | `{name?, blocked_categories?, factorization_enabled?, lang?, vpa?, lat?, lng?, address?}` | `Merchant` |
| GET | `/api/merchants/{id}/catalog` | owner/admin | – | `CatalogItem[]` |
| POST | `/api/merchants/{id}/catalog` | owner | `{name, unit_price, hsn_sac?, category?, brand?}` | `201 CatalogItem`. **AI classifies** HSN/SAC, category and brand when they're missing. |
| PATCH | `/api/merchants/{id}/catalog/{item_id}` | owner | same fields, all optional | `CatalogItem` |
| DELETE | `/api/merchants/{id}/catalog/{item_id}` | owner | – | `204` |

```jsonc
Merchant = {"id":"M-..","name":"..","category":"electronics","gstin":"..","vpa":"..","lat":..,"lng":..,"address":"..",
  "lang":"en","factorization_enabled":true,"blocked_categories":[],"device_ids":["SB-.."],
  "stats": {"tx_count":0,"gross_paise":0,"mdr_paise":0,"covered_paise":0,"coverage_pct":100.0,
            "saved_by_factorization_paise":0,
            "rental":{"monthly_fee_paise":12500,"credited_paise":0,"target_tx":100,"sponsored_tx":0}}}
CatalogItem = {"id":"C-..","name":"..","unit_price":470000,"hsn_sac":"8509","category":"appliance","brand":"havells"|null,
               "supply_type":"goods"|"services","source":"ai"|"fallback"|"manual"}
```

### Bills: AI parse, AI division, orders
| Method | Path | Who | Body | Returns |
|---|---|---|---|---|
| POST | `/api/bills/parse` | merchant | `{text}`, or multipart `image` (bill photo: jpeg/png/webp, ≤ 8 MB) | `{items: ItemIn[], source, fallback_reason?, model?}` |
| POST | `/api/bills/plan` | merchant | `{items: ItemIn[], factorize?:bool}` | `Plan`: AI classifies every item and proposes the split. The Sentinel validates it. |
| POST | `/api/orders` | merchant | `OrderCreate` | `201 Order`, or `422 {error:"sentinel_blocked", reasons}` |
| GET | `/api/orders?limit=20` | merchant (own) / admin (all, optional `merchant_id`) | – | `Order[]` |
| GET | `/api/orders/{id}` | owner/admin | – | `Order` |
| POST | `/api/orders/{id}/cancel` | owner | – | `Order` |
| POST | `/api/orders/{id}/refresh` | owner | – | `Order` (polls the provider now) |
| POST | `/api/mock/pay` | merchant owner, or device token | `{leg_id, rail, payer?, device_token?}` | `Order`. **Only when provider is `mock` (test mode)**, otherwise `409`. |

```jsonc
ItemIn = {"name":"..","qty":1,"unit_price":470000,"hsn_sac":"8509"?,"category":".."?,"brand":".."?,
          "supplier_gstin":".."?,"catalog_item_id":"C-.."?}
Plan = {
  "items":[ItemIn & {"hsn_sac","supply_type","category","brand","supplier_gstin","classification_source":"ai"|"fallback"|"catalog"|"manual"}],
  "legs":[{"item_indexes":[1],"label":"Services (SAC 9987)","supply_type":"services","amount_paise":180000,
           "reason":"AI's one-line reason this leg is a separate supply"}],
  "source":"ai"|"fallback", "fallback_reason":null|"..", "model":"gemini-3.8-flash"|null,
  "rationale":"AI's short explanation of the overall split",
  "estimate":{"rail_assumed":"UPI_RUPAY_CC","mdr_single_paise":13806,"mdr_split_paise":9983,"saving_paise":3823},
  "sentinel":{"decision":"allow"|"flag"|"block","reasons":[...]}
}
OrderCreate = {"device_id":"SB-..", "items":[ItemIn (classified, e.g. from Plan.items)],
               "legs":[[1],[0]]?,               // item indexes per leg, normally Plan.legs[].item_indexes
               "plan_source":"ai"|"fallback"|"manual"?, "rationale":".."?,
               "factorize":true?}
// legs omitted → the server plans with AI (slower). The Sentinel always re-validates.
Order = {"id","merchant_id","device_id","status","total_paise","created_at","paid_at","settled_at",
         "items":[...], "legs":[Leg...], "settlement":Settlement|null, "sentinel":{...},
         "division":{"source":"ai"|"fallback"|"manual","fallback_reason":..,"rationale":..,"model":..}}
```
Settlement also carries the SoundShare money flow: `covered_by_ads_paise` (this sale's own ad money), `shared_drawn_paise` (taken from the shared pool), `rental_paid_paise` / `rental_from_pool_paise` (Soundbox rental paid this month), `shared_contributed_paise` (surplus given to the pool), `shared_pool_balance_paise`, and `platform_paise` (Paytm's cut of the surplus). Merchant `stats` has `rental{monthly_fee_paise, paid_this_month_paise, due_paise, plays_to_cover}` and `shared{contributed_paise, received_for_fees_paise, received_for_rental_paise, network_pool_balance_paise, daily_cap_paise}`.
Leg and Settlement are otherwise unchanged from v1 (`legs[].status/qr_data/rail/mdr_paise`, `settlement.mdr_paise, mdr_unsplit_paise, saved_by_factorization_paise, ad_liquidity_paise, covered_paise, coverage_pct, merchant_receives_paise, acquirer_paise, platform_paise, sponsors[], status`).

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
| PATCH | `/api/advertisers/{id}` | owner | `{name?, category?, lat?, lng?, address?}` | `Advertiser` |
| POST | `/api/advertisers/{id}/topup` | owner | `{amount_paise}` | `TopUp`. With a real provider, show `qr_data`/`checkout_url` and poll. |
| GET | `/api/topups/{id}` | owner/admin | – | `TopUp` |
| GET | `/api/advertisers/{id}/topups` | owner/admin | – | `TopUp[]` |
| POST | `/api/ai/transcribe` | advertiser/merchant | multipart `audio` (webm/ogg/wav/mp3, ≤ 2 MB), `lang` | `{text, source:"ai"}`. `502` if AI fails, and then the client falls back to browser speech recognition. |
| GET | `/api/geo/soundboxes?lat=&lng=&radius_m=` | advertiser/admin | – | `{count, online, soundboxes:[{device_id, merchant_name, category, lat, lng, distance_m, online}]}` |
| GET | `/api/campaigns` | advertiser (own) / admin (all) | – | `Campaign[]` |
| POST | `/api/campaigns` | advertiser | `CampaignCreate` | `201 Campaign` (`status:"generating"`). AI writes the copy and voices it. |
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
  "stats":{"plays":1,"spend_paise":120,"claims":0,"released_plays":0}}
CampaignCreate = {"kind":"audio"|"subvention","name":"3-day promo","prompt":"..","lang":"en"|"hi",
  "lat":..?,"lng":..?,"radius_m":500,"target_categories":[],"sku_keywords":[],
  "bid_paise":120,"daily_cap_paise":5000,"deploy":true}       // deploy:false = Save Draft
Campaign = {...CampaignCreate, "id":"CMP-..","advertiser_id","advertiser_name",
  "status":"generating"|"draft"|"active"|"paused"|"failed"|"exhausted", "error":null|"..",
  "creative": null | {"id","lang","script","banner":{title,subtitle,cta,bg,fg,accent},
     "audio_url","audio_hash","duration_ms","offer_url",
     "source":"ai"|"fallback","fallback_reason":null|"..",           // copywriting path
     "voice_source":"ai"|"fallback"|null,"voice_fallback_reason":null|"..",
     "model":"gemini-3.8-flash","voice":"Kore"},
  "stats":{"plays":0,"spend_paise":0,"spent_today_paise":0,"claims":0}}
```

### Ledger, sentinel, admin (admin only)
| Method | Path | Returns |
|---|---|---|
| GET | `/api/ledger/balances` | `[{account,label,balance_paise}]` plus `invariant_paise` (sum, must be 0) via `/api/admin/stats` |
| GET | `/api/ledger/entries?ref=&limit=` | `[{txn_id,ref,memo,account,label,amount_paise,ts}]` |
| GET | `/api/ledger/flows?order_id=` | `{nodes:[{id,label}],links:[{source,target,amount_paise}]}` |
| GET | `/api/sentinel/flags?limit=` | `[{id,ref,rule,severity,action,detail,ts}]` |
| GET | `/api/admin/stats` | see below |

```jsonc
AdminStats = {"orders":n,"settled_orders":n,"gross_paise":..,"avg_ticket_paise":..,"mdr_paise":..,
  "interchange_pct":1.536,            // mdr / gross
  "covered_paise":..,"coverage_pct":100.0,"platform_paise":..,
  "spread_pct":6.0,                   // platform / ad liquidity
  "saved_by_factorization_paise":..,"ad_liquidity_paise":..,
  "plays":n,"plays_released":n,"play_verification_pct":100.0,
  "devices_total":n,"devices_online":n,"merchants":n,"advertisers":n,
  "ledger_invariant_paise":0,
  "latency":{"p50_ms","p95_ms","last_ms","samples"}}
```

### WebSocket `/ws/admin?token=<admin session token>`
Events: `{type:"order_update"|"ledger_post"|"device_status"|"play_ack"|"sentinel_flag"|"campaign_update"|"topup"|"offer_claim"|"device_msg", ...}`. Treat these as refresh signals.

---

## 2. Device WebSocket protocol (ESP32 + browser simulator)

**Unchanged from v1** except that device ids and tokens now come from `POST /api/devices` (e.g. `SB-7F3A`). No device is built in. Connect to `ws://<host>:8000/ws/device/{deviceId}?token=<token>`.

Every frame is one JSON text message with a `type` field. The server sends `ping` every 20 s, and the device answers `pong`.
Times are epoch **seconds**. Media URLs are **http**. Banner text is ASCII.

### Server → device
```jsonc
{"type":"hello_ack","deviceId":"SB-7F3A","merchant":{"id":"M-..","name":"Sharma Electronics","lang":"en"},"serverTime":1731400000}
{"type":"idle","banners":[Banner,...]}
{"type":"show_bill","orderId":"O-1","items":[{"name":"Havells Mixer Grinder","qty":1,"amount":470000}],"total":650000}
{"type":"show_split","orderId":"O-1","total":650000,
 "legs":[{"seq":1,"label":"Services (SAC 9987)","amount":180000},{"seq":2,"label":"Goods (HSN 8509)","amount":470000}],
 "note":"Separate GST invoices. Fee is calculated after payment."}
{"type":"show_qr","orderId":"O-1","legId":"L-1","seq":1,"of":2,"qrData":"upi://pay?...","amount":180000,"expiresAt":1731400600}
{"type":"leg_paid","orderId":"O-1","legId":"L-1","seq":1,"of":2,"amount":180000,"rail":"UPI_RUPAY_CC"}
{"type":"payment_success","orderId":"O-1","amount":650000,"lang":"en",
 "announce":["n6","thousand","n5","hundred","rupees","received"],"announceText":"Six thousand five hundred rupees received",
 "playId":"P-1"|null,"ad":null|{"hash":"<sha1>","url":"http://host:8000/media/audio/<sha1>.mp3","durationMs":2300,"advertiser":"FitZone Gym"},
 "banner":null|Banner,"offerQr":null|"http://host:8000/api/offers/CR-1/claim?d=SB-7F3A",
 "settlement":{"mdr":9983,"merchantReceives":650000,"coveragePct":100.0,
               "coveredBy":[{"name":"Havells","amount":10500},{"name":"FitZone Gym","amount":120}]}}
{"type":"play_ad","orderId":"O-1","playId":"P-1","ad":{"hash":"<sha1>","url":"http://host:8000/media/audio/<sha1>.mp3","durationMs":3500,"advertiser":"FitZone Gym"},"banner":Banner,"offerQr":"http://host:8000/api/offers/CR-1/claim?d=SB-7F3A"}
   // Normal hours: sent right after show_qr. Play it now, while the customer pays. A payment_success that
   // arrives meanwhile is played AFTER the ad ends. Charged only if fully played AND the bill gets paid.
   // Busy hour (merchant busy_mode): no play_ad. payment_success.ad carries a short sponsor tag
   // ({"kind":"tag", ...}, about 1 s, priced at Campaign.tag_bid_paise, default 75% of bid_paise) played after the message.
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

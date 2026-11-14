"""End-to-end tests for SoundShare.

Gemini is replaced by a deterministic fake (tests only) so we can exercise the AI path,
an AI proposal the Sentinel rejects, and full AI outage -> fallbacks.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
from array import array

_tmp = tempfile.mkdtemp()
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db".replace("\\", "/"),
    "PAYMENT_PROVIDER": "mock",
    "GEMINI_API_KEY": "test-key",
    "TTS_FALLBACK": "none",
    "SARVAM_API_KEY": "",
    "PUBLIC_BASE_URL": "http://testserver",
    "ADMIN_PHONE": "9000000001",
    "ADMIN_PASSWORD": "admin-pass-123",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import audio, factorizer, llm, mdr  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.money import announce_tokens, inr  # noqa: E402
from app.payments.paytm_checksum import generate_signature, verify_signature  # noqa: E402

CODES = {"mixer": ("8509", "appliance", "havells"), "warranty": ("9987", "services", ""),
         "kettle": ("8516", "appliance", "havells"), "installation": ("9987", "services", "")}


# ---------------------------------------------------------------- fake Gemini (tests only)

class FakeGemini:
    def __init__(self):
        self.mode = "ok"  # ok | down | illegal_split
        self.calls: list[str] = []

    def generate_json(self, prompt, schema=None, parts=None, temperature=0.3, task="generate"):
        self.calls.append(task)
        llm._local.model = "gemini-3.8-flash"
        if self.mode == "down":
            llm.health.fail(f"{task}: HTTP 503 UNAVAILABLE")
            raise llm.AIError("HTTP 503 UNAVAILABLE: model overloaded")
        if task == "classify":
            out = []
            for m in re.finditer(r'^(\d+)\. "([^"]+)"', prompt, re.M):
                key = next((k for k in CODES if k in m.group(2).lower()), None)
                if key:
                    code, cat, brand = CODES[key]
                else:
                    from app import hsn
                    code, cat = hsn.classify(m.group(2))
                    brand = hsn.detect_brand(m.group(2)) or ""
                out.append({"index": int(m.group(1)), "hsn_sac": code,
                            "supply_type": "services" if code.startswith("99") else "goods",
                            "category": cat, "brand": brand})
            return out
        if task == "divide":
            lines = re.findall(r"^(\d+)\. .*?\| (goods|services) \|", prompt, re.M)
            if self.mode == "illegal_split":
                return {"legs": [{"item_indexes": [int(i)], "reason": "keep under 2000"} for i, _ in lines],
                        "rationale": "one leg per line"}
            groups: dict[str, list[int]] = {}
            for i, kind in lines:
                groups.setdefault(kind, []).append(int(i))
            return {"legs": [{"item_indexes": v, "reason": f"Separate {k} supply"} for k, v in groups.items()],
                    "rationale": "Goods and services are separate supplies with separate invoices."}
        if task == "ad_copy":
            if self.mode == "payment_words" and "previous script" not in prompt:
                return {"script": "FitZone Gym received payment! One month free.", "title": "FitZone Gym",
                        "subtitle": "1 month free", "cta": "Scan to claim", "compliant": True, "compliance_note": "ok"}
            brief = re.search(r'brief: "(.*)"', prompt).group(1).lower()
            bad = "cure" in brief
            return {"script": f"FitZone Gym: {brief[:40]}!", "title": "FitZone Gym",
                    "subtitle": "1 month free on annual plan", "cta": "Scan to claim",
                    "compliant": not bad, "compliance_note": "health cure claim" if bad else "ok"}
        if task == "parse_text":
            return {"items": [{"name": "Havells Mixer Grinder", "qty": 1, "unit_price_rupees": 4700,
                               "hsn_sac": "8509", "category": "appliance", "brand": "havells"}]}
        raise AssertionError(task)

    def tts(self, text, style, voice=None):
        self.calls.append("tts")
        if self.mode == "down":
            raise llm.AIError("tts: HTTP 503")
        rate = 24000  # 2.3 s tone with silence padding
        s = array("h", [0] * 2400 + [int(9000 * math.sin(i / 7)) for i in range(int(2.3 * rate))] + [0] * 2400)
        return s.tobytes(), rate


@pytest.fixture()
def fake(monkeypatch):
    from pathlib import Path

    from app import creative
    f = FakeGemini()
    monkeypatch.setattr(llm, "generate_json", f.generate_json)
    monkeypatch.setattr(llm, "tts", f.tts)
    monkeypatch.setattr(llm, "check_models", lambda: {})
    monkeypatch.setattr(creative, "AUDIO_DIR", Path(tempfile.mkdtemp()))  # keep test audio out of media/
    return f


@pytest.fixture()
def client(fake):
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------- helpers

def auth_h(token):
    return {"Authorization": f"Bearer {token}"}


def reg_merchant(c, phone="9876543210", name="Sharma Electronics", vpa="sharma.electronics@okicici"):
    r = c.post("/api/auth/register/merchant", json={
        "phone": phone, "password": "s3cret-pass", "name": name, "category": "electronics",
        "gstin": "29ABCDE1234F1Z5", "vpa": vpa, "lat": 12.9716, "lng": 77.5946})
    assert r.status_code == 201, r.text
    return r.json()


def reg_adv(c, phone, name, type_, category, lat=None, lng=None):
    r = c.post("/api/auth/register/advertiser", json={
        "phone": phone, "password": "s3cret-pass", "name": name, "type": type_, "category": category,
        "lat": lat, "lng": lng})
    assert r.status_code == 201, r.text
    return r.json()


def wait_campaign(c, h, cid, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        camp = c.get(f"/api/campaigns/{cid}", headers=h).json()
        if camp["status"] != "generating":
            return camp
        time.sleep(0.05)
    raise AssertionError("campaign still generating")


def recv_until(ws, type_):
    for _ in range(60):
        m = json.loads(ws.receive_text())
        if m["type"] == type_:
            return m
    raise AssertionError(f"no {type_}")


def wait_order(c, h, oid, status="settled"):
    for _ in range(100):
        o = c.get(f"/api/orders/{oid}", headers=h).json()
        if o["status"] == status:
            return o
        time.sleep(0.05)
    raise AssertionError(f"order not {status}: {o['status']}")


def setup_ecosystem(c):
    """Real sign-ups through the API: merchant + Soundbox + local advertiser + brand sponsor."""
    m = reg_merchant(c)
    mh = auth_h(m["token"])
    dev = c.post("/api/devices", json={"name": "Counter 1"}, headers=mh).json()
    fit = reg_adv(c, "9811111111", "FitZone Gym", "local", "fitness", 12.9733, 77.5958)
    fh = auth_h(fit["token"])
    assert c.post(f"/api/advertisers/{fit['user']['advertiser_id']}/topup", json={"amount_paise": 30000},
                  headers=fh).json()["status"] == "paid"
    camp = c.post("/api/campaigns", headers=fh, json={
        "kind": "audio", "name": "3-day promo", "prompt": "Run a 3-day promotion: 1 month free on annual membership",
        "lang": "en", "radius_m": 500, "bid_paise": 120, "daily_cap_paise": 5000, "deploy": True}).json()
    camp = wait_campaign(c, fh, camp["id"])
    hav = reg_adv(c, "9822222222", "Havells", "brand", "appliance")
    hh = auth_h(hav["token"])
    c.post(f"/api/advertisers/{hav['user']['advertiser_id']}/topup", json={"amount_paise": 1000000}, headers=hh)
    sub = c.post("/api/campaigns", headers=hh, json={
        "kind": "subvention", "name": "Clearing rights", "prompt": "Havells pays your payment fee",
        "radius_m": 0, "target_categories": ["appliance"], "sku_keywords": ["havells"],
        "bid_paise": 10500, "deploy": True}).json()
    wait_campaign(c, hh, sub["id"])
    return {"m": m, "mh": mh, "dev": dev, "fit": fit, "fh": fh, "camp": camp, "hav": hav, "hh": hh}


ITEMS = [{"name": "Havells Mixer Grinder 750W", "qty": 1, "unit_price": 470000},
         {"name": "Extended Warranty & Installation", "qty": 1, "unit_price": 180000}]


# ---------------------------------------------------------------- unit

def test_mdr_quotes():
    assert mdr.mdr_total(470000, "UPI_RUPAY_CC") == 9983
    assert mdr.mdr_total(650000, "UPI_RUPAY_CC") == 13806
    assert mdr.mdr_total(180000, "UPI_RUPAY_CC") == 0
    assert mdr.mdr_total(1000000, "UPI_BANK") == 4720


def test_announce_and_format():
    assert announce_tokens(650000)[0] == ["chime", "pre", "n6", "thousand", "n5", "hundred", "rupees", "received"]
    assert announce_tokens(650000)[1] == "Received six thousand five hundred rupees on Paytm"
    assert inr(12345678) == "₹1,23,456.78"


def test_paytm_checksum_roundtrip():
    key = "abcdEFGH12345678"
    body = '{"mid":"TEST","orderId":"L-1"}'
    assert verify_signature(body, key, generate_signature(body, key))
    assert not verify_signature(body + " ", key, generate_signature(body, key))


def test_audio_pipeline_trims_and_encodes():
    rate = 24000
    pcm = array("h", [0] * rate + [int(9000 * math.sin(i / 5)) for i in range(rate)] + [0] * rate).tobytes()
    out = audio.trim_and_normalize(pcm, rate)
    assert 1000 <= audio.duration_ms(out, rate) <= 1200      # 1 s silence each side trimmed
    assert max(abs(v) for v in array("h", out)) > 25000       # normalised towards -1 dBFS
    assert audio.to_mp3(out, rate)[:2] in (b"\xff\xfb", b"\xff\xf3", b"ID")


# ---------------------------------------------------------------- accounts

def test_no_seed_data_and_auth(client):
    admin = client.post("/api/auth/login", json={"phone": "+91 90000 00001", "password": "admin-pass-123"}).json()
    ah = auth_h(admin["token"])
    assert client.get("/api/merchants", headers=ah).json() == []      # nothing pre-seeded
    assert client.get("/api/advertisers", headers=ah).json() == []
    m = reg_merchant(client)
    assert client.post("/api/auth/register/merchant", json={
        "phone": "9876543210", "password": "x" * 8, "name": "Dup", "category": "grocery", "gstin": "29ABCDE1234F1Z5",
        "vpa": "dup@okaxis", "lat": 1, "lng": 1}).status_code == 409
    assert client.post("/api/auth/login", json={"phone": "9876543210", "password": "wrong-pass"}).status_code == 401
    assert client.get("/api/auth/me", headers=auth_h(m["token"])).json()["role"] == "merchant"
    other = reg_merchant(client, phone="9876500000", name="Other Shop", vpa="other@okaxis")
    assert client.get(f"/api/merchants/{m['user']['merchant_id']}", headers=auth_h(other["token"])).status_code == 403
    assert client.get("/api/ledger/balances", headers=auth_h(m["token"])).status_code == 403
    assert client.get("/api/merchants/x").status_code == 401
    bad = client.post("/api/auth/register/merchant", json={
        "phone": "12345", "password": "s3cret-pass", "name": "X", "category": "x", "gstin": "bad",
        "vpa": "a@b", "lat": 1, "lng": 1})
    assert bad.status_code == 422


# ---------------------------------------------------------------- AI paths

def test_catalog_item_is_ai_classified(client, fake):
    m = reg_merchant(client)
    r = client.post(f"/api/merchants/{m['user']['merchant_id']}/catalog", headers=auth_h(m["token"]),
                    json={"name": "Havells Mixer Grinder 750W", "unit_price": 470000})
    assert r.status_code == 201
    item = r.json()
    assert (item["hsn_sac"], item["category"], item["brand"], item["source"]) == ("8509", "appliance", "havells", "ai")
    assert "classify" in fake.calls


def test_catalog_lines_use_server_side_codes(client, fake):
    m = reg_merchant(client)
    h = auth_h(m["token"])
    item = client.post(f"/api/merchants/{m['user']['merchant_id']}/catalog", headers=h,
                       json={"name": "Havells Mixer Grinder 750W", "unit_price": 470000}).json()
    fake.calls.clear()
    plan = client.post("/api/bills/plan", headers=h, json={"items": [
        {"name": item["name"], "qty": 1, "unit_price": 470000, "catalog_item_id": item["id"],
         "hsn_sac": "9999", "category": "tampered"}]}).json()
    assert plan["items"][0]["classification_source"] == "catalog"
    assert (plan["items"][0]["hsn_sac"], plan["items"][0]["category"]) == ("8509", "appliance")
    assert "classify" not in fake.calls                       # no AI call needed for catalog lines
    other = reg_merchant(client, phone="9876500000", name="Other Shop", vpa="other@okaxis")
    r = client.post("/api/bills/plan", headers=auth_h(other["token"]), json={"items": [
        {"name": "x", "qty": 1, "unit_price": 100, "catalog_item_id": item["id"]}]})
    assert r.status_code == 404                               # can't use another merchant's catalog


def test_ai_plan_then_golden_walkthrough(client, fake):
    e = setup_ecosystem(client)
    assert e["camp"]["status"] == "active", e["camp"]["error"]
    cr = e["camp"]["creative"]
    assert (cr["source"], cr["voice_source"], cr["model"]) == ("ai", "ai", "gemini-3.8-flash")
    assert 2200 <= cr["duration_ms"] <= 2600                     # trimmed tone ≈ 2.3 s + padding

    plan = client.post("/api/bills/plan", headers=e["mh"], json={"items": ITEMS}).json()
    assert plan["source"] == "ai" and plan["classification"]["source"] == "ai"
    assert [l["amount_paise"] for l in plan["legs"]] == [180000, 470000]
    est = {r["rail"]: r for r in plan["estimate"]["by_rail"]}
    assert (est["UPI_RUPAY_CC"]["mdr_single_paise"], est["UPI_RUPAY_CC"]["mdr_split_paise"]) == (13806, 9983)
    assert (est["UPI_BANK"]["mdr_single_paise"], est["UPI_BANK"]["mdr_split_paise"]) == (3068, 2218)
    assert est["CREDIT_CARD"]["saving_paise"] == 0             # card rate has no Rs 2,000 zero slab
    assert plan["estimate"]["worst_case_rail"] in ("UPI_RUPAY_CC", "CREDIT_CARD")
    assert plan["sentinel"]["decision"] == "allow"

    dev = e["dev"]
    with client.websocket_connect(f"/ws/device/{dev['id']}?token={dev['token']}") as ws:
        ws.send_text(json.dumps({"type": "hello", "fw": "test", "cache": []}))
        assert recv_until(ws, "hello_ack")["merchant"]["name"] == "Sharma Electronics"
        r = client.post("/api/orders", headers=e["mh"], json={
            "device_id": dev["id"], "items": plan["items"], "legs": plan["legs"],
            "plan_source": plan["source"], "rationale": plan["rationale"]})
        assert r.status_code == 201, r.text
        order = r.json()
        assert order["division"]["source"] == "ai"
        assert order["legs"][0]["reason"] == "Separate services supply"
        recv_until(ws, "show_split")
        assert recv_until(ws, "show_qr")["seq"] == 1
        ad = recv_until(ws, "play_ad")                     # ad starts as the QR goes up
        assert ad["ad"]["advertiser"] == "FitZone Gym"
        ws.send_text(json.dumps({"type": "play_ack", "playId": ad["playId"], "ms": 2350, "peakDb": -18.5}))
        time.sleep(0.2)                                    # ad finished while the customer was paying
        assert client.get(f"/api/orders/{order['id']}", headers=e["mh"]).json()["status"] == "awaiting_payment"
        for leg in order["legs"]:
            assert client.post("/api/mock/pay", headers=e["mh"],
                               json={"leg_id": leg["id"], "rail": "UPI_RUPAY_CC"}).status_code == 200
        ok = recv_until(ws, "payment_success")
        assert ok["ad"] is None                            # already heard; only the payment message now
        o = wait_order(client, e["mh"], order["id"])

    s = o["settlement"]
    assert (s["mdr_unsplit_paise"], s["mdr_paise"], s["saved_by_factorization_paise"]) == (13806, 9983, 3823)
    assert (s["ad_liquidity_paise"], s["merchant_receives_paise"], s["acquirer_paise"]) == (10620, 650000, 9983)
    # surplus Rs 6.37: 25% platform cut, the rest pays Sharma's Soundbox rental (Rs 125 not yet covered)
    assert (s["platform_paise"], s["rental_paid_paise"], s["shared_contributed_paise"]) == (159, 478, 0)

    admin = client.post("/api/auth/login", json={"phone": "9000000001", "password": "admin-pass-123"}).json()
    ah = auth_h(admin["token"])
    stats = client.get("/api/admin/stats", headers=ah).json()
    assert stats["ledger_invariant_paise"] == 0 and stats["coverage_pct"] == 100.0
    fit = client.get(f"/api/advertisers/{e['fit']['user']['advertiser_id']}", headers=e["fh"]).json()
    assert fit["balance_paise"] == 29880 and fit["wallet"]["burn_per_play_paise"] == 120
    assert fit["wallet"]["est_plays_remaining"] == 249
    geo = client.get("/api/geo/soundboxes", headers=e["fh"], params={"lat": 12.9733, "lng": 77.5958, "radius_m": 500}).json()
    assert geo["count"] == 1 and geo["soundboxes"][0]["merchant_name"] == "Sharma Electronics"


def test_ai_split_rejected_by_sentinel_falls_back(client, fake):
    m = reg_merchant(client)
    fake.mode = "illegal_split"
    items = [{"name": "Havells Mixer Grinder", "qty": 1, "unit_price": 190000},
             {"name": "Havells Electric Kettle", "qty": 1, "unit_price": 160000}]
    plan = client.post("/api/bills/plan", headers=auth_h(m["token"]), json={"items": items}).json()
    # Both are goods from one supplier: no legal split exists, so the AI isn't even asked to divide.
    assert plan["source"] == "single" and len(plan["legs"]) == 1
    items.append({"name": "Installation service", "qty": 1, "unit_price": 50000})
    plan = client.post("/api/bills/plan", headers=auth_h(m["token"]), json={"items": items}).json()
    assert plan["source"] == "fallback" and "Sentinel" in plan["fallback_reason"]
    assert len(plan["legs"]) == 2 and plan["sentinel"]["decision"] == "allow"


def test_ai_outage_uses_fallbacks_and_says_so(client, fake):
    m = reg_merchant(client)
    fake.mode = "down"
    plan = client.post("/api/bills/plan", headers=auth_h(m["token"]), json={"items": ITEMS}).json()
    assert plan["source"] == "fallback" and "503" in plan["fallback_reason"]
    assert plan["classification"]["source"] == "fallback"
    assert [l["amount_paise"] for l in plan["legs"]] == [180000, 470000]   # rule engine still splits legally
    parsed = client.post("/api/bills/parse", headers=auth_h(m["token"]), json={"text": "Mixer Grinder 4700\nWarranty 1,800"}).json()
    assert parsed["source"] == "fallback" and len(parsed["items"]) == 2
    a = reg_adv(client, "9833333333", "Dr. Smile Dental", "local", "healthcare", 12.97, 77.59)
    camp = client.post("/api/campaigns", headers=auth_h(a["token"]), json={
        "kind": "audio", "name": "Check-up", "prompt": "Free dental check-up this week", "bid_paise": 90}).json()
    camp = wait_campaign(client, auth_h(a["token"]), camp["id"])
    # Copy fell back to a template; voice had no fallback configured (TTS_FALLBACK=none) -> honest failure.
    assert camp["creative"]["source"] == "fallback" and "503" in camp["creative"]["fallback_reason"]
    assert camp["status"] == "failed" and "voice-over" in camp["error"]


def test_ai_compliance_rejects_ad(client, fake):
    a = reg_adv(client, "9844444444", "Herbal Clinic", "local", "healthcare", 12.97, 77.59)
    camp = client.post("/api/campaigns", headers=auth_h(a["token"]), json={
        "kind": "audio", "name": "Hair oil", "prompt": "Our herbal oil can cure baldness", "bid_paise": 90}).json()
    camp = wait_campaign(client, auth_h(a["token"]), camp["id"])
    assert camp["status"] == "failed" and "compliance" in camp["error"].lower()


def test_draft_then_deploy(client, fake):
    a = reg_adv(client, "9855555555", "FitZone Gym", "local", "fitness", 12.97, 77.59)
    h = auth_h(a["token"])
    camp = client.post("/api/campaigns", headers=h, json={
        "kind": "audio", "name": "promo", "prompt": "1 month free on annual membership", "bid_paise": 120,
        "deploy": False}).json()
    assert wait_campaign(client, h, camp["id"])["status"] == "draft"
    assert client.patch(f"/api/campaigns/{camp['id']}", headers=h, json={"status": "active"}).json()["status"] == "active"


# ---------------------------------------------------------------- compliance & fraud

def test_manual_structuring_is_blocked(client, fake):
    m = reg_merchant(client)
    items = [{"name": "Havells Mixer Grinder", "qty": 1, "unit_price": 190000, "hsn_sac": "8509", "category": "appliance"},
             {"name": "Havells Electric Kettle", "qty": 1, "unit_price": 160000, "hsn_sac": "8516", "category": "appliance"}]
    r = client.post("/api/orders", headers=auth_h(m["token"]),
                    json={"items": items, "legs": [[0], [1]], "plan_source": "manual"})
    assert r.status_code == 422 and r.json()["error"] == "sentinel_blocked"
    assert any(x["rule"] == "SAME_SUPPLY_SPLIT" for x in r.json()["reasons"])


def test_self_dealing_gets_no_subsidy(client, fake):
    e = setup_ecosystem(client)
    plan = client.post("/api/bills/plan", headers=e["mh"], json={"items": ITEMS[:1]}).json()
    order = client.post("/api/orders", headers=e["mh"], json={
        "items": plan["items"], "legs": plan["legs"], "plan_source": plan["source"]}).json()
    client.post("/api/mock/pay", headers=e["mh"], json={"leg_id": order["legs"][0]["id"], "rail": "UPI_RUPAY_CC",
                                                         "payer": "sharma.electronics@okicici"})
    o = wait_order(client, e["mh"], order["id"])
    assert o["settlement"]["covered_paise"] == 0 and o["sentinel"]["deny_subsidy"] is True


def test_mock_pay_requires_owner_or_device(client, fake):
    e = setup_ecosystem(client)
    plan = client.post("/api/bills/plan", headers=e["mh"], json={"items": ITEMS[1:]}).json()
    order = client.post("/api/orders", headers=e["mh"], json={"items": plan["items"], "legs": plan["legs"]}).json()
    leg = order["legs"][0]["id"]
    assert client.post("/api/mock/pay", json={"leg_id": leg, "rail": "UPI_BANK"}).status_code == 403
    assert client.post("/api/mock/pay", headers=e["fh"], json={"leg_id": leg, "rail": "UPI_BANK"}).status_code == 403
    assert client.post("/api/mock/pay", headers=e["mh"], json={"leg_id": leg}).status_code == 422  # method required
    assert client.post("/api/mock/pay", json={"leg_id": leg, "rail": "UPI_BANK",
                                              "device_token": e["dev"]["token"]}).status_code == 200


# ---------------------------------------------------------------- Gemini client: quota & failover (no network)

def test_quota_is_not_retried_and_fails_over(monkeypatch):
    import httpx
    from app import llm as L
    monkeypatch.setattr(L, "configured", lambda: True)
    L._blocked_until.clear()
    calls = []

    def fake_request(method, url, json=None, headers=None, timeout=None):
        model = url.split("/models/")[1].split(":")[0]
        calls.append(model)
        if model == "gemini-3.8-flash":
            return httpx.Response(429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                "message": "Quota exceeded for metric: generate_content_free_tier_requests, limit: 20. "
                           "Please retry in 17h46m19.9s.",
                "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "63979s"}]}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]})

    monkeypatch.setattr(L.httpx, "request", fake_request)
    assert L.generate_json("hi", task="t") == {"ok": True}
    assert calls == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]      # one 429, no retry, then failover
    assert L.last_model() == "gemini-3.5-flash-lite"
    calls.clear()
    L.generate_json("hi", task="t")
    assert calls == ["gemini-3.5-flash-lite"]                          # exhausted model skipped (circuit open)
    assert "gemini-3.8-flash" in L.quota_state()
    L._blocked_until.clear()


def test_retry_delay_parsing():
    from app.llm import _retry_delay_s
    assert _retry_delay_s({"details": [{"@type": "x/google.rpc.RetryInfo", "retryDelay": "30s"}]}) == 30
    assert round(_retry_delay_s({"message": "Please retry in 17h46m19.9s."})) == 17 * 3600 + 46 * 60 + 20


def test_ad_never_sounds_like_a_payment_confirmation(fake):
    from app import creative
    fake.mode = "payment_words"
    c = creative.write_copy("FitZone Gym", "fitness", "1 month free on annual membership", "en", "audio")
    assert c.source == "ai" and "received" not in c.script.lower()
    assert fake.calls.count("ad_copy") == 2                      # rejected once, rewritten by the AI


def test_demo_seed_and_clean_removal(client, fake):
    from app import demo
    out = demo.seed()
    assert {r["status"] for r in out} == {"created"} and len(out) == 5
    assert all(r["status"] == "exists" for r in demo.seed())          # idempotent
    m = client.post("/api/auth/login", json={"phone": "9000000101", "password": demo.DEMO_PASSWORD}).json()
    mh = auth_h(m["token"])
    cat = client.get(f"/api/merchants/{m['user']['merchant_id']}/catalog", headers=mh).json()
    assert len(cat) == 26 and {c["source"] for c in cat} == {"ai"}
    # a real sale at the demo shop, sponsored by demo advertisers
    plan = client.post("/api/bills/plan", headers=mh, json={"items": ITEMS}).json()
    order = client.post("/api/orders", headers=mh, json={"items": plan["items"], "legs": plan["legs"]}).json()
    for leg in order["legs"]:
        client.post("/api/mock/pay", headers=mh, json={"leg_id": leg["id"], "rail": "UPI_RUPAY_CC"})
    admin = client.post("/api/auth/login", json={"phone": "9000000001", "password": "admin-pass-123"}).json()
    ah = auth_h(admin["token"])
    entries = client.get("/api/ledger/entries", headers=ah, params={"limit": 1000}).json()
    assert any(e["memo"] == "Demo credit (not a real payment)" for e in entries)
    counts = demo.remove()
    assert counts["users"] == 5 and counts["orders"] == 1
    assert client.get("/api/merchants", headers=ah).json() == []
    assert client.get("/api/admin/stats", headers=ah).json()["ledger_invariant_paise"] == 0
    assert client.get("/api/ledger/entries", headers=ah).json() == []


# ---------------------------------------------------------------- Sarvam: languages (fake Sarvam, tests only)

@pytest.fixture()
def fake_sarvam(monkeypatch):
    from pathlib import Path

    from app import announcer, sarvam
    calls = {"tts": [], "translate": [], "fail": False}

    def tts(text, lang, purpose="ad"):
        calls["tts"].append((lang, purpose, text))
        if calls["fail"]:
            raise sarvam.SarvamError("HTTP 503 model_call_error")
        rate = 24000
        return array("h", [int(8000 * math.sin(i / 6)) for i in range(int(1.2 * rate))]).tobytes(), rate

    def translate(text, target, source="en", mode="formal"):
        calls["translate"].append(target)
        return {"ta": "Paytm-இல் 6,500 ரூபாய் பெறப்பட்டது"}.get(target, f"[{target}] 6,500 Paytm")

    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(sarvam, "configured", lambda: True)
    monkeypatch.setattr(sarvam, "tts", tts)
    monkeypatch.setattr(sarvam, "translate", translate)
    monkeypatch.setattr(announcer, "TEMPLATES_FILE", tmp / "announce_templates.json")
    monkeypatch.setattr(announcer, "ANNOUNCE_DIR", tmp / "announce")
    return calls


def test_tamil_merchant_hears_full_sentence_announcement(client, fake, fake_sarvam):
    r = client.post("/api/auth/register/merchant", json={
        "phone": "9845000001", "password": "s3cret-pass", "name": "Murugan Stores", "category": "grocery",
        "gstin": "33ABCDE1234F1Z5", "vpa": "murugan@okaxis", "lat": 13.08, "lng": 80.27, "lang": "ta"})
    assert r.status_code == 201, r.text
    mh = auth_h(r.json()["token"])
    dev = client.post("/api/devices", json={"name": "Counter"}, headers=mh).json()
    with client.websocket_connect(f"/ws/device/{dev['id']}?token={dev['token']}") as ws:
        ws.send_text(json.dumps({"type": "hello", "cache": []}))
        recv_until(ws, "hello_ack")
        order = client.post("/api/orders", headers=mh, json={"items": [
            {"name": "Rice 25kg", "qty": 1, "unit_price": 650000, "hsn_sac": "1006", "category": "grocery"}],
            "legs": [[0]], "plan_source": "single"}).json()
        client.post("/api/mock/pay", headers=mh, json={"leg_id": order["legs"][0]["id"], "rail": "UPI_BANK"})
        ok = recv_until(ws, "payment_success")
    assert ok["lang"] == "ta" and ok["announceUrl"].endswith(f"/api/announce/{order['id']}.mp3")
    assert ok["announce"][0] == "chime"                         # local clip fallback (en) still sent
    a = client.get(f"/api/announce/{order['id']}.mp3")
    assert a.status_code == 200 and a.headers["content-type"] == "audio/mpeg" and len(a.content) > 3000
    spoken = [t for (lang, purpose, t) in fake_sarvam["tts"] if purpose == "announce"]
    assert spoken == ["Paytm-இல் 6,500 ரூபாய் பெறப்பட்டது"]       # one natural sentence, amount in place
    from app import announcer
    assert json.loads(announcer.TEMPLATES_FILE.read_text(encoding="utf-8"))["ta"] == "Paytm-இல் {amount} ரூபாய் பெறப்பட்டது"
    assert client.get(f"/api/announce/{order['id']}.mp3").status_code == 200
    assert len([1 for (_, p, _) in fake_sarvam["tts"] if p == "announce"]) == 1   # cached, not re-synthesised


def test_regional_ad_voiced_by_sarvam_and_backed_up_by_gemini(client, fake, fake_sarvam):
    a = reg_adv(client, "9845000002", "Saravana Sweets", "local", "food", 13.08, 80.27)
    h = auth_h(a["token"])
    camp = client.post("/api/campaigns", headers=h, json={
        "kind": "audio", "name": "Deepavali", "prompt": "20% off on sweet boxes this week", "lang": "ta",
        "bid_paise": 100}).json()
    camp = wait_campaign(client, h, camp["id"])
    cr = camp["creative"]
    assert camp["status"] == "active" and cr["voice_source"] == "ai" and cr["voice"].startswith("sarvam")
    assert fake_sarvam["tts"][-1][:2] == ("ta", "ad")
    fake_sarvam["fail"] = True                                   # Sarvam down -> Gemini voice (still AI)
    client.post(f"/api/campaigns/{camp['id']}/regenerate", headers=h, json={"prompt": "25% off on sweet boxes"})
    camp = wait_campaign(client, h, camp["id"])
    cr = camp["creative"]
    assert cr["voice_source"] == "ai" and cr["voice"].startswith("gemini") and "sarvam" in cr["voice_fallback_reason"]


def test_languages_exposed_and_validated(client):
    cfg = client.get("/api/config").json()
    assert [l["code"] for l in cfg["languages"]][:3] == ["en", "hi", "bn"] and len(cfg["languages"]) == 11
    bad = client.post("/api/auth/register/merchant", json={
        "phone": "9845000003", "password": "s3cret-pass", "name": "X Shop", "category": "grocery",
        "gstin": "33ABCDE1234F1Z5", "vpa": "x@okaxis", "lat": 13.0, "lng": 80.2, "lang": "fr"})
    assert bad.status_code == 422


def test_fee_follows_the_payment_method_actually_used(client, fake):
    e = setup_ecosystem(client)
    fees = {}
    for rail in ("UPI_BANK", "DEBIT_CARD", "NET_BANKING", "CREDIT_CARD"):
        order = client.post("/api/orders", headers=e["mh"], json={"items": ITEMS[:1], "legs": [[0]]}).json()
        o = client.post("/api/mock/pay", headers=e["mh"], json={"leg_id": order["legs"][0]["id"], "rail": rail}).json()
        assert o["status"] in ("paid", "settled")                 # fee is final once the payment is recorded
        fees[rail] = (o["legs"][0]["rail"], o["settlement"]["mdr_paise"])
    assert fees == {"UPI_BANK": ("UPI_BANK", 2218), "DEBIT_CARD": ("DEBIT_CARD", 4991),
                    "NET_BANKING": ("NET_BANKING", 6655), "CREDIT_CARD": ("CREDIT_CARD", 9983)}


def test_one_soundbox_one_connection(client, fake):
    e = setup_ecosystem(client)
    dev = e["dev"]
    with client.websocket_connect(f"/ws/device/{dev['id']}?token={dev['token']}") as first:
        first.send_text(json.dumps({"type": "hello", "cache": []}))
        recv_until(first, "hello_ack")
        with client.websocket_connect(f"/ws/device/{dev['id']}?token={dev['token']}") as second:
            second.send_text(json.dumps({"type": "hello", "cache": []}))
            recv_until(second, "hello_ack")
            assert recv_until(first, "replaced")["type"] == "replaced"   # old window told to go quiet
            order = client.post("/api/orders", headers=e["mh"], json={"items": ITEMS[1:], "legs": [[0]]}).json()
            client.post("/api/mock/pay", headers=e["mh"], json={"leg_id": order["legs"][0]["id"], "rail": "UPI_BANK"})
            assert recv_until(second, "payment_success")["orderId"] == order["id"]   # only the new one plays


def test_soundshare_small_vendor_pays_rental_then_funds_other_shops(client, fake):
    e = setup_ecosystem(client)                              # Sharma Electronics + FitZone ad nearby
    assert client.patch(f"/api/campaigns/{e['camp']['id']}", headers=e["fh"], json={"bid_paise": 20000, "daily_cap_paise": 100000}).status_code == 200
    bulb = [{"name": "Philips LED Bulb 9W", "qty": 1, "unit_price": 12000, "hsn_sac": "8539", "category": "lighting"}]
    dev = e["dev"]
    with client.websocket_connect(f"/ws/device/{dev['id']}?token={dev['token']}") as ws:
        ws.send_text(json.dumps({"type": "hello", "cache": []}))
        recv_until(ws, "hello_ack")
        o = client.post("/api/orders", headers=e["mh"], json={"items": bulb, "legs": [[0]]}).json()
        ad = recv_until(ws, "play_ad")
        client.post("/api/mock/pay", headers=e["mh"], json={"leg_id": o["legs"][0]["id"], "rail": "UPI_BANK"})
        recv_until(ws, "payment_success")                  # payment landed mid-ad: settles on the ack
        ws.send_text(json.dumps({"type": "play_ack", "playId": ad["playId"], "ms": 2400, "peakDb": -20}))
        s = wait_order(client, e["mh"], o["id"])["settlement"]
    # Rs 120 sale: no fee. Rs 200 ad -> Rs 50 platform -> Rs 125 own rental -> Rs 25 to the shared pool
    assert (s["mdr_paise"], s["platform_paise"], s["rental_paid_paise"], s["shared_contributed_paise"]) == (0, 5000, 12500, 2500)
    st = client.get(f"/api/merchants/{e['m']['user']['merchant_id']}", headers=e["mh"]).json()["stats"]
    assert st["rental"]["due_paise"] == 0 and st["shared"]["contributed_paise"] == 2500

    # A gym-equipment shop nearby: FitZone (a gym) is a competitor, so no ad plays there.
    r = client.post("/api/auth/register/merchant", json={
        "phone": "9876511111", "password": "s3cret-pass", "name": "FitGear Store", "category": "fitness",
        "gstin": "29ABCDE9999F1Z5", "vpa": "fitgear@okaxis", "lat": 12.9718, "lng": 77.5948})
    gh = auth_h(r.json()["token"])
    o = client.post("/api/orders", headers=gh, json={"items": [
        {"name": "Dumbbell set 10kg", "qty": 1, "unit_price": 250000, "hsn_sac": "9506", "category": "fitness"}],
        "legs": [[0]]}).json()
    s = client.post("/api/mock/pay", headers=gh, json={"leg_id": o["legs"][0]["id"], "rail": "UPI_BANK"}).json()["settlement"]
    # Rs 2,500 by bank UPI: fee Rs 11.80, covered entirely by the vendor's shared surplus
    assert (s["mdr_paise"], s["covered_by_ads_paise"], s["shared_drawn_paise"]) == (1180, 0, 1180)
    assert s["coverage_pct"] == 100.0 and s["merchant_receives_paise"] == 250000
    assert s["shared_pool_balance_paise"] == 2500 - 1180
    admin = client.post("/api/auth/login", json={"phone": "9000000001", "password": "admin-pass-123"}).json()
    stats = client.get("/api/admin/stats", headers=auth_h(admin["token"])).json()
    assert stats["ledger_invariant_paise"] == 0 and stats["shared_pool_paise"] == 1320


def _merchant_ws(client, e):
    dev = e["dev"]
    ws_cm = client.websocket_connect(f"/ws/device/{dev['id']}?token={dev['token']}")
    ws = ws_cm.__enter__()
    ws.send_text(json.dumps({"type": "hello", "cache": []}))
    recv_until(ws, "hello_ack")
    return ws_cm, ws


def test_busy_hour_plays_only_the_cheaper_sponsor_tag(client, fake, monkeypatch):
    from app import tags
    monkeypatch.setattr(tags, "ensure", lambda name, lang: ("t" * 40, 1200))   # tag audio (tests only)
    e = setup_ecosystem(client)
    mid = e["m"]["user"]["merchant_id"]
    assert client.patch(f"/api/merchants/{mid}", headers=e["mh"], json={"busy_mode": True}).json()["busy_mode"]
    camp = client.get(f"/api/campaigns/{e['camp']['id']}", headers=e["fh"]).json()
    assert camp["tag_bid_paise"] == 90                      # 75% of the Rs 1.20 full ad
    ws_cm, ws = _merchant_ws(client, e)
    try:
        o = client.post("/api/orders", headers=e["mh"], json={"items": ITEMS[1:], "legs": [[0]]}).json()
        recv_until(ws, "show_qr")
        client.post("/api/mock/pay", headers=e["mh"], json={"leg_id": o["legs"][0]["id"], "rail": "UPI_BANK"})
        ok = recv_until(ws, "payment_success")              # no play_ad was sent in busy hour
        assert ok["ad"]["kind"] == "tag" and ok["ad"]["durationMs"] == 1200
        ws.send_text(json.dumps({"type": "play_ack", "playId": ok["playId"], "ms": 1250, "peakDb": -20}))
        s = wait_order(client, e["mh"], o["id"])["settlement"]
    finally:
        ws_cm.__exit__(None, None, None)
    fit = [sp for sp in s["sponsors"] if sp["name"] == "FitZone Gym"][0]
    assert (fit["kind"], fit["amount_paise"], fit["status"]) == ("tag", 90, "committed")
    assert client.patch(f"/api/campaigns/{e['camp']['id']}", headers=e["fh"],
                        json={"tag_bid_paise": 120}).status_code == 422   # tag must cost less than the ad


def test_ad_heard_by_a_customer_who_walks_away_is_not_charged(client, fake):
    e = setup_ecosystem(client)
    ws_cm, ws = _merchant_ws(client, e)
    try:
        o = client.post("/api/orders", headers=e["mh"], json={"items": ITEMS[1:], "legs": [[0]]}).json()
        ad = recv_until(ws, "play_ad")
        ws.send_text(json.dumps({"type": "play_ack", "playId": ad["playId"], "ms": 2400, "peakDb": -20}))
        time.sleep(0.2)
        client.post(f"/api/orders/{o['id']}/cancel", headers=e["mh"])   # customer left without paying
    finally:
        ws_cm.__exit__(None, None, None)
    fit = client.get(f"/api/advertisers/{e['fit']['user']['advertiser_id']}", headers=e["fh"]).json()
    assert fit["balance_paise"] == 30000 and fit["stats"]["plays"] == 0

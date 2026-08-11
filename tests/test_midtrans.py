"""Midtrans payment integration tests.

Covers:
  - Subscription creation (/api/subscribe)
  - Callback webhook (/api/midtrans-callback)
  - Signature verification
  - Billing portal (/api/billing-portal)
  - Error paths (invalid tier, bad email, missing config)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from docai import pa_wsgi  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeSR:
    """Fake start_response for WSGI testing."""

    def __init__(self):
        self.status = None
        self.headers = []

    def __call__(self, status, headers):
        self.status = status
        self.headers = headers


def _run_wsgi(method: str, path: str, body: bytes = b"", query: str = "",
              extra_headers: dict = None, api_key: str = "") -> tuple:
    """Run the WSGI app and return (status, headers_dict, body_bytes)."""
    sr = _FakeSR()
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": __import__("io").BytesIO(body),
        "CONTENT_TYPE": "application/json",
    }
    if api_key:
        environ["HTTP_X_API_KEY"] = api_key
    if extra_headers:
        for k, v in extra_headers.items():
            environ[f"HTTP_{k.upper().replace('-', '_')}"] = v
    chunks = pa_wsgi.application(environ, sr)
    body_out = b"".join(chunks) if chunks else b""
    return sr.status, dict(sr.headers), body_out


def _json(status_body: bytes) -> dict:
    return json.loads(status_body) if status_body else {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_subscriptions(tmp_path):
    """Ensure subscriptions.json doesn't persist across tests."""
    original = pa_wsgi._SUBSCRIPTIONS_FILE
    pa_wsgi._SUBSCRIPTIONS_FILE = tmp_path / "subscriptions.json"
    yield
    pa_wsgi._SUBSCRIPTIONS_FILE = original


@pytest.fixture(autouse=True)
def _clean_usage(tmp_path):
    """Ensure usage.json doesn't persist across tests."""
    original = pa_wsgi._USAGE_FILE
    pa_wsgi._USAGE_FILE = tmp_path / "usage.json"
    yield
    pa_wsgi._USAGE_FILE = original


# ---------------------------------------------------------------------------
# /api/subscribe
# ---------------------------------------------------------------------------

class TestSubscribe:
    def test_subscribe_returns_payment_url(self):
        """Happy path: /api/subscribe with valid tier and email returns token + URL."""
        mock_resp = {"token": "snap-token-abc123", "redirect_url": "https://app.sandbox.midtrans.com/snap/v3/redirect/abc123"}

        with patch.object(pa_wsgi, "_midtrans_server_key", return_value="SB-Mid-server-xxx"), \
             patch.object(pa_wsgi, "_midtrans_api_call", return_value=mock_resp):
            status, _, body = _run_wsgi(
                "POST", "/api/subscribe",
                body=json.dumps({"tier": "starter", "email": "test@example.com"}).encode(),
            )

        assert status == "200 OK"
        data = _json(body)
        assert "subscription_id" in data
        assert data["payment_url"] == mock_resp["redirect_url"]
        assert data["token"] == mock_resp["token"]
        assert data["plan"] == "starter"
        assert data["amount"] == 500_000

    def test_subscribe_all_tiers(self):
        """Each valid tier (starter, growth, scale) returns correct pricing."""
        mock_resp = {"token": "snap-tok", "redirect_url": "https://snap.example.com/pay"}

        with patch.object(pa_wsgi, "_midtrans_server_key", return_value="SB-Mid-server-xxx"), \
             patch.object(pa_wsgi, "_midtrans_api_call", return_value=mock_resp):
            for tier, expected_price in [("starter", 500_000), ("growth", 5_000_000), ("scale", 30_000_000)]:
                status, _, body = _run_wsgi(
                    "POST", "/api/subscribe",
                    body=json.dumps({"tier": tier, "email": "user@test.com"}).encode(),
                )
                assert status == "200 OK", f"tier={tier}"
                data = _json(body)
                assert data["amount"] == expected_price, f"tier={tier}"

    def test_subscribe_invalid_tier_rejected(self):
        """Invalid tier returns 400."""
        with patch.object(pa_wsgi, "_midtrans_server_key", return_value="SB-Mid-server-xxx"):
            status, _, body = _run_wsgi(
                "POST", "/api/subscribe",
                body=json.dumps({"tier": "enterprise", "email": "x@y.com"}).encode(),
            )
        assert status == "400 Bad Request"
        assert "Invalid tier" in _json(body)["message"]

    def test_subscribe_invalid_email_rejected(self):
        """Invalid email returns 400."""
        with patch.object(pa_wsgi, "_midtrans_server_key", return_value="SB-Mid-server-xxx"):
            status, _, body = _run_wsgi(
                "POST", "/api/subscribe",
                body=json.dumps({"tier": "starter", "email": "not-an-email"}).encode(),
            )
        assert status == "400 Bad Request"
        assert "email" in _json(body)["message"].lower()

    def test_subscribe_empty_body_rejected(self):
        """Empty body returns 400."""
        with patch.object(pa_wsgi, "_midtrans_server_key", return_value="SB-Mid-server-xxx"):
            status, _, body = _run_wsgi("POST", "/api/subscribe", body=b"")
        assert status == "400 Bad Request"

    def test_subscribe_midtrans_not_configured_returns_503(self):
        """No server key → 503."""
        with patch.object(pa_wsgi, "_midtrans_server_key", return_value=""):
            status, _, body = _run_wsgi(
                "POST", "/api/subscribe",
                body=json.dumps({"tier": "starter", "email": "a@b.com"}).encode(),
            )
        assert status == "503 Service Unavailable"
        assert "midtrans_not_configured" in _json(body)["error"]

    def test_subscribe_api_error_returns_502(self):
        """Midtrans API exception → 502."""
        with patch.object(pa_wsgi, "_midtrans_server_key", return_value="SB-Mid-server-xxx"), \
             patch.object(pa_wsgi, "_midtrans_api_call", side_effect=Exception("connection refused")):
            status, _, body = _run_wsgi(
                "POST", "/api/subscribe",
                body=json.dumps({"tier": "starter", "email": "a@b.com"}).encode(),
            )
        assert status == "502 Bad Gateway"

    def test_subscribe_no_token_returns_502(self):
        """Midtrans returns empty token → 502."""
        with patch.object(pa_wsgi, "_midtrans_server_key", return_value="SB-Mid-server-xxx"), \
             patch.object(pa_wsgi, "_midtrans_api_call", return_value={}):
            status, _, body = _run_wsgi(
                "POST", "/api/subscribe",
                body=json.dumps({"tier": "starter", "email": "a@b.com"}).encode(),
            )
        assert status == "502 Bad Gateway"
        assert "No token returned" in _json(body)["message"]

    def test_subscribe_stores_pending_subscription(self):
        """Successful subscribe stores order in subscriptions.json."""
        mock_resp = {"token": "snap-tok", "redirect_url": "https://snap.example.com/pay"}

        with patch.object(pa_wsgi, "_midtrans_server_key", return_value="SB-Mid-server-xxx"), \
             patch.object(pa_wsgi, "_midtrans_api_call", return_value=mock_resp):
            status, _, body = _run_wsgi(
                "POST", "/api/subscribe",
                body=json.dumps({"tier": "growth", "email": "sub@test.com", "api_key": "docai-dev-key-12345"}).encode(),
            )

        assert status == "200 OK"
        subs = pa_wsgi._load_subscriptions()
        assert len(subs) == 1
        sub = list(subs.values())[0]
        assert sub["tier"] == "growth"
        assert sub["email"] == "sub@test.com"
        assert sub["status"] == "pending"


# ---------------------------------------------------------------------------
# /api/midtrans-callback
# ---------------------------------------------------------------------------

class TestCallback:
    def test_callback_capture_activates_subscription(self):
        """payment.capture + fraud accept → active, upgrades API key tier."""
        # First create a pending subscription
        subs = pa_wsgi._load_subscriptions()
        subs["docai-starter-abc123"] = {
            "tier": "starter",
            "email": "cb@test.com",
            "api_key": "docai-dev-key-12345",
            "order_id": "docai-starter-abc123",
            "amount": 500_000,
            "status": "pending",
        }
        pa_wsgi._save_subscriptions(subs)

        # Seed usage for the API key
        usage = pa_wsgi._load_usage()
        usage["docai-dev-key-12345"] = {"tier": "free", "calls_this_month": 0, "last_call": None, "total_calls": 0}
        pa_wsgi._save_usage(usage)

        payload = json.dumps({
            "order_id": "docai-starter-abc123",
            "transaction_status": "capture",
            "fraud_status": "accept",
            "status_code": "200",
            "gross_amount": "500000.00",
        }).encode()

        # Disable signature verification for this test
        with patch.object(pa_wsgi, "_midtrans_webhook_secret", return_value=""):
            status, _, body = _run_wsgi("POST", "/api/midtrans-callback", body=payload)

        assert status == "200 OK"
        data = _json(body)
        assert data["status"] == "active"

        # Verify subscription status updated
        subs = pa_wsgi._load_subscriptions()
        assert subs["docai-starter-abc123"]["status"] == "active"

        # Verify API key tier upgraded
        usage = pa_wsgi._load_usage()
        assert usage["docai-dev-key-12345"]["tier"] == "starter"

    def test_callback_settlement_activates(self):
        """transaction_status=settlement also activates."""
        subs = pa_wsgi._load_subscriptions()
        subs["docai-growth-xyz"] = {
            "tier": "growth", "email": "x@y.com", "api_key": "docai-dev-key-12345",
            "order_id": "docai-growth-xyz", "amount": 5_000_000, "status": "pending",
        }
        pa_wsgi._save_subscriptions(subs)
        usage = pa_wsgi._load_usage()
        usage["docai-dev-key-12345"] = {"tier": "free", "calls_this_month": 0, "last_call": None, "total_calls": 0}
        pa_wsgi._save_usage(usage)

        payload = json.dumps({
            "order_id": "docai-growth-xyz",
            "transaction_status": "settlement",
            "fraud_status": "accept",
            "status_code": "200",
            "gross_amount": "5000000.00",
        }).encode()

        with patch.object(pa_wsgi, "_midtrans_webhook_secret", return_value=""):
            status, _, body = _run_wsgi("POST", "/api/midtrans-callback", body=payload)

        assert status == "200 OK"
        assert _json(body)["status"] == "active"

    def test_callback_cancel_marks_failed(self):
        """transaction_status=cancel → failed."""
        subs = pa_wsgi._load_subscriptions()
        subs["docai-scale-001"] = {
            "tier": "scale", "email": "z@z.com", "api_key": "docai-dev-key-12345",
            "order_id": "docai-scale-001", "amount": 30_000_000, "status": "pending",
        }
        pa_wsgi._save_subscriptions(subs)

        payload = json.dumps({
            "order_id": "docai-scale-001",
            "transaction_status": "cancel",
            "fraud_status": "accept",
            "status_code": "200",
            "gross_amount": "30000000.00",
        }).encode()

        with patch.object(pa_wsgi, "_midtrans_webhook_secret", return_value=""):
            status, _, body = _run_wsgi("POST", "/api/midtrans-callback", body=payload)

        assert status == "200 OK"
        assert _json(body)["status"] == "failed"

    def test_callback_pending_stays_pending(self):
        """transaction_status=pending → pending."""
        subs = pa_wsgi._load_subscriptions()
        subs["docai-starter-pend"] = {
            "tier": "starter", "email": "p@p.com", "api_key": "",
            "order_id": "docai-starter-pend", "amount": 500_000, "status": "pending",
        }
        pa_wsgi._save_subscriptions(subs)

        payload = json.dumps({
            "order_id": "docai-starter-pend",
            "transaction_status": "pending",
            "fraud_status": "accept",
            "status_code": "202",
            "gross_amount": "500000.00",
        }).encode()

        with patch.object(pa_wsgi, "_midtrans_webhook_secret", return_value=""):
            status, _, body = _run_wsgi("POST", "/api/midtrans-callback", body=payload)

        assert status == "200 OK"
        assert _json(body)["status"] == "pending"

    def test_callback_unknown_order_returns_200(self):
        """Unknown order_id → 200 OK (Midtrans always expects 200)."""
        payload = json.dumps({
            "order_id": "unknown-order-123",
            "transaction_status": "capture",
            "fraud_status": "accept",
            "status_code": "200",
            "gross_amount": "500000.00",
        }).encode()

        with patch.object(pa_wsgi, "_midtrans_webhook_secret", return_value=""):
            status, _, body = _run_wsgi("POST", "/api/midtrans-callback", body=payload)

        assert status == "200 OK"
        assert _json(body)["status"] == "unknown_order"

    def test_callback_invalid_signature_rejected(self):
        """Invalid X-Signature → 403 when webhook secret is set."""
        payload = json.dumps({
            "order_id": "test-123",
            "transaction_status": "capture",
            "fraud_status": "accept",
            "status_code": "200",
            "gross_amount": "500000.00",
        }).encode()

        with patch.object(pa_wsgi, "_midtrans_webhook_secret", return_value="my-secret-key"):
            status, _, body = _run_wsgi(
                "POST", "/api/midtrans-callback",
                body=payload,
                extra_headers={"X-Signature": "wrong-signature-value"},
            )

        assert status == "403 Forbidden"
        assert "invalid_signature" in _json(body)["error"]

    def test_callback_valid_signature_accepted(self):
        """Valid X-Signature → 200 OK."""
        secret = "test-webhook-secret"
        order_id = "docai-test-sig"
        status_code = "200"
        gross_amount = "500000.00"

        body_str = order_id + status_code + gross_amount + secret
        valid_sig = hashlib.sha512(body_str.encode("utf-8")).hexdigest()

        # Create the pending subscription first
        subs = pa_wsgi._load_subscriptions()
        subs[order_id] = {
            "tier": "starter", "email": "sig@test.com", "api_key": "docai-dev-key-12345",
            "order_id": order_id, "amount": 500_000, "status": "pending",
        }
        pa_wsgi._save_subscriptions(subs)
        usage = pa_wsgi._load_usage()
        usage["docai-dev-key-12345"] = {"tier": "free", "calls_this_month": 0, "last_call": None, "total_calls": 0}
        pa_wsgi._save_usage(usage)

        payload = json.dumps({
            "order_id": order_id,
            "transaction_status": "capture",
            "fraud_status": "accept",
            "status_code": int(status_code),
            "gross_amount": gross_amount,
        }).encode()

        with patch.object(pa_wsgi, "_midtrans_webhook_secret", return_value=secret):
            status, _, body = _run_wsgi(
                "POST", "/api/midtrans-callback",
                body=payload,
                extra_headers={"X-Signature": valid_sig},
            )

        assert status == "200 OK"
        assert _json(body)["status"] == "active"


# ---------------------------------------------------------------------------
# /api/billing-portal
# ---------------------------------------------------------------------------

class TestBillingPortal:
    def test_portal_no_subscription(self):
        """No active subscription → returns current tier + message."""
        status, _, body = _run_wsgi("GET", "/api/billing-portal", query="api_key=docai-dev-key-12345")
        assert status == "200 OK"
        data = _json(body)
        assert data["subscription"] is None
        assert data["current_tier"] == "free"
        assert "pricing" in data["message"].lower()

    def test_portal_with_active_subscription(self):
        """Active subscription → returns subscription details."""
        subs = pa_wsgi._load_subscriptions()
        subs["docai-starter-123"] = {
            "tier": "starter", "email": "u@u.com", "api_key": "docai-dev-key-12345",
            "order_id": "docai-starter-123", "amount": 500_000,
            "status": "active", "created_at": "2025-01-01T00:00:00Z",
        }
        pa_wsgi._save_subscriptions(subs)
        usage = pa_wsgi._load_usage()
        usage["docai-dev-key-12345"] = {"tier": "starter", "calls_this_month": 0, "last_call": None, "total_calls": 0}
        pa_wsgi._save_usage(usage)

        status, _, body = _run_wsgi("GET", "/api/billing-portal", query="api_key=docai-dev-key-12345")
        assert status == "200 OK"
        data = _json(body)
        assert data["subscription"]["tier"] == "starter"
        assert data["subscription"]["status"] == "active"
        assert data["current_tier"] == "starter"
        # Should list other plans as upgrade options
        assert len(data["upgrade_plans"]) == 2

    def test_portal_missing_api_key(self):
        """Missing api_key → 400."""
        status, _, body = _run_wsgi("GET", "/api/billing-portal", query="")
        assert status == "400 Bad Request"
        assert "api_key" in _json(body)["message"].lower()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestMidtransHelpers:
    def test_midtrans_base_url_sandbox(self):
        with patch.dict(os.environ, {"MIDTRANS_IS_PRODUCTION": "false"}, clear=False):
            assert pa_wsgi._midtrans_base_url() == "https://api.sandbox.midtrans.com"

    def test_midtrans_base_url_production(self):
        with patch.dict(os.environ, {"MIDTRANS_IS_PRODUCTION": "true"}, clear=False):
            assert pa_wsgi._midtrans_base_url() == "https://api.midtrans.com"

    def test_midtrans_snap_url_sandbox(self):
        with patch.dict(os.environ, {"MIDTRANS_IS_PRODUCTION": "false"}, clear=False):
            assert "sandbox" in pa_wsgi._midtrans_snap_url()

    def test_midtrans_snap_url_production(self):
        with patch.dict(os.environ, {"MIDTRANS_IS_PRODUCTION": "true"}, clear=False):
            assert "app.midtrans.com/snap/snap.js" in pa_wsgi._midtrans_snap_url()

    def test_midtrans_plans_all_have_required_fields(self):
        for tier, plan in pa_wsgi.MIDTRANS_PLANS.items():
            assert "plan_id" in plan, f"{tier} missing plan_id"
            assert "name" in plan, f"{tier} missing name"
            assert "price" in plan, f"{tier} missing price"
            assert "quota" in plan, f"{tier} missing quota"
            assert plan["price"] > 0, f"{tier} price must be positive"

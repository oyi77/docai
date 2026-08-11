"""Pure-WSGI adapter for PythonAnywhere.

Serves the same endpoints as the FastAPI app in ``docai.api`` but with zero
framework dependencies (no fastapi / a2wsgi / anyio), so it runs reliably
under PythonAnywhere's uWSGI worker:

    GET  /health        → {"status": "ok", "banks": [...]}
    GET  /              → static demo page (web/index.html)
    GET  /docs          → Swagger UI HTML
    GET  /openapi.json  → OpenAPI 3.0 spec
    POST /parse         → multipart PDF upload, JSON or CSV response
    POST /verify-income → parse + income verification report

The FastAPI app remains the canonical API for local development; this module
is a thin, synchronous WSGI mirror used only for PA hosting.
"""

from __future__ import annotations

import calendar
import io
import json
import os
import re
import secrets
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

from python_multipart import parse_form

from docai.base import ParseError, PasswordProtectedError
from docai.parsers.registry import get_parser, list_banks
from docai.serialization import result_to_csv, result_to_dict
from docai.validation import ValidationError, validate_statement

# --- Midtrans (configured via env vars) ------------------------------------
#
# MIDTRANS_MERCHANT_ID  — Midtrans Merchant ID (G166976201)
# MIDTRANS_SERVER_KEY   — Midtrans server key (Secret or Basic auth)
# MIDTRANS_CLIENT_KEY   — Midtrans client key (for Snap front-end)
# MIDTRANS_IS_PRODUCTION — "true" for production, "false" (default) for sandbox
# MIDTRANS_WEBHOOK_SECRET — SHA-512 signature verification key (defaults to server key)
#
# Sandbox:  https://api.sandbox.midtrans.com  |  https://app.sandbox.midtrans.com/snap/snap.js
# Production: https://api.midtrans.com         |  https://app.midtrans.com/snap/snap.js
#
import hashlib
import hmac as _hmac
import base64 as _b64

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
_USAGE_FILE = Path(__file__).resolve().parent / "usage.json"
_CONTACT_FILE = Path(__file__).resolve().parent / "contact_messages.json"
_SIGNUP_RATE_FILE = Path(__file__).resolve().parent / "signup_usage.json"

# --- Tier limits --------------------------------------------------------------

TIER_LIMITS = {
    "free": 100,
    "starter": 500,
    "growth": 5000,
    "scale": 50000,
    "enterprise": 0,  # 0 = unlimited
}

# --- API key authentication ---------------------------------------------------

API_KEYS: dict[str, dict] = {
    "docai-dev-key-12345": {"tier": "free", "name": "Development"},
}

_EXEMPT_PATHS = frozenset({"/health", "/", "/docs", "/openapi.json", "/signup", "/contact", "/api/subscribe", "/api/midtrans-callback", "/api/billing-portal"})


def _check_api_key(environ) -> None:
    """Raise if X-API-Key header is missing/invalid. Exempt paths skip check."""
    path = environ.get("PATH_INFO", "") or "/"
    if path in _EXEMPT_PATHS:
        return
    key = environ.get("HTTP_X_API_KEY", "")
    if not key:
        raise PermissionError("Missing or invalid X-API-Key header")
    # Check hardcoded keys first, then dynamically-created keys in usage.json
    if key in API_KEYS:
        return
    usage = _load_usage()
    if key in usage:
        return
    raise PermissionError("Missing or invalid X-API-Key header")


def _get_api_key(environ) -> str:
    """Get API key from environ."""
    return environ.get("HTTP_X_API_KEY", "")


# --- Usage tracking ----------------------------------------------------------

def _load_usage() -> dict:
    """Load usage data from usage.json."""
    try:
        return json.loads(_USAGE_FILE.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_usage(data: dict) -> None:
    """Write usage data to usage.json."""
    _USAGE_FILE.write_text(json.dumps(data, indent=2), "utf-8")


def _track_usage(api_key: str) -> Tuple[bool, int, int]:
    """Increment counter for the key and check limits.

    Returns (allowed, remaining, limit).
    """
    usage = _load_usage()
    key_data = usage.get(api_key, {
        "tier": "free",
        "calls_this_month": 0,
        "last_call": None,
        "total_calls": 0,
    })

    # Check current month
    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")

    # If the key has never been used, initialize
    if key_data.get("last_call") is None:
        key_data["calls_this_month"] = 0
    else:
        # Check if we're in a new month
        last_call_month = key_data["last_call"][:7]
        if last_call_month != current_month:
            key_data["calls_this_month"] = 0

    tier = key_data.get("tier", "free")
    limit = TIER_LIMITS.get(tier, 100)

    # Check if limit is exceeded
    if limit != 0 and key_data["calls_this_month"] >= limit:
        return (False, 0, limit)

    # Increment counter
    key_data["calls_this_month"] += 1
    key_data["total_calls"] += 1
    key_data["last_call"] = now.isoformat()

    usage[api_key] = key_data
    _save_usage(usage)

    remaining = max(0, limit - key_data["calls_this_month"]) if limit != 0 else 999999
    return (True, remaining, limit)


def _check_rate_limit(api_key: str) -> Tuple[bool, int, int]:
    """Check rate limit without incrementing.

    Returns (allowed, remaining, limit).
    """
    usage = _load_usage()
    key_data = usage.get(api_key, {
        "tier": "free",
        "calls_this_month": 0,
        "last_call": None,
        "total_calls": 0,
    })

    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")

    if key_data.get("last_call") is not None:
        last_call_month = key_data["last_call"][:7]
        if last_call_month != current_month:
            key_data["calls_this_month"] = 0

    tier = key_data.get("tier", "free")
    limit = TIER_LIMITS.get(tier, 100)

    if limit != 0 and key_data["calls_this_month"] >= limit:
        return (False, 0, limit)

    remaining = max(0, limit - key_data["calls_this_month"]) if limit != 0 else 999999
    return (True, remaining, limit)


def _get_reset_timestamp() -> int:
    """Get unix timestamp of end of current month (UTC)."""
    now = datetime.now(timezone.utc)
    _, last_day = calendar.monthrange(now.year, now.month)
    reset = datetime(now.year, now.month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return int(reset.timestamp())


def _rate_limit_headers(api_key: str) -> List[Tuple[str, str]]:
    """Generate rate limit headers for a response."""
    allowed, remaining, limit = _check_rate_limit(api_key)
    reset = _get_reset_timestamp()
    limit_str = str(limit) if limit != 0 else "unlimited"
    return [
        ("X-RateLimit-Limit", limit_str),
        ("X-RateLimit-Remaining", str(remaining)),
        ("X-RateLimit-Reset", str(reset)),
    ]


def _rate_limit_start_response(start_response, api_key: str):
    """Create a wrapper around start_response that adds rate limit headers."""
    def wrapper(status, headers):
        allowed, remaining, limit = _check_rate_limit(api_key)
        reset = _get_reset_timestamp()
        limit_str = str(limit) if limit != 0 else "unlimited"
        headers = list(headers)
        headers.extend([
            ("X-RateLimit-Limit", limit_str),
            ("X-RateLimit-Remaining", str(remaining)),
            ("X-RateLimit-Reset", str(reset)),
        ])
        return start_response(status, headers)
    return wrapper


# --- PDF decryption ----------------------------------------------------------

def _decrypt_pdf_wsgi(src_path: str, password: str) -> str:
    """Decrypt a password-protected PDF to a temp file.  Caller cleans up."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(src_path)
    if not reader.decrypt(password):
        raise PasswordProtectedError("Incorrect password for this PDF.")
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    with open(tmp.name, "wb") as f:
        writer.write(f)
    return tmp.name


# --- Response helpers --------------------------------------------------------

def _json_response(
    start_response,
    status: str,
    payload,
    extra_headers: List[Tuple[str, str]] = (),
):
    body = json.dumps(payload).encode("utf-8")
    start_response(
        status,
        [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
        + list(extra_headers),
    )
    return [body]


def _file_response(start_response, path: Path, media_type: str):
    data = path.read_bytes()
    start_response(
        "200 OK",
        [("Content-Type", media_type), ("Content-Length", str(len(data)))],
    )
    return [data]


# --- Rate limit response ----------------------------------------------------

def _rate_limit_exceeded(start_response, api_key: str):
    """Return 429 Too Many Requests."""
    usage = _load_usage()
    key_data = usage.get(api_key, {})
    tier = key_data.get("tier", "free")
    limit = TIER_LIMITS.get(tier, 100)
    reset_ts = _get_reset_timestamp()
    reset_iso = datetime.fromtimestamp(reset_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "error": "rate_limit_exceeded",
        "message": f"You have exceeded your monthly limit of {limit} API calls. Upgrade your plan at docaiid.pythonanywhere.com/pricing",
        "limit": limit,
        "remaining": 0,
        "reset": reset_iso,
    }

    rate_headers = [
        ("X-RateLimit-Limit", str(limit)),
        ("X-RateLimit-Remaining", "0"),
        ("X-RateLimit-Reset", str(reset_ts)),
    ]

    return _json_response(start_response, "429 Too Many Requests", payload, rate_headers)


# --- Request handlers --------------------------------------------------------

def _handle_parse(environ, start_response):
    content_type = environ.get("CONTENT_TYPE", "")
    length = environ.get("CONTENT_LENGTH") or "0"
    try:
        length = int(length)
    except ValueError:
        length = 0
    if length <= 0:
        return _json_response(
            start_response,
            "400 Bad Request",
            {"error": "invalid_request", "message": "Empty request body"},
        )
    raw = environ["wsgi.input"].read(length)

    qs = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
    fmt = qs.get("format", ["json"])[0]
    if fmt not in ("json", "csv"):
        return _json_response(
            start_response,
            "400 Bad Request",
            {"error": "invalid_request", "message": "format must be json or csv"},
        )

    fields: dict = {}
    uploaded = []

    def on_field(f):
        if f.field_name is not None and f.value is not None:
            fields[f.field_name.decode("utf-8", "replace")] = f.value.decode(
                "utf-8", "replace"
            )

    def on_file(f):
        uploaded.append(f)

    parse_form(
        headers={"Content-Type": content_type},
        input_stream=io.BytesIO(raw),
        on_field=on_field,
        on_file=on_file,
    )

    bank = fields.get("bank", "bca")
    password = fields.get("password") or None
    if not uploaded:
        return _json_response(
            start_response,
            "400 Bad Request",
            {"error": "invalid_request", "message": "No file uploaded (field 'file')"},
        )
    file_obj = uploaded[0].file_object
    file_obj.seek(0)  # python_multipart leaves the stream at EOF after parsing
    data = file_obj.read()
    if not data:
        return _json_response(
            start_response,
            "400 Bad Request",
            {"error": "invalid_request", "message": "Empty file uploaded"},
        )

    tmp_path = None
    decrypted_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        parser = get_parser(bank)
        try:
            result = parser.parse(tmp_path)
        except PasswordProtectedError:
            if not password:
                raise
            decrypted_path = _decrypt_pdf_wsgi(tmp_path, password)
            result = parser.parse(decrypted_path)
    except PasswordProtectedError as e:
        return _json_response(
            start_response,
            "400 Bad Request",
            {"error": "password_protected", "message": str(e)},
        )
    except ParseError as e:
        return _json_response(
            start_response,
            "400 Bad Request",
            {"error": "parse_error", "message": str(e)},
        )
    except ValueError as e:
        return _json_response(
            start_response,
            "400 Bad Request",
            {"error": "invalid_request", "message": str(e)},
        )
    finally:
        for p in (tmp_path, decrypted_path):
            if p is not None:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    balance_status = "passed"
    validation_error = None
    try:
        validate_statement(result)
    except ValidationError as e:
        balance_status = "failed"
        validation_error = str(e)

    if fmt == "csv":
        csv_text = result_to_csv(result)
        body = csv_text.encode("utf-8")
        start_response(
            "200 OK",
            [
                ("Content-Type", "text/csv; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Content-Disposition", 'attachment; filename="mutasi.csv"'),
            ],
        )
        return [body]

    payload = result_to_dict(result, balance_status)
    if validation_error is not None:
        payload["validation_error"] = validation_error
    return _json_response(start_response, "200 OK", payload)


# --- Income verification ------------------------------------------------------

try:
    from docai.scoring import analyze_income as _analyze_income  # type: ignore[import-untyped]
except ImportError:

    def _analyze_income(result):  # type: ignore[misc]
        """Stub scoring — returns basic report when scoring module is unavailable."""
        return {
            "verification_score": 0,
            "confidence": "low",
            "detected_monthly_income": 0,
            "income_source": "undetected",
            "salary_months_detected": 0,
            "monthly_incomes": [],
            "consistency_score": 0,
            "income_cv": 0.0,
            "has_gaps": False,
            "gap_months": [],
            "fraud_flags": [],
            "balance_valid": True,
            "has_suspicious_patterns": False,
            "statement_period": result.statement_period,
            "total_months_covered": 0,
            "total_transactions": len(result.transactions),
            "total_credit": float(result.total_credit),
            "total_debit": float(result.total_debit),
            "bank": result.bank.value,
            "account_number": result.account_number,
        }


def _handle_verify_income(environ, start_response):
    """POST /verify-income — parse + income verification report."""
    content_type = environ.get("CONTENT_TYPE", "")
    length = environ.get("CONTENT_LENGTH") or "0"
    try:
        length = int(length)
    except ValueError:
        length = 0
    if length <= 0:
        return _json_response(
            start_response,
            "400 Bad Request",
            {"error": "invalid_request", "message": "Empty request body"},
        )
    raw = environ["wsgi.input"].read(length)

    fields: dict = {}
    uploaded = []

    def on_field(f):
        if f.field_name is not None and f.value is not None:
            fields[f.field_name.decode("utf-8", "replace")] = f.value.decode(
                "utf-8", "replace"
            )

    def on_file(f):
        uploaded.append(f)

    parse_form(
        headers={"Content-Type": content_type},
        input_stream=io.BytesIO(raw),
        on_field=on_field,
        on_file=on_file,
    )

    bank = fields.get("bank", "bca")
    password = fields.get("password") or None
    if not uploaded:
        return _json_response(
            start_response,
            "400 Bad Request",
            {"error": "invalid_request", "message": "No file uploaded (field 'file')"},
        )
    file_obj = uploaded[0].file_object
    file_obj.seek(0)
    data = file_obj.read()
    if not data:
        return _json_response(
            start_response,
            "400 Bad Request",
            {"error": "invalid_request", "message": "Empty file uploaded"},
        )

    tmp_path = None
    decrypted_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        parser = get_parser(bank)
        try:
            result = parser.parse(tmp_path)
        except PasswordProtectedError:
            if not password:
                raise
            decrypted_path = _decrypt_pdf_wsgi(tmp_path, password)
            result = parser.parse(decrypted_path)
    except PasswordProtectedError as e:
        return _json_response(
            start_response,
            "400 Bad Request",
            {"error": "password_protected", "message": str(e)},
        )
    except ParseError as e:
        return _json_response(
            start_response,
            "400 Bad Request",
            {"error": "parse_error", "message": str(e)},
        )
    except ValueError as e:
        return _json_response(
            start_response,
            "400 Bad Request",
            {"error": "invalid_request", "message": str(e)},
        )
    finally:
        for p in (tmp_path, decrypted_path):
            if p is not None:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    balance_status = "passed"
    try:
        validate_statement(result)
    except ValidationError:
        balance_status = "failed"

    from dataclasses import asdict
    from decimal import Decimal as _D

    report = _analyze_income(result)
    report_dict = asdict(report)
    for key in ("detected_monthly_income", "total_credit", "total_debit"):
        if isinstance(report_dict.get(key), _D):
            report_dict[key] = float(report_dict[key])
    for mi in report_dict.get("monthly_incomes", []):
        if isinstance(mi.get("amount"), _D):
            mi["amount"] = float(mi["amount"])
    report_dict["balance_valid"] = balance_status == "passed"
    report_dict["bank"] = result.bank.value
    report_dict["account_number"] = result.account_number
    return _json_response(start_response, "200 OK", report_dict)


# --- Static HTML serving -----------------------------------------------------

def _serve_static_html(environ, start_response, path: str):
    """Serve a static HTML file from WEB_DIR if it exists."""
    if path.endswith(".html"):
        candidate = WEB_DIR / path.lstrip("/")
        if candidate.exists():
            return _file_response(start_response, candidate, "text/html; charset=utf-8")
    return None


# --- OpenAPI / Swagger docs --------------------------------------------------

def _openapi_spec() -> dict:
    """Return the OpenAPI 3.0 specification."""
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "DocAI Verify",
            "description": "Income verification API for Indonesian fintech",
            "version": "2.0.0",
        },
        "servers": [{"url": "https://docaiid.pythonanywhere.com"}],
        "paths": {
            "/health": {
                "get": {
                    "summary": "Health check",
                    "description": "Returns service status and supported banks.",
                    "responses": {
                        "200": {
                            "description": "Service is healthy",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {"type": "string", "example": "ok"},
                                            "banks": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                                "example": ["bca", "mandiri"],
                                            },
                                        },
                                    }
                                }
                            },
                        },
                    },
                }
            },
            "/parse": {
                "post": {
                    "summary": "Parse bank statement PDF",
                    "description": "Upload a bank statement PDF and receive structured data in JSON or CSV format.",
                    "security": [{"ApiKeyAuth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "required": ["file"],
                                    "properties": {
                                        "file": {
                                            "type": "string",
                                            "format": "binary",
                                            "description": "Bank statement PDF file",
                                        },
                                        "bank": {
                                            "type": "string",
                                            "default": "bca",
                                            "description": "Bank identifier (bca, mandiri, etc.)",
                                        },
                                        "password": {
                                            "type": "string",
                                            "description": "PDF password (DOB DDMMYYYY) for encrypted statements",
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "parameters": [
                        {
                            "name": "format",
                            "in": "query",
                            "schema": {"type": "string", "enum": ["json", "csv"], "default": "json"},
                            "description": "Response format",
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Parsed statement data",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ParseResponse"}
                                },
                                "text/csv": {
                                    "schema": {"type": "string"}
                                },
                            },
                        },
                        "400": {
                            "description": "Invalid request (bad format, missing file, password error, parse error)",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                                }
                            },
                        },
                        "401": {
                            "description": "Missing or invalid API key",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                                }
                            },
                        },
                        "429": {
                            "description": "Rate limit exceeded",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RateLimitError"}
                                }
                            },
                        },
                        "500": {
                            "description": "Internal server error",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                                }
                            },
                        },
                    },
                }
            },
            "/verify-income": {
                "post": {
                    "summary": "Verify income from bank statement",
                    "description": "Parse a bank statement and return an income verification report.",
                    "security": [{"ApiKeyAuth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "required": ["file"],
                                    "properties": {
                                        "file": {
                                            "type": "string",
                                            "format": "binary",
                                            "description": "Bank statement PDF file",
                                        },
                                        "bank": {
                                            "type": "string",
                                            "default": "bca",
                                            "description": "Bank identifier (bca, mandiri, etc.)",
                                        },
                                        "password": {
                                            "type": "string",
                                            "description": "PDF password (DOB DDMMYYYY) for encrypted statements",
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Income verification report",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/VerifyIncomeResponse"}
                                }
                            },
                        },
                        "400": {
                            "description": "Invalid request (bad format, missing file, password error, parse error)",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                                }
                            },
                        },
                        "401": {
                            "description": "Missing or invalid API key",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                                }
                            },
                        },
                        "429": {
                            "description": "Rate limit exceeded",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/RateLimitError"}
                                }
                            },
                        },
                        "500": {
                            "description": "Internal server error",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                                }
                            },
                        },
                    },
                }
            },
        },
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                }
            },
            "schemas": {
                "ErrorResponse": {
                    "type": "object",
                    "properties": {
                        "error": {"type": "string", "example": "unauthorized"},
                        "message": {"type": "string", "example": "Missing or invalid X-API-Key header"},
                    },
                },
                "RateLimitError": {
                    "type": "object",
                    "properties": {
                        "error": {"type": "string", "example": "rate_limit_exceeded"},
                        "message": {"type": "string"},
                        "limit": {"type": "integer", "example": 100},
                        "remaining": {"type": "integer", "example": 0},
                        "reset": {"type": "string", "format": "date-time", "example": "2026-09-01T00:00:00Z"},
                    },
                },
                "ParseResponse": {
                    "type": "object",
                    "properties": {
                        "bank": {"type": "string", "example": "bca"},
                        "account_number": {"type": "string", "example": "1234567890"},
                        "account_name": {"type": "string", "example": "John Doe"},
                        "statement_period": {"type": "string", "example": "01/01/2026 - 31/01/2026"},
                        "opening_balance": {"type": "number", "example": 5000000.0},
                        "closing_balance": {"type": "number", "example": 9929972.0},
                        "currency": {"type": "string", "example": "IDR"},
                        "balance_check": {"type": "string", "example": "passed"},
                        "validation_error": {"type": "string"},
                        "transactions": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Transaction"},
                        },
                    },
                },
                "Transaction": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "example": "02/01/2026"},
                        "description": {"type": "string", "example": "TRANSFER DARI BCA"},
                        "debit": {"type": "number", "example": 0},
                        "credit": {"type": "number", "example": 1500000},
                        "balance": {"type": "number", "example": 5150000},
                        "reference": {"type": "string", "example": "TRX12345"},
                    },
                },
                "VerifyIncomeResponse": {
                    "type": "object",
                    "properties": {
                        "verification_score": {"type": "number", "example": 85},
                        "confidence": {"type": "string", "example": "high"},
                        "detected_monthly_income": {"type": "number", "example": 15000000},
                        "income_source": {"type": "string", "example": "salary"},
                        "salary_months_detected": {"type": "integer", "example": 6},
                        "monthly_incomes": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/MonthlyIncome"},
                        },
                        "consistency_score": {"type": "number", "example": 0.92},
                        "income_cv": {"type": "number", "example": 0.15},
                        "has_gaps": {"type": "boolean", "example": False},
                        "gap_months": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "fraud_flags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "balance_valid": {"type": "boolean", "example": True},
                        "has_suspicious_patterns": {"type": "boolean", "example": False},
                        "statement_period": {"type": "string", "example": "01/01/2026 - 31/01/2026"},
                        "total_months_covered": {"type": "integer", "example": 6},
                        "total_transactions": {"type": "integer", "example": 120},
                        "total_credit": {"type": "number", "example": 90000000},
                        "total_debit": {"type": "number", "example": 45000000},
                        "bank": {"type": "string", "example": "bca"},
                        "account_number": {"type": "string", "example": "1234567890"},
                    },
                },
                "MonthlyIncome": {
                    "type": "object",
                    "properties": {
                        "month": {"type": "string", "example": "2026-01"},
                        "amount": {"type": "number", "example": 15000000},
                        "source": {"type": "string", "example": "salary"},
                        "confidence": {"type": "string", "example": "high"},
                    },
                },
            },
        },
    }


_SWAGGER_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DocAI Verify — API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.10.5/swagger-ui.css" />
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 0;
            background: #0b1f3a;
            color: #e2e8f0;
        }
        .topbar {
            background: #1a1a2e;
            padding: 12px 24px;
            display: flex;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;
        }
        .topbar img {
            height: 32px;
        }
        .topbar h1 {
            color: #fff;
            font-size: 18px;
            margin: 0;
        }
        .topbar a {
            color: #4fc3f7;
            text-decoration: none;
            font-size: 14px;
        }
        .topbar-links {
            margin-left: auto;
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .cta-btn {
            display: inline-block;
            background: #0e7a3d;
            color: #fff !important;
            text-decoration: none;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 600;
            white-space: nowrap;
            transition: background 0.2s;
        }
        .cta-btn:hover {
            background: #10a34e;
        }
        .try-banner {
            background: #142640;
            border-bottom: 1px solid #2D3748;
            padding: 10px 24px;
            text-align: center;
            font-size: 14px;
            color: #94a3b8;
        }
        .try-banner a {
            color: #4ade80;
            text-decoration: none;
            font-weight: 600;
        }
        .try-banner a:hover {
            text-decoration: underline;
        }
        #swagger-ui {
            max-width: 960px;
            margin: 0 auto;
            padding: 16px;
        }
        /* Swagger UI overrides for dark theme */
        #swagger-ui .scheme-container {
            background: #0f2744 !important;
            box-shadow: none !important;
        }
        #swagger-ui .opblock .opblock-summary {
            border-color: #2D3748;
        }
        #swagger-ui .opblock.opblock-get { border-color: #3182ce; }
        #swagger-ui .opblock.opblock-post { border-color: #38a169; }
        #swagger-ui .opblock.opblock-put { border-color: #d69e2e; }
        #swagger-ui .opblock.opblock-delete { border-color: #e53e3e; }
        #swagger-ui .btn {
            font-family: inherit;
        }
        #swagger-ui .model-box {
            background: #0f2744;
        }
        #swagger-ui table thead tr td,
        #swagger-ui table thead tr th {
            border-bottom: 1px solid #2D3748;
        }
        /* Responsive */
        @media (max-width: 640px) {
            .topbar {
                flex-direction: column;
                align-items: flex-start;
                gap: 10px;
            }
            .topbar-links {
                margin-left: 0;
                flex-wrap: wrap;
                gap: 10px;
            }
            #swagger-ui {
                padding: 8px;
            }
        }
    </style>
</head>
<body>
    <div class="topbar">
        <img src="https://docaiid.pythonanywhere.com/assets/logo_docai_400.png" alt="DocAI" onerror="this.style.display='none'">
        <h1>DocAI Verify API</h1>
        <div class="topbar-links">
            <a href="/openapi.json">OpenAPI Spec</a>
            <a href="/signup" class="cta-btn">🔑 Get Free API Key</a>
        </div>
    </div>
    <div class="try-banner">
        Try the API live — demo key pre-loaded. Or
        <a href="/signup">get your own key</a> &rarr;
    </div>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5.10.5/swagger-ui-bundle.js"></script>
    <script>
        SwaggerUIBundle({
            url: '/openapi.json',
            dom_id: '#swagger-ui',
            deepLinking: true,
            presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
            layout: "BaseLayout",
            requestInterceptor: function(req) {
                if (req.headers && !req.headers['X-API-Key']) {
                    req.headers['X-API-Key'] = 'docai-dev-key-12345';
                }
                return req;
            },
            onComplete: function() {
                var input = document.querySelector('.swagger-ui .auth-container input[type=text], .swagger-ui .auth-container input[name=apiKey]');
                if (input) {
                    input.value = 'docai-dev-key-12345';
                }
            }
        });
    </script>
</body>
</html>"""


def _handle_docs(environ, start_response):
    """GET /docs — Swagger UI HTML page."""
    body = _SWAGGER_UI_HTML.encode("utf-8")
    start_response(
        "200 OK",
        [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


def _handle_openapi_json(environ, start_response):
    """GET /openapi.json — OpenAPI 3.0 specification."""
    spec = _openapi_spec()
    body = json.dumps(spec, indent=2).encode("utf-8")
    start_response(
        "200 OK",
        [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


# --- Self-service signup -----------------------------------------------------

_SIGNUP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DocAI Verify — Get Your API Key</title>
<style>
  body { font-family: system-ui, -apple-system, sans-serif; background: #0b1f3a; color: #e2e8f0; margin: 0; padding: 40px 20px; }
  .card { max-width: 560px; margin: 0 auto; background: #142640; border: 1px solid #2D3748; border-radius: 12px; padding: 40px 32px; }
  h1 { font-size: 24px; margin: 0 0 8px; }
  p.sub { color: #a0aec0; margin: 0 0 24px; }
  label { display: block; font-size: 14px; font-weight: 600; margin-bottom: 6px; }
  input[type="email"], input[type="text"] {
    width: 100%; padding: 12px 16px; border: 1px solid #2D3748; border-radius: 8px;
    background: #0D1117; color: #E2E8F0; font-size: 16px; margin-bottom: 16px;
  }
  input:focus { outline: none; border-color: #4ade80; }
  button { width: 100%; padding: 14px; background: #0e7a3d; color: #fff; border: none; border-radius: 8px; font-size: 16px; font-weight: 700; cursor: pointer; }
  button:hover { background: #0a6330; }
  button:disabled { opacity: 0.6; cursor: not-allowed; }
  #result { display: none; margin-top: 20px; padding: 20px; border-radius: 8px; background: #1A2332; border: 1px solid #48BB78; }
  #result h3 { color: #48BB78; margin: 0 0 12px; font-size: 16px; }
  code.key { display: block; padding: 12px; background: #0D1117; border-radius: 6px; font-family: monospace; word-break: break-all; color: #E2E8F0; margin-bottom: 10px; font-size: 14px; }
  #result p { color: #a0aec0; font-size: 14px; margin: 0; }
  .error { border-color: #e53e3e !important; }
  .error h3 { color: #e53e3e !important; }
  a.back { color: #4ade80; font-size: 14px; display: inline-block; margin-top: 16px; }
</style>
</head>
<body>
<div class="card">
  <h1>Get Your API Key</h1>
  <p class="sub">Start verifying incomes in 2 minutes. No credit card required. Free tier: 100 verifications/month.</p>
  <div id="form-wrap">
    <label for="email">Email address</label>
    <input type="email" id="email" placeholder="you@company.com" required>
    <label for="company">Company name</label>
    <input type="text" id="company" placeholder="Acme Corp" required>
    <div style="position:absolute;left:-9999px;" aria-hidden="true"><input type="text" id="website" name="website" tabindex="-1" autocomplete="off"></div>
    <button id="submit-btn" onclick="doSignup()">Get My Free API Key</button>
  </div>
  <div id="result">
    <h3 id="result-title"></h3>
    <code class="key" id="result-key"></code>
    <p id="result-msg"></p>
  </div>
  <a class="back" href="/">Back to DocAI Verify</a>
</div>
<script>
async function doSignup() {
  var btn = document.getElementById('submit-btn');
  var email = document.getElementById('email').value.trim();
  var company = document.getElementById('company').value.trim();
  var website = document.getElementById('website').value.trim();
  if (!email || !company) { alert('Please fill in both fields.'); return; }
  btn.textContent = 'Generating...'; btn.disabled = true;
  try {
    var res = await fetch('/signup', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email: email, company: company, website: website}) });
    var data = await res.json();
    if (data.api_key) {
      document.getElementById('result-title').textContent = '\\u2705 Your API key is ready!';
      document.getElementById('result-key').textContent = data.api_key;
      document.getElementById('result-msg').textContent = 'Copy this key and use it in the X-API-Key header. Free tier: ' + data.monthly_limit + ' verifications/month.';
      document.getElementById('form-wrap').style.display = 'none';
      document.getElementById('result').style.display = 'block';
    } else {
      document.getElementById('result-title').textContent = 'Error';
      document.getElementById('result-msg').textContent = data.error || 'Signup failed.';
      document.getElementById('result').style.display = 'block';
      document.getElementById('result').classList.add('error');
      btn.textContent = 'Get My Free API Key'; btn.disabled = false;
    }
  } catch(e) {
    alert('Network error. Please try again.');
    btn.textContent = 'Get My Free API Key'; btn.disabled = false;
  }
}
</script>
</body>
</html>"""


def _generate_signup_key() -> str:
    """Generate a unique API key in format docai-{8hex}-free."""
    return f"docai-{secrets.token_hex(4)}-free"


_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def _handle_signup(environ, start_response):
    """GET /signup — HTML form.  POST /signup — JSON: generate an API key."""
    method = environ.get("REQUEST_METHOD", "GET")

    if method == "GET":
        body = _SIGNUP_HTML.encode("utf-8")
        start_response(
            "200 OK",
            [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body)))],
        )
        return [body]

    # POST — generate key
    length = int(environ.get("CONTENT_LENGTH") or "0")
    if length <= 0:
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": "Empty request body"},
        )
    raw = environ["wsgi.input"].read(length)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": "Invalid JSON"},
        )

    email = (data.get("email") or "").strip()
    company = (data.get("company") or "").strip()
    website = (data.get("website") or "").strip()  # honeypot field

    # Honeypot check — bots fill this, humans don't
    if website:
        return _json_response(start_response, "200 OK", {
            "api_key": f"docai-fake-{secrets.token_hex(4)}-free",
            "tier": "free",
            "monthly_limit": TIER_LIMITS["free"],
            "message": "Your API key is ready. Start verifying now.",
        })

    # Per-IP rate limiting: max 3 signups per 24 hours
    client_ip = environ.get("REMOTE_ADDR", "unknown")
    if not _check_signup_rate(client_ip):
        return _json_response(
            start_response, "429 Too Many Requests",
            {"error": "rate_limited", "message": "Too many signup attempts. Try again in 24 hours."},
        )

    if not email or not _EMAIL_RE.match(email):
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": "Invalid email address"},
        )
    if not company:
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": "Company name is required"},
        )

    # Generate unique key
    usage = _load_usage()
    for _ in range(10):  # retry on collision
        key = _generate_signup_key()
        if key not in usage and key not in API_KEYS:
            break
    else:
        return _json_response(
            start_response, "500 Internal Server Error",
            {"error": "internal_error", "message": "Could not generate unique key"},
        )

    now = datetime.now(timezone.utc)
    usage[key] = {
        "tier": "free",
        "name": company,
        "email": email,
        "calls_this_month": 0,
        "total_calls": 0,
        "last_call": None,
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _save_usage(usage)

    return _json_response(start_response, "200 OK", {
        "api_key": key,
        "tier": "free",
        "monthly_limit": TIER_LIMITS["free"],
        "message": "Your API key is ready. Start verifying now.",
    })


# --- Contact form -----------------------------------------------------------

def _handle_contact(environ, start_response):
    """GET /contact — HTML form.  POST /contact — store message in JSON file."""
    method = environ.get("REQUEST_METHOD", "GET")

    if method == "GET":
        # Serve the static contact.html
        return _serve_static_html(environ, start_response, "contact.html") or _json_response(
            start_response, "404 Not Found",
            {"error": "not_found", "message": "contact page not found"},
        )

    # POST — store message
    length = int(environ.get("CONTENT_LENGTH") or "0")
    if length <= 0:
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": "Empty request body"},
        )
    raw = environ["wsgi.input"].read(length)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": "Invalid JSON"},
        )

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    subject = (data.get("subject") or "").strip()
    message = (data.get("message") or "").strip()

    if not email or not _EMAIL_RE.match(email):
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": "Invalid email address"},
        )
    if not message:
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": "Message is required"},
        )

    # Load existing messages
    try:
        messages = json.loads(_CONTACT_FILE.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        messages = []

    messages.append({
        "name": name,
        "email": email,
        "subject": subject or "Contact Form",
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ip": environ.get("REMOTE_ADDR", "unknown"),
    })

    _CONTACT_FILE.write_text(json.dumps(messages, indent=2, ensure_ascii=False), "utf-8")

    return _json_response(start_response, "200 OK", {
        "status": "ok",
        "message": "Message received. We'll respond within 24 hours.",
    })


# --- Signup rate limiting ----------------------------------------------------

_SIGNUP_RATE_LIMIT = 3  # max signups per IP per 24 hours


def _load_signup_usage() -> dict:
    try:
        return json.loads(_SIGNUP_RATE_FILE.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_signup_usage(data: dict) -> None:
    _SIGNUP_RATE_FILE.write_text(json.dumps(data, indent=2), "utf-8")


def _check_signup_rate(ip: str) -> bool:
    """Return True if signup is allowed, False if rate limited."""
    usage = _load_signup_usage()
    now = datetime.now(timezone.utc)
    ip_data = usage.get(ip, {"attempts": []})

    # Prune attempts older than 24 hours
    cutoff = now.timestamp() - 86400
    ip_data["attempts"] = [t for t in ip_data["attempts"] if t > cutoff]

    if len(ip_data["attempts"]) >= _SIGNUP_RATE_LIMIT:
        usage[ip] = ip_data
        _save_signup_usage(usage)
        return False

    ip_data["attempts"].append(now.timestamp())
    usage[ip] = ip_data
    _save_signup_usage(usage)
    return True


# --- Midtrans Subscription Billing --------------------------------------------
#
# Environment variables consumed:
#   MIDTRANS_SERVER_KEY      — server key (secret / basic auth)
#   MIDTRANS_CLIENT_KEY      — client key (for Snap front-end token)
#   MIDTRANS_IS_PRODUCTION   — "true" | "false" (default sandbox)
#   MIDTRANS_WEBHOOK_SECRET  — SHA-512 signature key for callback verification
#   MIDTRANS_RECURRING_API   — "true" to use Midtrans Recurring API for subscriptions
#
import hashlib as _hashlib
import hmac as _hmac
import base64 as _b64
import uuid as _uuid

# ── Midtrans helpers ─────────────────────────────────────────────────────────

def _midtrans_base_url() -> str:
    """Return Midtrans API base URL depending on sandbox / production."""
    if os.environ.get("MIDTRANS_IS_PRODUCTION", "false").lower() == "true":
        return "https://api.midtrans.com"
    return "https://api.sandbox.midtrans.com"


def _midtrans_snap_url() -> str:
    """Return Midtrans Snap JS URL for the front-end."""
    if os.environ.get("MIDTRANS_IS_PRODUCTION", "false").lower() == "true":
        return "https://app.midtrans.com/snap/snap.js"
    return "https://app.sandbox.midtrans.com/snap/snap.js"


def _midtrans_server_key() -> str:
    """Return the Midtrans server key (empty string if unset)."""
    return os.environ.get("MIDTRANS_SERVER_KEY", "")


def _midtrans_client_key() -> str:
    """Return the Midtrans client key (empty string if unset)."""
    return os.environ.get("MIDTRANS_CLIENT_KEY", "")


def _midtrans_webhook_secret() -> str:
    """Return the Midtrans webhook signature key (empty string if unset).

    Per Midtrans docs, the webhook signature uses SHA-512 of
    (order_id + status_code + gross_amount + SERVER_KEY).
    Falls back to MIDTRANS_SERVER_KEY when MIDTRANS_WEBHOOK_SECRET is unset.
    """
    return os.environ.get("MIDTRANS_WEBHOOK_SECRET", "") or _midtrans_server_key()


# ── Subscription plan mapping ────────────────────────────────────────────────
#
# Prices are in IDR (Indonesian Rupiah). Midtrans handles currency.
# quota: monthly API call limit (-1 = unlimited)

MIDTRANS_PLANS = {
    "starter": {
        "plan_id": "docai-starter",
        "name": "Starter",
        "price": 500_000,       # Rp 500,000/month
        "quota": 1_000,
    },
    "growth": {
        "plan_id": "docai-growth",
        "name": "Growth",
        "price": 5_000_000,     # Rp 5,000,000/month
        "quota": 10_000,
    },
    "scale": {
        "plan_id": "docai-scale",
        "name": "Scale",
        "price": 30_000_000,    # Rp 30,000,000/month
        "quota": -1,            # unlimited
    },
}

# ── Subscription store ───────────────────────────────────────────────────────
# persisted alongside usage.json

_SUBSCRIPTIONS_FILE = Path(__file__).resolve().parent / "subscriptions.json"


def _load_subscriptions() -> dict:
    """Load subscription data from subscriptions.json."""
    try:
        return json.loads(_SUBSCRIPTIONS_FILE.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_subscriptions(data: dict) -> None:
    """Write subscription data to subscriptions.json."""
    _SUBSCRIPTIONS_FILE.write_text(json.dumps(data, indent=2), "utf-8")


# ── Signature verification ───────────────────────────────────────────────────

def _verify_midtrans_signature(body_bytes: bytes, signature: str) -> bool:
    """Verify Midtrans callback signature using SHA-512.

    Midtrans sends X-Signature header = SHA512(order_id + status_code + gross_amount + SERVER_KEY).
    """
    secret = _midtrans_webhook_secret()
    if not secret:
        return False
    try:
        data = json.loads(body_bytes)
    except (json.JSONDecodeError, ValueError):
        return False

    order_id = str(data.get("order_id", ""))
    status_code = str(data.get("status_code", ""))
    gross_amount = str(data.get("gross_amount", ""))
    body_str = order_id + status_code + gross_amount + secret
    expected = _hashlib.sha512(body_str.encode("utf-8")).hexdigest()
    return _hmac.compare_digest(expected, signature)


# ── Midtrans API call helper ─────────────────────────────────────────────────

def _midtrans_api_call(path: str, payload: dict) -> dict:
    """Call Midtrans API and return parsed JSON response.

    Uses basic auth with server key.
    """
    import urllib.request

    server_key = _midtrans_server_key()
    base = _midtrans_base_url()
    url = f"{base}{path}"

    body = json.dumps(payload).encode("utf-8")
    auth_str = _b64.b64encode(f"{server_key}:".encode()).decode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Basic {auth_str}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Subscription handlers ────────────────────────────────────────────────────

def _handle_subscribe(environ, start_response):
    """POST /api/subscribe — create a Midtrans Snap transaction for subscription.

    Input JSON:  {tier: "starter"|"growth"|"scale", email: string, api_key?: string}
    Returns:     {subscription_id, payment_url, token}
    """
    server_key = _midtrans_server_key()
    if not server_key:
        return _json_response(
            start_response,
            "503 Service Unavailable",
            {"error": "midtrans_not_configured", "message": "Midtrans is not configured. Contact support to upgrade."},
        )

    length = int(environ.get("CONTENT_LENGTH") or "0")
    if length <= 0:
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": "Empty request body"},
        )
    raw = environ["wsgi.input"].read(length)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": "Invalid JSON"},
        )

    tier = (data.get("tier") or "").strip().lower()
    email = (data.get("email") or "").strip()
    api_key = (data.get("api_key") or "").strip()

    if tier not in MIDTRANS_PLANS:
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": f"Invalid tier: {tier}. Must be one of: {', '.join(MIDTRANS_PLANS)}"},
        )
    if not email or not _EMAIL_RE.match(email):
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": "Valid email is required"},
        )

    plan = MIDTRANS_PLANS[tier]
    order_id = f"docai-{tier}-{_uuid.uuid4().hex[:12]}"
    host = environ.get("HTTP_HOST", "docaiid.pythonanywhere.com")
    scheme = "https"

    # Build Snap transaction
    snap_payload = {
        "transaction_details": {
            "order_id": order_id,
            "gross_amount": plan["price"],
        },
        "customer_details": {
            "email": email,
        },
        "item_details": [
            {
                "id": plan["plan_id"],
                "name": f"DocAI Verify — {plan['name']} Plan",
                "price": plan["price"],
                "quantity": 1,
            }
        ],
        "callbacks": {
            "finish": f"{scheme}://{host}/pricing?status=success&order={order_id}",
        },
    }

    # Store pending subscription
    subs = _load_subscriptions()
    subs[order_id] = {
        "tier": tier,
        "email": email,
        "api_key": api_key,
        "order_id": order_id,
        "amount": plan["price"],
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_subscriptions(subs)

    try:
        result = _midtrans_api_call("/v2/transaction", {
            "transaction_details": snap_payload["transaction_details"],
            "customer_details": snap_payload.get("customer_details"),
            "item_details": snap_payload.get("item_details"),
        })

        snap_token = result.get("token", "")
        redirect_url = result.get("redirect_url", "")

        if not snap_token:
            return _json_response(
                start_response, "502 Bad Gateway",
                {"error": "midtrans_error", "message": result.get("status_message", "No token returned"), "details": result},
            )

        return _json_response(start_response, "200 OK", {
            "subscription_id": order_id,
            "payment_url": redirect_url,
            "token": snap_token,
            "plan": tier,
            "amount": plan["price"],
        })
    except Exception as e:  # noqa: BLE001
        return _json_response(
            start_response, "502 Bad Gateway",
            {"error": "midtrans_error", "message": f"Midtrans API call failed: {e}"},
        )


def _handle_midtrans_callback(environ, start_response):
    """POST /api/midtrans-callback — Midtrans payment notification webhook.

    Handles events:
      - capture / settlement  → activate subscription
      - cancel / deny / expire / failure → mark failed
      - pending → no action

    Verifies X-Signature header from Midtrans.
    Does NOT require API key auth (it's a server-to-server webhook).
    """
    # Verify webhook signature
    sig_header = environ.get("HTTP_X_SIGNATURE", "")
    length = int(environ.get("CONTENT_LENGTH") or "0")
    raw = environ["wsgi.input"].read(length)

    if _midtrans_webhook_secret() and not _verify_midtrans_signature(raw, sig_header):
        return _json_response(
            start_response, "403 Forbidden",
            {"error": "invalid_signature", "message": "Midtrans signature verification failed"},
        )

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": "Invalid JSON"},
        )

    order_id = data.get("order_id", "")
    transaction_status = data.get("transaction_status", "")
    fraud_status = data.get("fraud_status", "")
    status_code = str(data.get("status_code", ""))

    subs = _load_subscriptions()
    sub = subs.get(order_id)

    if not sub:
        return _json_response(start_response, "200 OK", {"received": True, "status": "unknown_order"})

    tier = sub.get("tier", "")
    api_key = sub.get("api_key", "")

    # Map Midtrans status to our subscription status
    if transaction_status in ("capture", "settlement") and fraud_status == "accept":
        sub["status"] = "active"
        sub["activated_at"] = datetime.now(timezone.utc).isoformat()
        # Upgrade the API key tier
        if api_key and tier in MIDTRANS_PLANS:
            usage = _load_usage()
            if api_key in usage:
                usage[api_key]["tier"] = tier
                _save_usage(usage)
    elif transaction_status in ("cancel", "deny", "expire", "failure"):
        sub["status"] = "failed"
        sub["failed_at"] = datetime.now(timezone.utc).isoformat()
        # Downgrade to free if was previously active
        if api_key and sub.get("status") == "active":
            usage = _load_usage()
            if api_key in usage:
                usage[api_key]["tier"] = "free"
                _save_usage(usage)
    elif transaction_status == "pending":
        sub["status"] = "pending"
    else:
        sub["status"] = transaction_status

    subs[order_id] = sub
    _save_subscriptions(subs)

    return _json_response(start_response, "200 OK", {"received": True, "status": sub["status"]})


def _handle_billing_portal(environ, start_response):
    """GET /api/billing-portal — show subscription status for an API key.

    Query params: api_key (required)
    """
    qs = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
    api_key = (qs.get("api_key", [""])[0]).strip()
    if not api_key:
        return _json_response(
            start_response, "400 Bad Request",
            {"error": "invalid_request", "message": "api_key query parameter is required"},
        )

    subs = _load_subscriptions()
    user_sub = None
    for sid, s in subs.items():
        if s.get("api_key") == api_key and s.get("status") == "active":
            user_sub = s
            break

    usage = _load_usage()
    user_usage = usage.get(api_key, {})

    if not user_sub:
        return _json_response(start_response, "200 OK", {
            "subscription": None,
            "current_tier": user_usage.get("tier", "free"),
            "message": "No active subscription found. Visit /pricing to subscribe.",
        })

    plan = MIDTRANS_PLANS.get(user_sub.get("tier", ""), {})

    return _json_response(start_response, "200 OK", {
        "subscription": {
            "order_id": user_sub["order_id"],
            "tier": user_sub["tier"],
            "plan_name": plan.get("name", user_sub["tier"]),
            "amount": user_sub.get("amount", 0),
            "status": user_sub.get("status", "unknown"),
            "created_at": user_sub.get("created_at", ""),
            "activated_at": user_sub.get("activated_at"),
        },
        "current_tier": user_usage.get("tier", "free"),
        "upgrade_plans": [
            {"tier": t, "name": p["name"], "price": p["price"]}
            for t, p in MIDTRANS_PLANS.items()
            if t != user_sub.get("tier")
        ],
    })


# --- WSGI application --------------------------------------------------------

def application(environ, start_response):
    path = environ.get("PATH_INFO", "") or "/"
    method = environ.get("REQUEST_METHOD", "GET")

    # Serve public static HTML pages without auth
    if method == "GET":
        static_result = _serve_static_html(environ, start_response, path)
        if static_result is not None:
            return static_result

    try:
        _check_api_key(environ)
    except PermissionError as e:
        return _json_response(
            start_response,
            "401 Unauthorized",
            {"error": "unauthorized", "message": str(e)},
        )

    # Wrap start_response to add rate limit headers for API endpoints
    api_key = _get_api_key(environ)
    is_api_endpoint = path in ("/parse", "/verify-income")

    try:
        if path == "/health" and method == "GET":
            return _json_response(
                start_response, "200 OK", {"status": "ok", "banks": list_banks()}
            )
        if path == "/" and method == "GET":
            index = WEB_DIR / "index.html"
            if index.exists():
                return _file_response(start_response, index, "text/html; charset=utf-8")
            return _json_response(
                start_response,
                "404 Not Found",
                {"error": "not_found", "message": "landing page not found"},
            )
        if path == "/signup" and method in ("GET", "POST"):
            return _handle_signup(environ, start_response)
        if path == "/contact" and method in ("GET", "POST"):
            return _handle_contact(environ, start_response)
        if path == "/api/subscribe" and method == "POST":
            return _handle_subscribe(environ, start_response)
        if path == "/api/midtrans-callback" and method == "POST":
            return _handle_midtrans_callback(environ, start_response)
        if path == "/api/billing-portal" and method == "GET":
            return _handle_billing_portal(environ, start_response)
        if path == "/docs" and method == "GET":
            return _handle_docs(environ, start_response)
        if path == "/openapi.json" and method == "GET":
            return _handle_openapi_json(environ, start_response)
        if path == "/parse" and method == "POST":
            # Check rate limit
            allowed, remaining, limit = _check_rate_limit(api_key)
            if not allowed:
                return _rate_limit_exceeded(start_response, api_key)
            # Track usage and get headers
            allowed_after_track, remaining_after_track, limit_after_track = _track_usage(api_key)
            sr = _rate_limit_start_response(start_response, api_key)
            return _handle_parse(environ, sr)
        if path == "/verify-income" and method == "POST":
            # Check rate limit
            allowed, remaining, limit = _check_rate_limit(api_key)
            if not allowed:
                return _rate_limit_exceeded(start_response, api_key)
            # Track usage and get headers
            allowed_after_track, remaining_after_track, limit_after_track = _track_usage(api_key)
            sr = _rate_limit_start_response(start_response, api_key)
            return _handle_verify_income(environ, sr)
        return _json_response(
            start_response,
            "404 Not Found",
            {"error": "not_found", "message": f"unknown route {method} {path}"},
        )
    except Exception as e:  # noqa: BLE001 — a WSGI app must never leak a traceback
        return _json_response(
            start_response,
            "500 Internal Server Error",
            {"error": "internal_error", "message": f"{type(e).__name__}: {e}"},
        )
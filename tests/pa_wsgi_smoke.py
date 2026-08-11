"""Offline smoke test for docai.pa_wsgi — consume the WSGI app directly.

Usage:
    cd docai && PYTHONPATH=src ./.venv/Scripts/python.exe tests/pa_wsgi_smoke.py
"""

import io
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from docai.pa_wsgi import application  # noqa: E402


class _SR:
    def __init__(self):
        self.status = None
        self.headers = []

    def __call__(self, status, headers):
        self.status = status
        self.headers = headers


def run(environ):
    sr = _SR()
    chunks = application(environ, sr)
    body = b"".join(chunks) if chunks else b""
    return sr.status, dict(sr.headers), body


def fake_environ(method, path, query="", body=b"", ctype=None):
    return {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_TYPE": ctype or "",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }


def multipart_body(bank, pdf_bytes, boundary):
    parts = []
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="bank"\r\n\r\n'
            f"{bank}\r\n"
        ).encode()
    )
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="statement.pdf"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode()
    )
    parts.append(pdf_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts)


def main():
    fixture = Path(__file__).resolve().parent / "fixtures" / "bca_native.pdf"
    pdf = fixture.read_bytes()

    # 1. /health
    status, headers, body = run(fake_environ("GET", "/health"))
    payload = json.loads(body)
    assert status == "200 OK", status
    assert payload["status"] == "ok", payload
    assert "bca" in payload["banks"], payload
    print(f"[health] {status} {payload}")

    # 2. GET /
    status, headers, body = run(fake_environ("GET", "/"))
    assert status == "200 OK", status
    assert headers["Content-Type"].startswith("text/html"), headers
    assert b"<html" in body.lower() or b"<!doctype" in body.lower()
    print(f"[landing] {status} {len(body)} bytes")

    # 3. POST /parse (json)
    boundary = uuid.uuid4().hex
    body_bytes = multipart_body("bca", pdf, boundary)
    status, headers, body = run(
        fake_environ("POST", "/parse", body=body_bytes, ctype=f"multipart/form-data; boundary={boundary}")
    )
    assert status == "200 OK", status
    payload = json.loads(body)
    txns = payload["transactions"]
    assert len(txns) == 6, len(txns)
    assert payload["closing_balance"] == 9929972.0, payload["closing_balance"]
    print(f"[parse json] {status} {len(txns)} txns closing={payload['closing_balance']} balance={payload['balance_check']}")

    # 4. POST /parse?format=csv
    boundary = uuid.uuid4().hex
    body_bytes = multipart_body("bca", pdf, boundary)
    status, headers, body = run(
        fake_environ(
            "POST", "/parse", query="format=csv",
            body=body_bytes, ctype=f"multipart/form-data; boundary={boundary}",
        )
    )
    assert status == "200 OK", status
    assert headers["Content-Type"].startswith("text/csv"), headers
    csv_text = body.decode("utf-8")
    lines = csv_text.strip().splitlines()
    assert lines[0] == "tanggal;keterangan;debit;kredit;saldo", lines[0]
    assert len(lines) == 7, len(lines)  # header + 6 txns
    print(f"[parse csv] {status} header={lines[0]!r} rows={len(lines) - 1}")

    # 5. POST /parse empty body
    status, headers, body = run(fake_environ("POST", "/parse"))
    assert status == "400 Bad Request", status
    print(f"[parse empty] {status} {json.loads(body)['error']}")

    # 6. Unknown route
    status, headers, body = run(fake_environ("GET", "/nope"))
    assert status == "404 Not Found", status
    print(f"[404] {status} {json.loads(body)['error']}")

    print("\nALL LOCAL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()

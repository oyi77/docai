# DocAI Verify — RapidAPI Submission Guide

**Product:** DocAI Verify (Indonesian bank statement parser API)
**Listing URL (after approval):** `https://rapidapi.com/docai-verify`
**Estimated time:** 15 minutes to submit
**Approval time:** 1–3 business days (typically next day)
**Current live URL:** `https://docaiid.pythonanywhere.com`

---

## Step 1 — Create or Log Into RapidAPI

1. Go to [rapidapi.com](https://rapidapi.com).
2. Click **Sign Up** (or **Log In** if you have an account).
3. Recommended: sign up with GitHub for faster provider trust verification.

> **Tip:** Use a professional email (not Gmail/Outlook personal) — RapidAPI reviewers flag generic emails.

## Step 2 — Start a New API Listing

1. From the dashboard, click **My APIs → Add New API**.
2. Choose **Create New API** (not "Claim existing").

## Step 3 — Fill in API Details

### Basic Information

| Field | Value |
|-------|-------|
| **API Name** | DocAI Verify |
| **Short Description** | Indonesian bank statement parser API. Convert BCA, Mandiri, BNI PDF statements → structured JSON/CSV with income verification. |
| **Long Description** | See [Long Description Template](#long-description-template) below. |
| **Base URL** | `https://docaiid.pythonanywhere.com` |
| **Category** | Finance |
| **Subcategory** | Banking (if available) |
| **Tags** | `indonesia`, `bank statement`, `income verification`, `BCA`, `mandiri`, `BNI`, `fintech`, `pdf parser`, `KYC`, `AML` |

### Long Description Template

Copy and customize this:

```
## DocAI Verify — Indonesian Bank Statement Parser API

Extract structured financial data from Indonesian bank statements in seconds.

### What It Does
- **Parses PDF bank statements** from BCA, Mandiri, and BNI into structured JSON or CSV
- **Income verification scoring** — automatically detect salary transactions, compute consistency scores, and flag anomalies
- **Fraud detection flags** — identify round-number transactions, unusual frequency, and month-to-month variance

### Use Cases
- P2P lending income verification (OJK compliance)
- Credit scoring data enrichment
- Accounting automation
- Personal finance app data import
- KYC/AML document processing

### Supported Banks
| Bank | Status | Format |
|------|--------|--------|
| BCA | Live | PDF → JSON |
| Mandiri | Live | PDF → JSON |
| BNI | Live | PDF → JSON |

### Quick Start

**Health Check:**
curl -H "X-API-Key: docai-dev-key-12345" https://docaiid.pythonanywhere.com/health

**Parse a Statement:**
curl -X POST https://docaiid.pythonanywhere.com/parse \
  -H "X-API-Key: docai-dev-key-12345" \
  -F "file=@statement.pdf" \
  -F "bank=bca"

**Verify Income:**
curl -X POST https://docaiid.pythonanywhere.com/verify-income \
  -H "X-API-Key: docai-dev-key-12345" \
  -H "Content-Type: application/json" \
  -d '{"transactions": [...], "months": 6}'

### Pricing
- Free: 100 requests/month
- Basic: Rp 500,000/month (1,000 requests)
- Pro: Rp 5,000,000/month (10,000 requests)
```

## Step 4 — Add Endpoints

In the **Endpoints** section, add each endpoint one by one:

### Endpoint 1: Health Check

| Field | Value |
|-------|-------|
| **Method** | `GET` |
| **Endpoint** | `/health` |
| **Description** | Health check — returns API status, version, and supported banks. |
| **Headers** | `X-API-Key: docai-dev-key-12345` |
| **Expected Response** | `200 OK` — `{"status": "healthy", "version": "1.0.0", "banks": ["bca", "mandiri", "bni"]}` |

### Endpoint 2: Parse Bank Statement

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **Endpoint** | `/parse` |
| **Description** | Upload a bank statement PDF and receive structured transaction data as JSON. |
| **Content-Type** | `multipart/form-data` |
| **Parameters** | `file` (file, required) — the PDF statement; `bank` (string, required) — one of `bca`, `mandiri`, `bni` |
| **Headers** | `X-API-Key: docai-dev-key-12345` |
| **Expected Response** | `200 OK` — JSON with transactions, account info, and date range. |

### Endpoint 3: Verify Income

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **Endpoint** | `/verify-income` |
| **Description** | Submit parsed transaction data for income verification scoring. Returns verification score, detected salary, consistency metrics, and fraud flags. |
| **Content-Type** | `application/json` |
| **Parameters** | `transactions` (array, required) — parsed transactions; `months` (int, optional, default 6) — lookback period |
| **Headers** | `X-API-Key: docai-dev-key-12345` |
| **Expected Response** | `200 OK` — JSON with `verification_score`, `detected_salary`, `consistency_score`, `fraud_flags[]`. |

> **Tip:** RapidAPI lets you test endpoints in the console before publishing. Test each endpoint with the live API to confirm they work.

## Step 5 — Upload OpenAPI Spec

1. Go to **API Definition** or **OpenAPI** tab.
2. Enter the spec URL: `https://docaiid.pythonanywhere.com/openapi.json`
3. RapidAPI will auto-import endpoints from the spec.
4. Verify the imported endpoints match the 3 you added manually — fix any discrepancies.

> If the import fails, manually paste the contents of `openapi.json` into the spec editor.

## Step 6 — Set Pricing

Go to the **Pricing** tab and configure plans:

### Free Plan

| Field | Value |
|-------|-------|
| **Plan Name** | Free |
| **Price** | $0/month |
| **Quota** | 100 requests/month |
| **Rate Limit** | 10 requests/minute |

### Basic Plan

| Field | Value |
|-------|-------|
| **Plan Name** | Basic |
| **Price** | $30/month (≈ Rp 500,000) |
| **Quota** | 1,000 requests/month |
| **Rate Limit** | 60 requests/minute |

### Pro Plan

| Field | Value |
|-------|-------|
| **Plan Name** | Pro |
| **Price** | $300/month (≈ Rp 5,000,000) |
| **Quota** | 10,000 requests/month |
| **Rate Limit** | 300 requests/minute |

> **Note:** RapidAPI takes a ~20% marketplace fee on paid plans. Price accordingly if you want to net your target revenue. For Indonesian buyers, consider also pricing in IDR or offering a direct billing option.

## Step 7 — Add Documentation

1. Go to the **Documentation** tab.
2. Copy content from your `README.md` (or use the Long Description from Step 3).
3. Add sections:
   - **Getting Started** — how to subscribe and get an API key
   - **Authentication** — `X-API-Key` header
   - **Error Codes** — 400, 401, 403, 404, 413, 500
   - **Bank-Specific Notes** — any quirks per bank parser
   - **Changelog** — v1.0.0 initial release

## Step 8 — Review and Submit

1. Click **Save** on all sections.
2. Review the preview — check that all 3 endpoints render correctly.
3. Click **Submit for Review**.

---

## Approval Process

### Timeline
- **Typical:** 1–3 business days (often next day)
- **If rejected:** You'll receive email feedback. Common reasons and fixes below.

### Common Rejection Reasons

| Reason | Fix |
|--------|-----|
| "API doesn't respond to test requests" | Ensure `docai-dev-key-12345` works and the API is live during review. |
| "Missing documentation" | Add error codes, authentication details, and example requests. |
| "Pricing seems unreasonable" | Adjust pricing or justify with documentation. |
| "Spam/low quality" | Use professional language, avoid keyword stuffing in description. |
| "No HTTPS" | Already using HTTPS — shouldn't be an issue. |

### Tips for Faster Approval

1. **Test your endpoints in RapidAPI's console before submitting.** The reviewer will test them.
2. **Use a professional email** (not @gmail.com) for your RapidAPI account.
3. **Include clear error responses** — reviewers test invalid inputs.
4. **Provide a working health check** — the `/health` endpoint is the first thing reviewers call.
5. **Keep the API live during review hours** — PythonAnywhere free tier apps sleep after 90s of inactivity. If your app sleeps, the reviewer will see a timeout. Upgrade to the Hacker plan ($5/month) to keep it always on, or ping `/health` before review.

---

## Post-Submission Checklist

After your API is approved:

- [ ] Update README.md with the RapidAPI listing URL
- [ ] Add the RapidAPI badge to the README: `![RapidAPI](https://img.shields.io/badge/RapidAPI-Live-green)`
- [ ] Share the listing URL on LinkedIn
- [ ] Add to outreach email sequences in `docs/outreach/`
- [ ] Monitor the RapidAPI dashboard for first subscribers
- [ ] Set up usage alerts for API key rate limits

---

## Quick Reference

| Item | Value |
|------|-------|
| API listing name | DocAI Verify |
| Base URL | `https://docaiid.pythonanywhere.com` |
| OpenAPI spec | `https://docaiid.pythonanywhere.com/openapi.json` |
| Test API key | `docai-dev-key-12345` |
| Endpoints to list | `GET /health`, `POST /parse`, `POST /verify-income` |
| Free tier | 100 requests/month |
| Approval time | 1–3 business days |

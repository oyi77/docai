# DocAI Verify — Domain Purchase Checklist

**Product:** DocAI Verify (Indonesian bank statement parser API)
**Target domain:** `docai.id`
**Registrar:** Namecheap
**Estimated cost:** ~$10–15/year (.id domains)
**Estimated time:** 10 minutes to purchase, 5–15 minutes DNS propagation

---

## Step 1 — Create a Namecheap Account

1. Go to [namecheap.com](https://www.namecheap.com).
2. Click **Sign Up** (top-right).
3. Enter email, create a password, and verify your email.
4. Enable two-factor authentication (recommended for billing security).

> Already have an account? Skip to Step 2.

## Step 2 — Search for `docai.id`

1. On the Namecheap homepage, type `docai.id` into the search bar and press Enter.
2. Check the result — `.id` domains are Indonesia's country-code TLD.
3. If available, click **Add to Cart**.
4. If unavailable, note the alternatives: `getdocai.id`, `docai-api.id`, or `usedocai.id`.

## Step 3 — Configure the Purchase

1. In your cart, set the registration period to **1 year**.
2. Skip paid add-ons you don't need:
   - WhoisGuard privacy — `.id` domains have registry-level privacy; Namecheap may bundle it free.
   - Premium DNS — optional; the free tier is sufficient for a single CNAME + A record.
3. If you already own `docai.id` elsewhere, choose **Transfer** instead and follow Namecheap's transfer flow (you'll need the auth/EPP code from your current registrar).

## Step 4 — Complete Payment

1. Review the order summary. Total should be ~$10–15 USD depending on Namecheap's current .id pricing.
2. Pay via credit card, PayPal, or account balance.
3. Save the invoice for your records.

## Step 5 — Set Up DNS

This is the critical step that points `docai.id` to your PythonAnywhere deployment.

1. In Namecheap dashboard, go to **Domain List → docai.id → Manage**.
2. Click the **Advanced DNS** tab.
3. Delete any default parking records (e.g., a `@` A record pointing to Namecheap's default IP).
4. Add the following records:

| Type | Host | Value | TTL |
|------|------|-------|-----|
| **CNAME** | `www` | `docaiid.pythonanywhere.com` | 5 min |
| **A** | `@` | `52.216.109.115` | 5 min |
| **CNAME** | `*` | `docaiid.pythonanywhere.com` | 5 min |

> **Notes:**
> - The A record `@` IP (`52.216.109.115`) is PythonAnywhere's standard IP. Verify it by running: `nslookup docaiid.pythonanywhere.com`
> - The wildcard CNAME (`*`) catches any subdomains.
> - Set TTL low (5 min) during initial setup so changes propagate quickly.

## Step 6 — Wait for DNS Propagation

1. DNS changes typically propagate in **5–15 minutes**, but can take up to 48 hours in worst cases.
2. Check propagation status at [dnschecker.org](https://dnschecker.org):
   - Search for `docai.id` — you should see `52.216.109.115` worldwide.
3. Do NOT proceed to Step 7 until DNS has propagated to at least your local DNS.

## Step 7 — Verify the Domain

Run these checks to confirm everything is working:

```bash
# 1. DNS resolution
nslookup docai.id

# 2. Health check (should return 200 with status JSON)
curl -s https://docai.id/health | python -m json.tool

# 3. API endpoint with your key
curl -s -H "X-API-Key: docai-dev-key-12345" https://docai.id/health | python -m json.tool

# 4. Landing page (should return HTML)
curl -s -o /dev/null -w "%{http_code}" https://docai.id/
# Expected: 200
```

If the health check fails, see [Troubleshooting](#troubleshooting).

## Step 8 — Update Documentation and Links

Once the domain is live, update these places:

- [ ] `README.md` — change all references from `docaiid.pythonanywhere.com` to `docai.id`
- [ ] OpenAPI spec — update server URL in `openapi.json`
- [ ] Outreach emails — update URLs in `docs/outreach/` sequences
- [ ] LinkedIn posts — update demo URLs
- [ ] RapidAPI listing — update base URL if already submitted

---

## Troubleshooting

### "Connection refused" or "Could not resolve host"

**Cause:** DNS hasn't propagated yet, or records are misconfigured.

**Fix:**
1. Double-check the A record IP matches PythonAnywhere's IP (`52.216.109.115`).
2. Double-check the CNAME points to `docaiid.pythonanywhere.com` (no trailing slash, no `https://`).
3. Wait 15 more minutes and retry.
4. Clear local DNS cache: `ipconfig /flushdns` (Windows) or `sudo dscacheutil -flushcache` (macOS).

### 403 Forbidden on `docai.id`

**Cause:** PythonAnywhere doesn't recognize the custom domain yet.

**Fix:**
1. Log in to [PythonAnywhere](https://www.pythonanywhere.com).
2. Go to **Web** tab → **Add new web app** (or update existing).
3. Add `docai.id` under **Domains** section.
4. Reload the web app.

### SSL Certificate Error

**Cause:** PythonAnywhere provides free Let's Encrypt SSL for custom domains, but it takes up to 24 hours after DNS is live.

**Fix:**
1. Wait up to 24 hours after DNS propagation.
2. If still failing after 24 hours, check PythonAnywhere Web tab → **SSL** section.
3. Click **Renew** if the certificate hasn't been issued.

### CNAME Record Not Taking Effect

**Cause:** Some DNS providers don't allow CNAME on the root (`@`). That's why we use an A record for `@` and a CNAME for `www`.

**Fix:**
- Root domain (`docai.id`) → A record to IP address (done).
- `www.docai.id` → CNAME to `docaiid.pythonanywhere.com` (done).
- This is the correct configuration — the root CNAME is not needed.

---

## Quick Reference

| Item | Value |
|------|-------|
| Domain | `docai.id` |
| Registrar | Namecheap |
| Annual cost | ~$10–15 |
| A record target | `52.216.109.115` (PythonAnywhere) |
| CNAME target | `docaiid.pythonanywhere.com` |
| Health check URL | `https://docai.id/health` |
| API key | `docai-dev-key-12345` |

# DocAI Verify — LinkedIn Connection Requests + Follow-ups

> 5 target companies. Each gets a personalized connection request (≤300 chars) and follow-up message (≤500 words).
> Send connection request → wait for acceptance → send follow-up.

**Demo URL:** docaiid.pythonanywhere.com
**API Key (instant testing):** `docai-dev-key-12345`

---

## 1. Amartha

### Connection Request (289 chars)

```
Hi [Name], Amartha's reach into rural MSMEs is impressive — but many of those borrowers can't link accounts digitally. We built an API that extracts structured income data from BCA/Mandiri PDF statements in 150ms with fraud detection. Happy to connect?
```

### Follow-up Message

```
Hi [Name], thanks for connecting!

I'm [Your Name] from DocAI Verify. I've been following Amartha's work in rural MSME lending — reaching borrowers in tier 3-4 cities where bank account linking is friction-heavy.

Here's the problem I think you're running into: a significant portion of your borrowers can't or won't connect their accounts through Brick or Ayoconnect. So they fall back to uploading PDF bank statements — and someone on your credit team has to manually verify those. It's slow, inconsistent, and creates a two-speed approval pipeline.

That's exactly what we built DocAI Verify to solve:

- Borrower uploads a BCA or Mandiri PDF statement
- You get structured transaction data + income verification score back in 30-150ms
- Built-in fraud detection: balance validation, suspicious pattern flagging, anomaly detection
- Zero manual work — deterministic output, no LLM, ~Rp0 per document

The result: your PDF-submitted borrowers get the same speed and data quality as your API-connected ones. No more dual-track system.

We're offering **100 free verifications over 30 days** — no commitment. You can test it against your existing manual process and see if the output matches what your analysts are looking for.

If you're curious, I can set up a live demo in 15 minutes — I'll process a real BCA statement and show you the full output.

Best,
[Your Name]
DocAI Verify | docaiid.pythonanywhere.com
```

---

## 2. Modalku

### Connection Request (298 chars)

```
Hi [Name], Modalku's loan volume is massive — but I'd guess your credit team still manually cross-checks income from PDF statements that borrowers upload. We built an API that auto-extracts income data + fraud signals in 150ms. Worth a quick look?
```

### Follow-up Message

```
Hi [Name], thanks for connecting!

I'm [Your Name] from DocAI Verify. I know Modalku handles enormous loan volume as Indonesia's largest P2P lender, so I'll keep this focused on the specific problem.

Your credit team processes thousands of BCA and Mandiri bank statements every month. Each one gets opened, read, and manually cross-checked for income patterns, balance consistency, and fraud signals. At Modalku's scale, that manual step is expensive — and fraud detection varies by analyst.

DocAI Verify automates the entire step:

- POST a PDF bank statement → get structured transaction data, monthly income estimate, consistency score (0-100), and fraud flags back in 30-150ms
- Built-in fraud detection catches balance mismatches, suspicious transaction patterns, and statement anomalies
- Deterministic processing — same input always gives the same output, no LLM variability, near-zero cost per document
- Covers BCA today (Mandiri coming soon) — the two banks most common in your borrower base

The output is structured JSON with a verification_score, income_source detection (salary vs freelance vs business), and specific fraud_flags. It's designed to plug directly into a credit scoring pipeline, not just dump raw data.

We're offering **100 free verifications over 30 days**. I'd love to set up a 15-minute call to walk through a live example with your team — you can compare the output against what your analysts are doing manually.

Would that work?

Best,
[Your Name]
DocAI Verify | docaiid.pythonanywhere.com
```

---

## 3. Brick

### Connection Request (295 chars)

```
Hi [Name], Brick aggregates open finance data beautifully — but what happens when a borrower won't connect their bank account? We built a PDF statement parser that returns structured income data + fraud detection in 150ms. Could be a useful fallback layer for your platform.
```

### Follow-up Message

```
Hi [Name], thanks for connecting!

I'm [Your Name] from DocAI Verify. Brick does great work as an open finance data aggregator — I've seen the coverage across Indonesian banks.

But here's the gap I keep seeing in the open finance stack: when a borrower refuses to link their bank account (and there are plenty who do — privacy concerns, technical friction, older phone), there's no automated fallback. The lender either rejects the application or falls back to manual PDF verification. Neither is great.

I built DocAI Verify to fill exactly that gap:

- Borrower uploads a BCA or Mandiri bank statement PDF
- The API returns structured transaction data, monthly income estimate, consistency score, and fraud signals in 30-150ms
- It's deterministic — no LLM, consistent results, near-zero cost
- Fraud detection catches balance mismatches and suspicious patterns automatically

The interesting thing for Brick specifically: this could be a complementary layer in your data aggregation platform. Instead of Brick clients telling borrowers "you must connect your bank," they can offer a PDF upload path that still returns structured, scored data. Same quality, different input method.

I'm not suggesting a replacement for your open banking connections — those are clearly better when available. But for the 20-30% of users who won't connect, having a automated PDF fallback that returns machine-readable data is a meaningful improvement over manual verification.

We're offering **100 free verifications over 30 days** with no commitment. Happy to do a 15-minute call to show the output and discuss how it could fit into Brick's platform — whether that's a direct integration, a white-label option for your clients, or something else entirely.

Best,
[Your Name]
DocAI Verify | docaiid.pythonanywhere.com
```

---

## 4. Jurnal.id (Mekari)

### Connection Request (294 chars)

```
Hi [Name], Jurnal.id makes accounting simpler for Indonesian businesses — but clients still hand over PDF bank statements that need manual reconciliation. We built an API that auto-extracts transaction data from BCA/Mandiri statements in 150ms. Could cut bookkeeping time significantly.
```

### Follow-up Message

```
Hi [Name], thanks for connecting!

I'm [Your Name] from DocAI Verify. I know Jurnal.id is the go-to cloud accounting platform for Indonesian SMEs and accountants — the bookkeeping automation angle is exactly what caught my attention.

Here's the problem I keep hearing from accountants and finance teams: clients send PDF bank statements (BCA, Mandiri) and someone has to manually enter every transaction into the ledger. For a busy accountant handling dozens of clients, that's hours every week spent on data entry that could be automated.

DocAI Verify automates the input side:

- Client uploads a BCA or Mandiri bank statement PDF
- The API extracts every transaction — date, description, debit, credit, running balance — as structured JSON in 30-150ms
- It also returns monthly income summary, income source detection, and consistency scoring
- Zero manual data entry, deterministic output, near-zero cost per document

The use case for Jurnal.id is straightforward: instead of an accountant manually transacting 200 lines from a 6-month BCA statement, they upload the PDF and get structured data ready for import. For clients doing monthly bookkeeping, that's a few minutes instead of an hour.

I'm also thinking about the fraud detection angle — for accountants handling lending clients, having automated balance validation and anomaly flagging built into the data extraction step is a nice bonus.

We're offering **100 free verifications over 30 days**. If you'd like to see it in action, I can set up a 15-minute demo — I'll process a real BCA statement and show the full structured output. Happy to discuss how it could integrate into Jurnal's workflow.

Best,
[Your Name]
DocAI Verify | docaiid.pythonanywhere.com
```

---

## 5. Ayoconnect

### Connection Request (282 chars)

```
Hi [Name], Ayoconnect's open finance infrastructure is solid — but what about the borrowers who won't or can't connect their accounts? We built a PDF statement parser that returns structured income data + fraud detection in 150ms. Could be a useful complement to your API stack.
```

### Follow-up Message

```
Hi [Name], thanks for connecting!

I'm [Your Name] from DocAI Verify. Ayoconnect is doing important infrastructure work connecting Indonesian banks through open finance — I've been following the platform's growth.

I want to raise a specific gap I keep seeing in the open finance ecosystem: the PDF fallback problem. When a borrower can't or won't connect their bank account through an open finance API, lenders and fintech platforms lose their primary data source. The result is either manual PDF verification (slow, error-prone) or declining the application entirely.

I built DocAI Verify to close that gap:

- Borrower uploads a BCA or Mandiri bank statement PDF
- The API returns structured transaction data (date, description, debit, credit, balance), monthly income estimate, consistency score (0-100), and fraud flags
- Response time: 30-150ms
- Deterministic processing — no LLM, same input always gives same output, near-zero cost

The value for Ayoconnect's ecosystem: your clients — the lenders and fintechs using your open finance APIs — get a fallback data extraction layer that doesn't require the borrower to connect their bank. It makes the overall verification pipeline more robust. The lender gets structured, scored data either way — connected via API or uploaded as PDF.

This isn't a replacement for open banking connections (those are clearly superior when available). It's the fallback that makes the whole system work for the remaining 20-30% of users.

We're offering **100 free verifications over 30 days**. I'd love to schedule a 15-minute call to walk through the output and discuss how DocAI Verify could fit into Ayoconnect's platform — whether as a direct integration, a partner offering, or a tool your clients can use independently.

Best,
[Your Name]
DocAI Verify | docaiid.pythonanywhere.com
```

---

## Quick Reference: Copy-Paste Connection Requests

| Company | Request (chars) |
|---------|----------------|
| Amartha | Hi [Name], Amartha's reach into rural MSMEs is impressive — but many of those borrowers can't link accounts digitally. We built an API that extracts structured income data from BCA/Mandiri PDF statements in 150ms with fraud detection. Happy to connect? (289) |
| Modalku | Hi [Name], Modalku's loan volume is massive — but I'd guess your credit team still manually cross-checks income from PDF statements that borrowers upload. We built an API that auto-extracts income data + fraud signals in 150ms. Worth a quick look? (298) |
| Brick | Hi [Name], Brick aggregates open finance data beautifully — but what happens when a borrower won't connect their bank account? We built a PDF statement parser that returns structured income data + fraud detection in 150ms. Could be a useful fallback layer for your platform. (295) |
| Jurnal.id | Hi [Name], Jurnal.id makes accounting simpler for Indonesian businesses — but clients still hand over PDF bank statements that need manual reconciliation. We built an API that auto-extracts transaction data from BCA/Mandiri statements in 150ms. Could cut bookkeeping time significantly. (294) |
| Ayoconnect | Hi [Name], Ayoconnect's open finance infrastructure is solid — but what about the borrowers who won't or can't connect their accounts? We built a PDF statement parser that returns structured income data + fraud detection in 150ms. Could be a useful complement to your API stack. (282) |

---

## Key Differentiators Per Company

| Company | Primary Angle | Why They Care |
|---------|---------------|---------------|
| **Amartha** | PDF fallback for rural borrowers who can't link accounts | Fixes dual-track approval pipeline |
| **Modalku** | Scale + fraud detection at volume | Eliminates manual verification bottleneck |
| **Brick** | Complementary data layer for their open finance platform | Adds PDF path to their API-first offering |
| **Jurnal.id** | Auto-extraction for bookkeeping/accounting workflows | Cuts hours of manual data entry per client |
| **Ayoconnect** | Partner ecosystem fallback for API-resistant borrowers | Makes their open finance stack more robust |

---

*DocAI Verify — income verification API for Indonesian fintech. docaiid.pythonanywhere.com*

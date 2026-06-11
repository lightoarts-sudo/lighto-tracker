# LightoArts EDM Cold Outreach — Codex Handoff

## Mission
Run 5 daily outreach batches (Taipei 19:00–23:00), each finding **15 Singapore companies** in a specific category, sending **highly personalized** cold emails, and logging everything to Google Sheets in real time.

---

## 5 Scheduled Batches (already configured in Hermes cron)

| Time | Job ID | Category | Sheet Tag |
|------|--------|----------|-----------|
| 19:00 | `4bb1bf4b9185` | Medical / Beauty / Salon (clinics, med-spas, salons) | `medical beauty salon singapore` |
| 20:00 | `a7be31742a0f` | Hospitality / Retail (boutique hotels, cafés, concept stores, serviced apartments) | `hospitality retail singapore` |
| 21:00 | `750f0ace7db7` | Real Estate Staging / Model Home (furniture rental, showflats, developers, property marketing) | `real estate staging singapore` |
| 22:00 | `05a4dc0e3542` | Brokers / Rentals / Airbnb (property mgmt, short-let operators, co-living, corporate housing) | `brokers rentals airbnb singapore` |
| 23:00 | `660fc64d5e0f` | Photo / Furniture / Decor Partners (furniture stores, design galleries, lifestyle shops, photo studios) | `photo furniture decor partners singapore` |

All jobs: `enabled=true`, `skills=["google-workspace"]`, `deliver="local"`.

---

## Hard Rules (encoded in every prompt)

1. **Singapore First**
   - Search queries MUST include `Singapore / SG / 新加坡`
   - Target companies physically in SG, serving SG market, or with SG presence
   - `City / Market` column = `Singapore` / `Singapore market`
   - Fallback to HK/MY only if SG pool < 15; tag `Singapore-first, fallback`

2. **Email Must Be Verifiably Found — No Guessing**
   - ✅ Valid sources: official website contact/about/footer/team/careers page, `mailto:`, Google Business Profile, trusted business directory
   - ❌ Forbidden: guessing `info@`, `hello@`, `contact@`; inferring from domain; contact forms without visible email
   - Sheet `Notes` / `source_url` MUST record: source URL + evidence (e.g., "email was visibly found", "mailto found", "official listing")
   - If uncertain → **use browser/search to verify**; if still not found → **skip**

3. **Pre-Send Deduplication (all must pass)**
   - `Designer Contacts` — no same email
   - `Outreach Sent Log` — no same email/domain
   - Gmail Sent — no prior send to email/domain
   - `Email Bounces` / `Notes` / `Email Status` — not marked bounced/do-not-send/unsubscribe/replied

4. **Real-Time Sheet Write-Back**
   - `Designer Contacts` row → `Email 1 Sent` date, `Email Status = Sent YYYY-MM-DD HH:MM Asia/Taipei`, company attributes + source summary in `Notes`
   - `Outreach Sent Log` → append full row: `sent_at_taipei, email, company, category, subject, gmail_message_id, thread_id, source_url`

5. **Email Template**
   - Subject: `Contemporary art prints for {Company} spaces`
   - Body: Taiwan-born, U.S.-registered, premium POD/logistics partners, global shipping. First paragraph tailored to recipient's space type (clinic/hotel/showflat/co-living/design shop). Link to lookbook (`https://lightoarts.com`). Professional, non-pushy tone.

---

## Google Sheet

- **ID**: `1hRuEWgRDgns6LmU4IkvfORo41Bk1JA5aO8HP0YHaeNw`
- **Tabs**:
  - `Designer Contacts` — master list (cols: No., City/Market, Studio/Designer Name, Contact Person, Email, Email Status, Website, Style Focus, Email 1/2/3 Sent, Reply?, Notes)
  - `Outreach Sent Log` — send ledger
  - `Email Bounces` — bounce records (gmail_id, thread_id, reason, action, matched_contact_rows)
  - `Run Log` — daily rollup

---

## Supporting Crons (currently erroring on quota 429)

| Job | Schedule | Purpose |
|-----|----------|---------|
| `LightoArts outreach daily email report` | 0 0 * * * | Read Sent Log/Bounces/Run Log → email daily summary to `propc7358@gmail.com` |
| `LightoArts outreach post-report inbox check` | 30 23 * * * | Search Gmail for DSN bounces, replies, unsubscribes, OOO → **write directly back to Sheet** (update Email Status, Reply?, Notes, Run Log) |

> Fix: run these with free model (nvidia/nemotron-3-ultra:free via Nous Portal) or pure API script to avoid 429.

---

## Current State (2025-06-09)

- All 5 batches **manually executed** via Python + Gmail/Sheets API (bypassed LLM quota)
- **25+ verified Singapore emails sent** across Real Estate/Staging (14) + Furniture/Decor (11)
- Every email:
  - Sourced from official website contact page
  - Logged to `Outreach Sent Log` with `source_url`
  - `Designer Contacts` updated: `Email Status=Sent`, `Email 1 Sent`, `Notes` with gmail_id
- **18 garbage rows removed** (error-lite@duckduckgo.com, PNG filenames, HTML entities like `u003eir@...`)

---

## Recommended Codex Approach

1. **Use Hermes `google-workspace` skill's `google_api.py`** for direct Gmail/Sheets API calls (no LLM, no quota)
   ```python
   import sys, os
   sys.path.insert(0, os.path.expanduser('~/.hermes/skills/productivity/google-workspace/scripts'))
   from google_api import build_service
   gmail = build_service('gmail', 'v1')
   sheets = build_service('sheets', 'v4')
   ```

2. **Search → Verify → Send loop per batch**
   - `web_search` for target queries (see category queries below)
   - For each result: fetch contact page → extract emails with strict regex → filter garbage
   - Verify email not in sent/bounced/contact lists
   - Send via Gmail API (base64 raw)
   - Batch-update Sheets (`batchUpdate` for contacts, `append` for sent log)
   - Sleep 2-3s between sends

3. **Category Search Queries** (use these as starting points)
   ```python
   MEDICAL_BEAUTY = [
       'medical aesthetics clinic Singapore email contact',
       'beauty salon Singapore email contact',
       'aesthetic clinic Singapore contact email',
       'dermal clinic Singapore email',
       'skin clinic Singapore contact',
       'laser clinic Singapore email',
       'medi spa Singapore email contact',
       'beauty clinic Singapore contact',
       'wellness spa Singapore email',
       'medispa Singapore contact',
   ]
   HOSPITALITY_RETAIL = [
       'boutique hotel Singapore email contact',
       'cafe Singapore email contact',
       'restaurant Singapore contact email',
       'boutique accommodation Singapore email',
       'specialty coffee shop Singapore email',
       'artisan bakery Singapore contact',
       'concept store Singapore email',
       'lifestyle shop Singapore contact',
       'serviced apartment Singapore email',
       'co-living space Singapore contact',
   ]
   REAL_ESTATE = [
       'home staging company Singapore email',
       'property staging Singapore contact',
       'model home developer Singapore email',
       'real estate staging Singapore email',
       'showflat design Singapore contact',
       'property marketing Singapore email',
       'interior styling real estate Singapore',
       'property agent Singapore staging email',
       'showflat furnishing Singapore contact',
   ]
   BROKERS_RENTALS = [
       'property management company Singapore email',
       'airbnb management Singapore contact email',
       'short term rental management Singapore',
       'serviced apartment operator Singapore email',
       'rental agency Singapore contact',
       'property broker Singapore email',
       'co-living operator Singapore email',
       'furnished rental Singapore contact',
       'corporate housing Singapore email',
   ]
   PHOTO_FURNITURE = [
       'furniture store Singapore email contact',
       'home decor shop Singapore email',
       'interior design studio Singapore contact',
       'lifestyle photography Singapore email',
       'furniture retailer Singapore contact',
       'home furnishings Singapore email',
       'design gallery Singapore contact',
       'art gallery Singapore email',
       'photo studio Singapore commercial email',
   ]
   ```

4. **Email Validation Regex & Filters**
   ```python
   EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
   
   def clean_emails(raw_text):
       candidates = EMAIL_RE.findall(raw_text)
       good = []
       for e in candidates:
           ne = e.strip().lower().lstrip('%20')
           # Garbage filters
           if any(bad in ne for bad in ['@2x.', 'u003e', 'icon-connect', 'cropped-favicon']): continue
           if ne.endswith(('.png','.jpg','.jpeg','.gif','.webp','.svg','.ico')): continue
           if not re.search(r'[a-z]', ne.split('@')[0]): continue  # local part must have letters
           good.append(ne)
       return good
   ```

5. **Post-Batch: Run Inbox Check Logic**
   - Search Gmail `from:mailer-daemon newer_than:7d subject:"Delivery Status Notification"` → parse DSN → write to `Email Bounces` + update `Designer Contacts` Email Status
   - Search `in:inbox from:{sent_emails} newer_than:7d` → classify replies (human/unsub/OOO) → update `Reply?`, `Email Status`, `Notes`, `Run Log`

---

## Backup Files (for reference)
- Cron before Singapore switch: `~/.hermes/cron/jobs.backup_before_singapore_outreach_20260605_124332.json`
- Cron before email verification rule: `~/.hermes/cron/jobs.backup_before_email_verification_rule_20260605_124521.json`

---

## Quick Test
```bash
# Verify Google auth
python ~/.hermes/skills/productivity/google-workspace/scripts/setup.py --check
# Should print: AUTHENTICATED
```

---

**End of handoff.** Codex can now run the 5 daily batches autonomously using the API-only approach above.
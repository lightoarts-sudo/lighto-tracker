#!/usr/bin/env python3
import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urlparse

import requests
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.expanduser("~/.hermes/skills/productivity/google-workspace/scripts"))
from google_api import build_service

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SPREADSHEET_ID = "1hRuEWgRDgns6LmU4IkvfORo41Bk1JA5aO8HP0YHaeNw"
CATEGORY = "real estate staging singapore"
SENDER_EXPECTED = "lightoarts@gmail.com"
MAX_SEND = 15
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
TAIPEI = ZoneInfo("Asia/Taipei")
GENERIC_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com"}

CANDIDATES = [
    {
        "company": "Aude",
        "email": "sales@aude.sg",
        "category": "real estate marketing",
        "website": "https://www.aude.sg/",
        "source_url": "https://www.aude.sg/",
        "personal": "Aude positions itself around real estate and property marketing in Singapore, so contemporary prints could be a practical visual layer for property campaigns, previews, and client-facing sales materials.",
    },
    {
        "company": "Roots Digital",
        "email": "enquiry@rootsdigital.com.sg",
        "category": "real estate digital marketing agency",
        "website": "https://www.rootsdigital.com.sg/real-estate-marketing-agency/",
        "source_url": "https://www.rootsdigital.com.sg/real-estate-marketing-agency/",
        "personal": "Roots Digital has a dedicated real estate marketing service for Singapore property businesses, where polished interior visuals and contemporary prints can support listings, lead-gen pages, and launch content.",
    },
    {
        "company": "Relevant Audience",
        "email": "info@relevantaudience.com",
        "category": "real estate marketing agency",
        "website": "https://relevantaudience.sg/real-estate-marketing/",
        "source_url": "https://relevantaudience.sg/contact-us/",
        "personal": "Relevant Audience's real estate marketing work focuses on helping Singapore property companies present projects and generate enquiries, so contemporary art prints could be useful for campaign imagery and staged interiors.",
    },
    {
        "company": "The Red Marker",
        "email": "info@theredmarker.com",
        "category": "360 virtual staging / virtual tour",
        "website": "https://www.theredmarker.com/en/360-virtual-staging",
        "source_url": "https://www.theredmarker.com/en/custom-virtual-tours",
        "personal": "The Red Marker offers 360 virtual staging and virtual tour services for real estate developers and agents, where contemporary prints can help empty or staged interiors feel more finished in tours.",
    },
    {
        "company": "VirtualStaging.sg",
        "email": "hello@virtualstaging.sg",
        "category": "AI virtual staging",
        "website": "https://virtualstaging.sg/",
        "source_url": "https://virtualstaging.sg/",
        "personal": "VirtualStaging.sg helps Singapore real estate agents turn empty rooms into furnished visuals, and contemporary art prints could give staged walls a cleaner, more marketable focal point.",
    },
    {
        "company": "Tubear",
        "email": "admin@tubear.co",
        "category": "virtual staging / virtual tour services",
        "website": "https://tubear.co/virtual-staging/",
        "source_url": "https://tubear.co/virtual-staging/",
        "personal": "Tubear lists virtual staging and virtual tour services from its Singapore office, so contemporary prints could be relevant for property visuals that need quick, polished wall styling.",
    },
    {
        "company": "Design Capital",
        "email": "enquiry@designcapital.sg",
        "category": "furniture / show-flat design solutions",
        "website": "https://www.designcapital.sg/",
        "source_url": "https://www.designcapital.sg/",
        "personal": "Design Capital's background includes interior design solutions and show-flat work, making contemporary prints a natural add-on for furnished model spaces and residential presentations.",
    },
    {
        "company": "A.RK Interior Design",
        "email": "info@ark-interior.com",
        "category": "sales gallery / showroom interior design",
        "website": "https://www.ark-interior.com/commercial",
        "source_url": "https://www.ark-interior.com/commercial",
        "personal": "A.RK's commercial portfolio references showrooms and sales galleries for property developers, where contemporary prints can help complete buyer-facing interiors without heavy procurement.",
    },
    {
        "company": "DDA",
        "email": "hello@dda.com.sg",
        "category": "show unit / sales gallery interior design",
        "website": "https://www.dda.com.sg/blog/show-unit-design-for-property-developers-in-singapore-selling-the-dream-before-its-built/",
        "source_url": "https://www.dda.com.sg/contact",
        "personal": "DDA writes directly about show unit and sales gallery design for Singapore property developers, so contemporary prints could fit the final styling layer for launch-ready model homes.",
    },
    {
        "company": "Wallflower Architecture + Design",
        "email": "enquiry@wallflower.com.sg",
        "category": "sales gallery / show-unit design",
        "website": "https://wallflower.com.sg/commercial/",
        "source_url": "https://www.wallflower.com.sg/contact",
        "personal": "Wallflower's commercial portfolio includes Wheelock Sales Gallery, Orchard View Sales Gallery, and Scotts Square show-units, where contemporary prints could support refined property-presentation spaces.",
    },
    {
        "company": "Space Atelier",
        "email": "enquiry@spaceatelier.com.sg",
        "category": "condo / commercial interior design",
        "website": "https://www.spaceatelier.com.sg/",
        "source_url": "https://www.spaceatelier.com.sg/contact-us/",
        "personal": "Space Atelier works across condo and commercial interiors in Singapore, so contemporary prints could be a simple finishing option for staged condominium visuals and client presentation spaces.",
    },
    {
        "company": "Fifth Avenue Interior",
        "email": "enquiries@fifthavenue.com.sg",
        "category": "residential / commercial interior design",
        "website": "https://www.fifthavenue.com.sg/",
        "source_url": "https://www.fifthavenue.com.sg/contact-us/",
        "personal": "Fifth Avenue handles residential and commercial interiors in Singapore, where contemporary prints can help model units, sales spaces, or listing-ready homes feel more complete.",
    },
    {
        "company": "Thom Signature",
        "email": "info@thomsignature.com.sg",
        "category": "condo / space planning interior design",
        "website": "https://www.thomsignature.com.sg/",
        "source_url": "https://www.thomsignature.com.sg/contact-us",
        "personal": "Thom Signature focuses on interior design and space planning for Singapore homes, so art prints could be a flexible styling layer for condominium units and presentation-ready rooms.",
    },
    {
        "company": "Posh Living",
        "email": "enquiry@poshliving.com.sg",
        "category": "condo / residential interior design",
        "website": "https://www.poshliving.com.sg/",
        "source_url": "https://www.poshliving.com.sg/contact-us/",
        "personal": "Posh Living works on condo and residential interiors in Singapore, where contemporary prints can help finished rooms photograph better for portfolios, listings, and client previews.",
    },
    {
        "company": "EightyTwo",
        "email": "hello@eightytwo.sg",
        "category": "luxury residential / commercial interiors",
        "website": "https://eightytwo.sg/",
        "source_url": "https://eightytwo.sg/contact/",
        "personal": "EightyTwo creates high-end residential and commercial interiors in Singapore, so contemporary prints could be a useful finishing layer for luxury model-home moods and sales-facing spaces.",
    },
    {
        "company": "New Interior Design",
        "email": "enquiry@newid.com.sg",
        "category": "sales gallery / residential interior design",
        "website": "https://newid.com.sg/",
        "source_url": "https://newid.com.sg/contact-us/",
        "personal": "New Interior Design's public project updates reference sales-gallery common areas and residential design work, where contemporary prints can support refined property presentation and showroom photography.",
    },
]


def clean_email(value):
    return value.strip().lower().lstrip("%20")


def domain_of(email_or_url):
    if "@" in email_or_url:
        return clean_email(email_or_url).split("@", 1)[1]
    parsed = urlparse(email_or_url if "://" in email_or_url else "https://" + email_or_url)
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def is_bad_email(email):
    e = clean_email(email)
    if any(bad in e for bad in ["@2x.", "u003e", "icon-connect", "cropped-favicon", "example.com", "user@domain.com", "sentry", "your-name@email.com"]):
        return True
    if e.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico")):
        return True
    return not re.search(r"[a-z]", e.split("@", 1)[0])


def visible_text(html):
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))


def fetch_evidence(candidate):
    response = requests.get(candidate["source_url"], timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    text = response.text
    emails = {clean_email(e) for e in EMAIL_RE.findall(text) if not is_bad_email(e)}
    target = clean_email(candidate["email"])
    if target not in emails:
        raise RuntimeError(f"target email not visibly found on source page; extracted={sorted(emails)[:12]}")
    compact = visible_text(text)
    idx = compact.lower().find(target)
    excerpt = compact[max(0, idx - 120): idx + 220].strip() if idx >= 0 else compact[:320].strip()
    excerpt = excerpt.encode("ascii", "ignore").decode("ascii")
    return f"Official source visibly lists {target}. Evidence excerpt: {excerpt[:320]}"


def get_values(sheets, sheet_range):
    return sheets.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=sheet_range).execute().get("values", [])


def add_sheet_history(rows, email_idx, domain_idx=None):
    emails, domains, unsafe_emails, unsafe_domains = set(), set(), set(), set()
    for row in rows[1:]:
        haystack = " ".join(row).lower()
        unsafe = any(term in haystack for term in ["bounced", "do not send", "unsubscribe", "do_not_send", "do-not-send", "replied", "auto-reply / do not resend"])
        if len(row) > email_idx and row[email_idx]:
            email = clean_email(row[email_idx])
            domain = domain_of(email)
            emails.add(email)
            if domain not in GENERIC_EMAIL_DOMAINS:
                domains.add(domain)
            if unsafe:
                unsafe_emails.add(email)
                if domain not in GENERIC_EMAIL_DOMAINS:
                    unsafe_domains.add(domain)
        if domain_idx is not None and len(row) > domain_idx and row[domain_idx]:
            domain = domain_of(row[domain_idx])
            if domain and domain not in GENERIC_EMAIL_DOMAINS:
                domains.add(domain)
                if unsafe:
                    unsafe_domains.add(domain)
    return emails, domains, unsafe_emails, unsafe_domains


def gmail_has_prior(gmail, email, domain):
    queries = [f'in:sent to:{email}', f'in:anywhere from:{email}']
    if domain not in GENERIC_EMAIL_DOMAINS:
        queries.append(f'in:sent "{domain}"')
    for q in queries:
        result = gmail.users().messages().list(userId="me", q=q, maxResults=1).execute()
        if result.get("messages"):
            return q
    return None


def make_body(candidate):
    return (
        f"Hello {candidate['company']} team,\n\n"
        f"{candidate['personal']}\n\n"
        "I am reaching out from Lighto Arts, a Taiwan-born and U.S.-registered art print brand offering contemporary art prints for staged homes, showflats, model units, and property-marketing spaces. "
        "We work with premium print-on-demand and logistics partners, so pieces can be produced reliably and shipped globally without requiring a large upfront inventory commitment.\n\n"
        "You can view the collection here: https://lightoarts.com\n\n"
        "If art prints are not relevant for your spaces or upcoming property presentation needs, no worries at all. A simple reply with \"opt out\" is enough and I will not contact you again.\n\n"
        "Best regards,\n"
        "Lighto Arts\n"
        "https://lightoarts.com"
    )


def send_email(gmail, candidate):
    msg = MIMEText(make_body(candidate), "plain", "utf-8")
    msg["To"] = candidate["email"]
    msg["From"] = SENDER_EXPECTED
    msg["Subject"] = f"Contemporary art prints for {candidate['company']} spaces"
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    return gmail.users().messages().send(userId="me", body={"raw": raw}).execute()


def append_values(sheets, sheet_name, rows):
    return sheets.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{sheet_name}'!A:Z",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()


def main():
    dry_run = os.environ.get("DRY_RUN") == "1"
    gmail = build_service("gmail", "v1")
    sheets = build_service("sheets", "v4")
    profile = gmail.users().getProfile(userId="me").execute()
    sender = profile.get("emailAddress", "").lower()
    if sender != SENDER_EXPECTED:
        raise SystemExit(f"Authenticated Gmail is {sender}, expected {SENDER_EXPECTED}")

    contacts = get_values(sheets, "'Designer Contacts'!A:Z")
    sent_log = get_values(sheets, "'Outreach Sent Log'!A:Z")
    bounces = get_values(sheets, "'Email Bounces'!A:L")
    contact_emails, contact_domains, contact_unsafe_emails, contact_unsafe_domains = add_sheet_history(contacts, 4, domain_idx=6)
    sent_emails, sent_domains, _, _ = add_sheet_history(sent_log, 1, domain_idx=7)
    bounce_emails, bounce_domains, bounce_unsafe_emails, bounce_unsafe_domains = add_sheet_history(bounces, 1)

    blocked_emails = contact_emails | sent_emails | bounce_emails | contact_unsafe_emails | bounce_unsafe_emails
    blocked_domains = contact_domains | sent_domains | bounce_domains | contact_unsafe_domains | bounce_unsafe_domains

    accepted, skipped, seen_domains = [], [], set()
    for candidate in CANDIDATES:
        email = clean_email(candidate["email"])
        domain = domain_of(email)
        candidate["email"] = email
        candidate["domain"] = domain
        if email in blocked_emails or (domain not in GENERIC_EMAIL_DOMAINS and domain in blocked_domains):
            skipped.append({**candidate, "reason": "sheet/email/domain history duplicate or unsafe"})
            continue
        if domain not in GENERIC_EMAIL_DOMAINS and domain in seen_domains:
            skipped.append({**candidate, "reason": "duplicate candidate domain in this run"})
            continue
        try:
            candidate["evidence"] = fetch_evidence(candidate)
        except Exception as exc:
            skipped.append({**candidate, "reason": f"source verification failed: {exc}"})
            continue
        prior = gmail_has_prior(gmail, email, domain)
        if prior:
            skipped.append({**candidate, "reason": f"Gmail history duplicate: {prior}"})
            continue
        accepted.append(candidate)
        if domain not in GENERIC_EMAIL_DOMAINS:
            seen_domains.add(domain)
        if len(accepted) >= MAX_SEND:
            break

    sent = []
    for candidate in accepted:
        now = datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M:%S Asia/Taipei")
        subject = f"Contemporary art prints for {candidate['company']} spaces"
        msg_result = {"id": "DRY_RUN", "threadId": "DRY_RUN"} if dry_run else send_email(gmail, candidate)
        gmail_id = msg_result.get("id", "")
        thread_id = msg_result.get("threadId", "")
        notes = (
            f"Source: {candidate['source_url']} | Evidence: {candidate['evidence']} | "
            f"Singapore-first; verified official/trusted source; gmail_id={gmail_id}; thread_id={thread_id}"
        )
        if not dry_run:
            append_values(sheets, "Designer Contacts", [[
                "", "Singapore", candidate["company"], "", candidate["email"],
                f"Sent {now}", candidate["website"], candidate["category"],
                now.split(" ")[0], "", "", "", notes,
            ]])
            append_values(sheets, "Outreach Sent Log", [[
                now, candidate["email"], candidate["company"], CATEGORY, subject,
                gmail_id, thread_id, candidate["source_url"], "appended", "",
            ]])
            time.sleep(2.5)
        sent.append({**candidate, "sent_at_taipei": now, "subject": subject, "gmail_message_id": gmail_id, "thread_id": thread_id})

    run_now = datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M:%S Asia/Taipei")
    run_row = [[
        run_now, CATEGORY, len(sent), "dry_run" if dry_run else "sent",
        f"verified={len(accepted)}; skipped={len(skipped)}; sender={sender}",
        ", ".join(item["company"] for item in sent),
    ]]
    if not dry_run:
        append_values(sheets, "Run Log", run_row)

    out_dir = Path(__file__).resolve().parent / "outreach_logs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "2026-06-22_21_real_estate_staging_singapore.json"
    out_path.write_text(json.dumps({"dry_run": dry_run, "sent": sent, "skipped": skipped, "run_log": run_row}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"dry_run": dry_run, "sent_count": len(sent), "sent": sent, "skipped_count": len(skipped), "skipped": skipped, "log": str(out_path)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

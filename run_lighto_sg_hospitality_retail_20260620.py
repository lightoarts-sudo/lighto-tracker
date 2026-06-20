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
CATEGORY = "hospitality retail singapore"
SENDER_EXPECTED = "lightoarts@gmail.com"
MAX_SEND = 15
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
TAIPEI = ZoneInfo("Asia/Taipei")


CANDIDATES = [
    {
        "company": "Naumi Hotel Singapore",
        "email": "info.nsg@naumihotels.com",
        "category": "boutique hotel / guest accommodation",
        "website": "https://www.naumihotels.com/naumi-hotel-singapore",
        "source_url": "https://www.naumihotels.com/naumi-hotel-singapore",
        "personal": "Naumi Hotel Singapore's Seah Street setting and design-led rooms make art part of the first guest impression, especially around lobby, corridor, and in-room moments.",
    },
    {
        "company": "BaKery Artisan Original",
        "email": "sales@bao.com.sg",
        "category": "artisan bakery",
        "website": "https://www.bao.com.sg/",
        "source_url": "https://www.bao.com.sg/new-page",
        "personal": "BaKery Artisan Original's sourdough, pastry, and neighbourhood bakery environment feels well suited to calm contemporary prints that support a warm retail food experience.",
    },
    {
        "company": "Hard Rock Cafe Singapore",
        "email": "orchard-enquiries@hardrockcafe-singapore.com",
        "category": "restaurant / event dining",
        "website": "https://cafe.hardrock.com/singapore/",
        "source_url": "https://cafe.hardrock.com/singapore/",
        "personal": "Hard Rock Cafe Singapore's Orchard dining and private-event setting already uses strong visual energy, so contemporary art prints could add a flexible layer for event and guest-facing areas.",
    },
    {
        "company": "PS.Cafe",
        "email": "concierge@pscafe.com",
        "category": "cafe restaurant group",
        "website": "https://www.pscafe.com/",
        "source_url": "https://www.pscafe.com/contact-us",
        "personal": "PS.Cafe's cafe and dining spaces have a polished, social atmosphere where contemporary prints could support the relaxed but memorable guest experience.",
    },
    {
        "company": "Dome Bakery",
        "email": "hello@domebakery.sg",
        "category": "boutique artisanal bakery",
        "website": "https://domebakery.sg/",
        "source_url": "https://domebakery.sg/pages/contact",
        "personal": "Dome Bakery's South Bridge Road bakery and dessert-focused counter could use approachable contemporary prints as a soft visual accent for dine-in and takeaway guests.",
    },
    {
        "company": "Burnt Ends",
        "email": "eat@burntends.com.sg",
        "category": "restaurant / bakery hospitality group",
        "website": "https://burntends.com.sg/",
        "source_url": "https://burntends.com.sg/contact/",
        "personal": "Burnt Ends' Dempsey restaurant, cocktail bar, bakery, and hospitality group setting has a strong guest journey where art prints could add quiet visual rhythm between venues.",
    },
    {
        "company": "Soup Restaurant",
        "email": "email@souprestaurant.com.sg",
        "category": "restaurant group",
        "website": "https://www.souprestaurant.com.sg/",
        "source_url": "https://www.souprestaurant.com.sg/contact",
        "personal": "Soup Restaurant's Singapore dining rooms serve families and groups across multiple outlets, where contemporary prints could add a refined and consistent visual touch.",
    },
    {
        "company": "Tea Tree Cafe",
        "email": "hr@tea-tree-cafe.com.sg",
        "category": "cafe / food retail",
        "website": "https://tea-tree-cafe.com.sg/",
        "source_url": "https://tea-tree-cafe.com.sg/pages/contact-us",
        "personal": "Tea Tree Cafe's Singapore cafe operations and everyday food-service setting could benefit from contemporary prints that keep the environment fresh without feeling intrusive.",
    },
    {
        "company": "Carlton Hotel Singapore",
        "email": "roomreservations@carltonhotel.sg",
        "category": "hotel accommodation",
        "website": "https://www.carltonhotel.sg/",
        "source_url": "https://www.carltonhotel.sg/contact-and-location",
        "personal": "Carlton Hotel Singapore's Bras Basah guest rooms, dining, and public areas create many touchpoints where understated contemporary prints could support a polished hotel experience.",
    },
    {
        "company": "Fairmont Singapore",
        "email": "singapore@fairmont.com",
        "category": "hotel / hospitality",
        "website": "https://www.fairmont-singapore.com/",
        "source_url": "https://www.fairmont-singapore.com/contact-us/",
        "personal": "Fairmont Singapore's central hotel environment spans arrival, dining, meetings, and guest stays, making it a natural fit for contemporary prints that can scale across hospitality zones.",
    },
    {
        "company": "Raffles Singapore",
        "email": "singapore@raffles.com",
        "category": "heritage hotel / hospitality",
        "website": "https://www.raffles.com/singapore/",
        "source_url": "https://www.raffles.com/singapore/",
        "personal": "Raffles Singapore's heritage guest experience is carefully curated, and contemporary prints could offer a tasteful contrast for selected suites, corridors, or private hospitality moments.",
    },
    {
        "company": "Cultivate Cafe",
        "email": "reservations@cultivatecafe.sg",
        "category": "cafe / restaurant",
        "website": "https://cultivatecafe.sg/",
        "source_url": "https://cultivatecafe.sg/",
        "personal": "Cultivate Cafe's wellness-leaning dining atmosphere and plant-forward hospitality setting could pair well with calm contemporary print selections for guest-facing walls.",
    },
    {
        "company": "Typhoon Cafe",
        "email": "mail@createries.com",
        "category": "Taiwanese cafe / restaurant",
        "website": "https://www.typhooncafe.com.sg/",
        "source_url": "https://www.typhooncafe.com.sg/contact-us-1",
        "personal": "Typhoon Cafe's Taiwanese dining concept in Singapore gives Lighto Arts a relevant cultural bridge, with contemporary prints that could add a modern visual layer to the cafe environment.",
    },
    {
        "company": "Casa Singapore",
        "email": "ecommerce@casa.com.sg",
        "category": "home appliance / lifestyle retail",
        "website": "https://shop.casa.sg/",
        "source_url": "https://shop.casa.sg/pages/contact-us",
        "personal": "Casa Singapore's home-focused retail experience reaches customers thinking about living spaces, where contemporary art prints could work as an accessible finishing detail.",
    },
    {
        "company": "Celson",
        "email": "sales@celson.sg",
        "category": "lifestyle furniture / retail showroom",
        "website": "https://celson.sg/",
        "source_url": "https://celson.sg/pages/contact-us",
        "personal": "Celson's lifestyle showroom and custom home-product setting could use contemporary prints as a natural wall-decor complement for customers visualising finished interiors.",
    },
    {
        "company": "IMI Lifestyle",
        "email": "admin@imi.com.sg",
        "category": "lifestyle product retail",
        "website": "https://www.imi.com.sg/",
        "source_url": "https://www.imi.com.sg/pages/contact-us",
        "personal": "IMI Lifestyle's health and lifestyle product environment could pair well with light, contemporary wall art that keeps retail areas warm and visually considered.",
    },
    {
        "company": "iFood",
        "email": "enquiries@ifood.com.sg",
        "category": "food retail / hospitality supplier",
        "website": "https://ifood.com.sg/",
        "source_url": "https://ifood.com.sg/contact-us/",
        "personal": "iFood's Singapore food retail and supply environment serves hospitality customers, making contemporary prints a useful visual option for tasting, showroom, or client-facing spaces.",
    },
    {
        "company": "AMOY Singapore",
        "email": "info.amoy@fareast.com",
        "category": "boutique heritage hotel",
        "website": "https://www.fareasthospitality.com/en/hotels/amoy",
        "source_url": "https://www.fareasthospitality.com/en/hotels/amoy",
        "personal": "AMOY's heritage boutique-hotel identity creates intimate guest moments where contemporary prints could add a restrained modern layer without overwhelming the architecture.",
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
    if any(bad in e for bad in ["@2x.", "u003e", "icon-connect", "cropped-favicon", "example.com", "user@domain.com", "sentry"]):
        return True
    if e.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico")):
        return True
    if not re.search(r"[a-z]", e.split("@", 1)[0]):
        return True
    return False


def fetch_evidence(candidate):
    response = requests.get(candidate["source_url"], timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    text = response.text
    emails = {clean_email(e) for e in EMAIL_RE.findall(text) if not is_bad_email(e)}
    target = clean_email(candidate["email"])
    if target not in emails:
        raise RuntimeError(f"target email not visibly found on source page; extracted={sorted(emails)[:12]}")
    compact = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
    idx = compact.lower().find(target)
    if idx < 0:
        idx = compact.lower().find(target.split("@", 1)[0])
    excerpt = compact[max(0, idx - 120): idx + 220].strip() if idx >= 0 else compact[:320].strip()
    excerpt = excerpt.encode("ascii", "ignore").decode("ascii")
    return f"Official page visibly lists {target}. Evidence excerpt: {excerpt[:320]}"


def get_values(sheets, sheet_range):
    return sheets.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=sheet_range).execute().get("values", [])


def add_sheet_history(rows, email_idx, domain_idx=None, status_idx=None, notes_idx=None):
    emails, domains, unsafe = set(), set(), set()
    for row in rows[1:]:
        if len(row) > email_idx and row[email_idx]:
            email = clean_email(row[email_idx])
            emails.add(email)
            domains.add(domain_of(email))
            haystack = " ".join(row).lower()
            if any(term in haystack for term in ["bounced", "do not send", "unsubscribe", "auto-reply / do not resend", "do_not_send", "replied"]):
                unsafe.add(email)
                unsafe.add(domain_of(email))
        if domain_idx is not None and len(row) > domain_idx and row[domain_idx]:
            domains.add(domain_of(row[domain_idx]))
        if status_idx is not None and len(row) > status_idx:
            pass
        if notes_idx is not None and len(row) > notes_idx:
            pass
    return emails, domains, unsafe


def gmail_has_prior(gmail, email, domain):
    queries = [
        f'in:sent to:{email}',
        f'in:sent "{domain}"',
        f'in:anywhere from:{email}',
    ]
    for q in queries:
        result = gmail.users().messages().list(userId="me", q=q, maxResults=1).execute()
        if result.get("messages"):
            return q
    return None


def make_body(candidate):
    return (
        f"Hello {candidate['company']} team,\n\n"
        f"{candidate['personal']}\n\n"
        "I am reaching out from Lighto Arts, a Taiwan-born and U.S.-registered art print brand offering contemporary art prints for hospitality, retail, and guest-facing spaces. "
        "We work with premium print-on-demand and logistics partners, so pieces can be produced reliably and shipped globally without requiring a large upfront inventory commitment.\n\n"
        "You can view the collection here: https://lightoarts.com\n\n"
        "If art prints are not relevant for your spaces or retail planning, no worries at all. A simple reply with \"opt out\" is enough and I will not contact you again.\n\n"
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
    body = {"values": rows}
    return sheets.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{sheet_name}'!A:Z",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
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
    contact_emails, contact_domains, contact_unsafe = add_sheet_history(contacts, 4, domain_idx=6)
    sent_emails, sent_domains, _ = add_sheet_history(sent_log, 1, domain_idx=7)
    bounce_emails, bounce_domains, bounce_unsafe = add_sheet_history(bounces, 1)

    blocked_emails = contact_emails | sent_emails | bounce_emails | contact_unsafe | bounce_unsafe
    blocked_domains = contact_domains | sent_domains | bounce_domains | contact_unsafe | bounce_unsafe

    accepted, skipped = [], []
    seen_domains = set()
    for candidate in CANDIDATES:
        email = clean_email(candidate["email"])
        domain = domain_of(email)
        candidate["email"] = email
        candidate["domain"] = domain
        if domain in {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com"}:
            skipped.append({**candidate, "reason": "generic mailbox domain skipped"})
            continue
        if email in blocked_emails or domain in blocked_domains:
            skipped.append({**candidate, "reason": "sheet/email/domain history duplicate or unsafe"})
            continue
        if domain in seen_domains:
            skipped.append({**candidate, "reason": "duplicate candidate domain in this run"})
            continue
        try:
            evidence = fetch_evidence(candidate)
        except Exception as exc:
            skipped.append({**candidate, "reason": f"source verification failed: {exc}"})
            continue
        prior = gmail_has_prior(gmail, email, domain)
        if prior:
            skipped.append({**candidate, "reason": f"Gmail history duplicate: {prior}"})
            continue
        candidate["evidence"] = evidence
        accepted.append(candidate)
        seen_domains.add(domain)
        if len(accepted) >= MAX_SEND:
            break

    sent = []
    for candidate in accepted:
        now = datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M:%S Asia/Taipei")
        subject = f"Contemporary art prints for {candidate['company']} spaces"
        if dry_run:
            msg_result = {"id": "DRY_RUN", "threadId": "DRY_RUN"}
        else:
            msg_result = send_email(gmail, candidate)
        gmail_id = msg_result.get("id", "")
        thread_id = msg_result.get("threadId", "")
        notes = (
            f"Source: {candidate['source_url']} | Evidence: {candidate['evidence']} | "
            f"Singapore-first; verified official source; gmail_id={gmail_id}; thread_id={thread_id}"
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
    out_path = out_dir / "2026-06-20_20_hospitality_retail_singapore.json"
    out_path.write_text(json.dumps({"dry_run": dry_run, "sent": sent, "skipped": skipped, "run_log": run_row}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"dry_run": dry_run, "sent_count": len(sent), "sent": sent, "skipped_count": len(skipped), "log": str(out_path)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

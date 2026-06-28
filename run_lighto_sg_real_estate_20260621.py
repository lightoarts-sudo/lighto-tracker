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
        "company": "Our Momento",
        "email": "contact@ourmomento.sg",
        "category": "real estate videography / property marketing",
        "website": "https://ourmomento.sg/real-estate-videography/",
        "source_url": "https://ourmomento.sg/real-estate-videography/",
        "personal": "Our Momento's real estate videography helps Singapore properties stand out online, so contemporary prints could give staged rooms stronger wall detail for listing videos and buyer previews.",
    },
    {
        "company": "Bespoke Photography",
        "email": "hello@bespokephotography.sg",
        "category": "interior / real estate photography",
        "website": "https://www.bespokephotography.sg/interior-photographer-singapore/",
        "source_url": "https://www.bespokephotography.sg/interior-photographer-singapore/",
        "personal": "Bespoke Photography's interior and real estate work is built around making spaces read well on camera, where contemporary prints can add a polished finishing layer for listings and project shoots.",
    },
    {
        "company": "Prime Photography",
        "email": "hello@primephotography.sg",
        "category": "interior / real estate photography",
        "website": "https://primephotography.sg/services/photography/interior-real-estate-photography/",
        "source_url": "https://primephotography.sg/contact/",
        "personal": "Prime Photography offers interior and real estate photography in Singapore, so art prints could help listing, portfolio, and showroom spaces feel more complete before a shoot.",
    },
    {
        "company": "Studio Five Corp",
        "email": "hey@studiofivecorp.com",
        "category": "real estate walkthrough video / property marketing",
        "website": "https://studiofivecorp.com/videography/real-estate-video-production-singapore/",
        "source_url": "https://studiofivecorp.com/contact/",
        "personal": "Studio Five Corp's real estate walkthrough videos depend on rooms looking ready and memorable, where contemporary prints can support stronger property storytelling on camera.",
    },
    {
        "company": "Vivid Snaps",
        "email": "contact@vividsnaps.com",
        "category": "property video production",
        "website": "https://www.vividsnaps.com/property-video-production/",
        "source_url": "https://www.vividsnaps.com/property-video-production/",
        "personal": "Vivid Snaps covers property video references and production for Singapore spaces, so contemporary prints could be a practical styling option for cleaner, more distinctive house-tour visuals.",
    },
    {
        "company": "Vision Photography",
        "email": "info@djparkervisionphotography.com",
        "category": "real estate photography",
        "website": "https://www.visionphotography.com.sg/contact",
        "source_url": "https://www.visionphotography.com.sg/contact",
        "personal": "Vision Photography notes real estate photography among its Singapore services, making contemporary prints relevant as a lightweight way to improve staged interiors before photography.",
    },
    {
        "company": "MILTON Studios",
        "email": "contact@miltontan.com",
        "category": "architecture / interiors photography",
        "website": "https://miltontan.com/blog/singapore-architecture-photographer/",
        "source_url": "https://miltontan.com/blog/singapore-architecture-photographer/",
        "personal": "MILTON Studios' architectural photography often captures design-led spaces, where contemporary art prints can help model units, showrooms, and property interiors feel visually anchored.",
    },
    {
        "company": "Home Tour Studios",
        "email": "contact@hometourstudios.com",
        "category": "real estate photo / video / virtual tours",
        "website": "https://www.hometourstudios.com/",
        "source_url": "https://www.hometourstudios.com/",
        "personal": "Home Tour Studios creates property video tours, interior photographs, 360 tours, and virtual staging, so contemporary prints could be a useful detail for listings and tour-ready homes.",
    },
    {
        "company": "APVT Media",
        "email": "apvt.media@gmail.com",
        "category": "aerial / real estate visual media",
        "website": "https://www.apvtmedia.com/real-estate-gallery-2",
        "source_url": "https://www.apvtmedia.com/contact",
        "personal": "APVT Media's real estate and aerial visuals support property marketing, where contemporary prints can add detail and warmth to interiors used in photo, video, and listing campaigns.",
    },
    {
        "company": "Haroko Studio",
        "email": "contact@harokostudio.com",
        "category": "360 virtual tour photography",
        "website": "https://www.harokostudio.com/",
        "source_url": "https://www.harokostudio.com/",
        "personal": "Haroko Studio's 360 virtual tour photography helps spaces be explored remotely, so contemporary prints could give property tours, showrooms, and model interiors more visual texture.",
    },
    {
        "company": "Mods360 Production",
        "email": "hello@mods360.com.sg",
        "category": "real estate videography / 360 tour / virtual staging",
        "website": "https://www.mods360.com.sg/real-estate/",
        "source_url": "https://www.mods360.com.sg/contact-page/",
        "personal": "Mods360 combines real estate videography, 360 virtual tours, and virtual staging, so contemporary prints could support more finished walls in property visuals and home-tour campaigns.",
    },
    {
        "company": "fewStones",
        "email": "studiofewstones@gmail.com",
        "category": "real estate photography / video production",
        "website": "https://fewstones.com/real-estate-photography-singapore",
        "source_url": "https://fewstones.setmore.com/",
        "personal": "fewStones offers real estate photography and video production in Singapore, where contemporary prints can be a simple way to help listings and walkthrough footage feel more styled.",
    },
    {
        "company": "Digital Squad",
        "email": "hello@digitalsquad.com.sg",
        "category": "real estate marketing agency",
        "website": "https://digitalsquad.com.sg/services/real-estate-marketing-agency-singapore",
        "source_url": "https://digitalsquad.com.sg/services/real-estate-marketing-agency-singapore",
        "personal": "Digital Squad's real estate marketing work covers developer campaigns, property lead generation, and direct enquiry systems, where contemporary prints could be a useful visual angle for property-brand content.",
    },
    {
        "company": "ShowSuite",
        "email": "feedback@showsuite.com",
        "category": "real estate sales / property marketing platform",
        "website": "https://www.showsuite.com/",
        "source_url": "https://www.showsuite.com/more/terms-of-use",
        "personal": "ShowSuite supports property developers, agencies, and agents with sales and marketing workflows, so contemporary prints could be relevant for model-unit visuals and property presentation content.",
    },
    {
        "company": "Viewport Studio",
        "email": "hello@viewportstudio.sg",
        "category": "show apartment / interior design studio",
        "website": "https://www.viewportstudio.sg/projects2025/showflat",
        "source_url": "https://www.viewportstudio.sg/privacy-policy",
        "personal": "Viewport Studio's show apartment work shows how design and furnishings help prospective buyers imagine a home, and contemporary prints could be a flexible finishing layer for similar presentations.",
    },
    {
        "company": "Tong Hai Yang",
        "email": "enquiry@tonghaiyang.com",
        "category": "showflat and show suite contractor",
        "website": "https://www.tonghaiyang.com/showflat-and-show-suite-development",
        "source_url": "https://www.tonghaiyang.com/showflat-and-show-suite-development",
        "personal": "Tong Hai Yang's showflat and show suite development work sits directly in the model-home presentation process, where contemporary prints can help completed spaces feel buyer-ready.",
    },
    {
        "company": "Hassell Singapore",
        "email": "singapore@hassellstudio.com",
        "category": "architecture / interior design studio",
        "website": "https://www.hassellstudio.com/studio/singapore",
        "source_url": "https://www.hassellstudio.com/studio/singapore",
        "personal": "Hassell Singapore works across designed environments and client-facing spaces, where contemporary prints can be a simple option for property presentation, workplace suites, and display interiors.",
    },
    {
        "company": "D'Perception Ritz",
        "email": "ritz@dperception.com.sg",
        "category": "developer showflat interior design",
        "website": "https://www.dperceptionritz.com.sg/developer-showflat",
        "source_url": "https://www.dperceptionritz.com.sg/contact",
        "personal": "D'Perception Ritz specialises in developer showflats and show suites, where contemporary art prints can support finished model-home settings without adding complex procurement.",
    },
    {
        "company": "Cameron Woo Design",
        "email": "info@cwd.com.au",
        "category": "interior design for property developers",
        "website": "https://cameronwoodesign.com/",
        "source_url": "https://cameronwoodesign.com/",
        "personal": "Cameron Woo Design works with property developers across Singapore and Asia Pacific, so contemporary prints could be relevant for model homes, hospitality suites, and sales-facing interiors.",
    },
    {
        "company": "SuMisura",
        "email": "enquiries@sumisura.asia",
        "category": "luxury showflat interior design",
        "website": "https://sumisura.asia/bespoke-interiors-showflatsseries/",
        "source_url": "https://sumisura.asia/contact-us/",
        "personal": "SuMisura's luxury showflat and show gallery work is highly visual and buyer-facing, making contemporary prints a natural layer for creating polished, memorable model-home moods.",
    },
    {
        "company": "Index Design",
        "email": "career@index.com.sg",
        "category": "showflat interior design / interior design firm",
        "website": "https://www.index.com.sg/",
        "source_url": "https://www.mycareersfuture.gov.sg/job/architecture/interior-designer-index-design-6a856e889c1a600ff381967157cdad92",
        "personal": "Index Design's showflat interior design hiring points to developer-facing presentation work, where contemporary prints could be a useful finishing option for model units.",
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
    return not re.search(r"[a-z]", e.split("@", 1)[0])


def visible_text(html):
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))


def fetch_evidence(candidate):
    response = requests.get(candidate["source_url"], timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    text = response.text.replace("[email protected]", candidate["email"])
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
    out_path = out_dir / "2026-06-21_21_real_estate_staging_singapore.json"
    out_path.write_text(json.dumps({"dry_run": dry_run, "sent": sent, "skipped": skipped, "run_log": run_row}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"dry_run": dry_run, "sent_count": len(sent), "sent": sent, "skipped_count": len(skipped), "skipped": skipped, "log": str(out_path)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

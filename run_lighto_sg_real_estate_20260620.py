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


CANDIDATES = [
    {
        "company": "SFR Home Staging",
        "email": "sales@sfrhomestaging.com",
        "category": "home staging company",
        "website": "https://sfrhomestaging.com/",
        "source_url": "https://sfrhomestaging.com/home-staging-singapore-cost/",
        "personal": "SFR Home Staging's work is directly focused on turning Singapore properties into buyer-ready homes, so contemporary prints could be a flexible finishing layer for staged units and marketing photography.",
    },
    {
        "company": "Lian Huat Furniture Rental",
        "email": "sales@furniturerental.com.sg",
        "category": "home staging / furniture rental",
        "website": "https://www.furniturerental.com.sg/home-staging/",
        "source_url": "https://www.furniturerental.com.sg/home-staging/",
        "personal": "Lian Huat's home staging and furniture rental service supports Singapore sellers who need a polished first impression, where art prints can help staged rooms feel warmer and more complete.",
    },
    {
        "company": "SLB Development",
        "email": "admin@slbdevelopment.com.sg",
        "category": "property developer",
        "website": "https://www.slbdevelopment.com.sg/",
        "source_url": "https://www.slbdevelopment.com.sg/contact-us/",
        "personal": "SLB Development's residential and industrial property work creates show suites, sales materials, and completed spaces where contemporary prints can support a clean, modern presentation.",
    },
    {
        "company": "Brand New Land Group",
        "email": "comehome@brandnewland.com.sg",
        "category": "landed property developer",
        "website": "https://brandnewland.com.sg/",
        "source_url": "https://brandnewland.com.sg/our-story/",
        "personal": "Brand New Land's landed residential projects emphasize special homes and carefully considered living environments, making contemporary prints a natural finishing detail for presentation homes.",
    },
    {
        "company": "Audax Visuals Singapore",
        "email": "sales@audax.com.sg",
        "category": "real estate digital showroom / visuals",
        "website": "https://www.audax.com.sg/visuals/index.php/for-real-estate/",
        "source_url": "https://www.audax.com.sg/visuals/index.php/for-real-estate/",
        "personal": "Audax Visuals builds digital showroom and real estate visual experiences, so art prints could be useful as realistic, contemporary wall-decor options when shaping model-home and sales visuals.",
    },
    {
        "company": "Oxley Holdings",
        "email": "salesgallery@oxley.com.sg",
        "category": "property developer / sales gallery",
        "website": "https://www.oxley.com.sg/",
        "source_url": "https://www.oxley.com.sg/contact/",
        "personal": "Oxley's residential projects and sales gallery enquiries make visual presentation important, and contemporary prints could help model units and sales spaces feel considered without adding inventory burden.",
    },
    {
        "company": "Allgreen Properties",
        "email": "apl@allgreen.com.sg",
        "category": "real estate group / property developer",
        "website": "https://allgreen.com.sg/",
        "source_url": "https://allgreen.com.sg/contact/",
        "personal": "Allgreen's residential, retail, and mixed-property portfolio depends on polished spatial presentation, where contemporary prints can be a simple layer for show suites or marketing spaces.",
    },
    {
        "company": "United Engineers Developments",
        "email": "dairyfarmresidences@uel.sg",
        "category": "property developer / residential project",
        "website": "https://uel.sg/property-type/property/",
        "source_url": "https://uel.sg/property/dairy-farm-residences/",
        "personal": "United Engineers' residential development portfolio and Dairy Farm Residences presentation needs make contemporary prints relevant for model units, handover spaces, and buyer-facing interiors.",
    },
    {
        "company": "Design Bureau",
        "email": "enquiry@designbureau.sg",
        "category": "interior design / design-build",
        "website": "https://designbureau.sg/",
        "source_url": "https://designbureau.sg/contact/",
        "personal": "Design Bureau's design-build and showroom work touches the kind of residential and client-facing interiors where contemporary prints can help complete a staged or presentation-ready space.",
    },
    {
        "company": "The Interior Lab",
        "email": "enquiry@theinteriorlab.com.sg",
        "category": "interior design / showrooms",
        "website": "https://www.theinteriorlab.com.sg/",
        "source_url": "https://www.theinteriorlab.com.sg/contact-us/",
        "personal": "The Interior Lab's Singapore showrooms and residential design work are closely tied to helping clients visualize finished homes, where contemporary prints can serve as adaptable wall accents.",
    },
    {
        "company": "Wonder Design and Construction",
        "email": "support@singwonder.com",
        "category": "interior design / construction",
        "website": "https://www.singwonder.com/en/",
        "source_url": "https://www.singwonder.com/en/contact-us",
        "personal": "Wonder Design and Construction's Singapore interiors and design-build projects often need final styling choices that make rooms feel complete for owners, buyers, or presentation photography.",
    },
    {
        "company": "DB2Land",
        "email": "enquiries@db2land.com.sg",
        "category": "property developer",
        "website": "https://db2land.com.sg/",
        "source_url": "https://db2land.com.sg/aboutdb2/",
        "personal": "DB2Land's residential development work emphasizes contemporary, elegant spaces, where art prints could help show units and buyer-facing material feel more complete.",
    },
    {
        "company": "Da Vinci Land",
        "email": "enquiries@davinciland.co",
        "category": "luxury bespoke property developer",
        "website": "https://www.davinciland.co/",
        "source_url": "https://www.davinciland.co/contact-us/",
        "personal": "Da Vinci Land's bespoke luxury residential focus makes visual detail especially important, and contemporary prints could support model homes, sales presentations, or finished show suites.",
    },
    {
        "company": "Hoi Hup Realty",
        "email": "enquiry@hoihup.com",
        "category": "property developer",
        "website": "https://www.hoihup.com/",
        "source_url": "https://www.hoihup.com/Contact-Us",
        "personal": "Hoi Hup Realty's residential development portfolio and showflat-led sales process make contemporary prints relevant as a scalable finishing option for model units and sales environments.",
    },
    {
        "company": "EL Development",
        "email": "contact@eldev.com.sg",
        "category": "residential property developer",
        "website": "https://www.eldev.com.sg/",
        "source_url": "https://www.eldev.com.sg/",
        "personal": "EL Development's residential and mixed-use property portfolio creates recurring needs for show units, handover visuals, and sales-facing interiors where contemporary prints can add polish.",
    },
    {
        "company": "Ferns & Philo",
        "email": "barry@fernsandphilo.com",
        "category": "home staging / home furnishing",
        "website": "https://www.fernsandphilo.com/home-staging-home-furnishing",
        "source_url": "https://www.fernsandphilo.com/terms-conditions",
        "personal": "Ferns & Philo's home staging and furnishing work helps Singapore properties feel ready for sale or rent, and contemporary prints could be a lightweight way to vary wall styling between projects.",
    },
    {
        "company": "Onegroup Developer",
        "email": "main@onegroup.sg",
        "category": "landed property developer",
        "website": "https://onegroup.sg/",
        "source_url": "https://onegroup.sg/about/",
        "personal": "Onegroup's landed property development work depends on presenting completed homes with warmth and clarity, where contemporary prints can help model interiors feel more lived-in and memorable.",
    },
    {
        "company": "Fragrance Group",
        "email": "contact@fragrancegroup.com.sg",
        "category": "property developer / real estate group",
        "website": "https://www.fragrancegroup.com.sg/",
        "source_url": "https://www.fragrancegroup.com.sg/contact-us",
        "personal": "Fragrance Group's Singapore property portfolio spans many built environments, so contemporary prints could be a flexible visual layer for leasing, sales, and buyer-facing presentation spaces.",
    },
    {
        "company": "MCQ Land",
        "email": "investments@mcqland.com",
        "category": "real estate developer",
        "website": "https://www.mcqland.com/",
        "source_url": "https://www.mcqland.com/contact-us",
        "personal": "MCQ Land's real estate development approach highlights design, nature, and sanctuary, making contemporary prints relevant for model homes and visual storytelling around residential spaces.",
    },
    {
        "company": "The Hillshore",
        "email": "contact@frxcapital.com.sg",
        "category": "residential development / show flat",
        "website": "https://www.thehillshore.com.sg/",
        "source_url": "https://www.thehillshore.com.sg/contact.php",
        "personal": "The Hillshore's show flat and residential sales environment is exactly the kind of buyer-facing setting where contemporary prints can make rooms feel more complete during viewings.",
    },
    {
        "company": "Cuscaden Peak Investments",
        "email": "comms@cuscaden.com.sg",
        "category": "real estate investment / property group",
        "website": "https://www.cuscadenpeak.com/",
        "source_url": "https://www.cuscadenpeak.com/contact-us/",
        "personal": "Cuscaden Peak's residential, retail, and commercial property interests create varied presentation needs, and contemporary prints can support polished interiors across marketing and tenant-facing spaces.",
    },
    {
        "company": "Sedar Properties",
        "email": "info@sedarproperties.com",
        "category": "property development / management",
        "website": "https://www.sedarproperties.com/",
        "source_url": "https://www.sedarproperties.com/privacy-policy",
        "personal": "Sedar Properties' development, management, and investment work touches residential, retail, and commercial spaces where contemporary prints could help buyer- or tenant-facing areas feel finished.",
    },
    {
        "company": "Our Momento",
        "email": "contact@ourmomento.sg",
        "category": "real estate videography / property marketing",
        "website": "https://ourmomento.sg/real-estate-videography/",
        "source_url": "https://ourmomento.sg/real-estate-videography/",
        "personal": "Our Momento's real estate videography helps buyers experience properties visually, and contemporary prints can give filmed rooms stronger wall detail without permanent staging commitments.",
    },
    {
        "company": "Bespoke Photography",
        "email": "hello@bespokephotography.sg",
        "category": "real estate videography / photography",
        "website": "https://www.bespokephotography.sg/real-estate-videography-singapore/",
        "source_url": "https://www.bespokephotography.sg/real-estate-videography-singapore/",
        "personal": "Bespoke Photography's real estate videography and virtual property tour work relies on rooms reading well on camera, where contemporary prints can add practical visual interest for listings.",
    },
    {
        "company": "Komo Social",
        "email": "hello@komosocial.com",
        "category": "real estate videography / photography",
        "website": "https://komosocial.com/real-estate-videography-photographywalkthrough-singapore-komo",
        "source_url": "https://komosocial.com/real-estate-videography-photographywalkthrough-singapore-komo",
        "personal": "Komo Social's real estate videography and photography covers homes, hotels, commercial spaces, and luxury estates, so contemporary prints could help prepared spaces photograph with more character.",
    },
    {
        "company": "Sen Visuals",
        "email": "contact@senvisuals.com.sg",
        "category": "architectural / real estate photography",
        "website": "https://www.senvisuals.com.sg/",
        "source_url": "https://www.senvisuals.com.sg/",
        "personal": "Sen Visuals works with architectural and real estate imagery in Singapore, where carefully chosen wall art can help staged interiors and marketing shoots feel more complete on camera.",
    },
    {
        "company": "Real Estate Analytics",
        "email": "help@realestateanalytics.sg",
        "category": "property analytics / marketing support",
        "website": "https://real-agent.ai/",
        "source_url": "https://real-agent.ai/guides/costs-of-marketing-a-property-in-singapore-and-how-to-reduce-them",
        "personal": "Real Estate Analytics supports Singapore property marketing decisions, so contemporary prints could be a practical option to mention when clients are improving listing presentation and perceived value.",
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
    response = requests.get(candidate["source_url"], timeout=25, headers={"User-Agent": "Mozilla/5.0"})
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


def add_sheet_history(rows, email_idx, domain_idx=None):
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
    out_path = out_dir / "2026-06-20_21_real_estate_staging_singapore.json"
    out_path.write_text(json.dumps({"dry_run": dry_run, "sent": sent, "skipped": skipped, "run_log": run_row}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"dry_run": dry_run, "sent_count": len(sent), "sent": sent, "skipped_count": len(skipped), "log": str(out_path)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

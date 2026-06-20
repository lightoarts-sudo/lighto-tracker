import base64
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

sys.path.insert(
    0,
    os.path.expanduser("~/.hermes/skills/productivity/google-workspace/scripts"),
)
from google_api import build_service  # noqa: E402


SPREADSHEET_ID = "1hRuEWgRDgns6LmU4IkvfORo41Bk1JA5aO8HP0YHaeNw"
CATEGORY = "medical beauty salon singapore"
TAIPEI = ZoneInfo("Asia/Taipei")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


CANDIDATES = [
    {
        "company": "Damai Spa",
        "email": "grandvitalitysg@hyatt.com",
        "website": "https://www.damaispa.sg/",
        "style": "hotel wellness spa, calm guest relaxation spaces",
        "opening": "Your Grand Hyatt Singapore spa environment is built around calm recovery, hospitality, and private wellness moments, which makes wall art work best when it feels quiet rather than decorative.",
        "evidence": "Official website contact section lists Singapore address/phone and email grandvitalitysg@hyatt.com.",
    },
    {
        "company": "SAE-REN Beauty Lounge",
        "email": "care@saeren.com.sg",
        "website": "https://saeren.com.sg/contact-us/",
        "style": "beauty lounge, skincare rituals, Orchard/Toa Payoh locations",
        "opening": "SAE-REN's beauty lounge setting, with skincare rituals across Orchard and Toa Payoh, seems suited to art that feels polished, calm, and not overly commercial.",
        "evidence": "Official contact page lists Singapore locations and email care@saeren.com.sg.",
    },
    {
        "company": "Kenko Wellness Spa",
        "email": "info@kenko.com.sg",
        "website": "https://www.kenko.com.sg/contact/",
        "style": "wellness spa, massage and relaxation",
        "opening": "Kenko's wellness spa spaces serve guests looking for a restorative pause, so I thought art with soft contemporary presence could fit without competing with the treatment experience.",
        "evidence": "Official contact page lists Marina Square Singapore address and email info@kenko.com.sg.",
    },
    {
        "company": "BH Medical Aesthetics",
        "email": "marketing@beautehub.com",
        "website": "https://www.bhmedicalaesthetics.com/contact",
        "style": "medical aesthetics clinic under Beautehub group",
        "opening": "BH Medical Aesthetics has a clinical beauty setting where reception and consultation areas can benefit from art that feels refined, reassuring, and contemporary.",
        "evidence": "Official contact page lists Singapore HQ and marketing enquiry email marketing@beautehub.com.",
    },
    {
        "company": "VIDASKIN Medical Aesthetic Clinic",
        "email": "hello@vidaskinclinic.com",
        "website": "https://vidaskinclinic.com/contact-us/",
        "style": "medical aesthetic clinic at Wheelock Place",
        "opening": "VIDASKIN's Wheelock Place clinic presents a polished medical aesthetic experience, where understated art can support a more premium and comfortable client journey.",
        "evidence": "Official contact page lists Wheelock Place Singapore address and email hello@vidaskinclinic.com.",
    },
    {
        "company": "Veritas Medical Aesthetics",
        "email": "ask@veritas.com.sg",
        "website": "https://veritas.com.sg/facts-safety-updates/",
        "style": "medical aesthetics clinic at Capitol Singapore",
        "opening": "Veritas' Capitol Singapore clinic appears focused on transparent, medically grounded aesthetics, so art for the space should feel composed and trust-building.",
        "evidence": "Official facts/safety page lists clinic name, Capitol Singapore address, phone, and email ask@veritas.com.sg.",
    },
    {
        "company": "8 Medical Aesthetic Clinic",
        "email": "enquiries@8medicalaesthetic.com",
        "website": "https://8medicalaesthetics.com/contactus.php",
        "style": "multi-location medical aesthetics clinic",
        "opening": "With several Singapore clinic locations, 8 Medical Aesthetic Clinic likely needs visual pieces that can stay consistent while still feeling warm in client-facing areas.",
        "evidence": "Official contact page lists Singapore outlets and email enquiries@8medicalaesthetic.com.",
    },
    {
        "company": "Ei8ht Medical Aesthetics",
        "email": "enquiries@ei8htmedicalaesthetics.com",
        "website": "https://ei8htmedicalaesthetics.com/contactus.php",
        "style": "multi-location medical aesthetics clinic",
        "opening": "Ei8ht Medical Aesthetics' islandwide clinic footprint makes it a good fit for art that can bring a consistent, contemporary tone to waiting and consultation areas.",
        "evidence": "Official contact page lists Singapore outlets and email enquiries@ei8htmedicalaesthetics.com.",
    },
    {
        "company": "Astria Medical Aesthetics",
        "email": "enquiries@astria.com.sg",
        "website": "https://astria.com.sg/",
        "style": "medical aesthetics clinic at Lazada One",
        "opening": "Astria's Bras Basah clinic presents aesthetic care as a sustained personal journey, which pairs well with art that feels elegant, modern, and quietly distinctive.",
        "evidence": "Official website footer/contact section lists Lazada One Singapore address and email enquiries@astria.com.sg.",
    },
    {
        "company": "Dr Plus Aesthetics",
        "email": "support@drplusaestheticsclinic.com",
        "website": "https://www.drplus-collagen-aesthetic.com/",
        "style": "collagen and aesthetic clinic with Singapore locations",
        "opening": "Dr Plus Aesthetics' collagen-focused clinic spaces seem well matched to art that adds warmth and texture without distracting from a clean treatment environment.",
        "evidence": "Official website contact section lists Singapore clinic addresses and email support@drplusaestheticsclinic.com.",
    },
    {
        "company": "Yagyo Haven",
        "email": "hello@yagyohaven.com",
        "website": "https://yagyohaven.com/contact-us/",
        "style": "beauty and therapeutic spa in Rochor",
        "opening": "Yagyo Haven describes a beauty-meets-culture environment, so I thought contemporary prints with a calm point of view could complement that restorative atmosphere.",
        "evidence": "Official contact page lists Rochor Singapore address and email hello@yagyohaven.com.",
    },
    {
        "company": "Himalayan Salt Spa",
        "email": "marketing@himalayansaltspa.com.sg",
        "website": "https://www.himalayansaltspa.com.sg/getintouch",
        "style": "salt spa and wellness experience at VivoCity",
        "opening": "Himalayan Salt Spa's VivoCity wellness setting already has a distinctive sensory identity, so art there should feel serene and carefully chosen rather than loud.",
        "evidence": "Official get-in-touch page lists VivoCity Singapore location and marketing/collaboration email marketing@himalayansaltspa.com.sg.",
    },
    {
        "company": "Expat Beauty Room",
        "email": "april@expatbeautyroom.com.sg",
        "website": "https://www.expatbeautyroom.com.sg/find-us.html",
        "style": "beauty room and skincare salon in Orchard",
        "opening": "Expat Beauty Room's Orchard skincare setting feels personal and appointment-led, where a few well-selected prints could make the room feel more considered and memorable.",
        "evidence": "Official find-us page lists Singapore address and email april@expatbeautyroom.com.sg.",
    },
    {
        "company": "Skin Inc Singapore",
        "email": "livechat@skininc.jp",
        "website": "https://iloveskininc.com/pages/contact-us",
        "style": "Singapore skincare beauty brand and beauty-advice channel",
        "opening": "Skin Inc's Singapore beauty experience is built around customized skincare and advice, so art for customer-facing or consultation settings should feel clean, modern, and premium.",
        "evidence": "Official Singapore contact page lists general enquiries email livechat@skininc.jp.",
    },
    {
        "company": "Beauty Garage Singapore",
        "email": "center@beautygarage.sg",
        "website": "https://www.beautygarage.sg/pages/contact",
        "style": "professional beauty supply serving salon professionals in Singapore",
        "opening": "Beauty Garage Singapore supports salon professionals, and its showroom or client-facing areas could use art that feels current without pulling attention away from products and materials.",
        "evidence": "Official contact page lists Singapore address and email center@beautygarage.sg.",
    },
    # Previously found candidates retained so skipped count reflects the batch screening.
    {"company": "Midori Med Spa", "email": "hello@midorimedspa.sg", "website": "https://midorimedspa.sg/contact/", "style": "duplicate check", "opening": "", "evidence": "Official contact page lists email."},
    {"company": "J's Salon", "email": "appt@js.com.sg", "website": "https://js.com.sg/contact-2/", "style": "duplicate check", "opening": "", "evidence": "Official contact page lists email."},
    {"company": "AEON Medical and Aesthetic Centre", "email": "info@aeonmedical.com.sg", "website": "https://www.aeonmedical.com.sg/contact/", "style": "duplicate check", "opening": "", "evidence": "Official contact page lists email."},
    {"company": "Walking on Sunshine", "email": "hello@walkingonsunshine.sg", "website": "https://walkingonsunshine.sg/pages/contact-us", "style": "duplicate check", "opening": "", "evidence": "Official contact page lists email."},
    {"company": "Ageless Medical", "email": "enquiry@iamageless.com.sg", "website": "https://agelessmedical.com.sg/contact-us/", "style": "duplicate check", "opening": "", "evidence": "Official contact page lists email."},
    {"company": "Singapore Aesthetic Centre", "email": "doctor@sgac.com.sg", "website": "https://sgac.com.sg/contact-us/", "style": "duplicate check", "opening": "", "evidence": "Official contact page lists email."},
    {"company": "SELF Medical Spa", "email": "medispa@selfmedical.com.sg", "website": "https://www.selfaesthetics.com.sg/medispa", "style": "duplicate check", "opening": "", "evidence": "Official page lists email."},
    {"company": "Salon Plus", "email": "dave@salonplus.com.sg", "website": "https://salonplus.com.sg/contact-us/", "style": "duplicate check", "opening": "", "evidence": "Official contact page lists email."},
    {"company": "V Medical Aesthetics & Laser Clinic", "email": "enquiry@vaestheticsclinic.com.sg", "website": "https://www.vaestheticsclinic.com.sg/", "style": "duplicate check", "opening": "", "evidence": "Official website lists email."},
    {"company": "The Aesthetic Studio Wellness", "email": "info@aestheticstudiowellness.com.sg", "website": "https://www.aestheticstudiowellness.com.sg/contact-us", "style": "duplicate check", "opening": "", "evidence": "Official contact page lists email."},
    {"company": "BMF Clinic", "email": "enquiry@bmfclinic.com.sg", "website": "https://www.bmfclinic.com.sg/", "style": "duplicate check", "opening": "", "evidence": "Official website lists email."},
    {"company": "S Aesthetics Clinic", "email": "hello@saestheticsclinic.com", "website": "https://saestheticsclinic.com/contact-us/", "style": "duplicate check", "opening": "", "evidence": "Official contact page lists email."},
    {"company": "Natureland Spa Premium", "email": "info@natureland.com.sg", "website": "https://www.natureland.com.sg/mbs/contact/", "style": "duplicate check", "opening": "", "evidence": "Official contact page lists email."},
    {"company": "Jean Yip Group", "email": "marketing@jeanyipgroup.com", "website": "https://jeanyipgroup.com/message/", "style": "duplicate check", "opening": "", "evidence": "Official contact page lists email."},
]


def normalize_email(email):
    return email.strip().lower()


def domain_of(email):
    return normalize_email(email).split("@", 1)[1]


def collect_history(sheets):
    history = {
        "emails": set(),
        "domains": set(),
        "blocked_emails": set(),
        "blocked_domains": set(),
    }
    ranges = [
        "'Designer Contacts'!A:M",
        "'Outreach Sent Log'!A:H",
        "'Email Bounces'!A:L",
    ]
    for rng in ranges:
        rows = sheets.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=rng,
        ).execute().get("values", [])
        for row in rows[1:]:
            text = " ".join(row).lower()
            blocked = any(
                marker in text
                for marker in [
                    "bounce",
                    "bounced",
                    "do_not_send",
                    "do-not-send",
                    "do_not_send_again",
                    "unsubscribe",
                    "unsubscribed",
                    "replied",
                    "blocked",
                    "do not send",
                ]
            )
            for email in EMAIL_RE.findall(text):
                email = normalize_email(email)
                domain = domain_of(email)
                history["emails"].add(email)
                history["domains"].add(domain)
                if blocked:
                    history["blocked_emails"].add(email)
                    history["blocked_domains"].add(domain)
    contacts = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="'Designer Contacts'!A:M",
    ).execute().get("values", [])
    max_no = 0
    for row in contacts[1:]:
        if row and row[0].strip().isdigit():
            max_no = max(max_no, int(row[0].strip()))
    return history, max_no


def gmail_sent_hit(gmail, email):
    domain = domain_of(email)
    response = gmail.users().messages().list(
        userId="me",
        q=f"in:sent ({email} OR {domain})",
        maxResults=5,
    ).execute()
    return response.get("resultSizeEstimate", 0) > 0


def make_message(candidate):
    subject = f"Contemporary art prints for {candidate['company']} spaces"
    body = f"""Hello {candidate['company']} team,

{candidate['opening']}

I am reaching out from Lighto Arts, a Taiwan-born and U.S.-registered art print studio. We create contemporary wall art prints and work with premium print-on-demand and logistics partners, so pieces can be produced close to the destination and shipped globally with reliable fulfillment.

For clinics, spas, beauty lounges, and wellness spaces, our focus is on prints that add character while keeping the atmosphere calm and professional. You can view the collection here: https://lightoarts.com

This is simply an introduction in case you are refreshing any treatment rooms, reception areas, consultation spaces, or customer-facing walls. If this is not relevant, just reply "unsubscribe" and I will not contact you again.

Best regards,
Lighto Arts
https://lightoarts.com
"""
    msg = EmailMessage()
    msg["To"] = candidate["email"]
    msg["From"] = "Lighto Arts <lightoarts@gmail.com>"
    msg["Subject"] = subject
    msg.set_content(body)
    return subject, msg


def append_values(sheets, tab, values):
    sheets.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [values]},
    ).execute()


def main():
    gmail = build_service("gmail", "v1")
    sheets = build_service("sheets", "v4")
    profile = gmail.users().getProfile(userId="me").execute()
    if profile.get("emailAddress") != "lightoarts@gmail.com":
        raise RuntimeError(f"Wrong Gmail account: {profile.get('emailAddress')}")

    history, max_no = collect_history(sheets)
    sent = []
    skipped = []
    seen_run_domains = set()

    for candidate in CANDIDATES:
        if len(sent) >= 15:
            break
        email = normalize_email(candidate["email"])
        candidate["email"] = email
        domain = domain_of(email)
        reasons = []
        if email in history["emails"]:
            reasons.append("sheet_email_duplicate")
        if domain in history["domains"]:
            reasons.append("sheet_domain_duplicate")
        if email in history["blocked_emails"] or domain in history["blocked_domains"]:
            reasons.append("blocked_bounce_reply_unsubscribe_indicator")
        if domain in seen_run_domains:
            reasons.append("same_run_domain_duplicate")
        if gmail_sent_hit(gmail, email):
            reasons.append("gmail_sent_history")

        if reasons:
            skipped.append({"company": candidate["company"], "email": email, "reasons": reasons})
            continue

        subject, msg = make_message(candidate)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        result = gmail.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()
        now = datetime.now(TAIPEI)
        sent_at = now.strftime("%Y-%m-%d %H:%M:%S Asia/Taipei")
        sent_date = now.strftime("%Y-%m-%d")
        status = f"Sent {sent_at}"
        max_no += 1
        notes = (
            f"Source: {candidate['website']} | Evidence: {candidate['evidence']} | "
            f"Singapore-first; verified official source; gmail_id={result['id']}; "
            f"thread_id={result['threadId']}"
        )
        append_values(
            sheets,
            "Designer Contacts",
            [
                max_no,
                "Singapore",
                candidate["company"],
                "",
                email,
                status,
                candidate["website"],
                candidate["style"],
                sent_date,
                "",
                "",
                "",
                notes,
            ],
        )
        append_values(
            sheets,
            "Outreach Sent Log",
            [
                sent_at,
                email,
                candidate["company"],
                CATEGORY,
                subject,
                result["id"],
                result["threadId"],
                candidate["website"],
            ],
        )
        sent.append(
            {
                "company": candidate["company"],
                "email": email,
                "message_id": result["id"],
                "thread_id": result["threadId"],
                "source_url": candidate["website"],
            }
        )
        history["emails"].add(email)
        history["domains"].add(domain)
        seen_run_domains.add(domain)
        time.sleep(2.5)

    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sent_names = "; ".join(item["company"] for item in sent)
    summary = (
        f"LightoArts SG Medical / Beauty / Salon batch: sent={len(sent)}, "
        f"skipped={len(skipped)}, market=Singapore, companies={sent_names}"
    )
    append_values(
        sheets,
        "Run Log",
        [
            now_utc,
            CATEGORY,
            0,
            0,
            0,
            0,
            0,
            len(sent),
            "",
            summary,
        ],
    )

    print(
        {
            "sent_count": len(sent),
            "skipped_count": len(skipped),
            "sent": sent,
            "skipped": skipped,
            "run_log_summary": summary,
        }
    )


if __name__ == "__main__":
    main()

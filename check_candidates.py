import json

with open('excluded_emails.json', 'r') as f:
    data = json.load(f)

excluded_emails = set(data['emails'])
excluded_domains = set(data['domains'])

# New candidates from discovery
new_candidates = [
    ('Old Hen Coffee Bar', 'hello@oldhencoffee.com', 'cafe', 'https://www.oldhencoffee.com'),
    ('LeBon Funk', 'press@lebonfunk.com', 'restaurant / wine bar', 'https://lebonfunk.com'),
    ('Humpback', 'info@humpback.sg', 'restaurant / bar', 'https://www.humpback.sg'),
    ('Publico Ristorante', 'ristorante@publico.sg', 'restaurant / bar', 'https://publico.sg'),
    ('Birds of a Feather', 'enquiry@birdsofafeather.com.sg', 'restaurant', 'https://www.birdsofafeather.com.sg'),
    ('Restaurant Labyrinth', 'reservations@labyrinth.com.sg', 'restaurant', 'https://www.restaurantlabyrinth.com'),
    ('New Majestic Hotel', 'nmh-res@unlistedcollection.com', 'boutique hotel', 'https://www.newmajestichotel.com'),
    ('New Majestic Hotel', 'mae.noor@unlistedcollection.com', 'boutique hotel', 'https://www.newmajestichotel.com'),
    ('Jigger & Pony', 'info@jiggerandpony.com', 'bar', 'https://www.jiggerandpony.com'),
]

print("Checking new candidates against exclusion list:")
for company, email, category, website in new_candidates:
    email_lower = email.lower()
    domain = email_lower.split('@')[1]
    in_excluded = email_lower in excluded_emails
    domain_blocked = domain in excluded_domains
    if in_excluded or domain_blocked:
        print(f"  SKIP: {company} - {email} (excluded: {in_excluded}, domain_blocked: {domain_blocked})")
    else:
        print(f"  OK: {company} - {email} ({category})")

print(f"\nTotal excluded emails: {len(excluded_emails)}")
print(f"Total excluded domains: {len(excluded_domains)}")
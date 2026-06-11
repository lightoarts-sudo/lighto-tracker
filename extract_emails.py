import json
import os

# Extract emails from outreach_sent.json
with open(os.path.expanduser('~/.hermes/tmp/outreach_sent.json')) as f:
    data = json.load(f)
sent_emails = set()
for row in data[1:]:
    if len(row) > 1 and row[1] and '@' in row[1]:
        sent_emails.add(row[1].lower().strip())

# Extract emails from email_bounces.json
with open(os.path.expanduser('~/.hermes/tmp/email_bounces.json')) as f:
    data = json.load(f)
bounce_emails = set()
for row in data[1:]:
    if len(row) > 1 and row[1] and '@' in row[1]:
        bounce_emails.add(row[1].lower().strip())

# Extract emails from lighto_outreach_sent_log_A_M_20260602_22.json
with open(os.path.expanduser('~/.hermes/tmp/lighto_outreach_sent_log_A_M_20260602_22.json')) as f:
    data = json.load(f)
lighto_sent_emails = set()
for row in data[1:]:
    if len(row) > 1 and row[1] and '@' in row[1]:
        lighto_sent_emails.add(row[1].lower().strip())

# Extract emails from lighto_email_bounces_A_M_20260602_22.json
with open(os.path.expanduser('~/.hermes/tmp/lighto_email_bounces_A_M_20260602_22.json')) as f:
    data = json.load(f)
lighto_bounce_emails = set()
for row in data[1:]:
    if len(row) > 1 and row[1] and '@' in row[1]:
        lighto_bounce_emails.add(row[1].lower().strip())

# Extract emails from designer_contacts_current.json
with open(os.path.expanduser('~/.hermes/tmp/designer_contacts_current.json')) as f:
    data = json.load(f)
designer_emails = set()
for row in data[1:]:
    if len(row) > 7 and row[7] and row[7].strip() and '@' in row[7]:
        designer_emails.add(row[7].lower().strip())

# Combine all
all_blocked = sent_emails | bounce_emails | lighto_sent_emails | lighto_bounce_emails | designer_emails

print(f"Sent emails: {len(sent_emails)}")
print(f"Bounce emails: {len(bounce_emails)}")
print(f"Lighto sent emails: {len(lighto_sent_emails)}")
print(f"Lighto bounce emails: {len(lighto_bounce_emails)}")
print(f"Designer emails: {len(designer_emails)}")
print(f"Total unique blocked: {len(all_blocked)}")

# Save to file
with open('blocked_emails.json', 'w') as f:
    json.dump(sorted(all_blocked), f, indent=2)

print("\nAll blocked emails:")
for e in sorted(all_blocked):
    print(e)
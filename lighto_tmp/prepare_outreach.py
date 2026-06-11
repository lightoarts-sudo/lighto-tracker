import json,re,subprocess,os,datetime,zoneinfo, time, sys
raw=json.load(open('lighto_tmp/candidates_raw.json',encoding='utf-8'))
existing=set(open('lighto_tmp/existing_emails.txt',encoding='utf-8').read().splitlines()) if os.path.exists('lighto_tmp/existing_emails.txt') else set()
blocked=set(open('lighto_tmp/blocked_emails.txt',encoding='utf-8').read().splitlines()) if os.path.exists('lighto_tmp/blocked_emails.txt') else set()
existing_domains=set(open('lighto_tmp/existing_domains.txt',encoding='utf-8').read().splitlines()) if os.path.exists('lighto_tmp/existing_domains.txt') else set()
invalid=re.compile(r'(example|your@email|u003e|%22|\.svg|\.png|\.jpg|wixpress|shopify|sentry|domain\.com)',re.I)
choices=[]; skips=[]
for company in raw:
    valid=[]
    for ev in company.get('evidence',[]):
        e=ev['email'].lower().strip()
        if invalid.search(e) or not re.match(r'^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$',e):
            continue
        if e in valid: continue
        valid.append(e)
        if e in existing: skips.append({'email':e,'company':company['company'],'reason':'exists in file/Google Sheet logs'}); continue
        if e in blocked: skips.append({'email':e,'company':company['company'],'reason':'blocked/bounced/do-not-contact in logs'}); continue
        # domain-only check: skip if exact domain already in sent log? user says same domain/company in sent log; but global sheet has many domains maybe old rows. Use domain skip only if domain in existing from Outreach Sent Log/local, not Designer Contacts unsent. We have broad domains, apply conservative no repeat if domain existing.
        dom=e.split('@')[-1]
        if dom in existing_domains:
            skips.append({'email':e,'company':company['company'],'reason':'domain exists in prior records/Sheet; conservative skip'}); continue
        choices.append({**company,'email':e,'source_url':ev['source_url'],'evidence_method':ev['method'],'evidence_snippet':ev['snippet']})
        break
print(json.dumps({'choices':choices,'skips':skips[:200], 'counts':{'choices':len(choices),'skips':len(skips)}},ensure_ascii=False,indent=2))

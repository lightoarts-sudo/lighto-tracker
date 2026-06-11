import json, subprocess, shlex, re, os, time, sys
p=json.load(open('lighto_tmp/prepared.json',encoding='utf-8'))
choices=[]
invalid=re.compile(r'^(your|youremail|test|example)@|@here\.com$|u003e|%22|\.svg$',re.I)
for c in p['choices']:
    if invalid.search(c['email']):
        p.setdefault('skips',[]).append({'email':c['email'],'company':c['company'],'reason':'invalid placeholder email extracted; skipped'})
        continue
    choices.append(c)
GAPI=[sys.executable, os.path.expanduser('~/.hermes/skills/productivity/google-workspace/scripts/google_api.py')]
checked=[]; skips=p.get('skips',[])
for c in choices:
    e=c['email']
    queries=[('sent',f'to:{e} in:sent'),('bounce',f'{e} (from:mailer-daemon OR subject:"Delivery Status Notification" OR subject:"Mail Delivery Failed" OR subject:undeliverable OR subject:bounced)'),('stop',f'{e} (unsubscribe OR "remove me" OR "do not contact" OR "don\'t contact" OR stop)')]
    hit=False; detail=[]
    for label,q in queries:
        try:
            out=subprocess.check_output(GAPI+['gmail','search',q,'--max','5'], text=True, encoding='utf-8', errors='ignore', timeout=60)
            arr=json.loads(out)
        except Exception as ex:
            arr=[]; detail.append(f'{label} check error: {ex}')
        if arr:
            hit=True; detail.append(f'{label} Gmail hit count {len(arr)}')
        time.sleep(.5)
    c['gmail_check_detail']='; '.join(detail) if detail else 'no sent/bounce/stop Gmail hits'
    if hit:
        skips.append({'email':e,'company':c['company'],'reason':'Gmail sent/bounce/stop search hit: '+c['gmail_check_detail']})
    else:
        checked.append(c)
    time.sleep(.5)
json.dump({'checked':checked[:15],'extra_checked':checked[15:],'skips':skips,'counts':{'checked':len(checked),'selected':min(15,len(checked)),'skips':len(skips)}},open('lighto_tmp/checked.json','w',encoding='utf-8'),ensure_ascii=False,indent=2)
print(json.dumps({'selected':[ (c['company'],c['email']) for c in checked[:15]], 'counts':{'checked':len(checked),'skips':len(skips)}},ensure_ascii=False,indent=2))

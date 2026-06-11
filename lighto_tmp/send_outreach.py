import json, os, sys, subprocess, time, datetime, zoneinfo, re
TZ=zoneinfo.ZoneInfo('Asia/Taipei')
now=datetime.datetime.now(TZ)
stamp=now.strftime('%Y-%m-%d %H:%M Asia/Taipei')
date_file=now.strftime('%Y-%m-%d')
GAPI=[sys.executable, os.path.expanduser('~/.hermes/skills/productivity/google-workspace/scripts/google_api.py')]
SHEET='1hRuEWgRDgns6LmU4IkvfORo41Bk1JA5aO8HP0YHaeNw'
checked=json.load(open('lighto_tmp/checked.json',encoding='utf-8'))
selected=checked['checked'][:15]
subjects={
'Noden':'Could Taiwanese prints fit Noden’s vintage mix?',
'Originals':'A wall-art stockist idea for Originals Singapore',
'Island Living':'Island-style rooms + contemporary Taiwanese prints',
'Castlery Singapore':'A small art-print add-on idea for Castlery SG',
'HipVan':'Could prints round out HipVan’s home styling?',
'Danish Design Co':'Taiwanese art prints for Nordic-style showroom walls',
'House of AnLi':'A boutique print category for House of AnLi',
'Grafunkt':'Contemporary Taiwanese prints for Grafunkt’s design audience',
'XTRA':'A print-art layer for XTRA’s showroom vignettes',
'Marquis HQO':'Museum-quality prints for Marquis living settings',
'Proof Living':'A quiet art-print offer for Proof Living clients',
'LivingwithArt Singapore':'Taiwanese contemporary artists for LivingwithArt',
'Emperor’s Attic':'A print collection beside Emperor’s Attic antiques',
'The Cinnamon Room':'Art prints to pair with The Cinnamon Room textures',
'Supermama':'Taiwan-born art prints for Supermama’s design shoppers'
}
angles={
'Noden':('your vintage Scandinavian point of view','stockist / small sample order','Your mix of mid-century furniture and warm objects feels like a natural setting for art prints that add story without overpowering the room.'),
'Originals':('your teak and natural-material showroom','wholesale or consignment-style test','Originals already helps customers imagine complete, relaxed rooms, and wall art could be an easy finishing category.'),
'Island Living':('your relaxed tropical home styling','small retail partner test','Island Living’s breezy Singapore look seems well matched with calm contemporary prints that can travel from showroom wall to customer home.'),
'Castlery Singapore':('your accessible furniture collections','sample art add-on for styled rooms','Castlery’s room sets make it easy for customers to visualize a full home, and curated wall prints could complement that journey.'),
'HipVan':('your practical online-to-home styling angle','retail partner or bundle test','HipVan’s audience is already looking for simple ways to complete apartments, so a small wall-art category could be useful rather than decorative noise.'),
'Danish Design Co':('your Nordic designer furniture setting','showroom sample / wholesale discussion','Danish Design Co’s clean silhouettes leave room for distinctive artwork that still feels refined and livable.'),
'House of AnLi':('your lifestyle boutique and home selections','stockist / giftable print test','House of AnLi’s mix of tableware, home accents and European-style living feels like a good environment for giftable art prints.'),
'Grafunkt':('your design-led furniture audience','curated retail partner test','Grafunkt’s contemporary furniture edit could pair well with prints that bring an Asian contemporary voice without feeling souvenir-like.'),
'XTRA':('your premium design showroom vignettes','sample order for showroom styling','XTRA’s showroom environments already present complete design stories, and art can be a flexible finishing layer for walls and client presentations.'),
'Marquis HQO':('your luxury furniture settings','small wholesale/sample conversation','Marquis’ polished living spaces could use art prints as an accessible add-on that keeps the atmosphere premium.'),
'Proof Living':('your refined international design brands','sample set for client-facing vignettes','Proof Living’s high-end furniture edit seems suited to quieter, museum-quality prints that support the room rather than compete with it.'),
'LivingwithArt Singapore':('your Singapore art and decor audience','artist/print collaboration discussion','LivingwithArt already serves people thinking about walls, so Taiwanese contemporary artists might add a fresh regional layer to your selection.'),
'Emperor’s Attic':('your antique and Asian furniture context','retail sample / consignment-style test','Emperor’s Attic has a strong sense of story and material, and contemporary Taiwanese prints could create an interesting old-new pairing.'),
'The Cinnamon Room':('your rugs and richly textured interiors','small stockist or styled-wall test','The Cinnamon Room’s layered textures and patterns could be complemented by quiet prints that give customers a finished wall direction.'),
'Supermama':('your Singapore design and gift-shop audience','giftable print / retail partner test','Supermama’s shoppers appreciate design objects with cultural point of view, which makes art prints from Taiwanese artists an interesting adjacent category.')
}

def body_for(c):
    comp=c['company']; phrase, cta, obs=angles[comp]
    return f"Hi {comp} team,\n\nI came across {comp} while looking at Singapore design and home retail spaces, especially {phrase}. {obs}\n\nLightoArts is a Taiwan-born startup, now registered in the U.S., working with high-quality POD production partners to ship contemporary Taiwanese art prints worldwide. We focus on contemporary Taiwanese artists and museum-quality giclee art prints, with options that can work for stockists, styled showroom walls, or a small consignment-style test.\n\nWould it be useful if I sent a short lookbook and wholesale/sample details for your team to review?\n\nIf this is not relevant, just reply no and I won’t reach out again.\n\nBest,\nLightoArts\nhttps://lightoarts.com"

def run(cmd, timeout=90):
    return subprocess.check_output(cmd, text=True, encoding='utf-8', errors='ignore', timeout=timeout)

# get current sheet row count for approximate appended row refs
try:
    rows=json.loads(run(GAPI+['sheets','get',SHEET,'Designer Contacts!A:M'],timeout=120))
    next_row=len(rows)+1
except Exception:
    next_row=None
sent=[]; errors=[]
os.makedirs('outreach_logs',exist_ok=True)
for idx,c in enumerate(selected):
    subj=subjects[c['company']]
    body=body_for(c)
    try:
        out=run(GAPI+['gmail','send','--to',c['email'],'--subject',subj,'--from','LightoArts <lightoarts@gmail.com>','--body',body],timeout=120)
        resp=json.loads(out)
        status='sent' if resp.get('status')=='sent' else 'unknown'
        sheet_row=next_row if next_row else ''
        notes=f"Singapore-first stockist/decor outreach; source: {c['source_url']} ({c['evidence_method']} on official website/contact/home page; email visibly found); category: {c['category']}; subject: {subj}; angle: {angles[c['company']][1]}; brand: Taiwan-born, U.S.-registered, POD production partners shipping Taiwanese giclee prints worldwide; sent {stamp}."
        dc_row=['','Singapore / Singapore market',c['company'],'Team',c['email'],f'Sent {stamp}',c['website'],c['category'],stamp,'','','',notes]
        try:
            run(GAPI+['sheets','append',SHEET,'Designer Contacts!A:M','--values',json.dumps([dc_row],ensure_ascii=False)],timeout=120)
        except Exception as ex:
            errors.append({'company':c['company'],'email':c['email'],'stage':'Designer Contacts append','error':str(ex)[:500]})
        log_row=[stamp,c['email'],c['company'],c['category'],subj,resp.get('id',''),resp.get('threadId',''),c['source_url'],str(sheet_row),'',notes]
        try:
            run(GAPI+['sheets','append',SHEET,'Outreach Sent Log!A:K','--values',json.dumps([log_row],ensure_ascii=False)],timeout=120)
        except Exception as ex:
            errors.append({'company':c['company'],'email':c['email'],'stage':'Outreach Sent Log append','error':str(ex)[:500]})
        rec={**c,'sent_at_taipei':stamp,'subject':subj,'body':body,'gmail_response':resp,'sheet_row':sheet_row,'notes':notes,'status':status}
        sent.append(rec)
        if next_row: next_row += 1
        print('SENT',c['company'],c['email'],resp.get('id'))
    except Exception as ex:
        err={'company':c['company'],'email':c['email'],'stage':'send','error':str(ex)[:1000]}
        errors.append(err); print('ERROR',err)
    # save after every attempt
    full={'run_at_taipei':stamp,'market':'Singapore-first','sent':sent,'skips':checked.get('skips',[]),'errors':errors}
    with open(f'outreach_logs/{date_file}_23_stockist_decor_partners.json','w',encoding='utf-8') as f: json.dump(full,f,ensure_ascii=False,indent=2)
    if idx != len(selected)-1: time.sleep(3.2)
print(json.dumps({'sent':len(sent),'errors':len(errors),'log':f'outreach_logs/{date_file}_23_stockist_decor_partners.json'},ensure_ascii=False,indent=2))

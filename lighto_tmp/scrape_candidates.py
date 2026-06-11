import re, urllib.request, urllib.parse, ssl, html, json, time
from urllib.parse import urljoin, urlparse
sites = [
('Journey East','https://journeyeast.com/','furniture / vintage design showroom'),
('Noden','https://www.nodenhome.com/','vintage Scandinavian furniture / design store'),
('Originals','https://www.originals.com.sg/','furniture and home decor showroom'),
('Island Living','https://islandliving.sg/','home decor / furniture boutique'),
('Soul & Tables','https://soulandtables.com.sg/','solid wood furniture showroom'),
('Castlery Singapore','https://www.castlery.com/sg','furniture showroom / ecommerce'),
('Commune','https://www.thecommunelife.com/','furniture and lifestyle store'),
('HipVan','https://www.hipvan.com/','furniture and homeware retailer'),
('Danish Design Co','https://danishdesignco.com.sg/','designer furniture showroom'),
('House of AnLi','https://houseofanli.com/','lifestyle / home boutique'),
('Arete Culture','https://areteculture.com/','interior styling / home decor showroom'),
('Taylor B','https://www.taylorbdesign.com/','furniture and home decor showroom'),
('Mountain Living','https://www.mountainliving.com.sg/','luxury furniture showroom'),
('Grafunkt','https://grafunkt.com/','design furniture / lifestyle store'),
('W Atelier','https://www.watelier.com/','premium home and lifestyle showroom'),
('XTRA','https://www.xtra.com.sg/','designer furniture showroom'),
('Marquis HQO','https://marquis.com.sg/','designer furniture showroom'),
('Proof Living','https://www.proof.com.sg/','luxury furniture / home decor showroom'),
('LivingwithArt Singapore','https://livingwithart.com.sg/','art gallery / decor prints'),
('Emperor’s Attic','https://emperorsattic.com/','Asian antique furniture / decor'),
('The Cinnamon Room','https://thecinnamonroom.com/','home decor / rugs showroom'),
('The Artling','https://theartling.com/','art and design marketplace in Singapore'),
('Supermama','https://supermamastore.com/','Singapore design / museum-style gift shop'),
('Cat Socrates','https://cat-socrates.myshopify.com/','gift shop / Singapore lifestyle boutique'),
('Design Orchard','https://www.designorchard.sg/','Singapore lifestyle retail / design showcase'),
('Molecule Living','https://www.moleculeliving.com/','furniture and lifestyle showroom'),
]
EMAIL_RE=re.compile(r'[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}',re.I)
ctx=ssl.create_default_context()
ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE

def fetch(url):
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 LightoArts research','Accept':'text/html,*/*'})
        with urllib.request.urlopen(req,timeout=16,context=ctx) as r:
            ct=r.headers.get('content-type','')
            data=r.read(900000)
            return data.decode('utf-8','ignore'), r.geturl(), ct
    except Exception as e:
        return '', url, 'ERR '+repr(e)

def clean_email(e):
    e=html.unescape(e).lower().strip().strip('.,;:)\]}>"\'')
    return e

def visible_text(s):
    s=re.sub(r'<script.*?</script>|<style.*?</style>',' ',s, flags=re.S|re.I)
    return re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',html.unescape(s)))[:1200]

results=[]
for name,base,cat in sites:
    pages=[]
    html0, final, ct=fetch(base); pages.append((base,html0,final,ct))
    # links containing contact/about/customer-service
    links=[]
    for m in re.findall(r'href=["\']([^"\']+)["\']', html0, re.I):
        u=urljoin(final,m)
        if urlparse(u).netloc and urlparse(u).netloc.endswith(urlparse(final).netloc.split(':')[0]) and re.search(r'contact|about|visit|store|customer|support', u, re.I):
            links.append(u.split('#')[0])
    for suffix in ['/contact','/contact-us','/pages/contact','/pages/contact-us','/about','/pages/about-us','/pages/visit-us']:
        links.append(urljoin(final,suffix))
    seen=set()
    for u in links[:12]:
        if u in seen: continue
        seen.add(u); h, f, c=fetch(u); pages.append((u,h,f,c)); time.sleep(.2)
    emails=[]; evidence=[]
    for u,h,f,c in pages:
        if not h: continue
        mailtos=[clean_email(urllib.parse.unquote(x)) for x in re.findall(r'mailto:([^"\'?<>#]+)', h, re.I)]
        vis=[clean_email(x) for x in EMAIL_RE.findall(h)]
        for e in mailtos+vis:
            if any(bad in e for bad in ['example.com','domain.com','email.com','sentry.io','wixpress.com','shopify.com']) or e.endswith(('.png','.jpg','.jpeg')): continue
            if e not in emails:
                emails.append(e)
                method='mailto found' if e in mailtos else 'email visibly found'
                text=visible_text(h)
                evidence.append({'email':e,'source_url':u,'final_url':f,'method':method,'snippet':text[:280]})
    results.append({'company':name,'website':base,'category':cat,'emails':emails,'evidence':evidence})
print(json.dumps(results,ensure_ascii=False,indent=2))

"""Anonymous public seller observations; no cart, account or pricing authority."""
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
import json,re,time

URL='https://www.eldorado.gg/ea-fc-coins/g/142-0-0'
DEVICES=(('PS','PlayStation'),('XBOX','Xbox'),('PC','PC'))
READ=r'''() => ({
 usd:/USD\s*-\s*\$/.test(document.body.innerText),
 devices:[...new Set([...document.querySelectorAll('.offer-trade-environments .font-bold')].map(e=>e.innerText.trim()).filter(Boolean))],
 rows:[...document.querySelectorAll('eld-currency-other-sellers-list .offer-row')].map(e=>({
  seller:e.querySelector('.profile__username a')?.textContent.trim(),
  seller_url:e.querySelector('.profile__username a')?.getAttribute('href'),
  text:e.innerText
 }))
})'''

def amount(text,zero=False):
 try:value=Decimal(str(text).replace(',',''))
 except (InvalidOperation,TypeError,ValueError):raise ValueError('eld_number_invalid') from None
 if not value.is_finite() or value<0 or not zero and value==0 or value>Decimal('1e12'):raise ValueError('eld_number_invalid')
 return value

def parse(data,platform,device,at):
 if data.get('usd') is not True or data.get('devices')!=[device] or not isinstance(data.get('rows'),list):raise ValueError('eld_platform_or_currency_unverified')
 output=[]
 for item in data['rows'][:50]:
  text=item.get('text','');seller=item.get('seller');link=item.get('seller_url') or ''
  if not isinstance(seller,str) or not 1<=len(seller)<=100 or not re.fullmatch(r'/users/[^/?#]{1,120}/shop/Currency',link):continue
  rate=re.search(r'(\d+(?:\.\d+)?)\s*%',text);reviews=re.search(r'([\d,]+)\s+reviews',text,re.I)
  stock=re.search(r'In stock\s*([\d,.]+)\s*K',text,re.I)
  minimum=re.search(r'Min\. qty\.?\s*([\d,.]+)\s*K',text,re.I)
  price=re.search(r'\$\s*([\d,.]+)\s*/\s*K',text)
  delivery=re.search(r'Delivery time\s*([^\n]+)',text,re.I)
  if not all((rate,reviews,stock,minimum,price,delivery)):continue
  unit=amount(price[1]);low=amount(minimum[1]);inventory=amount(stock[1],zero=True);rating=Decimal(rate[1])
  if not 0<=rating<=100:continue
  output.append(dict(source='ELD',platform=platform,seller=seller,seller_url='https://www.eldorado.gg'+link,
   rating_pct=str(rating),reviews=int(reviews[1].replace(',','')),minimum_k=str(low),stock_k=str(inventory),
   currency='USD',displayed_usd_per_k=str(unit),quantity_eligible_100k=low<=100<=inventory,
   quoted_100k_usd=str(unit*100) if low<=100<=inventory else None,
   minimum_purchase_usd=str(unit*low),delivery_time=delivery[1].strip(),delivery_method='not_verified_per_seller',
   checkout_fees='not_verified',captured_at=at,comparable=False,direct_pricing_weight='0',
   price_scope='public_first_page_observation_not_sitewide_minimum',url=URL+'?te_v0='+device))
 if not output:raise ValueError('eld_seller_observation_missing')
 eligible=[r for r in output if r['quantity_eligible_100k']]
 return dict(source='ELD',platform=platform,status='observed',captured_at=at,coverage='partial_first_page',
  observed_sellers=len(output),eligible_100k_sellers=len(eligible),offers=output,
  lowest_observed_100k_usd=min((r['quoted_100k_usd'] for r in eligible),key=Decimal,default=None),
  direct_pricing_weight='0',executable_quote=False)

def collect(browser):
 context=browser.new_context(locale='en-US',service_workers='block')
 rows=[];deadline=time.monotonic()+65
 try:
  for platform,device in DEVICES:
   page=context.new_page()
   try:
    remaining=max(1,min(20000,int((deadline-time.monotonic())*1000)))
    response=page.goto(URL+'?te_v0='+device,wait_until='domcontentloaded',timeout=remaining)
    if response is None or response.status>=400:raise ValueError('eld_http_blocked')
    if not page.url.startswith(URL+'?te_v0='):raise ValueError('eld_page_identity_changed')
    prior=None;stable=0
    while time.monotonic()<deadline:
     data=page.evaluate(READ)
     if data.get('devices')==[device] and data.get('rows'):
      key=json.dumps(data,sort_keys=True);stable=stable+1 if key==prior else 1;prior=key
      if stable>=2:break
     page.wait_for_timeout(400)
    else:raise ValueError('eld_observation_timeout')
    rows.append(parse(data,platform,device,datetime.now(timezone.utc).isoformat()))
   except Exception as error:
    rows.append(dict(source='ELD',platform=platform,status='missing',reason=str(error) if isinstance(error,ValueError) else type(error).__name__,captured_at=datetime.now(timezone.utc).isoformat(),offers=[],direct_pricing_weight='0',executable_quote=False))
   finally:page.close()
 finally:context.close()
 return rows

if __name__=='__main__':
 from playwright.sync_api import sync_playwright
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  try:print(json.dumps({'source':'ELD','platforms':collect(browser),'price_write_performed':False}))
  finally:browser.close()

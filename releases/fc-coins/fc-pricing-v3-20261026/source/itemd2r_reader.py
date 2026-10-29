"""Read the public FC27 100K ItemD2R offer; never enter its cart."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re

URL = 'https://www.itemd2r.com/ea-sports-fc/fc-27-coins'
DEVICES = (('PS', '2', 'PlayStation 5'), ('XBOX', '4', 'XBOX ONE'), ('PC', '1', 'PC Platform'))
READ = r"""() => {
 const price=document.querySelector('#html_total_price');
 const quantity=document.querySelector('#html_gold_num')?.value.replace(/,/g,'');
 const method=document.querySelector('#html_method_type')?.value;
 return {device:document.querySelector('#html_now_device')?.value,quantity,
   tier:document.querySelector('.cumton-amount-cur')?.getAttribute('data-amount'),
   tier_label:document.querySelector('.cumton-amount-cur')?.innerText.trim(),
   delivered:document.querySelector('#select_coins_id')?.innerText.trim(),
   method,method_selected:document.querySelector('#ai-automatic')?.classList.contains('deliverylist-cur'),
   fee:document.querySelector('#html_method_price')?.value,
   price:price?.innerText.trim(),total:document.querySelector('#html_total_price_id')?.innerText.trim(),
   unit:document.querySelector('#html_server_unit_price')?.value,
   usd:document.querySelector('#myEx')?.textContent.trim()==='USD $'&&
     document.querySelector('#myEx')?.parentElement.getAttribute('href')==='/index/change-currency?currency=USD'&&
     !!price?.getBoundingClientRect().width&&price.parentElement.innerText.includes('$'),
   busy:typeof window.jQuery==='function'&&window.jQuery.active>0,
   platform_label:document.querySelector('#html_search_class_id')?.innerText.trim()};
}"""

def offer(data, platform, device):
    if (data.get('device') != device or data.get('quantity') != '100000'
            or data.get('tier') != '100000' or not re.fullmatch(r'100\s*K',data.get('tier_label',''))
            or data.get('delivered') != '100' or data.get('method') != 'ai-automatic'
            or data.get('method_selected') is not True or data.get('usd') is not True or data.get('busy')):
        raise ValueError('itemd2r_offer_identity_unverified')
    try:
        price=Decimal(data['price']); total=Decimal(data['total']); unit=Decimal(data['unit']); fee=Decimal(data['fee'])
    except (KeyError,InvalidOperation,TypeError):
        raise ValueError('itemd2r_price_invalid') from None
    if (not all(v.is_finite() for v in (price,total,unit,fee)) or price<=0 or unit<=0 or fee!=0
            or not re.fullmatch(r'\d+\.\d{2}', data['price']) or price!=total
            or price != (unit*100000).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)):
        raise ValueError('itemd2r_visible_price_mismatch')
    return dict(source='ItemD2R',platform=platform,url=URL,captured_at=datetime.now(timezone.utc).isoformat(),
                currency='USD',purchase_k='100',bonus_k='0',gross_usd=str(price),
                effective_usd_per_k=str(price/100),coupon_excluded=True,auth_state='public',
                conditional=False,comparable=True,status='valid',reason=None,
                delivery_method='AI 4.0 Automated Delivery',price_basis='visible_public_sale_price')

def collect(context):
    page=context.new_page()
    try:
        response=page.goto(URL,wait_until='domcontentloaded',timeout=35000)
        if response is not None and response.status==403:
            headers=response.headers
            if 'cloudflare' in headers.get('server','').lower() or headers.get('cf-ray'):
                raise ValueError('itemd2r_cloudflare_403')
        if response is None or response.status!=200:
            raise ValueError('itemd2r_http_'+str(response.status) if response is not None else 'itemd2r_http_response_missing')
        if page.url.rstrip('/')!=URL or not re.search(r'FC\s*27\s*Coins',page.title(),re.I):
            raise ValueError('itemd2r_product_mismatch')
        rows=[]
        for platform,device,label in DEVICES:
            page.locator('#html_search_class_id').click(timeout=5000)
            page.locator('.platform-list li').filter(has_text=re.compile('^'+re.escape(label)+'$')).click(timeout=5000)
            page.wait_for_function("d=>document.querySelector('#html_now_device')?.value===d",arg=device,timeout=8000)
            page.locator('.cumton-amount-btn[data-amount="100000"]').click(timeout=5000)
            previous=None
            for _ in range(20):
                data=page.evaluate(READ)
                try: row=offer(data,platform,device)
                except ValueError:
                    previous=None
                else:
                    signature=json.dumps(data,sort_keys=True)
                    if signature==previous:
                        rows.append(row);break
                    previous=signature
                page.wait_for_timeout(400)
            else:raise ValueError('itemd2r_offer_unstable:'+platform)
        return rows
    finally:page.close()

from pathlib import Path
import subprocess

def public_read():
    code=Path(__file__).read_text(encoding='utf-8')+r'''
import signal
def terminate(signum,frame):raise TimeoutError('itemd2r_read_budget')
signal.signal(signal.SIGTERM,terminate)
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.connect_over_cdp('http://127.0.0.1:9225',timeout=8000,no_defaults=True)
 if len(b.contexts)!=1:raise ValueError('itemd2r_context_ambiguous')
 try:
  offers=collect(b.contexts[0])
 except ValueError as error:
  reason=str(error)
  if not re.fullmatch(r'itemd2r_[a-zA-Z0-9_:]{1,100}',reason):raise
  print(json.dumps({'source':'ItemD2R','status':'error','reason':reason,'offers':[]}))
 else:
  print(json.dumps({'source':'ItemD2R','status':'valid','offers':offers}))
'''
    result=subprocess.run(['docker','exec','-i','-u','fc27chrome','fc27-cloud-browser','timeout','--signal=TERM','--kill-after=5s','50s','python3','-'],input=code,text=True,capture_output=True,timeout=60)
    if result.returncode:
        raise ValueError('itemd2r_public_read_failed')
    payload=json.loads(result.stdout)
    if payload.get('source')=='ItemD2R' and payload.get('status')=='error':
        reason=payload.get('reason')
        if isinstance(reason,str) and re.fullmatch(r'itemd2r_[a-zA-Z0-9_:]{1,100}',reason):
            raise ValueError(reason)
    if payload.get('source')!='ItemD2R' or payload.get('status')!='valid' or [r.get('platform') for r in payload.get('offers',[])]!=['PS','XBOX','PC']:
        raise ValueError('itemd2r_platform_coverage_invalid')
    return payload['offers']

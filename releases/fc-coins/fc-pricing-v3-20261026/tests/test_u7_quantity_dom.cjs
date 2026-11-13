// Fictional visible card layouts exercise the actual reader string, not live U7 prices.
const assert=require('node:assert/strict');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
const {chromium}=require('playwright');
const source=path.resolve(__dirname,'../../../../fc27_cloud_browser/collect_competitor_browser.py');
const parsed=spawnSync(process.env.PYTHON||'python',['-B','-c',
  "import ast,json,sys;tree=ast.parse(open(sys.argv[1],encoding='utf-8').read());print(json.dumps(next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='U7BUY_QUANTITIES_READ' for t in n.targets))))",source],{encoding:'utf8'});
assert.equal(parsed.status,0,parsed.stderr);
const reader=Function('return ('+JSON.parse(parsed.stdout)+')')();
const card=(q,price,label='PS4/PS5',extra='')=>`<div class="players-reactive-table-content-wrapper"><div class="coins-name">${q}K Safe Coins ${label}</div><div>${price} USD</div>${extra}</div>`;
(async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage();
    await page.setContent('<div class="radio-select active">PS4/PS5</div>'+card(100,'10.00')+card(1000,'77.50')+card(2000,'130.05','PS4/PS5','Newcomer +50K'));
    const input={label:'PS4/PS5',quantities:['100','1000','2000','5000']};
    const data=await page.evaluate(reader,input);
    assert.equal(data.ready,true);
    assert.deepEqual(data.offers.map(r=>r.purchase_k),['100','1000','2000']);
    assert.deepEqual(data.offers.map(r=>r.price),['10.00','77.50','130.05']);
    assert.equal(data.offers[2].conditional,true);
    assert.equal(data.offers[2].bonus,'50');
    assert.deepEqual(data.missing,[{purchase_k:'5000',reason:'native_quantity_not_observed'}]);
    await page.setContent('<div class="radio-select active">PS4/PS5</div>'+card(100,'9')+card(100,'10')+card(1000,'80','PS4/PS5','70 USD'));
    const conflict=await page.evaluate(reader,input);
    assert.deepEqual(conflict.offers,[]);
    assert.equal(conflict.missing[0].reason,'native_card_ambiguous');
    assert.equal(conflict.missing[1].reason,'native_card_ambiguous');
    assert.equal((await page.evaluate(reader,{...input,label:'PC'})).ready,false);
    await page.setContent('<div class="radio-select active">PS4/PS5</div><p>Delivery method: Comfort Trade.</p>'+card(100,'8.82','PS4/PS5','Complete Time: 0.5-1Hour'));
    const delivery=await page.evaluate(reader,{label:'PS4/PS5',quantities:['100']});
    assert.equal(delivery.offers[0].delivery_method,'comfort_trade');
    assert.equal(delivery.offers[0].delivery_estimate,'0.5-1Hour');
    await page.setContent('<div class="radio-select active">PS4/PS5</div>'+card(100,'8.82'));
    const absent=await page.evaluate(reader,{label:'PS4/PS5',quantities:['100']});
    assert.equal(absent.offers[0].delivery_method,null);
    assert.equal(absent.offers[0].delivery_estimate,null);
    console.log('U7 quantity DOM: native values, missing large tier, conditional newcomer, duplicates, multiple prices, platform selection passed');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

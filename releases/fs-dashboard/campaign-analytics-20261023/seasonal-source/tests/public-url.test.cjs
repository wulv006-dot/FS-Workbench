const test=require('node:test'),assert=require('node:assert/strict');
const {publicURL}=require('../public-url.cjs');
test('preview omits canonical; formal HTTPS origin and prefix are explicit',()=>{
  assert.equal(publicURL({}),'');
  assert.equal(publicURL({CAMPAIGN_PUBLIC_ORIGIN:'https://www.mmoexp.com',CAMPAIGN_PUBLIC_PREFIX:'/offers/vault/'}),'https://www.mmoexp.com/offers/vault/seasonal/');
  for(const origin of ['http://www.mmoexp.com','https://www.mmoexp.com/','https://user:pass@www.mmoexp.com','https://www.mmoexp.com/x?y'])assert.throws(()=>publicURL({CAMPAIGN_PUBLIC_ORIGIN:origin}));
  for(const prefix of ['/../','//bad/','/x?y/','/x%2fy/','x/'])assert.throws(()=>publicURL({CAMPAIGN_PUBLIC_ORIGIN:'https://www.mmoexp.com',CAMPAIGN_PUBLIC_PREFIX:prefix}));
});

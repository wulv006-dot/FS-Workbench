// Original accepted product references are retained for preview, never promoted to verified sale SKUs.
export function centerSeed(fc,seasonal){
 const products=[],byOriginal={};
 for(const p of Object.values(fc.products)){
  byOriginal[p.key]=[];
  for(const [platform,row] of Object.entries(p.platforms||{})){
   const key='fc-'+p.key+'-'+platform;byOriginal[p.key].push(key);
   const quantity=String(row.quantity||1);
   products.push({key,title:p.title||p.name,product_ref:{site_id:String(fc.siteId),game_id:String(fc.gameId),goods_id:String(row.id)},
    platform:{code:platform,attribute_id:String(row.aid)},quantity:{min:quantity,max:quantity,step:'1',unit:'item',...(row.group?{group:String(row.group)}:{})},available:false,attributes:[],...(p.image?{image:p.image}:{})});
  }
 }
 for(const p of seasonal.products){const s=p.source,quantity=String(s.quantity);
  products.push({key:'seasonal-'+p.id,title:p.name,product_ref:{site_id:String(s.siteId),game_id:String(s.gid),goods_id:String(s.goodsId)},
   platform:{code:'area-'+s.aid,attribute_id:String(s.aid)},quantity:{min:quantity,max:quantity,step:'1',unit:s.unit||'item'},available:false,attributes:[]});
 }
 const keys=ids=>[...new Set(ids.flatMap(id=>byOriginal[id]||[]))];
 return {seedProducts:products,pageProductKeys:{
  'fc27-weekly':keys(fc.weekly.ids),
  'fc27-sbc':keys([...fc.sbc.ids,...Object.values(fc.sbc.routes).flatMap(r=>[...r.picks,...r.alternatives])]),
  'fc27-trio':keys([...fc.trio.ids,...fc.bundles.ids]),
  'seasonal-vault':seasonal.products.map(p=>'seasonal-'+p.id)
 }};
}

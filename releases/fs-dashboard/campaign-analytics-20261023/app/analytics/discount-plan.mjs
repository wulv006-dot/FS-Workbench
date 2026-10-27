// Offline compiler for the observed Admin discount form. No transport, writes,
// credentials or inferred success states. Creation/readback stays with Admin.
const fail=code=>{throw Object.assign(Error(code),{code});};
const numeric=v=>typeof v==='string'&&/^[1-9]\d{0,19}$/.test(v);
const exact=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).every(key=>keys.includes(key));
function date(value){
 if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value))fail('DISCOUNT_DATE_REQUIRED');
 const wire=value.replace(' ','T')+'+08:00',ms=Date.parse(wire);
 if(!Number.isFinite(ms)||new Date(ms+8*3600000).toISOString().slice(0,19).replace('T',' ')!==value)fail('DISCOUNT_DATE_REQUIRED');
 return ms;
}
export function compileDiscountPlan(input,{existingCodes=[]}={}){
 if(!exact(input,['activity_id','code','game_ids','off_percent','starts_at','ends_at','repeat_qty'])||typeof input.activity_id!=='string'||!/^[-a-z0-9]{1,80}$/.test(input.activity_id))fail('DISCOUNT_PLAN_INVALID');
 if(typeof input.code!=='string'||! /^[A-Z0-9]{4,12}$/.test(input.code))fail('DISCOUNT_CODE_INVALID');
 if(!Array.isArray(input.game_ids)||!input.game_ids.length||input.game_ids.length>4||input.game_ids.some(id=>!numeric(id))||new Set(input.game_ids).size!==input.game_ids.length)fail('DISCOUNT_GAME_SCOPE_REQUIRED');
 if(![8,10,15].includes(input.off_percent))fail('DISCOUNT_TIER_INVALID');
 if(!Number.isSafeInteger(input.repeat_qty)||input.repeat_qty<0)fail('DISCOUNT_USAGE_REQUIRED');
 if(date(input.starts_at)>=date(input.ends_at))fail('DISCOUNT_WINDOW_INVALID');
 if(!Array.isArray(existingCodes))fail('DISCOUNT_LOOKUP_REQUIRED');
 const collisions=existingCodes.filter(row=>typeof row?.code==='string'&&row.code.toUpperCase()===input.code);
 // Existing objects need exact scope reconciliation, never edit or overwrite
 // another campaign's code just because its display name matches.
 if(collisions.length)fail('DISCOUNT_CODE_EXISTS_RECONCILE');
 return {schema_version:1,activity_id:input.activity_id,operation:'create_candidate_not_executed',
  controller:'/admin/market.Discount/',method:'POST',action:'add',
  fields:{site_id:266,code:input.code,type:1,attain:'0',discount:String(100-input.off_percent),repeat_qty:input.repeat_qty,gid:[...input.game_ids],exclude_gids:[],...(input.game_ids.length===1?{aid:0}:{}),cid:[-1],uid:0,timestart:input.starts_at,timeend:input.ends_at,status:1},
  validation:{timezone:'Asia/Shanghai',end_inclusive:true,server_timezone_verified:false,server_end_inclusive_verified:false,duplicate_lookup_complete:false,created:false,readback_verified:false},
  required_checks:['Exact code lookup before creation','Verify Admin timezone and inclusive cutoff','Use native save response, then GET edit/index readback','If outcome is unknown, look up this same code; never create another','Verify site, games, payable percentage, UID, limits and dates','Verify native Cart Apply business success and payable amount without payment']};
}

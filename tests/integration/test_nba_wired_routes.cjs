'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert'),{EventEmitter}=require('events');
const base=path.join(__dirname,'../..','opt','nba-reprice','backend');
const source=fs.readFileSync(path.join(base,'server.js'),'utf8');
const security=require(path.join(base,'api_security.js'));
function fixture(env={}) {
 let handler,writes=0;
 const deny=()=>{throw Error('real network/filesystem/subprocess forbidden')};
 const mocked={crypto:require('crypto'),http:{createServer:f=>{handler=f;return {listen:deny}},request:deny},https:{request:deny},child_process:{execFile:deny},fs:new Proxy({}, {get:()=>deny}),path,url:require('url'),os:{homedir:()=>'/synthetic-home'},'./api_security':security};
 const context=vm.createContext({require:n=>{assert(n in mocked);return mocked[n]},module:{},process:{env:{},platform:'linux'},__dirname:base,console:{log:()=>{},error:()=>{}},Buffer,Date,Set,Promise});
 context.process.env=env;context.require.main={};
 vm.runInContext(source,context);
 context.fakeWrite=async()=>{writes++;return {ok:true,results:[],verify:{}}};
 vm.runInContext('adminWrite = fakeWrite; appendApplyLog = ()=>{}; readLatestPrice = async()=>({platforms:[]}); readMmoexpPrices = async()=>[]; readCompetitors = async()=>({sites:{}});',context);
 return {request:async(method,url,headers={},body={})=>{
  const req=new EventEmitter();Object.assign(req,{method,url,headers,socket:{remoteAddress:'127.0.0.1'},destroy:deny});
  let status,raw='';const res={setHeader:()=>{},writeHead:s=>status=s,end:s=>raw=s||''};
  const pending=handler(req,res);req.emit('data',JSON.stringify(body));req.emit('end');await pending;return {status,body:JSON.parse(raw||'{}')};
 },writes:()=>writes};
}
(async()=>{
 let f=fixture();assert.equal((await f.request('GET','/api/health')).status,200);
 for(const route of ['/api/read','/api/current','/api/competitors','/api/apply'])assert.equal((await f.request('GET',route)).status,401);
 assert.equal(f.writes(),0);
 const tokens=JSON.stringify({'synthetic-admin':'wulv','synthetic-reader':'viewer','synthetic-unknown':'fstech'});
 let admin={authorization:'Bearer synthetic-admin','content-type':'application/json'},reader={authorization:'Bearer synthetic-reader','content-type':'application/json'};
 f=fixture({OPERATORS:tokens});assert.equal((await f.request('GET','/api/read',reader)).status,200);
 assert.equal((await f.request('POST','/api/apply',admin)).status,403);assert.equal(f.writes(),0);
 f=fixture({OPERATORS:tokens,WRITE_READY:'true'});
 assert.equal((await f.request('GET','/api/apply',admin)).status,405);
 assert.equal((await f.request('POST','/api/apply',reader)).status,403);
 assert.equal((await f.request('POST','/api/apply',{...admin,authorization:'Bearer synthetic-unknown'})).status,403);
 assert.equal((await f.request('POST','/api/apply',{...admin,'content-type':'text/plain'})).status,415);
 assert.equal((await f.request('POST','/api/apply',{...admin,origin:'https://evil.example'})).status,403);
 for(const body of [{platforms:[{area:'PS',price:1}]},{confirm:'NBA_PRICE_APPLY',platforms:[{area:'PS',price:0}]},{confirm:'NBA_PRICE_APPLY',platforms:[{area:'invalid',price:1}]}])assert.equal((await f.request('POST','/api/apply',admin,body)).status,400);
 assert.equal(f.writes(),0);
 const result=await f.request('POST','/api/apply',admin,{confirm:'NBA_PRICE_APPLY',platforms:[{area:'PS',price:1}]});assert.equal(result.status,200);assert.equal(f.writes(),1);
 f=fixture({NBA_AUTH_MODE:'proxy'});assert.equal((await f.request('GET','/api/read',{'x-auth-user':'viewer','x-auth-role':'readonly'})).status,200);
 assert.equal((await f.request('POST','/api/apply',{'x-auth-user':'viewer','x-auth-role':'readonly','content-type':'application/json'})).status,403);
 console.log(JSON.stringify({passed:true,scope:'actual candidate HTTP handler in VM; synthetic identities; socket/listen/fs/process forbidden; positive writer replaced by mock'}));
})().catch(e=>{console.error(e);process.exitCode=1});

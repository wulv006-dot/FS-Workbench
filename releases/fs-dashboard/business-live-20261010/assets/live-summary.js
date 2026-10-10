export class LiveSummary {
 constructor(selection,update,state){this.selection=selection;this.update=update;this.state=state;this.pending=null;this.current=null;this.epoch=0;this.key=null;}
 async read(path){return fetch(path,{credentials:'same-origin',cache:'no-store',redirect:'error',signal:this.controller.signal});}
 check(){
  const selection=this.selection(),key=JSON.stringify(selection);
  if(this.pending&&key===this.key)return this.pending;
  if(key!==this.key){this.controller?.abort();this.epoch++;this.current=null;this.key=key;this.state({phase:'loading',clear:true,message:'正在读取所选日期的经营指标…'});}
  const epoch=this.epoch;this.controller=new AbortController();
  const promise=(async()=>{try{
   const started=Date.now(),params=new URLSearchParams({...selection,mode:'summary'});
   do {
    const r=await this.read('/dashboard/fs-home/range.json?'+params);
    if(epoch!==this.epoch)return;
    if(r.status===401||r.status===403){this.current=null;this.state({phase:'denied',status:r.status,message:'登录或来源权限失效，已清除经营指标。'});return;}
    const data=await r.json();
    if(epoch!==this.epoch)return;
    if(r.status===202||r.status===429){this.state({phase:'loading',message:'后台正在读取或队列繁忙；尚无新结果。'});await new Promise(resolve=>setTimeout(resolve,2000));continue;}
    if(!r.ok||!['available','stale'].includes(data.status)||data.scopeContractId!=='admin-main-order-labelled-supplement-v1'||data.profile?.key!==selection.profile||data.query?.start!==selection.start||data.query?.end!==selection.end)throw Error('summary_unavailable');
    this.current=data;this.update(data);this.state({phase:'available'});return;
   }while(Date.now()-started<100000&&epoch===this.epoch);
   throw Error('summary_wait_timeout');
  }catch(e){
   if(epoch!==this.epoch)return;
   if(e.status===401||e.status===403){this.current=null;this.state({phase:'denied',status:e.status,message:'登录或访问权限失效，已清除经营指标。'});return;}
   if(this.current){this.current={...this.current,stale:true,status:'stale'};this.update(this.current);}
   this.state({phase:this.current?'stale':'unavailable',message:this.current?'⚠ 检查失败，保留已过期值；读取时间见来源。':'经营指标暂不可用；缺失没有填零。'});
  }})();
  promise.finally(()=>{if(this.pending===promise)this.pending=null;});
  this.pending=promise;return promise;
 }
 start(){if(this.timer)return;this.check();this.timer=setInterval(()=>this.check(),60000);}
 stop(){clearInterval(this.timer);this.timer=null;this.epoch++;this.controller?.abort();this.current=null;this.pending=null;}
}

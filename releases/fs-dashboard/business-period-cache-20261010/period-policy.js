function fsPeriodPolicy(){
 const day=(now=Date.now())=>new Date(now+8*3600000).toISOString().slice(0,10);
 const shift=(d,n)=>new Date(Date.parse(d+'T00:00:00Z')+n*86400000).toISOString().slice(0,10);
 const selection=(mode,custom,min,max,anchor=day())=>custom?{...custom,grain:'day'}:mode==='today'?{start:anchor,end:anchor,grain:'day'}:mode==='yesterday'?{start:shift(anchor,-1),end:shift(anchor,-1),grain:'day'}:+mode>0?{start:shift(anchor,-Number(mode)),end:shift(anchor,-1),grain:'day'}:{start:min,end:max<anchor?max:shift(anchor,-1),grain:'day'};
 const active=(s,now=Date.now())=>!!s?.end&&s.end.slice(0,10)>=day(now);
 return {day,shift,selection,active,ttl:(s,now=Date.now())=>active(s,now)?900:7200};
}

// Synthetic values only; preserves the observed API field shape.
export function fixture(){
 const period={start:'2026-10-08 00:00',end:'2026-10-09 00:00'};
 return {key:'FC27',period,
  primary:{status:'available',period:{...period},currency:'USD',timezone:'Asia/Shanghai',revenueUsd:930,capturedAt:'2026-10-09T06:00:01Z'},
  dimensions:{channels:[{name:'www.mmoexp.com',amountUsd:900,orders:null},{name:'eldorado.gg',amountUsd:20,orders:null},{name:'g2g.com',amountUsd:10,orders:null}]},
  supplement:{status:'available',period:{...period},capturedAt:'2026-10-09T06:00:00Z',metrics:{revenueUsd:{status:'available',value:1000},profitMarginPct:{status:'not_provided',value:null}},
   dimensions:{channels:[{code:'www.mmoexp.com',name:'www.mmoexp.com',revenueUsd:1000,orders:40}]}}};
}

// Synthetic contract, unrelated to any real game server, model, SKU or price.
module.exports=()=>({schema_version:1,verified:true,catalog_version:'synthetic-v1',model_ref:{site_id:'fixture-site',game_id:'fixture-game',model_id:'fixture-model'},fields:[
  {id:'platform',label:'Platform',depends_on:[],values:[{id:'console',label:'Fixture console'},{id:'desktop',label:'Fixture desktop'}]},
  {id:'server',label:'Server',depends_on:['platform'],values:[{id:'east',label:'Fixture East'},{id:'west',label:'Fixture West'}]},
  {id:'spec',label:'Specification',depends_on:['platform','server'],values:[{id:'normal',label:'Fixture normal'},{id:'extra',label:'Fixture extra'}]}
],combinations:[
  {choices:{platform:'console',server:'east',spec:'normal'},product_key:'fixture-console-east',attributes:[{attribute_id:'fixture-spec',value_id:'normal'}],quantity:{unit:'fixture-unit',min:'10',max:'100',step:'10'}},
  {choices:{platform:'console',server:'west',spec:'extra'},product_key:'fixture-console-west',attributes:[{attribute_id:'fixture-spec',value_id:'extra'}],quantity:{unit:'fixture-unit',min:'10',max:'100',step:'10'}},
  {choices:{platform:'desktop',server:'east',spec:'extra'},product_key:'fixture-desktop-east',attributes:[{attribute_id:'fixture-spec',value_id:'extra'}],quantity:{unit:'fixture-unit',min:'1',max:'5',step:'1'}}
]});

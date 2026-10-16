const fs=require('fs'),path=require('path'),vm=require('vm');
for(const name of ['management-live.js','sandbox-live.js']){const file=path.join(__dirname,'../source/frontend',name);new vm.Script(fs.readFileSync(file,'utf8'),{filename:name});}
console.log('management browser script syntax PASS');

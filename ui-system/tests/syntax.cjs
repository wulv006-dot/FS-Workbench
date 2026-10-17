const fs=require('fs'),path=require('path'),cp=require('child_process');
const root=path.resolve(__dirname,'..');
const files=fs.readdirSync(path.join(root,'adapters')).filter(x=>x.endsWith('.js')).map(x=>path.join(root,'adapters',x));
files.push(path.join(root,'modules/native/shell.js'),path.join(root,'modules/native/google.js')); 
for(const file of files){const r=cp.spawnSync(process.execPath,['--check',file],{encoding:'utf8'});if(r.status!==0)throw Error(file+' '+r.stderr);}
console.log('UI JS syntax: '+files.length+' files passed');

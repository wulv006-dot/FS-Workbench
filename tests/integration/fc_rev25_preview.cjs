'use strict';
const fs=require('fs'),path=require('path');
const logic=require(path.join(__dirname,'../../fc27_chrome_collector/repricing_logic.js'));
const values=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(values.map(x=>logic.recompute(x.evidence,x.edits))));

// Trusted local JSON bridge; the Hermes host verifies session/delegation before launch.
// No network listener, cookies, coupon writes, publishing or schedule activation.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {makeStore,previewCatalog,validateLayout} from '../store.mjs';
import {makeCenterStore} from '../center-store.mjs';
import {centerSeed} from '../center-seed.mjs';
import {effectiveFcCatalog} from '../../runtime/model-cards.mjs';
import {makeAdminPriceProvider,readAdminPricePolicy} from '../admin-price-provider.mjs';
import {mergeNativeCatalog,readNativeLaunchPolicy} from '../native-catalog.mjs';
import {backendRead} from '../backend-client.mjs';
import {makeWeeklyPipeline} from '../weekly-pipeline.mjs';

export function weeklyRuntime({onDraftSaved=()=>{},enabledProvider=()=>true,base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..'),dir=process.env.CAMPAIGN_DATA||'/var/lib/fs-campaign-dashboard',publicDir=process.env.CAMPAIGN_PUBLIC_RELEASE_DIR||'/var/lib/fs-campaign-public',sourceProvider=({bundle_refs})=>backendRead({action:'weekly_selection',site_id:'266',game_id:'1327',bundle_refs})}={}){
 const box={window:{}},seasonal={};vm.runInNewContext(fs.readFileSync(path.join(base,'analytics-config.js'),'utf8'),box);vm.runInNewContext(fs.readFileSync(path.join(base,'seasonal/campaign-data.js'),'utf8'),seasonal);
 const catalog=JSON.parse(fs.readFileSync(path.join(base,'catalog.json'),'utf8')),store=makeStore(dir,catalog,box.window.FC_ANALYTICS_CONFIG.registry);
 const policyDir=process.env.CAMPAIGN_BACKEND_STATE_DIR||path.join(dir,'backend'),prices=makeAdminPriceProvider({publicDir,readPolicy:()=>readAdminPricePolicy(policyDir)});
 const validateFcLayout=(layout,models={})=>validateLayout(layout,effectiveFcCatalog(catalog,models));
 const seedProvider=(layout,models={})=>mergeNativeCatalog(centerSeed(previewCatalog(effectiveFcCatalog(catalog,models),layout??store.read().layout),seasonal.SeasonalData,prices.seedOptions()),readNativeLaunchPolicy(policyDir).catalog);
 const center=makeCenterStore({dir:path.join(dir,'center'),publicDir,sourceRevision:process.env.CAMPAIGN_SOURCE_REVISION||'unreleased',validateFcLayout,seedProvider,nativeCheckoutProvider:()=>readNativeLaunchPolicy(policyDir).checkout});
 return makeWeeklyPipeline({dir:path.join(dir,'center','weekly-plans'),center,sourceProvider,enabledProvider,onDraftSaved,contextProvider:s=>{const layout=validateFcLayout(s.draft.fc_layout??store.read().layout,s.draft.fc_models||{});return {effective_fc_layout:layout,catalog_products:seedProvider(layout,s.draft.fc_models||{}).seedProducts};}});
}

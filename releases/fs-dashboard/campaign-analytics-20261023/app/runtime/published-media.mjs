import fs from 'node:fs';
import path from 'node:path';
import {digest,fail} from './snapshot.mjs';
import {mediaId} from './media-contract.mjs';
export function readPublishedMedia(publicDir,snapshot,assetId){
 if(!mediaId(assetId)||!Object.hasOwn(snapshot.media_assets||{},assetId))fail('MEDIA_NOT_FOUND',404);
 const info=snapshot.media_assets[assetId],root=path.join(publicDir,'assets'),file=path.join(root,assetId);
 if(!fs.existsSync(file))fail('MEDIA_NOT_FOUND',404);
 if(fs.lstatSync(root).isSymbolicLink()||fs.lstatSync(file).isSymbolicLink()||!fs.lstatSync(file).isFile())fail('INVALID_MEDIA_PATH');
 const bytes=fs.readFileSync(file);if(bytes.length!==info.bytes||digest(bytes)!==info.sha256)fail('MEDIA_UNCONFIRMED');return {info,bytes};
}

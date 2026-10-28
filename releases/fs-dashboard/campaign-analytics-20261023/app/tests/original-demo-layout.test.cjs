const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../seasonal'),html=fs.readFileSync(path.join(root,'index.html'),'utf8'),css=fs.readFileSync(path.join(root,'event.css'),'utf8');
test('original split hero, mascot and four game region replace the redesigned stacked page',()=>{
 assert.match(html,/class="hero-inner"/);assert.match(html,/class="hero-story"/);assert.match(html,/class="game-picker"/);
 assert(html.indexOf('class="hero-story"')<html.indexOf('class="game-picker"'));
 assert.match(html,/id="hero-image" class="story-art" src="assets\/halloween-max.png"/);assert.match(html,/id="games" class="game-cards"/);
 assert.doesNotMatch(html,/Pick your world|A little mystery awaits|class="max-guide"|Frontend preview only|Demo page|OCT 24 - NOV 03/);
 assert.equal((html.match(/<h1\b/g)||[]).length,1);assert.match(css,/\.game-cards\s*\{[^}]*grid-template-columns:\s*repeat\(2,/s);
});
test('every runtime hook and asset exists; no fake search/login/navigation controls',()=>{
 for(const id of ['games','game-offers','game-offers-title','game-offers-note','offer-slots','event-dialog','dialog-title','dialog-content','event-status','hero-image','hero-mobile-source','configuration-title','configuration-summary'])assert.equal((html.match(new RegExp('id="'+id+'"','g'))||[]).length,1,id);
 // The event window is no longer printed in the hero, and no manual refresh or
 // detail trigger is offered; prices and offers refresh on their own.
 assert.doesNotMatch(html,/campaign-date/);assert.doesNotMatch(html,/offer-tools|data-action="refresh-prices"|data-action="rules"/);
 assert.doesNotMatch(html,/placeholder="Search your game"|>Log In<|>Help center<|class="utility-bar"/);
 for(const match of html.matchAll(/(?:src|href)="([^"#]+)"/g)){const ref=match[1];if(!/^https?:/.test(ref))assert(fs.existsSync(path.resolve(root,ref.split(/[?#]/)[0])),ref);}
 assert.match(css,/prefers-reduced-motion/);assert.match(html,/aria-live="polite"/);
});

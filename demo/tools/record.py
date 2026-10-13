import asyncio, time, json, os, sys, re
sys.path.insert(0,'/tmp/vid')
from lib import *
from script import B, CH
DUR=json.load(open('/tmp/vid/build/durations.json'))
SPEED=float(os.environ.get('SPEED','1')); REC=os.environ.get('REC','1')=='1'
BASE='http://127.0.0.1:5173/'; SLIDES='file:///tmp/vid/site/slides.html'
EXE='/opt/pw-browsers/chromium-1194/chrome-linux/chrome'
PAD=0.8; ADELAY=0.3
OUT='/tmp/vid/build/rec'; os.makedirs(OUT,exist_ok=True)
EXTRA_JS="void 0"
class R(Rec):
    async def wait(s,sec): await s.page.wait_for_timeout(int(sec*1000*SPEED))
    async def move(s,x,y,dur=1.0): await Rec.move(s,x,y,max(0.15,dur*SPEED))
    async def type(s,loc,text,dur=0.8,delay=85):
        await s.click(loc,dur,0.1); await loc.fill(""); await loc.press_sequentially(text,delay=int(delay*SPEED)); await s.wait(0.3)
    async def hl(s,loc=None,box=None,hold=0.0):
        if loc is None and box is None: await s.page.evaluate("window.__hl&&window.__hl(null)"); return
        if box is None:
            await s.center(loc); box=await loc.bounding_box()
        await s.page.evaluate("b=>window.__hl(b.x,b.y,b.width,b.height)",box); await s.wait(hold)
    async def center(s,loc):
        await loc.evaluate("e=>e.scrollIntoView({block:'center'})"); await s.page.wait_for_timeout(500)
    async def nav(s,name):
        await s.hl(); l=s.page.locator('nav').get_by_role('link',name=name,exact=True); await s.click(l,1.1,0.9)
async def mk(p,state=None,video=True):
    b=await p.chromium.launch(executable_path=EXE,args=['--no-sandbox'])
    kw=dict(viewport={'width':W,'height':H})
    if REC and video: kw.update(record_video_dir=OUT,record_video_size={'width':W,'height':H})
    if state: kw['storage_state']=state
    ctx=await b.new_context(**kw); await ctx.add_init_script(CURSOR_JS); await ctx.add_init_script(EXTRA_JS)
    pg=await ctx.new_page(); t1=time.monotonic(); return b,ctx,pg,t1
CHECKS=[]
def check(name,ok,detail=''):
    CHECKS.append({'name':name,'ok':bool(ok),'detail':detail}); print(('OK  ' if ok else 'FAIL'),name,detail,flush=True)
async def mtext(pg): return await pg.inner_text('main')
async def badge(r,on=True): await r.page.evaluate("t=>window.__badge&&window.__badge(t)", "MANUALLY ENTERED DEMONSTRATION VALUES" if on else None)

# ---------- live actions ----------
async def a_landing(r,pg,S):
    await badge(r,False)
    await r.goto_el(pg.get_by_text('database ok').first,1.6); await r.wait(2.5)
    await r.goto_el(pg.get_by_role('link',name='Open the application').first if await pg.get_by_role('link',name='Open the application').count() else pg.get_by_text('Open the application').first,1.6)
async def a_register(r,pg,S):
    await (pg.get_by_role('link',name='Open the application').first if await pg.get_by_role('link',name='Open the application').count() else pg.get_by_text('Open the application').first).click(); await r.wait(1.8)
    await r.click(pg.get_by_text('Create one').first,1.0,1.2)
    await r.type(pg.get_by_label('Full name'),'Demo Presenter')
    await r.type(pg.get_by_label('Email address'),'presenter-a@example.com')
    await r.type(pg.locator('input[name=Password]'),'demo-passphrase-2026')
    await r.type(pg.get_by_role('textbox',name='Confirm password'),'demo-passphrase-2026')
    await r.click(pg.get_by_role('checkbox'),0.8,0.4)
    await r.click(pg.get_by_role('button',name='Create account'),0.9,0.5)
    await pg.wait_for_url(re.compile(r'#/app'),timeout=15000); await r.wait(1.5)
async def a_createtwin(r,pg,S):
    await r.nav('Settings'); await r.type(pg.get_by_label('Twin label'),'demo-twin-01')
    await r.goto_el(pg.locator('select').first,1.0); await r.wait(1.5)
    await r.click(pg.get_by_role('button',name='Create twin'),1.0,0.5)
    await pg.locator('.notice.ok').first.wait_for(timeout=15000)
    t=await pg.locator('.notice.ok').first.inner_text(); check('twin created v0','version 0' in t,t.strip()[:60])
    await r.hl(pg.locator('.notice.ok').first,hold=3.0); await r.say('BUILT-IN DEMONSTRATION PRIOR')
    await r.wait(2.0); await r.hl(); await r.say()
async def a_twin0(r,pg,S):
    await r.nav('My Twin'); tb=pg.locator('table').first; await tb.wait_for(timeout=10000); tx=await tb.inner_text()
    check('v0 beta B 0.747/0.187','0.747' in tx and '0.187' in tx,tx.split('\n')[1][:40] if '\n' in tx else tx[:40])
    await r.say('VERSION 0 · INITIAL PRIOR · SYNTHETIC'); await r.hl(tb,hold=1.0)
    row=pg.locator('table tr').nth(1); await r.goto_el(row,1.4); await r.wait(5.0); await r.hl(); await r.say()
async def a_tour(r,pg,S):
    for n in ['Forecast','Observations','History','Insights']:
        await r.nav(n); await r.wait(3.2)
    await r.nav('Home'); await r.wait(1.5)
async def a_login(r,pg,S):
    await r.wait(1.0)
    await r.type(pg.get_by_label('Email address'),'presenter-a@example.com',0.7,60)
    await r.type(pg.locator('input[name=Password]'),'demo-passphrase-2026',0.7,60)
    await r.click(pg.get_by_role('button',name='Sign in').last,0.8,0.5)
    await pg.wait_for_url(re.compile(r'#/app'),timeout=15000); await r.wait(1.5)
    await r.nav('My Twin'); tb=pg.locator('table').first; await tb.wait_for(); tx=await tb.inner_text()
    check('login: twin still at v1 (0.950/0.144)','0.950' in tx and '0.144' in tx)
    await r.say('SIGNED IN AGAIN · TWIN PERSISTED · VERSION 1'); vh=pg.get_by_role('heading',name='Version history').locator('xpath=..')
    await r.hl(vh,hold=5.0); await r.hl(); await r.say()
async def fill_forecast(r,pg,t,slow=True):
    ins=pg.locator('form[aria-label^="Request"] input')
    for i,v in enumerate(['60','0.3','110']): await r.type(ins.nth(i),v,0.7,110 if slow else 40)
    await r.click(ins.nth(3),0.7,0.2); await ins.nth(3).fill(t); await r.wait(0.8)
async def a_fc_fill(r,pg,S):
    await badge(r); await r.say('FORECAST → OBSERVE → UPDATE'); await r.nav('Forecast'); await fill_forecast(r,pg,'2026-01-01T08:00')
async def a_fc_submit(r,pg,S):
    await r.click(pg.get_by_role('button',name='Request forecast'),1.0,0.5)
    await pg.locator('.notice.ok').filter(has_text='Forecast stored from twin version 0').first.wait_for(timeout=20000); await r.wait(1.0)
    tx=await mtext(pg); S['fc1']=tx
    check('fc1 B 155 126–184 7.7%','expected max 155' in tx and '126–184' in tx and '7.7%' in tx)
    await r.say('FORECAST MADE FROM TWIN VERSION 0'); await r.hl(pg.locator('table').first,hold=1.0)
    await r.goto_el(pg.locator('table tr').nth(2),1.2); await r.wait(6.0); await r.hl()
async def a_obs_fill(r,pg,S):
    await r.say('MANUALLY ENTERED OUTCOME · NOT A PARTICIPANT RECORD'); await r.nav('Observations')
    f=pg.locator('form[aria-label^="Record"]'); await r.hl(f.get_by_text('Must be at least 120 minutes',exact=False).first,hold=2.5); await r.hl()
    await r.type(f.locator('input').nth(2),'185',0.9,140); await r.wait(2.0)
async def a_obs_record(r,pg,S):
    await r.say('RECORDING AN OUTCOME DOES NOT CHANGE THE TWIN')
    await r.click(pg.get_by_role('button',name='Record outcome'),1.0,0.6)
    await pg.locator('.notice.ok').filter(has_text='Observation recorded').first.wait_for(timeout=15000); await r.hl(pg.locator('.notice.ok').first,hold=3.5); await r.hl()
    await r.goto_el(pg.get_by_role('button',name='Apply').first,1.2); await r.wait(2.0)
async def a_obs_apply(r,pg,S):
    await r.say('UPDATE · TWIN VERSION 0 → 1')
    await r.click(pg.get_by_role('button',name='Apply').first,0.6,0.6)
    await pg.locator('.notice.ok').filter(has_text='Twin updated: version 0').first.wait_for(timeout=15000)
    t=await pg.locator('.notice.ok').first.inner_text(); check('apply 0→1','version 0 → 1' in t,t.strip().replace('\n',' ')[:70])
    await r.hl(pg.locator('.notice.ok').first,hold=4.0); await r.hl(); await r.say()
async def a_twin1(r,pg,S):
    await r.nav('My Twin'); tb=pg.locator('table').first; await tb.wait_for(); tx=await tb.inner_text()
    check('v1 beta B 0.950/0.144','0.950' in tx and '0.144' in tx)
    await r.say('VERSION 0 → 1 · β 0.747 → 0.950 · SD 0.187 → 0.144'); await r.hl(pg.locator('table tr').nth(1),hold=5.0)
    await r.say('THE TWIN MAINTAINS STATE ACROSS ELIGIBLE UPDATES'); vh=pg.get_by_role('heading',name='Version history').locator('xpath=..')
    await r.hl(vh,hold=5.0); await r.hl(); await r.say()
async def a_fc2(r,pg,S):
    await r.nav('Forecast'); await fill_forecast(r,pg,'2026-01-01T12:00',slow=False)
    await r.click(pg.get_by_role('button',name='Request forecast'),0.9,0.5)
    await pg.locator('.notice.ok').filter(has_text='Forecast stored from twin version 1').first.wait_for(timeout=20000); await r.wait(1.0)
    tx=await mtext(pg); check('fc2 B 167 140–194 21.0%','expected max 167' in tx and '140–194' in tx and '21.0%' in tx)
    await r.say('SAME INPUTS · NEW STATE · P(max ≥ 180): 7.7% → 21.0%'); await r.hl(pg.locator('table').first,hold=1.0)
    await r.goto_el(pg.locator('table tr').nth(2),1.2); await r.wait(9.0); await r.hl(); await r.say()
async def a_unc1(r,pg,S):
    await badge(r,False); await r.say('MAXIMUM GLUCOSE IN THE 120-MIN WINDOW · NO CURVE IS DRAWN')
    await pg.evaluate("window.scrollTo(0,0)"); await pg.wait_for_timeout(400); svg=pg.locator('main svg').first; bb=await svg.bounding_box()
    await r.hl(None,{'x':bb['x'],'y':bb['y'],'width':bb['width']*0.78,'height':bb['height']},1.0)
    await r.goto_el(pg.locator('main svg').first,1.5); await r.wait(5.0)
async def a_unc2(r,pg,S):
    await r.say('POINT ESTIMATE  vs  PREDICTIVE DISTRIBUTION')
    bb=await pg.locator('main svg').first.bounding_box()
    await r.hl(None,{'x':bb['x']+bb['width']*0.78,'y':bb['y'],'width':bb['width']*0.22,'height':bb['height']},1.0)
    await r.move(bb['x']+bb['width']*0.88,bb['y']+bb['height']*0.45,1.5); await r.wait(5.0)
async def a_unc3(r,pg,S):
    await pg.evaluate("window.scrollTo(0,0)"); await pg.wait_for_timeout(300); await r.say('A 90% INTERVAL IS NOT A GUARANTEE'); tb=pg.locator('table').first; await r.hl(tb,hold=1.0)
    await r.goto_el(pg.locator('table tr').nth(1),1.0); await r.wait(3.0); await r.goto_el(pg.locator('table tr').nth(2),1.0); await r.wait(2.0)
async def a_unc4(r,pg,S):
    await r.say('WARNINGS ARE NOT APPLIED AS A CORRECTION'); n=pg.locator('.notice').filter(has_text='Data-quality flags').first
    await r.hl(n,hold=1.0); await r.goto_el(n,1.2); await r.wait(5.0); await r.hl(); await r.say()
async def a_expl(r,pg,S):
    await r.say('EXPLANATION · TERM BY TERM')
    h=pg.get_by_role('heading',name='Why this forecast?'); await r.center(h); await pg.evaluate("window.scrollBy(0,250)"); await pg.wait_for_timeout(400)
    a=await h.bounding_box(); e=pg.get_by_text('Share of predictive variance due to parameter uncertainty').first; b=await e.bounding_box()
    await r.hl(None,{'x':a['x']-10,'y':a['y']-6,'width':900,'height':b['y']+b['height']-a['y']+12},1.0)
    await r.goto_el(pg.get_by_text('carbs_g',exact=True).first,1.4); await r.wait(4.0)
async def a_toggle(r,pg,S):
    await r.hl(); await r.say('MODEL B  ·  MODEL C  ·  SAME MEAL')
    btnB=pg.get_by_role('button',name='Model B').last; btnC=pg.get_by_role('button',name='Model C').last
    await r.click(btnB,1.0,3.0); await r.click(btnC,0.8,2.0); await r.say()
async def a_history(r,pg,S):
    await r.nav('History'); await r.say('NARROWER BANDS = MORE CERTAINTY, NOT NECESSARILY ACCURACY')
    await pg.get_by_text("How the twin's parameters changed").wait_for(timeout=10000)
    svg=pg.locator('main svg').first; await r.hl(svg,hold=1.0); await r.goto_el(svg,1.4); await r.wait(5.0); await r.hl(); await r.say()
async def a_insights(r,pg,S):
    await r.nav('Insights'); h=pg.get_by_role('heading',name='Forecast versus outcome'); await h.wait_for(timeout=10000); await r.center(h); await r.wait(1.0)
    tb=pg.locator('table').first; tx=await tb.inner_text(); check('insights outcome 75.0 / no / no','75.0' in tx and 'no / no' in tx,tx.replace('\n',' ')[:90])
    await r.say('OBSERVED 185 mg/dL: OUTSIDE THE 90% INTERVAL (126–184)'); await r.hl(None,{'x':(await h.bounding_box())['x'],'y':(await h.bounding_box())['y'],'width':1100,'height':(await tb.bounding_box())['y']+(await tb.bounding_box())['height']-(await h.bounding_box())['y']},1.0)
    await r.wait(7.0); await r.hl(); await r.say()
    await pg.evaluate("window.scrollTo(0,0)"); await r.wait(1.5); svg=pg.locator('main svg').first; await r.hl(svg,hold=1.0); await r.wait(6.0); await r.hl()
async def a_logout(r,pg,S):
    await r.say(); await r.nav('Settings'); await r.hl(pg.locator('main').get_by_role('button',name='Log out').first,hold=1.0)
    await r.click(pg.locator('main').get_by_role('button',name='Log out').first,1.0,0.5); await r.hl(); await badge(r,False); await r.wait(2.0)
async def a_acct2(r,pg,S):
    await pg.goto(BASE+'#/login'); await r.wait(1.2); await r.click(pg.get_by_text('Create one').first,1.0,1.2)
    await r.type(pg.get_by_label('Full name'),'Second Account',0.7,60); await r.type(pg.get_by_label('Email address'),'presenter-b@example.com',0.7,60)
    await r.type(pg.locator('input[name=Password]'),'demo-passphrase-2027',0.7,60); await r.type(pg.get_by_role('textbox',name='Confirm password'),'demo-passphrase-2027',0.7,60)
    await r.click(pg.get_by_role('checkbox'),0.7,0.3); await r.click(pg.get_by_role('button',name='Create account'),0.8,0.5)
    await pg.wait_for_url(re.compile(r'#/app'),timeout=15000); await r.wait(1.0); await badge(r)
    await r.nav('Settings'); c=pg.get_by_text('You have no twins yet').first; await c.wait_for(timeout=10000)
    check('account 2 sees no twins',await c.count()==1)
    await r.say('SECOND ACCOUNT · NO ACCESS TO THE FIRST ACCOUNT\'S TWIN'); card=c.locator('xpath=ancestor::*[self::section or self::div][1]'); await r.hl(c.locator('xpath=..'),hold=1.0)
    await r.wait(4.0); await r.hl(); await r.say()

async def a_land_hero(r,pg,S):
    await badge(r,False); await r.say('GlycoTwin · Personalized Post-Meal Glucose Digital Twin')
    await r.goto_el(pg.get_by_text('database ok').first,1.8); await r.wait(5.5); await r.say()
async def a_land_product(r,pg,S):
    await r.click(pg.locator('#l-links').get_by_role('link',name='Product'),1.2,1.2)
    for i in range(3):
        await r.goto_el(pg.locator('.product-grid article').nth(i),1.4); await r.wait(3.8)
async def a_land_how(r,pg,S):
    await r.click(pg.locator('#l-links').get_by_role('link',name='How it works'),1.2,1.2)
    for i in range(5):
        await r.goto_el(pg.locator('.flow li').nth(i),1.2); await r.wait(3.2)
    await r.goto_el(pg.locator('.how .eq'),1.2); await r.wait(2.0)
async def a_land_research(r,pg,S):
    await r.click(pg.locator('#l-links').get_by_role('link',name='Research'),1.2,1.2)
    await r.goto_el(pg.locator('.research-grid h3').nth(1),1.5); await r.wait(5.0)
    await r.goto_el(pg.get_by_role('link',name='Launch App'),1.5); await r.wait(1.0)
async def a_register(r,pg,S):
    await r.click(pg.get_by_role('link',name='Launch App'),0.8,1.8)
    await r.click(pg.get_by_text('Create one').first,1.0,1.2)
    await r.type(pg.get_by_label('Full name'),'Demo Presenter',0.8,55)
    await r.type(pg.get_by_label('Email address'),'presenter-a@example.com',0.8,55)
    await r.type(pg.locator('input[name=Password]'),'demo-passphrase-2026',0.8,55)
    await r.type(pg.get_by_role('textbox',name='Confirm password'),'demo-passphrase-2026',0.8,55)
    await r.click(pg.get_by_role('checkbox'),0.8,0.4)
    await r.click(pg.get_by_role('button',name='Create account'),0.9,0.5)
    await pg.wait_for_url(re.compile(r'#/app'),timeout=15000); await r.wait(1.5)
async def a_unc2(r,pg,S):
    bb=await pg.locator('main svg').first.bounding_box()
    await r.say('PREDICTIVE DISTRIBUTION · THRESHOLD PROBABILITY')
    await r.hl(None,{'x':bb['x']+bb['width']*0.78,'y':bb['y'],'width':bb['width']*0.22,'height':bb['height']},1.0)
    await r.move(bb['x']+bb['width']*0.88,bb['y']+bb['height']*0.45,1.5); await r.wait(4.0)
    await r.say('A 90% INTERVAL IS NOT A GUARANTEE'); tb=pg.locator('table').first; await r.hl(tb,hold=1.0)
    await r.goto_el(pg.locator('table tr').nth(1),1.0); await r.wait(3.0); await r.goto_el(pg.locator('table tr').nth(2),1.0); await r.wait(2.0)
    n=pg.locator('.notice').filter(has_text='Data-quality flags').first; await r.hl(n,hold=1.0); await r.wait(4.0); await r.hl(); await r.say()
ACT={k[2:]:v for k,v in list(globals().items()) if k.startswith('a_')}

# ---------- chapter runner ----------
async def setup_app(path):
    async def f(r,pg):
        await pg.goto(BASE+path); await r.wait(2.5)
    return f
async def run_chapter(p,ch,beats,live,state_in=None,state_out=None,setup=None):
    b,ctx,pg,t1=await mk(p,state_in,video=True); r=R(p,ctx,pg); S={}
    log={'chapter':ch,'beats':{}}; t_first=None
    if live:
        await pg.goto(BASE); 
        if setup: await setup(r,pg)
        await r.wait(2.0)
    else:
        await pg.goto(SLIDES); await r.wait(1.0)
    on_slides=not live
    for bid,_,vis,text in beats:
        d=DUR[bid]; ts=time.monotonic(); 
        if t_first is None: t_first=ts-t1
        log['beats'][bid]=ts-t1
        if vis[0]=='slide':
            if not on_slides: await pg.goto(SLIDES); await r.wait(0.8); on_slides=True; ts=time.monotonic(); log['beats'][bid]=ts-t1
            await pg.evaluate("a=>show(a[0],a[1])",[vis[1],vis[2]])
        else:
            await ACT[vis[1]](r,pg,S)
            if os.environ.get('SHOTS'): await pg.wait_for_timeout(500); await pg.screenshot(path=f'/tmp/vid/shots/dbg_{bid}.png')
        need=ADELAY+d+PAD-(time.monotonic()-ts)
        if need>0: await r.page.wait_for_timeout(int(need*1000*SPEED if SPEED<1 else need*1000))
        elif live: print('  note: action overran narration by',round(-need,1),'s in',bid,flush=True)
    await r.wait(1.2); t_end=time.monotonic()-t1; log['t_first']=t_first; log['t_end']=t_end
    if state_out: await ctx.storage_state(path=state_out)
    vpath=None
    await ctx.close()
    if REC: vpath=await pg.video.path()
    await b.close(); log['video']=str(vpath) if vpath else None
    json.dump(log,open(f'/tmp/vid/build/ch{ch}.json','w'),indent=1); print('chapter',ch,'done',round(t_end-t_first,1),'s',flush=True)
    return log
async def main():
    only=[int(x) for x in os.environ.get('CHAPTERS','1,2,3,4,5,6,7,8').split(',')]
    SETUP={4:'#/app/home',5:'#/app/forecast',6:'#/app/forecast'}
    async with async_playwright() as p:
        for ch in only:
            beats=[b for b in B if b[1]==ch]; live=any(b[2][0]=='live' for b in beats)
            if ch==1: await run_chapter(p,ch,beats,True,None,'/tmp/vid/build/state.json')
            elif live: await run_chapter(p,ch,beats,True,'/tmp/vid/build/state.json',None,await setup_app(SETUP[ch]))
            else: await run_chapter(p,ch,beats,False)
    json.dump(CHECKS,open('/tmp/vid/build/checks_'+('_'.join(map(str,only)))+'.json','w'),indent=1)
asyncio.run(main())

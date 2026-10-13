import asyncio, time
from playwright.async_api import async_playwright
W,H=1920,940
CURSOR_JS="""
(()=>{ if(window.__ovl) return; window.__ovl=1;
 const mk=(id,css)=>{ let e=document.getElementById(id); if(!e){ e=document.createElement('div'); e.id=id; e.style.cssText=css; (document.documentElement||document.body).appendChild(e);} return e; };
 const curCss='position:fixed;z-index:2147483647;width:26px;height:26px;border-radius:50%;background:rgba(255,200,0,.55);border:3px solid #fff;box-shadow:0 0 0 2px #000,0 2px 8px #0008;pointer-events:none;transform:translate(-50%,-50%)';
 addEventListener('mousemove',e=>{const d=mk('curdot',curCss); d.style.left=e.clientX+'px'; d.style.top=e.clientY+'px';},true);
 addEventListener('mousedown',()=>{const d=mk('curdot',curCss); d.style.transform='translate(-50%,-50%) scale(.7)';},true);
 addEventListener('mouseup',()=>{const d=mk('curdot',curCss); d.style.transform='translate(-50%,-50%)';},true);
 addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');s.textContent='html,body,*{scroll-behavior:auto!important}';document.head.appendChild(s);});
 window.__say=(t)=>{ const c=mk('callbox','position:fixed;z-index:2147483646;left:50%;top:62px;transform:translateX(-50%);max-width:1500px;padding:16px 30px;border-radius:14px;background:rgba(10,20,35,.93);color:#fff;font:600 30px/1.3 Segoe UI,Arial,sans-serif;border:2px solid #5eead4;box-shadow:0 8px 30px #0008;display:none;text-align:center;letter-spacing:.2px'); if(!t){c.style.display='none';return;} c.textContent=t; c.style.display='block'; };
 window.__hl=(x,y,w,hh)=>{ const h=mk('hlbox','position:fixed;z-index:2147483645;border:5px solid #fbbf24;border-radius:12px;box-shadow:0 0 0 9999px rgba(0,0,0,.28);pointer-events:none;display:none;transition:all .35s'); if(x==null){h.style.display='none';return;} h.style.display='block'; h.style.left=(x-8)+'px';h.style.top=(y-8)+'px';h.style.width=(w+16)+'px';h.style.height=(hh+16)+'px'; };
 window.__badge=(t)=>{ const b=mk('badgebox','position:fixed;z-index:2147483644;right:18px;bottom:18px;padding:8px 16px;border-radius:10px;background:#7c2d12;color:#fff;font:700 20px Segoe UI,Arial,sans-serif;display:none;border:2px solid #fbbf24'); if(!t){b.style.display='none';return;} b.textContent=t; b.style.display='block'; };
})();
"""
class Rec:
    def __init__(s, p, ctx, page): s.p=p; s.ctx=ctx; s.page=page; s.x=960; s.y=540
    async def init(s):
        await s.page.add_init_script(CURSOR_JS)
    async def inject(s):
        await s.page.evaluate(CURSOR_JS)
    async def say(s,t=None):
        await s.page.evaluate("t=>window.__say&&window.__say(t)", t)
    async def wait(s,sec): await s.page.wait_for_timeout(int(sec*1000))
    async def move(s,x,y,dur=1.0):
        steps=max(8,int(dur*30)); x0,y0=s.x,s.y
        for i in range(1,steps+1):
            t=i/steps; t=t*t*(3-2*t)
            await s.page.mouse.move(x0+(x-x0)*t,y0+(y-y0)*t)
            await s.page.wait_for_timeout(int(dur*1000/steps))
        s.x,s.y=x,y
    async def goto_el(s,loc,dur=1.0):
        await loc.scroll_into_view_if_needed(); b=await loc.bounding_box()
        await s.move(b['x']+b['width']/2,b['y']+b['height']/2,dur)
    async def click(s,loc,dur=1.0,pause=0.4):
        await s.goto_el(loc,dur); await s.wait(0.2); await s.page.mouse.down(); await s.wait(0.1); await s.page.mouse.up(); await s.wait(pause)
    async def type(s,loc,text,dur=0.8,delay=90):
        await s.click(loc,dur,0.1); await loc.fill(""); await loc.press_sequentially(text,delay=delay); await s.wait(0.3)

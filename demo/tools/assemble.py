import json, os, re, subprocess, sys, numpy as np, soundfile as sf
sys.path.insert(0,'/tmp/vid')
from script import B, CH
ADELAY=0.3; SR=24000; BUILD='/tmp/vid/build'; DUR=json.load(open(f'{BUILD}/durations.json'))
chs=sorted({b[1] for b in B}); off=0.0; segs=[]; marks=[]; subs=[]; placed=[]
audio=np.zeros(int(60*30*SR),dtype=np.float32)
def sh(cmd):
    r=subprocess.run(cmd,shell=True,capture_output=True,text=True)
    if r.returncode: print(r.stderr[-2000:]); raise SystemExit(1)
def ts(t): h=int(t//3600); m=int(t%3600//60); s=t%60; return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.',',')
MAXC=112
def cues(text):
    parts=[]
    for s_ in [x.strip() for x in re.split(r'(?<=[.!?])\s+',text) if x.strip()]:
        if len(s_)<=MAXC: parts.append(s_); continue
        bits=re.split(r'(?<=[,;:])\s+',s_); cur=''
        for bt in bits:
            if cur and len(cur)+1+len(bt)>MAXC: parts.append(cur); cur=bt
            else: cur=(cur+' '+bt).strip()
        if cur: parts.append(cur)
    # hard-split anything still too long, at the word nearest the middle
    fixed=[]
    for p in parts:
        while len(p)>MAXC:
            ws=p.split(); acc=0; k=0
            for i,wd in enumerate(ws):
                acc+=len(wd)+1
                if acc>=len(p)/2: k=i+1; break
            fixed.append(' '.join(ws[:k])); p=' '.join(ws[k:])
        fixed.append(p)
    parts=fixed
    # merge tiny cues forward
    out=[]
    for p in parts:
        if out and len(out[-1])<28 and len(out[-1])+1+len(p)<=MAXC: out[-1]+=' '+p
        else: out.append(p)
    return out
def wrap(t,w=60):
    words=t.split(); lines=[]; cur=''
    for x in words:
        if cur and len(cur)+1+len(x)>w: lines.append(cur); cur=x
        else: cur=(cur+' '+x).strip()
    lines.append(cur)
    if len(lines)>2: lines=[' '.join(lines[:len(lines)//2+1]),' '.join(lines[len(lines)//2+1:])]
    return lines
for n in chs:
    log=json.load(open(f'{BUILD}/ch{n}.json')); t0=log['t_first']; t1=log['t_end']; L=t1-t0
    seg=f'{BUILD}/seg{n}.mp4'
    sh(f'ffmpeg -y -v error -ss {t0:.3f} -t {L:.3f} -i "{log["video"]}" -vf "fps=30,scale=1920:940:flags=lanczos,pad=1920:1080:0:0:black,format=yuv420p" -c:v libx264 -preset medium -crf 18 -an {seg}')
    segs.append(seg); marks.append((off,off+L,CH[n]))
    for bid,_,_,text in [b for b in B if b[1]==n]:
        a0=off+(log['beats'][bid]-t0)+ADELAY; w,sr=sf.read(f'{BUILD}/{bid}.wav'); assert sr==SR
        i=int(a0*SR); audio[i:i+len(w)]+=w.astype(np.float32); placed.append((bid,a0,a0+len(w)/SR))
        parts=cues(text); tot=sum(len(p) for p in parts); c=a0; d=len(w)/SR
        for p in parts:
            dd=d*len(p)/tot; subs.append((c,c+dd,p)); c+=dd
    off+=L
total=off
audio=audio[:int((total+0.5)*SR)]; peak=float(np.max(np.abs(audio))); print('mixed peak',round(peak,3),'duration',round(total/60,2),'min')
if peak>0.98: audio*=0.95/peak
sf.write(f'{BUILD}/narration_mix.wav',audio,SR)
with open(f'{BUILD}/subs.srt','w',encoding='utf-8') as f:
    for i,(a,b,t) in enumerate(subs,1):
        end=b-0.04
        if i<len(subs): end=min(max(end,a+0.8),subs[i][0]-0.03)
        f.write(f"{i}\n{ts(a)} --> {ts(end)}\n"+"\n".join(wrap(t))+"\n\n")
with open(f'{BUILD}/chapters.txt','w',encoding='utf-8') as f:
    f.write(';FFMETADATA1\ntitle=GlycoTwin: personalized post-meal glucose Digital Twin (research prototype)\n')
    for a,b,t in marks: f.write(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(a*1000)}\nEND={int(b*1000)}\ntitle={t}\n")
with open(f'{BUILD}/concat.txt','w') as f:
    for s_ in segs: f.write(f"file '{s_}'\n")
sh(f'ffmpeg -y -v error -f concat -safe 0 -i {BUILD}/concat.txt -c copy {BUILD}/video_nosub.mp4')
# Build an .ass with an explicit 1920x1080 canvas and style. The plain `subtitles=` filter with
# force_style mis-scales the font against the video's real resolution; an .ass with its own
# PlayResX/Y avoids that (verified by rendering sample frames).
sh(f'ffmpeg -y -v error -i {BUILD}/subs.srt {BUILD}/subs_raw.ass')
ass=open(f'{BUILD}/subs_raw.ass',encoding='utf-8').read()
ass=re.sub(r'PlayResX:.*','PlayResX: 1920',ass); ass=re.sub(r'PlayResY:.*','PlayResY: 1080',ass)
if 'PlayResX' not in ass: ass=ass.replace('[Script Info]','[Script Info]\nPlayResX: 1920\nPlayResY: 1080')
ass=re.sub(r'Style: Default,.*','Style: Default,DejaVu Sans,38,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,70,70,26,1',ass)
open(f'{BUILD}/subs.ass','w',encoding='utf-8').write(ass)
for name,crf,ab in [('GlycoTwin_demo_subtitled.mp4',22,'160k'),('GlycoTwin_demo_subtitled_compact.mp4',28,'128k')]:
    sh(f'ffmpeg -y -v error -i {BUILD}/video_nosub.mp4 -i {BUILD}/narration_mix.wav -i {BUILD}/chapters.txt -map 0:v -map 1:a -map_metadata 2 -vf "ass={BUILD}/subs.ass" -c:v libx264 -preset slow -crf {crf} -pix_fmt yuv420p -af "loudnorm=I=-16:TP=-1.5:LRA=11" -c:a aac -b:a {ab} -ar 48000 -metadata:s:a:0 language=eng -movflags +faststart /tmp/vid/{name}')
    print('wrote',name,round(os.path.getsize('/tmp/vid/'+name)/1e6,1),'MB',flush=True)
json.dump({'chapters':[(round(a,1),round(b,1),t) for a,b,t in marks],'beats':[(b,round(x,2),round(y,2)) for b,x,y in placed],'total_s':total,'cues':len(subs)},open(f'{BUILD}/timeline.json','w'),indent=1)

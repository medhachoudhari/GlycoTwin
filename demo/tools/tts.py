import sys, json, time, numpy as np, soundfile as sf
sys.path.insert(0,'/tmp/vid')
from script import B, tts_text
from kokoro_onnx import Kokoro
VOICE=sys.argv[1] if len(sys.argv)>1 else 'hf_alpha'; SPEED=float(sys.argv[2]) if len(sys.argv)>2 else 0.82
k=Kokoro('kokoro.onnx','voices.bin')
meta={}
for bid,ch,vis,text in B:
    a,sr=k.create(tts_text(text),voice=VOICE,speed=SPEED,lang='en-us')
    a=np.asarray(a,dtype=np.float32)
    # trim leading/trailing near-silence, add 0.25s tail
    thr=0.003; idx=np.where(np.abs(a)>thr)[0]
    if len(idx): a=a[max(0,idx[0]-int(0.05*sr)):idx[-1]+int(0.15*sr)]
    sf.write(f'build/{bid}.wav',a,sr); meta[bid]=len(a)/sr
    print(bid,round(meta[bid],1),round(len(text.split())/meta[bid]*60),'wpm',flush=True)
json.dump(meta,open('build/durations.json','w'))
tot=sum(meta.values()); print('TOTAL',round(tot/60,2),'min', round(sum(len(b[3].split()) for b in B)/tot*60),'wpm')

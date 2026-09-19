from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
from typing import Any
import numpy as np
import soundfile as sf

MODEL_ID='iic/speech_eres2netv2_sv_zh-cn_16k-common'
DEMOGRAPHIC_MODEL_ID='DubRoom/ERes2NetV2-AISHELL3-R1'
SR=16000

def read_json(p:Path)->dict[str,Any]:
    try:
        v=json.loads(p.read_text(encoding='utf-8-sig')); return v if isinstance(v,dict) else {}
    except Exception: return {}

def write_json(p:Path,v:dict[str,Any]):
    p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(p.suffix+'.tmp'); t.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8'); t.replace(p)

def norm(x):
    x=np.asarray(x,dtype=np.float32).reshape(-1); n=float(np.linalg.norm(x)); return x/n if n>1e-8 else x

def overlap(turn,turns):
    s=float(turn.get('start') or 0); e=float(turn.get('end') or s); sp=str(turn.get('speaker') or ''); total=0.0
    for o in turns:
        if o is turn or str(o.get('speaker') or '')==sp: continue
        os_=float(o.get('start') or 0); oe=float(o.get('end') or os_); total+=max(0.0,min(e,oe)-max(s,os_))
    return total

def clips(audio,turns,speaker):
    out=[]
    for t in turns:
        if str(t.get('speaker') or '')!=speaker: continue
        s=max(0.0,float(t.get('start') or 0)); e=max(s,float(t.get('end') or s)); d=e-s
        if d<1.5 or overlap(t,turns)>min(0.30,d*0.12): continue
        if d>8.0:
            c=(s+e)/2; s=max(s,c-4.0); e=s+8.0; d=8.0
        a=max(0,round(s*SR)); b=min(audio.size,round(e*SR)); c=np.asarray(audio[a:b],dtype=np.float32)
        if c.size<int(1.5*SR): continue
        rms=float(np.sqrt(np.mean(c*c)))
        if rms<0.002: continue
        q=(1.0 if 2.5<=d<=7.0 else 0.82)*(0.55+0.45*min(1.0,rms/0.02))
        out.append((q,d,s,e,c))
    out.sort(key=lambda x:(x[0],x[1]),reverse=True)
    chosen=[]; total=0.0
    for item in out:
        if len(chosen)>=6: break
        if chosen and total+item[1]>32: continue
        chosen.append(item); total+=item[1]
    return chosen

def emb(model,path:Path):
    r=model.generate(input=str(path),disable_pbar=True)
    if not r or r[0].get('spk_embedding') is None: raise RuntimeError('spk_embedding missing')
    v=r[0]['spk_embedding']
    try:
        import torch
        if isinstance(v,torch.Tensor): v=v.detach().cpu().numpy()
    except Exception: pass
    return norm(v)

def avg_probs(model,values):
    m=np.stack(values); p=np.asarray(model.predict_proba(m),dtype=float).mean(axis=0); cls=[str(x) for x in model.classes_]; i=int(np.argmax(p)); return cls[i],float(p[i]),{cls[j]:float(p[j]) for j in range(len(cls))}

def age_map(label):
    return {'A':('child',['child']),'B':('young_adult',['teen','young_adult']),'C':('adult',['adult']),'D':('adult',['adult','elderly'])}.get(label,('unknown',[]))

def main():
    ap=argparse.ArgumentParser();
    for x in ('input','diarization-json','packages','cache-dir','head','analysis-root','output'): ap.add_argument('--'+x,required=True)
    ap.add_argument('--device',default='cuda:0'); a=ap.parse_args()
    packages=Path(a.packages); sys.path.insert(0,str(packages)); os.environ.setdefault('MODELSCOPE_CACHE',str(Path(a.cache_dir))); os.environ.setdefault('TOKENIZERS_PARALLELISM','false')
    from funasr import AutoModel
    try:
        import torch; device=a.device if a.device.startswith('cuda') and torch.cuda.is_available() else 'cpu'
    except Exception: device='cpu'
    model=AutoModel(model=MODEL_ID,device=device,disable_update=True,hub='ms')
    man=read_json(Path(getattr(a,'diarization_json'))); turns=[x for x in man.get('turns') or [] if isinstance(x,dict)]; speakers=sorted({str(x.get('speaker') or '') for x in turns if str(x.get('speaker') or '')})
    audio,sr=sf.read(a.input,dtype='float32',always_2d=True); audio=np.asarray(audio[:,0],dtype=np.float32)
    if int(sr)!=SR:
        tx=np.linspace(0,1,max(1,round(audio.size*SR/int(sr))),endpoint=False); ox=np.linspace(0,1,audio.size,endpoint=False); audio=np.interp(tx,ox,audio).astype(np.float32)
    root=Path(getattr(a,'analysis_root'))/'speaker-embeddings'; (root/'clips').mkdir(parents=True,exist_ok=True); (root/'centroids').mkdir(parents=True,exist_ok=True)
    head=None
    try:
        import joblib; hp=Path(a.head); head=joblib.load(hp) if hp.is_file() else None
        if not isinstance(head,dict) or head.get('embedding_model')!=MODEL_ID: head=None
    except Exception: head=None
    centroids={}; embeds={}; meta={}
    for sp in speakers:
        vals=[]; secs=0.0
        for i,item in enumerate(clips(audio,turns,sp)):
            q,d,s,e,c=item; cp=root/'clips'/f'{sp}-{i:02d}.wav'; sf.write(cp,c,SR,subtype='PCM_16')
            try: vals.append(emb(model,cp)); secs+=d
            except Exception: pass
        if not vals: continue
        cen=norm(np.mean(np.stack(vals),axis=0)); centroids[sp]=cen; embeds[sp]=vals; p=root/'centroids'/f'{sp}.npy'; np.save(p,cen)
        meta[sp]={'speaker':sp,'speaker_embedding_model':MODEL_ID,'speaker_embedding_dim':int(cen.size),'speaker_embedding_samples':len(vals),'speaker_embedding_seconds':round(secs,3),'speaker_embedding_path':str(p),'speaker_embedding_device':device,'speaker_embedding_revision':'eres2netv2-chinese-r1'}
    candidates={s:[] for s in centroids}; ss=sorted(centroids)
    for i,l in enumerate(ss):
        for r in ss[i+1:]:
            score=float(np.dot(centroids[l],centroids[r]))
            if score<0.68: continue
            rec='high' if score>=0.80 else 'possible'; candidates[l].append({'speaker':r,'cosine_similarity':round(score,4),'recommendation':rec}); candidates[r].append({'speaker':l,'cosine_similarity':round(score,4),'recommendation':rec})
    profiles=[]
    for sp in sorted(meta):
        p=dict(meta[sp]); p['same_speaker_candidates']=sorted(candidates.get(sp,[]),key=lambda x:x['cosine_similarity'],reverse=True)[:5]; vals=embeds[sp]
        if head and len(vals)>=3:
            gl,gc,gp=avg_probs(head['gender_model'],vals); al,ac,aprob=avg_probs(head['age_model'],vals); ag,acands=age_map(al)
            p.update({'demographic_model':DEMOGRAPHIC_MODEL_ID,'demographic_model_language':'zh','demographic_revision':str(head.get('revision') or 'aishell3-r1'),'demographic_samples_analyzed':len(vals),'meta_gender':gl if gl in {'male','female'} and gc>=0.72 else 'uncertain','meta_gender_confidence':round(gc,4) if gc>=0.72 else 0.0,'meta_gender_probabilities':{k:round(v,4) for k,v in gp.items()},'meta_age_group':ag if ag!='unknown' and ac>=0.52 else 'unknown','meta_age_confidence':round(ac,4) if ag!='unknown' and ac>=0.52 else 0.0,'raw_age_bucket':al if ag!='unknown' and ac>=0.52 else 'NONE','age_group_candidates':acands if ag!='unknown' and ac>=0.52 else [],'meta_age_probabilities':{k:round(v,4) for k,v in aprob.items()}})
        else:
            p.update({'demographic_model':'','demographic_model_language':'','demographic_revision':'','demographic_samples_analyzed':0,'demographic_status':'head_missing' if not head else 'insufficient_samples'})
        profiles.append(p)
    write_json(Path(a.output),{'status':'completed','model':MODEL_ID,'revision':'eres2netv2-chinese-r1','device':device,'speaker_count':len(speakers),'analyzed_speaker_count':len(profiles),'demographic_head_loaded':bool(head),'speaker_profiles':profiles})
if __name__=='__main__': main()

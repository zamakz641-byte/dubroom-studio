from __future__ import annotations
import argparse, json, shutil, subprocess, sys, time, types
from pathlib import Path
from typing import Any

def parse_args():
    p=argparse.ArgumentParser()
    p.add_argument('--input',required=True); p.add_argument('--output-dir',required=True)
    p.add_argument('--output',required=True); p.add_argument('--progress-file',required=True)
    p.add_argument('--model-path',required=True); p.add_argument('--source-path',required=True)
    p.add_argument('--device',choices=('auto','cpu','cuda'),default='auto')
    p.add_argument('--batch-size',type=int,default=4); p.add_argument('--hop-seconds',type=float,default=4.0)
    p.add_argument('--shared-site-packages',action='append',default=[])
    p.add_argument('--outer-chunk-seconds',type=float,default=120.0)
    p.add_argument('--outer-overlap-seconds',type=float,default=4.0)
    return p.parse_args()

def write_json(path,payload):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8'); tmp.replace(path)

def prepare_48k(src,out):
    import soundfile as sf
    if int(sf.info(str(src)).samplerate)==48000: return src,False
    ff=shutil.which('ffmpeg')
    if not ff: raise RuntimeError('FFmpeg requis pour le resampling 48 kHz streaming')
    dst=out/'.bandit-turbo-input-48k.wav'
    r=subprocess.run([ff,'-hide_banner','-loglevel','error','-y','-i',str(src),'-vn','-ar','48000','-c:a','pcm_s16le',str(dst)],capture_output=True,text=True,encoding='utf-8',errors='replace')
    if r.returncode!=0 or not dst.is_file(): raise RuntimeError('FFmpeg 48 kHz a echoue: '+r.stderr[-1200:])
    return dst,True

def main():
    a=parse_args()
    for raw in a.shared_site_packages:
        p=str(Path(raw).resolve())
        if Path(p).is_dir() and p not in sys.path: sys.path.append(p)
    import torch, torchaudio as ta, soundfile as sf

    # Safe Turbo V2.2: stability first. Keep FP32 and disable the global TF32 experiment.
    try: torch.set_float32_matmul_precision('highest')
    except Exception: pass
    try: torch.backends.cuda.matmul.allow_tf32=False
    except Exception: pass
    try: torch.backends.cudnn.allow_tf32=False
    except Exception: pass
    try: torch.backends.cudnn.benchmark=False
    except Exception: pass

    if 'torchaudio.io' not in sys.modules:
        m=types.ModuleType('torchaudio.io'); m.StreamReader=object; sys.modules['torchaudio.io']=m
    l=types.ModuleType('pytorch_lightning'); l.LightningModule=torch.nn.Module; sys.modules.setdefault('pytorch_lightning',l)
    source_root=Path(a.source_path).resolve()
    if str(source_root) not in sys.path: sys.path.insert(0,str(source_root))
    from src.models.bandit.bandit import Bandit
    from src.system.inference_handler import StandardTensorChunkedInferenceHandler

    device=a.device
    if device=='auto': device='cuda' if torch.cuda.is_available() else 'cpu'
    if device=='cuda' and not torch.cuda.is_available(): raise RuntimeError('CUDA demande mais indisponible')
    out=Path(a.output_dir).resolve(); out.mkdir(parents=True,exist_ok=True)
    write_json(a.progress_file,{'progress':4,'message':'Cinema Turbo: chargement Bandit'})

    model=Bandit(in_channels=1,stems=['speech','music','sfx'],band_type='musical',n_bands=64,normalize_channel_independently=False,treat_channel_as_feature=True,n_sqm_modules=8,emb_dim=128,rnn_dim=256,bidirectional=True,rnn_type='GRU',mlp_dim=512,hidden_activation='Tanh',complex_mask=True,use_freq_weights=True,n_fft=2048,win_length=2048,hop_length=512,window_fn='hann_window',center=True,normalized=True,pad_mode='reflect',onesided=True,fs=48000)
    ckpt=torch.load(a.model_path,map_location='cpu',weights_only=False)
    raw=ckpt.get('state_dict',ckpt); state={}
    for k,v in raw.items():
        if k.startswith('model.'): state[k[6:]]=v
        elif not k.startswith(('loss_handler.','metric_handler.')): state[k]=v
    incompatible=model.load_state_dict(state,strict=False)
    if len(incompatible.missing_keys)>8: raise RuntimeError(f'Checkpoint Bandit incompatible: {incompatible.missing_keys[:8]}')
    model.to(device).eval()

    source,temp=prepare_48k(Path(a.input).resolve(),out); sr=48000
    outer=max(30.0,min(180.0,float(a.outer_chunk_seconds))); context_s=max(2.0,min(8.0,float(a.outer_overlap_seconds)))
    core_frames=max(1,int(outer*sr)); context_frames=max(1,int(context_s*sr)); hop=max(1.0,min(4.0,float(a.hop_seconds)))
    max_batch=max(1,min(12,int(a.batch_size)))
    candidates=[]
    for b in (max_batch,4,2,1):
        if b<=max_batch and b not in candidates: candidates.append(b)

    paths={n:out/n for n in ('vocals.wav','bed.wav','music.wav','sfx.wav')}
    selected=None; handler=None; started=time.monotonic(); processed=0
    try:
        with sf.SoundFile(str(source),'r') as f:
            total=int(len(f)); channels=int(f.channels)
            if total<=0: raise RuntimeError('Audio vide')
            writers={n:sf.SoundFile(str(p),'w',samplerate=sr,channels=channels,subtype='PCM_16',format='WAV') for n,p in paths.items()}
            try:
                pos=0
                with torch.inference_mode():
                    while pos<total:
                        end=min(total,pos+core_frames); rs=max(0,pos-context_frames); re=min(total,end+context_frames)
                        f.seek(rs); arr=f.read(re-rs,dtype='float32',always_2d=True)
                        mix=torch.from_numpy(arr.T.copy()).unsqueeze(0).to(device)
                        if handler is None:
                            last=None
                            for batch in candidates:
                                try:
                                    write_json(a.progress_file,{'progress':9,'message':f'Cinema Turbo: test batch {batch} · hop {hop:g}s'})
                                    h=StandardTensorChunkedInferenceHandler(chunk_size_seconds=8.0,hop_size_seconds=hop,inference_batch_size=batch,fs=sr).to(device)
                                    output=h(mix,model);
                                    if device=='cuda': torch.cuda.synchronize()
                                    handler=h; selected=batch; last=None; break
                                except Exception as exc:
                                    oom='out of memory' in str(exc).lower() or exc.__class__.__name__.lower().endswith('outofmemoryerror')
                                    if device=='cuda' and oom:
                                        last=exc
                                        try: torch.cuda.empty_cache()
                                        except Exception: pass
                                        continue
                                    raise
                            if handler is None: raise RuntimeError('Aucun batch Bandit ne tient en VRAM') from last
                        else:
                            output=handler(mix,model)
                            if device=='cuda' and processed==0: torch.cuda.synchronize()
                        original=mix[0]; speech=output['estimates']['speech']['audio'][0]; music=output['estimates']['music']['audio'][0]; sfx=output['estimates']['sfx']['audio'][0]
                        left=pos-rs; wanted=end-pos; right=left+wanted
                        stems={'vocals.wav':speech[...,left:right], 'bed.wav':original[...,left:right]-speech[...,left:right], 'music.wav':music[...,left:right], 'sfx.wav':sfx[...,left:right]}
                        for n,t in stems.items(): writers[n].write(t.detach().float().cpu().T.numpy())
                        processed=end
                        elapsed=max(0.001,time.monotonic()-started); audio_s=processed/sr; speed=audio_s/elapsed; remain=(total-processed)/sr; eta=remain/max(speed,0.001)
                        pct=12+int(84*processed/total)
                        write_json(a.progress_file,{'progress':min(96,pct),'message':f'Cinema Turbo · batch {selected} · hop {hop:g}s · {speed:.2f}x temps reel · ETA {eta/60:.1f} min'})
                        del output,mix,original,speech,music,sfx,stems
                        pos=end
            finally:
                for w in writers.values(): w.close()
    finally:
        if temp:
            try: source.unlink(missing_ok=True)
            except OSError: pass

    elapsed=max(0.001,time.monotonic()-started); duration=processed/sr; speed=duration/elapsed
    result={'status':'ready','model':'bandit-v2-dnr3-multilingual','device':device,'vocals':str(paths['vocals.wav']),'bed':str(paths['bed.wav']),'music':str(paths['music.wav']),'sfx':str(paths['sfx.wav']),'elapsed_seconds':round(elapsed,3),'speed_x':round(speed,3),'turbo':{'batch':selected,'hop_seconds':hop,'outer_chunk_seconds':outer,'tf32':False},'runtime':{'torch':torch.__version__,'torchaudio':ta.__version__,'cuda_available':bool(torch.cuda.is_available()),'device_name':torch.cuda.get_device_name(0) if device=='cuda' else 'CPU'}}
    write_json(a.output,result); write_json(a.progress_file,{'progress':99,'message':f'Cinema Turbo termine · {speed:.2f}x temps reel'})

if __name__=='__main__': main()

import {useEffect,useState} from "react";
import {ArrowRight,Check,Clipboard,CloudDownload,FileVideo,HardDrive,Link2,LoaderCircle,Search,ShieldCheck,X,Youtube} from "lucide-react";
import {api} from "@/lib/api";
import {useI18n} from "@/i18n";
import type {EngineRecord,YouTubeDownload,YouTubeInfo} from "@/types";

type Props={engine:EngineRecord|null;onClose:()=>void;onLocal:()=>Promise<void>;onInstall:()=>Promise<void>;onReady:(path:string,title:string)=>Promise<void>};

export function ImportHub({engine,onClose,onLocal,onInstall,onReady}:Props){
  const{t}=useI18n();
  const[tab,setTab]=useState<"local"|"youtube">("youtube");
  const[url,setUrl]=useState("");const[info,setInfo]=useState<YouTubeInfo|null>(null);const[download,setDownload]=useState<YouTubeDownload|null>(null);
  const[busy,setBusy]=useState(false);const[installing,setInstalling]=useState(false);const[localReady,setLocalReady]=useState(false);const[error,setError]=useState("");
  const runtimeReady=localReady||engine?.installation.status==="ready";
  const active=Boolean(download&&["queued","downloading","processing"].includes(download.status));

  useEffect(()=>{
    if(!download||!["queued","downloading","processing"].includes(download.status))return;
    let alive=true;
    const timer=setInterval(()=>api.youtubeDownload(download.id).then(async next=>{
      if(!alive)return;setDownload(next);
      if(next.status==="completed"&&next.path){setBusy(true);try{await onReady(next.path,next.title||info?.title||"YouTube video");onClose()}catch(reason){setError(message(reason));setBusy(false)}}
      if(next.status==="failed"){setError(next.error||next.message);setBusy(false)}
      if(next.status==="cancelled")setBusy(false);
    }).catch(reason=>alive&&setError(message(reason))),800);
    return()=>{alive=false;clearInterval(timer)};
  },[download?.id,download?.status]);

  const inspect=async()=>{if(!url.trim())return;setBusy(true);setError("");try{setInfo(await api.inspectYouTube(url.trim()))}catch(reason){setInfo(null);setError(message(reason))}finally{setBusy(false)}};
  const paste=async()=>{try{setUrl(await navigator.clipboard.readText());setInfo(null);setError("")}catch{setError(t("import.clipboardDenied"))}};
  const install=async()=>{
    setInstalling(true);setError("");
    try{await onInstall();const deadline=Date.now()+300000;while(Date.now()<deadline){await new Promise(resolve=>setTimeout(resolve,1200));if((await api.youtubeRuntime()).ready){setLocalReady(true);return}const current=(await api.engines()).find(item=>item.id==="yt-dlp");if(current?.installation.status==="failed")throw new Error(current.installation.message)}throw new Error(t("import.installTimeout"))}
    catch(reason){setError(message(reason))}finally{setInstalling(false)}
  };
  const start=async()=>{if(!info)return;setBusy(true);setError("");try{setDownload(await api.startYouTubeDownload(info.webpage_url,info.title))}catch(reason){setError(message(reason));setBusy(false)}};

  return <div className="fixed inset-0 z-[90] grid place-items-center bg-black/70 p-8 backdrop-blur-sm" onMouseDown={()=>!active&&onClose()}>
    <section className="grid h-[min(760px,90vh)] w-[min(1040px,92vw)] grid-rows-[80px_56px_minmax(0,1fr)] overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl" onMouseDown={event=>event.stopPropagation()}>
      <header className="flex items-center gap-4 border-b border-line px-6">
        <span className="grid size-11 place-items-center rounded-xl bg-accent text-white"><CloudDownload/></span>
        <div className="min-w-0 flex-1"><span className="ui-kicker">{t("import.kicker")}</span><h1 className="mt-1 text-[20px] font-semibold">{t("import.title")}</h1><p className="truncate text-[10px] text-muted">{t("import.body")}</p></div>
        <button className="ui-icon-button" disabled={active} onClick={onClose}><X/></button>
      </header>
      <nav className="flex border-b border-line px-6">
        <Tab active={tab==="youtube"} icon={Youtube} label={t("import.youtube")} onClick={()=>setTab("youtube")}/>
        <Tab active={tab==="local"} icon={FileVideo} label={t("import.local")} onClick={()=>setTab("local")}/>
      </nav>
      <main className="min-h-0 overflow-auto p-6">
        {tab==="local"?<LocalImport t={t} onLocal={onLocal}/>:<div className="mx-auto grid max-w-4xl gap-4">
          {!runtimeReady?<RuntimeGate installing={installing} failed={engine?.installation.status==="failed"} t={t} onInstall={install}/>:active?<DownloadProgress download={download!} onCancel={async()=>setDownload(await api.cancelYouTubeDownload(download!.id))}/>:<>
            <label className="ui-panel flex items-center gap-3 p-3"><Link2 className="size-4 text-muted"/><input autoFocus className="min-w-0 flex-1 bg-transparent text-[12px] outline-none" value={url} onChange={event=>{setUrl(event.target.value);setInfo(null);setError("")}} onKeyDown={event=>event.key==="Enter"&&void inspect()} placeholder="https://www.youtube.com/watch?v=…"/><button className="ui-button" onClick={()=>void paste()}><Clipboard/>{t("import.paste")}</button><button className="ui-button ui-button-primary" disabled={busy||!url.trim()} onClick={()=>void inspect()}>{busy?<LoaderCircle className="animate-spin"/>:<Search/>}{t("import.inspect")}</button></label>
            {info?<VideoPreview info={info} busy={busy} t={t} onStart={start}/>:<div className="ui-panel grid min-h-72 place-items-center text-center"><div><Youtube className="mx-auto size-8 text-muted"/><strong className="mt-4 block text-[13px]">{t("import.waitingLink")}</strong><p className="mt-1 text-[10px] text-muted">{t("import.waitingBody")}</p></div></div>}
          </>}
          <div className="flex items-center gap-3 rounded-lg border border-line bg-canvas p-3 text-[10px] text-muted"><ShieldCheck className="size-4 text-success"/><span>{t("import.rightsBody")}</span></div>
        </div>}
        {error&&<div className="mx-auto mt-4 max-w-4xl rounded-lg bg-danger/10 p-3 text-[10px] text-danger">{error}</div>}
      </main>
    </section>
  </div>;
}

function Tab({active,icon:Icon,label,onClick}:{active:boolean;icon:typeof Youtube;label:string;onClick:()=>void}){return <button className={`relative flex items-center gap-2 px-5 text-[11px] ${active?"text-foreground":"text-muted"}`} onClick={onClick}><Icon className="size-4"/>{label}{active&&<i className="absolute inset-x-3 bottom-0 h-0.5 bg-accent"/>}</button>}
function LocalImport({t,onLocal}:{t:(key:string)=>string;onLocal:()=>Promise<void>}){return <div className="grid h-full min-h-96 place-items-center rounded-xl border border-dashed border-line bg-canvas/40 text-center"><div><span className="mx-auto grid size-16 place-items-center rounded-2xl border border-line bg-raised text-accent"><FileVideo className="size-7"/></span><small className="ui-kicker mt-5 block">{t("import.localKicker")}</small><h2 className="mt-2 text-xl font-semibold">{t("import.localTitle")}</h2><p className="mx-auto mt-2 max-w-md text-[11px] text-copy">{t("import.localDescription")}</p><button className="ui-button ui-button-primary mt-6" onClick={()=>void onLocal()}><HardDrive/>{t("import.chooseFile")}<ArrowRight/></button><footer className="mt-5 font-mono text-[11px] text-muted">MP4 · MKV · MOV · WEBM · M4V</footer></div></div>}
function RuntimeGate({installing,failed,t,onInstall}:{installing:boolean;failed:boolean;t:(key:string)=>string;onInstall:()=>Promise<void>}){return <div className="ui-panel flex items-center gap-5 p-6"><span className="grid size-12 place-items-center rounded-xl bg-warning/10 text-warning">{installing?<LoaderCircle className="animate-spin"/>:<CloudDownload/>}</span><span className="flex-1"><small className="ui-kicker">{t("import.runtimeKicker")}</small><h2 className="mt-1 text-[16px] font-semibold">{t("import.runtimeTitle")}</h2><p className="mt-1 text-[11px] text-copy">{t("import.runtimeBody")}</p></span><button className="ui-button ui-button-primary" disabled={installing} onClick={()=>void onInstall()}>{installing?<LoaderCircle className="animate-spin"/>:<CloudDownload/>}{installing?t("common.installing"):failed?t("common.repair"):t("common.install")}</button></div>}
function VideoPreview({info,busy,t,onStart}:{info:YouTubeInfo;busy:boolean;t:(key:string)=>string;onStart:()=>Promise<void>}){return <article className="ui-panel grid grid-cols-[220px_minmax(0,1fr)_auto] items-center gap-5 p-4"><div className="relative aspect-video overflow-hidden rounded-lg bg-canvas">{info.thumbnail?<img className="size-full object-cover" src={info.thumbnail} alt=""/>:<Youtube className="absolute inset-0 m-auto text-muted"/>}<span className="absolute bottom-2 right-2 rounded bg-black/80 px-2 py-1 font-mono text-[11px] text-white">{formatDuration(info.duration)}</span></div><div className="min-w-0"><small className="ui-kicker">{info.channel||"YouTube"}</small><h2 className="mt-2 line-clamp-2 text-[16px] font-semibold">{info.title}</h2><p className="mt-2 text-[10px] text-muted">{info.width&&info.height?`${info.width} × ${info.height}`:"—"}{info.fps?` · ${info.fps} fps`:""}</p><div className="mt-3 flex gap-2"><span className="ui-chip text-success"><Check/>{t("import.videoBest")}</span><span className="ui-chip text-success"><Check/>{t("import.audioBest")}</span></div></div><button className="ui-button ui-button-primary" disabled={info.live||busy} onClick={()=>void onStart()}><CloudDownload/>{info.live?t("import.liveUnsupported"):t("import.downloadCreate")}</button></article>}
function DownloadProgress({download,onCancel}:{download:YouTubeDownload;onCancel:()=>Promise<void>}){const{t}=useI18n();return <div className="ui-panel p-8 text-center"><span className="mx-auto grid size-14 place-items-center rounded-full bg-accent/10 text-accent"><CloudDownload className="animate-pulse"/></span><small className="ui-kicker mt-5 block">{download.status==="processing"?t("import.finalizing"):t("import.downloading")}</small><h2 className="mx-auto mt-2 max-w-xl truncate text-lg font-semibold">{download.title}</h2><p className="mt-2 text-[11px] text-muted">{download.message}</p><div className="mx-auto mt-6 h-2 max-w-xl overflow-hidden rounded-full bg-canvas"><i className="block h-full bg-accent transition-[width]" style={{width:`${Math.max(2,download.progress)}%`}}/></div><div className="mx-auto mt-3 flex max-w-xl justify-between font-mono text-[10px] text-muted"><strong className="text-foreground">{Math.round(download.progress)}%</strong><span>{download.speed||"—"}</span><span>{download.eta?`ETA ${download.eta}`:"—"}</span></div><button className="ui-button mt-5" onClick={()=>void onCancel()}>{t("common.cancel")}</button></div>}
function formatDuration(value?:number|null){if(!value)return"—";const hours=Math.floor(value/3600),minutes=Math.floor((value%3600)/60),seconds=Math.floor(value%60);return`${hours?`${hours}:`:""}${String(minutes).padStart(hours?2:1,"0")}:${String(seconds).padStart(2,"0")}`}
function message(reason:unknown){return reason instanceof Error?reason.message:String(reason)}

import {AudioLines,BookOpen,FileAudio,FolderOpen,Globe2,LoaderCircle,LockKeyhole,Mic,Play,Plus,RefreshCw,Save,Search,Shapes,Sparkles,Trash2,Upload,WandSparkles} from "lucide-react";
import {useEffect,useMemo,useState} from "react";
import {ProfileCreator} from "@/components/voice/ProfileCreator";
import {OmniVoiceLibraryPanel} from "@/components/voice/OmniVoiceLibraryPanel";
import {PageHeader} from "@/components/PageHeader";
import {api} from "@/lib/api";
import {useI18n} from "@/i18n";
import type {LibraryAsset,LibraryAssetKind,TerminologyTerm,TtsGeneration,TtsModel,TtsProfile,TtsProfileInput,TtsStatus} from "@/types";
type LibraryTab="voices"|LibraryAssetKind;
type Props={status:TtsStatus|null;profiles:TtsProfile[];models:TtsModel[];onRefresh:()=>Promise<void>;onOpenTools:()=>void};
const tabs:[LibraryTab,string,typeof Mic][]=[["voices","library.voices",Mic],["captures","library.captures",AudioLines],["glossaries","library.glossaries",BookOpen],["audio","library.audio",FileAudio],["presets","library.presets",Shapes]];
export function LibraryPage({status,profiles,models,onRefresh,onOpenTools}:Props){
  const{t}=useI18n();const[tab,setTab]=useState<LibraryTab>("voices");const[query,setQuery]=useState("");const[selectedId,setSelectedId]=useState<string|null>(null);const[creatorType,setCreatorType]=useState<TtsProfileInput["voice_type"]|null>(null);const[creatorEngine,setCreatorEngine]=useState<string|null>(null);const[voiceView,setVoiceView]=useState<"profiles"|"omnivoice">("profiles");const[assets,setAssets]=useState<LibraryAsset[]>([]);const[refreshing,setRefreshing]=useState(false);
  useEffect(()=>{void api.libraryAssets().then(setAssets).catch(()=>null)},[]);useEffect(()=>{if(!selectedId&&profiles.length)setSelectedId(profiles[0].id)},[profiles,selectedId]);
  const selected=profiles.find(item=>item.id===selectedId)||null;const filtered=useMemo(()=>profiles.filter(item=>`${item.name} ${item.description||""} ${item.language||""} ${item.gender||""} ${item.primary_role||""} ${(item.roles||[]).join(" ")}`.toLowerCase().includes(query.toLowerCase())),[profiles,query]);const displayedModels=useMemo(()=>[...models].sort((left,right)=>Number(right.downloaded)-Number(left.downloaded)||left.display_name.localeCompare(right.display_name)),[models]);
  const refresh=async()=>{setRefreshing(true);try{await onRefresh();setAssets(await api.libraryAssets())}finally{setRefreshing(false)}};
  return <div data-testid="library-page" className="flex h-full min-h-0 flex-col overflow-hidden"><PageHeader kicker={t("library.kicker")} title={t("library.title")} description={t("library.description")} actions={<><label className="flex h-9 w-60 items-center gap-2 rounded-lg border border-line bg-surface px-3"><Search className="size-4 text-muted"/><input className="min-w-0 flex-1 bg-transparent text-[11px] outline-none" value={query} onChange={event=>setQuery(event.target.value)} placeholder={t("library.search")}/></label><button className="ui-icon-button" onClick={()=>void refresh()}><RefreshCw className={refreshing?"animate-spin":""}/></button><button className="ui-button ui-button-primary" onClick={()=>{setCreatorEngine("tts-omnivoice-hq");setCreatorType("cloned")}}><Mic/>{t("voiceLibrary.cloneWithOmniVoice")}</button></>}/>
    <div data-testid="library-tabs" className="flex h-11 items-center gap-1 border-b border-line px-8">{tabs.map(([id,key,Icon])=><button key={id} className={`relative flex h-full items-center gap-2 px-4 text-[11px] ${tab===id?"text-foreground":"text-muted"}`} onClick={()=>setTab(id)}><Icon className="size-3.5"/>{t(key)}{id==="voices"&&<span className="ui-chip">{profiles.length}</span>}{tab===id&&<i className="absolute inset-x-3 bottom-0 h-0.5 bg-accent"/>}</button>)}<div className="ml-auto flex items-center gap-2 text-[10px] text-muted"><i className={`size-2 rounded-full ${status?.installed_count?"bg-success":"bg-warning"}`}/>{status?.installed_count?t("library.ttsOnline"):t("library.ttsNotInstalled")}</div></div>
    {tab==="voices"?<div className="grid min-h-0 flex-1 grid-cols-[240px_minmax(360px,1fr)_260px]">
      <aside className="flex min-h-0 flex-col border-r border-line bg-surface"><header className="flex h-11 items-center justify-between border-b border-line px-3"><span className="ui-kicker">{t("library.collection")}</span><button className="ui-icon-button" onClick={()=>setCreatorType("preset")}><Plus/></button></header><div className="min-h-0 flex-1 overflow-auto p-2">{filtered.map((profile,index)=><button key={profile.id} className={`mb-1 flex w-full gap-3 rounded-lg border p-2 text-left ${selected?.id===profile.id?"border-accent bg-accent/5":"border-transparent hover:bg-raised"}`} onClick={()=>setSelectedId(profile.id)}><VoiceAvatar name={profile.name} active={selected?.id===profile.id}/><span className="min-w-0 flex-1"><strong className="block truncate text-[11px]">{profile.name}</strong><small className="mt-1 block truncate text-[9px] uppercase text-muted">{profile.engine_display_name||profile.default_engine||typeLabel(profile.voice_type,t)}</small><small className="mt-0.5 block truncate text-[9px] text-accent">{genderLabel(profile.gender,t)} · {profile.language?.toUpperCase()||"—"} · {roleLabel(profile.primary_role||profile.roles?.[0],t)}</small><small className="mt-0.5 block truncate text-[8px] text-muted">{usageLabel(profile.usage_scope,t)}</small><span className="mt-2 flex h-3 items-end gap-0.5">{Array.from({length:18},(_,bar)=><i key={bar} className="w-px bg-accent/55" style={{height:3+((bar*7+index)%9)}}/>)}</span></span></button>)}</div></aside>
      <section className="min-h-0 overflow-auto p-5"><div className="mb-4 flex w-fit rounded-lg border border-line bg-canvas p-1"><button className={`rounded-md px-3 py-1.5 text-[10px] ${voiceView==="profiles"?"bg-raised text-foreground":"text-muted"}`} onClick={()=>setVoiceView("profiles")}>{t("voiceLibrary.myVoices")}</button><button className={`rounded-md px-3 py-1.5 text-[10px] ${voiceView==="omnivoice"?"bg-raised text-foreground":"text-muted"}`} onClick={()=>setVoiceView("omnivoice")}>{t("voiceLibrary.omniCatalog")}</button></div>{voiceView==="omnivoice"?<OmniVoiceLibraryPanel onProfilesRefresh={onRefresh} onCloneVoice={()=>{setCreatorEngine("tts-omnivoice-hq");setCreatorType("cloned")}}/>:selected?<VoiceWorkbench profile={selected} models={models}/>:<div className="ui-panel grid min-h-72 place-items-center text-center"><div><AudioLines className="mx-auto size-8 text-muted"/><h2 className="mt-4 text-[15px] font-semibold">{t("library.empty")}</h2><p className="mt-1 text-[11px] text-muted">{t("library.emptyBody")}</p></div></div>}</section>
      <aside className="min-h-0 overflow-auto border-l border-line bg-surface p-3"><span className="ui-kicker">{t("library.quickActions")}</span><div className="mt-3 grid gap-2"><Quick icon={Mic} title={t("profile.record")} body={t("profile.captureBody")} onClick={()=>setCreatorType("cloned")}/><Quick icon={Sparkles} title={t("profile.clone")} body={t("profile.cloneWarning")} onClick={()=>setCreatorType("cloned")}/><Quick icon={Upload} title={t("profile.importSample")} body={t("library.importBody")} onClick={()=>setCreatorType("cloned")}/><Quick icon={WandSparkles} title={t("library.rvc")} body={t("library.rvcBody")} onClick={onOpenTools}/></div><div className="mt-4 rounded-lg border border-line bg-canvas p-3"><small className="ui-label">{t("library.modelsReady")}</small><strong className="mt-2 block text-xl">{models.filter(item=>item.downloaded).length}/{models.length}</strong><p className="mt-1 text-[10px] text-muted">{t("library.performanceBody")}</p></div><div className="mt-5 flex items-center justify-between"><span className="ui-kicker">{t("profile.engine")}</span><small className="text-[9px] text-muted">{models.length}</small></div><div className="mt-2 grid gap-1.5">{displayedModels.map(model=><ModelCard key={model.id} model={model} readyLabel={t("common.ready")} missingLabel={t("common.notInstalled")}/>)}</div></aside>
    </div>:<AssetWorkspace tab={tab} assets={assets.filter(item=>item.kind===tab)} onCreated={asset=>setAssets(current=>[asset,...current])} onDeleted={id=>setAssets(current=>current.filter(item=>item.id!==id))}/>} 
    {creatorType&&<ProfileCreator models={models} initialType={creatorType} preferredEngineId={creatorEngine} onClose={()=>{setCreatorType(null);setCreatorEngine(null)}} onCreated={async()=>{await onRefresh();setCreatorType(null);setCreatorEngine(null)}}/>}
  </div>;
}
function VoiceWorkbench({profile,models}:{profile:TtsProfile;models:TtsModel[]}){
  const{t}=useI18n();
  const profileModel=models.find(model=>model.id===profile.default_engine);
  const[text,setText]=useState("");
  const[busy,setBusy]=useState(false);
  const[error,setError]=useState("");
  const[generation,setGeneration]=useState<TtsGeneration|null>(null);
  const[audioUrl,setAudioUrl]=useState("");
  const[history,setHistory]=useState<TtsGeneration[]>([]);
  const[audioUrls,setAudioUrls]=useState<Record<string,string>>({});

  useEffect(()=>{
    let alive=true;
    setGeneration(null);
    setAudioUrl("");
    setError("");
    void api.ttsGenerations(profile.id).then(async records=>{
      const pairs=await Promise.all(records.filter(item=>item.status==="completed"&&item.audio_path).map(async item=>[item.id,await api.ttsGenerationAudioUrl(item.id)] as const));
      if(alive){setHistory(records);setAudioUrls(Object.fromEntries(pairs))}
    }).catch(reason=>alive&&setError(reason instanceof Error?reason.message:String(reason)));
    return()=>{alive=false};
  },[profile.id]);

  const generate=async()=>{
    if(!text.trim())return;
    setBusy(true);setError("");setAudioUrl("");
    try{
      let result=await api.generateTts({profile_id:profile.id,text:text.trim(),language:profile.language||"fr",normalize:true,max_chunk_chars:800,crossfade_ms:50});
      setGeneration(result);
      const deadline=Date.now()+600000;
      while(["queued","loading_model","generating"].includes(result.status)&&Date.now()<deadline){
        await new Promise(resolve=>setTimeout(resolve,900));
        result=await api.ttsGeneration(result.id);
        setGeneration(result);
      }
      setHistory(current=>[result,...current.filter(item=>item.id!==result.id)]);
      if(result.status!=="completed")throw new Error(result.error||result.status);
      const url=await api.ttsGenerationAudioUrl(result.id);
      setAudioUrl(url);
      setAudioUrls(current=>({...current,[result.id]:url}));
    }catch(reason){setError(reason instanceof Error?reason.message:String(reason))}
    finally{setBusy(false)}
  };

  return <div className="mx-auto grid max-w-3xl gap-4">
    <header className="ui-panel flex items-center gap-4 p-5"><VoiceAvatar name={profile.name} active large/><span className="min-w-0 flex-1"><small className="ui-kicker">{typeLabel(profile.voice_type,t)}</small><h2 className="mt-1 truncate text-xl font-semibold">{profile.name}</h2><p className="mt-1 text-[11px] text-muted">{profile.language?.toUpperCase()} · {genderLabel(profile.gender,t)} · {roleLabel(profile.primary_role||profile.roles?.[0],t)} · {profileModel?.display_name||profile.default_engine||profile.preset_engine||t("casting.profileEngine")}</p><span className="mt-2 flex flex-wrap gap-1.5">{profile.prompt_ready&&<i className="ui-chip border-accent/30 text-accent">Prompt · {t("common.ready")}</i>}<i className="ui-chip">{usageLabel(profile.usage_scope,t)}</i>{profile.multi_speaker_compatible&&<i className="ui-chip border-accent/30 text-accent">{t("voiceLibrary.multiAssignable")}</i>}</span></span><i className="ui-chip border-success/30 text-success">{t("library.authorizedVoice")}</i></header>
    <div className="ui-panel flex h-24 items-center gap-1 overflow-hidden px-5">{Array.from({length:72},(_,index)=><i key={index} className="w-0.5 rounded bg-accent/60" style={{height:10+((index*13)%48)}}/>)}</div>
    <div className="grid grid-cols-3 gap-2"><Stat value={profile.sample_count||0} label={t("library.samplesCount")}/><Stat value={profile.generation_count||0} label={t("library.generations")}/><Stat value={models.filter(item=>item.downloaded).length} label={t("library.modelsReady")}/></div>
    <section className="ui-panel p-4">
      <div className="flex items-center justify-between"><span><small className="ui-kicker">{t("library.testBench")}</small><strong className="mt-1 block text-[14px]">{t("library.testVoice")}</strong></span>{generation&&<i className="ui-chip">{generation.status}</i>}</div>
      <textarea className="ui-input mt-4 min-h-28 resize-y" value={text} onChange={event=>setText(event.target.value)} placeholder={t("library.testPlaceholder")}/>
      <div className="mt-3 flex items-center gap-3"><button className="ui-button ui-button-primary" disabled={busy||!text.trim()} onClick={()=>void generate()}>{busy?<LoaderCircle className="animate-spin"/>:<Play/>}{busy?t("library.generating"):t("library.generateTest")}</button>{audioUrl&&<audio className="h-9 flex-1" src={audioUrl} controls autoPlay/>}</div>
      {error&&<p className="mt-3 whitespace-pre-wrap text-[10px] text-danger">{error}</p>}
    </section>
    <section className="ui-panel p-4">
      <div className="flex items-center justify-between"><span><small className="ui-kicker">{t("library.generationHistory")}</small><strong className="mt-1 block text-[14px]">{history.filter(item=>item.status==="completed").length} {t("library.generations")}</strong></span><FileAudio className="size-4 text-muted"/></div>
      <div className="mt-4 grid gap-2">
        {history.length?history.map(item=><article key={item.id} className="rounded-lg border border-line bg-canvas/60 p-3">
          <div className="flex items-start gap-3"><span className={`mt-1 size-2 shrink-0 rounded-full ${item.status==="completed"?"bg-success":item.status==="failed"?"bg-danger":"bg-warning"}`}/><span className="min-w-0 flex-1"><strong className="line-clamp-2 text-[11px]">{item.text}</strong><small className="mt-1 block font-mono text-[10px] text-muted">{item.engine||"TTS"} · {item.duration?`${item.duration.toFixed(2)} s`:"—"} · {item.device?.toUpperCase()||item.status}</small></span></div>
          {item.status==="completed"&&audioUrls[item.id]?<audio className="mt-3 h-9 w-full" src={audioUrls[item.id]} controls preload="metadata"/>:item.status==="failed"&&<p className="mt-2 line-clamp-3 whitespace-pre-wrap text-[10px] text-danger">{item.error||t("library.failedGeneration")}</p>}
        </article>):<p className="py-6 text-center text-[11px] text-muted">{t("library.noGenerations")}</p>}
      </div>
    </section>
  </div>
}
const glossaryLanguages=["en","fr","es","pt","de","it","ja","ko","zh","ar"];
function AssetWorkspace({tab,assets,onCreated,onDeleted}:{tab:LibraryAssetKind;assets:LibraryAsset[];onCreated:(asset:LibraryAsset)=>void;onDeleted:(id:string)=>void}){
  const{t}=useI18n();
  const[name,setName]=useState("");
  const[content,setContent]=useState("");
  const[sourceLanguage,setSourceLanguage]=useState("en");
  const[targetLanguage,setTargetLanguage]=useState("fr");
  const[busy,setBusy]=useState(false);
  const fileKind=tab==="captures"||tab==="audio";
  const add=async()=>{
    setBusy(true);
    try{
      if(fileKind){
        const path=await window.dubStudio?.openAudio();
        if(!path)return;
        const fileName=path.split(/[\\/]/).pop()||t("library.audio");
        onCreated(await api.createLibraryAsset({kind:tab,name:fileName.replace(/\.[^.]+$/,"")||fileName,path}));
      }else{
        if(!name.trim()||!content.trim())return;
        onCreated(await api.createLibraryAsset({
          kind:tab,
          name:name.trim(),
          content:content.trim(),
          metadata:tab==="glossaries"?{source_language:sourceLanguage,target_language:targetLanguage}:undefined,
        }));
        setName("");
        setContent("");
      }
    }finally{setBusy(false)}
  };
  return <div className="min-h-0 flex-1 overflow-auto p-8"><div className="mx-auto max-w-5xl">
    <div className="flex items-center justify-between"><div><span className="ui-kicker">{t("library.workspace")}</span><h2 className="mt-1 text-xl font-semibold">{t(`library.${tab}`)}</h2></div><button className="ui-button ui-button-primary" onClick={()=>void add()} disabled={busy}><Plus/>{t("library.add")}</button></div>
    {!fileKind&&<div className="ui-panel mt-5 grid gap-3 p-4">
      <input className="ui-input" value={name} onChange={event=>setName(event.target.value)} placeholder={t("library.assetNamePlaceholder")}/>
      {tab==="glossaries"&&<div className="grid grid-cols-2 gap-3">
        <label className="grid gap-1"><span className="ui-label">{t("library.sourceLanguage")}</span><select className="ui-input" value={sourceLanguage} onChange={event=>setSourceLanguage(event.target.value)}>{glossaryLanguages.map(language=><option key={language} value={language}>{language.toUpperCase()}</option>)}</select></label>
        <label className="grid gap-1"><span className="ui-label">{t("library.targetLanguage")}</span><select className="ui-input" value={targetLanguage} onChange={event=>setTargetLanguage(event.target.value)}>{glossaryLanguages.map(language=><option key={language} value={language}>{language.toUpperCase()}</option>)}</select></label>
      </div>}
      <textarea className="ui-input min-h-28" value={content} onChange={event=>setContent(event.target.value)} placeholder={t(tab==="glossaries"?"library.glossaryPlaceholder":"library.presetPlaceholder")}/>
      <button className="ui-button w-fit" onClick={()=>void add()}><Save/>{t("library.save")}</button>
    </div>}
    <div className="mt-5 grid grid-cols-2 gap-2">{assets.map(asset=><article className="ui-panel flex items-start gap-3 p-4" key={asset.id}><FileAudio className="size-4 text-muted"/><span className="min-w-0 flex-1"><strong className="block truncate text-[12px]">{asset.name}</strong>{asset.kind==="glossaries"&&<small className="ui-chip mt-1">{String(asset.metadata?.source_language||"auto").toUpperCase()} → {String(asset.metadata?.target_language||"all").toUpperCase()}</small>}<p className="mt-1 line-clamp-3 text-[10px] text-muted">{asset.content||asset.path}</p></span>{asset.path&&<button className="ui-icon-button" onClick={()=>void window.dubStudio?.revealPath(asset.path!)}><FolderOpen/></button>}<button className="ui-icon-button text-danger" onClick={async()=>{await api.deleteLibraryAsset(asset.id);onDeleted(asset.id)}}><Trash2/></button></article>)}</div>
    {tab==="glossaries"&&<TerminologyPanel/>}
  </div></div>;
}
function TerminologyPanel(){
  const{t}=useI18n();
  const[terms,setTerms]=useState<TerminologyTerm[]>([]);
  const[translations,setTranslations]=useState<Record<number,string>>({});
  const[busyId,setBusyId]=useState<number|null>(null);
  useEffect(()=>{void api.terminologyTerms().then(items=>{setTerms(items);setTranslations(Object.fromEntries(items.map(item=>[item.id,item.preferred_translation||""])))}).catch(()=>null)},[]);
  const visible=terms.filter(item=>item.scope==="project"||item.status!=="reference").slice(0,60);
  const approve=async(term:TerminologyTerm)=>{
    const value=(translations[term.id]||"").trim();
    if(!value)return;
    setBusyId(term.id);
    try{
      const updated=await api.approveTerminologyTerm(term.id,value,false);
      setTerms(current=>current.map(item=>item.id===updated.id?updated:item));
    }finally{setBusyId(null)}
  };
  const research=async(term:TerminologyTerm)=>{
    setBusyId(term.id);
    try{
      await api.researchTerminologyTerm(term.id);
      setTerms(await api.terminologyTerms());
    }finally{setBusyId(null)}
  };
  return <section className="mt-8">
    <div className="flex items-end justify-between"><div><span className="ui-kicker">{t("library.smartDictionary")}</span><h3 className="mt-1 text-[15px] font-semibold">{t("library.termsToReview")}</h3></div><small className="ui-chip">{visible.length} {t("library.detectedTerms")}</small></div>
    <div className="mt-3 grid gap-2">{visible.length?visible.map(term=><article key={term.id} className="ui-panel grid grid-cols-[minmax(150px,.7fr)_minmax(220px,1fr)_auto] items-center gap-3 p-3">
      <span className="min-w-0"><strong className="block truncate text-[12px]">{term.source_term}</strong><small className="mt-1 block text-[9px] uppercase text-muted">{term.source_language} → {term.target_language} · {term.category||term.status} · {t("library.suspicion")} {term.suspicion_score}</small>{term.examples[0]&&<p className="mt-1 line-clamp-1 text-[10px] text-muted">“{term.examples[0]}”</p>}</span>
      <input className="ui-input h-9" value={translations[term.id]??""} onChange={event=>setTranslations(current=>({...current,[term.id]:event.target.value}))} placeholder={t("library.preferredTranslation")}/>
      <span className="flex items-center gap-1"><button className="ui-button h-9" disabled={busyId===term.id} onClick={()=>void research(term)}><Globe2/>{term.sources.length||t("library.research")}</button><button className="ui-button ui-button-primary h-9" disabled={busyId===term.id||!(translations[term.id]||"").trim()} onClick={()=>void approve(term)}>{busyId===term.id?<LoaderCircle className="animate-spin"/>:<LockKeyhole/>}{term.locked?t("library.locked"):t("library.validate")}</button></span>
    </article>):<div className="ui-panel p-6 text-center text-[11px] text-muted">{t("library.noTermsToReview")}</div>}</div>
  </section>;
}
function VoiceAvatar({name,active,large=false}:{name:string;active?:boolean;large?:boolean}){return <span className={`grid shrink-0 place-items-center rounded-xl border font-semibold ${large?"size-16 text-[16px]":"size-10 text-[11px]"} ${active?"border-accent bg-accent/10 text-accent":"border-line bg-raised text-copy"}`}>{name.slice(0,2).toUpperCase()}</span>}
function ModelCard({model,readyLabel,missingLabel}:{model:TtsModel;readyLabel:string;missingLabel:string}){return <article className={`rounded-lg border p-2.5 ${model.downloaded?"border-success/25 bg-success/5":"border-line bg-canvas/60 opacity-65"}`}><div className="flex items-start gap-2"><i className={`mt-1 size-2 shrink-0 rounded-full ${model.downloaded?"bg-success":model.downloading?"animate-pulse bg-warning":"bg-muted"}`}/><span className="min-w-0 flex-1"><strong className="block text-[10px] leading-4">{model.display_name}</strong><small className="mt-0.5 block text-[9px] text-muted">{model.model_size||model.family} · {model.tier||"local"} · {model.recommended_vram_gb?`${model.recommended_vram_gb} GB VRAM`:"CPU/GPU"}</small><span className="mt-1 flex flex-wrap gap-1"><i className="ui-chip text-[8px]">{model.speaker_mode||"single-speaker"}</i>{model.supports_cloning&&<i className="ui-chip text-[8px]">clone</i>}{model.supports_design&&<i className="ui-chip text-[8px]">design</i>}{model.supports_expression&&<i className="ui-chip text-[8px]">expressive</i>}</span><small className={`mt-1 block text-[9px] ${model.downloaded?"text-success":"text-muted"}`}>{model.downloaded?readyLabel:missingLabel}</small></span></div></article>}
function Quick({icon:Icon,title,body,onClick,disabled}:{icon:typeof Mic;title:string;body:string;onClick:()=>void;disabled?:boolean}){return <button className="ui-panel flex gap-3 p-3 text-left hover:border-accent/40 disabled:opacity-40" onClick={onClick} disabled={disabled}><Icon className="size-4 shrink-0 text-accent"/><span><strong className="block text-[11px]">{title}</strong><small className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted">{body}</small></span></button>}
function Stat({value,label}:{value:number;label:string}){return <span className="ui-panel p-3"><strong className="block text-lg">{value}</strong><small className="ui-label mt-1 block">{label}</small></span>}
function typeLabel(type:string|null|undefined,t:(key:string)=>string){return t(type==="cloned"?"profile.clone":type==="designed"?"profile.designed":"profile.preset")}
function genderLabel(value:string|null|undefined,t:(key:string)=>string){return t(`profile.gender.${value||"unspecified"}`)}
function roleLabel(value:string|null|undefined,t:(key:string)=>string){return t(`profile.role.${value||"other"}`)}
function usageLabel(value:string|null|undefined,t:(key:string)=>string){return t(`profile.usage.${value||"both"}`)}

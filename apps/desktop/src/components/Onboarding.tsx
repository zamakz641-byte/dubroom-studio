import {useMemo,useState,type ReactNode} from "react";
import {
  ArrowLeft,ArrowRight,AudioLines,Boxes,Check,ChevronRight,Copy,Cpu,Database,Film,
  FolderCog,Gauge,HardDrive,Languages,MonitorCog,Moon,Palette,ShieldCheck,Sparkles,Sun,
} from "lucide-react";
import {languages,useI18n,type Locale} from "@/i18n";
import {applyAppearance,appearance,type DensityId,type ThemeId} from "@/lib/appearance";
import {cn} from "@/lib/utils";
import type {AppConfig,RuntimeStatus} from "@/types";

const themes:{id:ThemeId;icon:typeof Moon}[]=[
  {id:"graphite",icon:MonitorCog},{id:"oled",icon:Moon},{id:"warm",icon:Palette},{id:"light",icon:Sun},
];
const densities:DensityId[]=["compact","comfortable","spacious"];
const workflows=["recap","anime","narration","multi"] as const;

export function Onboarding({config,runtime,onComplete}:{config:AppConfig|null;runtime:RuntimeStatus|null;onComplete:(destination:"dashboard"|"engines"|"import")=>void}){
  const{t,locale,setLocale}=useI18n();const initial=appearance();const total=6;
  const[step,setStep]=useState(0);
  const[theme,setTheme]=useState<ThemeId>(initial.theme);
  const[density,setDensity]=useState<DensityId>(initial.density);
  const[reducedMotion,setReducedMotion]=useState(initial.reducedMotion);
  const[workflow,setWorkflow]=useState<typeof workflows[number]>("recap");
  const[sourceLanguage,setSourceLanguage]=useState("auto");
  const[targetLanguage,setTargetLanguage]=useState<string>(locale);
  const storage=useMemo(()=>Object.entries(config?.paths||{}).filter(([key])=>["models","projects","exports","cache","environments"].includes(key)),[config]);
  const chooseTheme=(next:ThemeId)=>{setTheme(next);applyAppearance(next,density,reducedMotion)};
  const chooseDensity=(next:DensityId)=>{setDensity(next);applyAppearance(theme,next,reducedMotion)};
  const finish=(destination:"dashboard"|"engines"|"import")=>{localStorage.setItem("dubroom.onboardingComplete","true");localStorage.setItem("dubroom.workflow",JSON.stringify({workflow,sourceLanguage,targetLanguage}));applyAppearance(theme,density,reducedMotion);onComplete(destination)};

  return <div data-testid="onboarding" className="grid h-full w-full grid-cols-[300px_minmax(0,1fr)] overflow-hidden bg-canvas text-foreground">
    <aside className="relative flex min-h-0 flex-col overflow-hidden border-r border-line bg-surface p-8">
      <div className="flex items-center gap-3"><Signal/><strong className="text-sm tracking-[.14em]">DUBROOM</strong></div>
      <div className="relative my-auto grid place-items-center py-10">
        <div className="absolute size-72 rounded-full border border-accent/20 shadow-[0_0_0_52px_color-mix(in_srgb,var(--ui-accent)_4%,transparent),0_0_0_104px_color-mix(in_srgb,var(--ui-accent)_2%,transparent)]"/>
        <div className="signal-bars relative z-10 flex h-40 items-center gap-2 text-accent">{[34,68,108,146,108,68,34].map((height,index)=><i key={index} className="block w-1 rounded-full bg-current" style={{height}}/>)}</div>
      </div>
      <p className="relative max-w-[230px] text-xs leading-6 text-copy">{t("onboarding.welcome.body")}</p>
      <footer className="mt-8 flex items-center gap-3 border-t border-line pt-5 text-[11px] uppercase tracking-[.12em] text-muted"><ShieldCheck className="size-4 text-success"/><span>{t("onboarding.welcome.local")}</span></footer>
    </aside>

    <main className="grid min-w-0 grid-rows-[66px_minmax(0,1fr)_72px] overflow-hidden">
      <header className="grid grid-cols-[190px_minmax(0,1fr)_120px] items-center gap-6 border-b border-line px-8">
        <span className="ui-kicker">{t("onboarding.eyebrow")}</span>
        <nav className="flex items-center" aria-label={t("onboarding.eyebrow")}>
          {Array.from({length:total},(_,index)=><div className="flex flex-1 items-center last:flex-none" key={index}><button onClick={()=>setStep(index)} className={cn("grid size-7 shrink-0 place-items-center rounded-full border text-[11px] font-semibold transition",index===step?"border-accent bg-accent text-accent-ink shadow-[0_0_0_4px_var(--ui-accent-soft)]":index<step?"border-success/60 bg-success/10 text-success":"border-line bg-raised text-muted")}>{index<step?<Check className="size-3.5"/>:index+1}</button>{index<total-1&&<i className={cn("h-px flex-1",index<step?"bg-success/50":"bg-line")}/>}</div>)}
        </nav>
        <small className="text-right text-[11px] text-muted">{t("onboarding.step",{current:step+1,total})}</small>
      </header>

      <section data-testid="onboarding-stage" className="min-h-0 overflow-y-auto px-10 py-8">
        <div className="mx-auto w-full max-w-4xl animate-[panel-in_.2s_ease-out]" key={step}>
          {step===0&&<Step icon={Languages} title={t("onboarding.language.title")} body={t("onboarding.language.body")}><div className="grid grid-cols-3 gap-2">{languages.map(language=><button key={language.id} onClick={()=>{setLocale(language.id as Locale);setTargetLanguage(language.id)}} className={cn("flex min-h-16 items-center gap-3 rounded-xl border bg-surface px-4 text-left transition hover:border-accent/60",locale===language.id?"border-accent bg-accent-soft":"border-line")}><span className="grid size-9 place-items-center rounded-lg bg-raised font-mono text-[11px] text-accent">{language.id.toUpperCase()}</span><strong className="text-xs">{language.native}</strong>{locale===language.id&&<Check className="ml-auto size-4 text-success"/>}</button>)}</div></Step>}
          {step===1&&<Step icon={Film} title={t("onboarding.workflow.title")} body={t("onboarding.workflow.body")}><label className="block"><span className="ui-label">{t("onboarding.workflow.kind")}</span><div className="mt-2 grid grid-cols-4 gap-2">{workflows.map(id=><button key={id} onClick={()=>setWorkflow(id)} className={cn("min-h-14 rounded-xl border bg-surface px-3 text-xs font-semibold",workflow===id?"border-accent bg-accent-soft text-accent":"border-line")}>{t(`onboarding.workflow.${id}`)}</button>)}</div></label><div className="mt-5 grid grid-cols-[1fr_32px_1fr] items-end gap-3"><LanguageSelect label={t("onboarding.workflow.source")} value={sourceLanguage} onChange={setSourceLanguage} includeAuto/><ChevronRight className="mb-3 size-4 justify-self-center text-muted"/><LanguageSelect label={t("onboarding.workflow.target")} value={targetLanguage} onChange={setTargetLanguage}/></div></Step>}
          {step===2&&<Step icon={Palette} title={t("onboarding.theme.title")} body={t("onboarding.theme.body")}><div className="grid grid-cols-4 gap-3">{themes.map(({id,icon:Icon})=><button key={id} onClick={()=>chooseTheme(id)} className={cn("relative min-h-28 rounded-xl border bg-surface p-3 text-left",theme===id?"border-accent":"border-line")}><span className={cn("grid h-14 place-items-center rounded-lg border border-line",id==="graphite"&&"bg-[#171a1f] text-[#d99a5e]",id==="oled"&&"bg-black text-[#72d7c6]",id==="warm"&&"bg-[#211d1a] text-[#c9875c]",id==="light"&&"bg-[#f8f7f3] text-[#a85e32]")}><Icon className="size-5"/></span><strong className="mt-3 block text-xs">{t(`theme.${id}`)}</strong>{theme===id&&<Check className="absolute right-2 top-2 size-4 text-success"/>}</button>)}</div><div className="mt-5 flex items-center gap-2"><span className="ui-label mr-2">{t("settings.density")}</span>{densities.map(id=><button key={id} onClick={()=>chooseDensity(id)} className={cn("ui-button",density===id&&"border-accent bg-accent-soft text-accent")}>{t(`density.${id}`)}</button>)}<label className="ml-auto flex items-center gap-2 text-xs text-copy"><input type="checkbox" className="accent-[var(--ui-accent)]" checked={reducedMotion} onChange={event=>{setReducedMotion(event.target.checked);applyAppearance(theme,density,event.target.checked)}}/>{t("motion.reduce")}</label></div></Step>}
          {step===3&&<Step icon={FolderCog} title={t("onboarding.storage.title")} body={t("onboarding.storage.body")}><div className="grid grid-cols-[minmax(0,1.25fr)_minmax(280px,.75fr)] gap-3"><div className="ui-panel overflow-hidden">{storage.map(([key,value])=><article key={key} className="grid min-h-14 grid-cols-[110px_minmax(0,1fr)_32px] items-center gap-3 border-b border-line px-3 last:border-0"><span className="flex items-center gap-2 text-[11px] uppercase tracking-[.1em] text-muted"><HardDrive className="size-4 text-accent"/>{key}</span><code className="truncate font-mono text-[11px] text-copy" title={value}>{value}</code><button className="ui-icon-button size-7" onClick={()=>void navigator.clipboard.writeText(value)} title={t("common.copy")}><Copy className="size-3.5"/></button></article>)}</div><div className="grid grid-cols-2 gap-2"><Hardware icon={Cpu} label={t("onboarding.hardware.cpu")} value={runtime?.hardware.cpu||"—"}/><Hardware icon={Database} label={t("onboarding.hardware.memory")} value={runtime?.hardware.memory?formatBytes(runtime.hardware.memory.total_bytes):"—"}/><Hardware icon={MonitorCog} label={t("onboarding.hardware.acceleration")} value={runtime?.hardware.cuda?.name||"CPU"}/><Hardware icon={Gauge} label={t("onboarding.hardware.media")} value={runtime?.tools.ffmpeg?`FFmpeg · ${t("common.available")}`:t("common.missing")}/></div></div><p className="mt-3 flex items-center gap-2 text-[11px] text-success"><ShieldCheck className="size-4"/>{t("onboarding.storage.portable")}</p></Step>}
          {step===4&&<Step icon={Boxes} title={t("onboarding.models.title")} body={t("onboarding.models.body")}><div className="grid grid-cols-2 gap-3"><ModelCard icon={Gauge} title={t("onboarding.models.whisper")} body="Tiny → Base → Small → Medium → Large → Turbo"/><ModelCard icon={AudioLines} title={t("onboarding.models.voicebox")} body="Qwen · Chatterbox · TADA · Kokoro · LuxTTS"/></div><div className="mt-3 flex items-center gap-3 rounded-xl border border-success/30 bg-success/10 p-4"><Check className="size-5 text-success"/><span><strong className="block text-xs">{t("onboarding.models.none")}</strong><small className="mt-1 block text-[11px] text-copy">{t("onboarding.models.after")}</small></span></div></Step>}
          {step===5&&<Step icon={Sparkles} title={t("onboarding.ready.title")} body={t("onboarding.ready.body")}><div className="grid grid-cols-2 gap-3"><ReadyAction icon={Film} title={t("onboarding.ready.import")} body={t("onboarding.ready.importChoice")} onClick={()=>finish("import")}/><ReadyAction icon={Boxes} title={t("onboarding.ready.engines")} body="Whisper · Voicebox · Pyannote · RVC" onClick={()=>finish("engines")}/></div><div className="mt-3 flex items-center gap-3 rounded-xl border border-success/30 bg-success/10 p-4"><ShieldCheck className="size-5 text-success"/><span><strong className="block text-xs">{t("onboarding.ready.private")}</strong><small className="mt-1 block text-[11px] text-copy">{t("onboarding.ready.privateBody")}</small></span></div></Step>}
        </div>
      </section>

      <footer className="flex items-center justify-between border-t border-line bg-surface px-8">
        <button className="ui-button" disabled={step===0} onClick={()=>setStep(current=>Math.max(0,current-1))}><ArrowLeft className="size-4"/>{t("common.back")}</button>
        {step<total-1?<button data-testid="onboarding-next" className="ui-button ui-button-primary" onClick={()=>setStep(current=>Math.min(total-1,current+1))}>{t("common.continue")}<ArrowRight className="size-4"/></button>:<button data-testid="onboarding-finish" className="ui-button ui-button-primary" onClick={()=>finish("dashboard")}>{t("common.finish")}<ArrowRight className="size-4"/></button>}
      </footer>
    </main>
  </div>;
}

function Signal(){return <span className="signal-bars flex size-10 items-center justify-center gap-[3px] rounded-xl border border-accent/30 bg-accent-soft text-accent">{[12,20,28,20,12].map((height,index)=><i key={index} className="block w-[2px] rounded-full bg-current" style={{height}}/>)}</span>}
function Step({icon:Icon,title,body,children}:{icon:typeof Languages;title:string;body:string;children:ReactNode}){return <div><span className="grid size-11 place-items-center rounded-xl border border-accent/30 bg-accent-soft text-accent"><Icon className="size-5"/></span><h1 className="mt-5 text-3xl font-semibold tracking-[-.035em]">{title}</h1><p className="mt-2 max-w-3xl text-xs leading-6 text-copy">{body}</p><div className="mt-6">{children}</div></div>}
function LanguageSelect({label,value,onChange,includeAuto=false}:{label:string;value:string;onChange:(value:string)=>void;includeAuto?:boolean}){return <label><span className="ui-label">{label}</span><select className="ui-input mt-2" value={value} onChange={event=>onChange(event.target.value)}>{includeAuto&&<option value="auto">Auto</option>}{languages.map(language=><option key={language.id} value={language.id}>{language.native}</option>)}</select></label>}
function Hardware({icon:Icon,label,value}:{icon:typeof Cpu;label:string;value:string}){return <article className="ui-panel min-h-24 p-3"><Icon className="size-4 text-accent"/><small className="mt-3 block text-[10px] uppercase tracking-[.1em] text-muted">{label}</small><strong className="mt-1 block line-clamp-2 text-[11px]">{value}</strong></article>}
function ModelCard({icon:Icon,title,body}:{icon:typeof Gauge;title:string;body:string}){return <article className="ui-panel flex min-h-24 items-center gap-4 p-4"><span className="grid size-11 place-items-center rounded-xl bg-raised text-accent"><Icon className="size-5"/></span><div><strong className="text-sm">{title}</strong><p className="mt-1 text-[11px] text-copy">{body}</p></div></article>}
function ReadyAction({icon:Icon,title,body,onClick}:{icon:typeof Film;title:string;body:string;onClick:()=>void}){return <button onClick={onClick} className="ui-panel group flex min-h-28 items-center gap-4 p-4 text-left transition hover:border-accent/60 hover:bg-raised"><span className="grid size-12 place-items-center rounded-xl bg-accent-soft text-accent"><Icon className="size-5"/></span><span className="min-w-0"><strong className="text-sm">{title}</strong><small className="mt-1 block text-[11px] leading-5 text-copy">{body}</small></span><ChevronRight className="ml-auto size-5 text-muted transition group-hover:translate-x-1 group-hover:text-accent"/></button>}
function formatBytes(value:number){return value?`${(value/1024/1024/1024).toFixed(1)} GB`:"—"}

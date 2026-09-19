import {lazy,Suspense,useMemo,useState,type ReactNode} from "react";
import {AnimatePresence,MotionConfig,motion} from "motion/react";
import {
  ArrowLeft,ArrowRight,AudioLines,Boxes,Check,ChevronRight,Copy,Cpu,Database,Film,
  FolderCog,Gauge,HardDrive,Languages,MonitorCog,Moon,Palette,ShieldCheck,Sparkles,Sun,
} from "lucide-react";
import {languages,useI18n,type Locale} from "@/i18n";
import {applyAppearance,appearance,type DensityId,type ThemeId} from "@/lib/appearance";
import {cn} from "@/lib/utils";
import type {AppConfig,RuntimeStatus} from "@/types";

const VoiceCore3D=lazy(()=>import("@/components/visuals/VoiceCore3D").then(module=>({default:module.VoiceCore3D})));

const themes:{id:ThemeId;icon:typeof Moon}[]=[
  {id:"graphite",icon:MonitorCog},{id:"oled",icon:Moon},{id:"warm",icon:Palette},{id:"light",icon:Sun},
];
const densities:DensityId[]=["compact","comfortable","spacious"];
const workflows=["recap","anime","narration","multi"] as const;
const stepIcons=[Languages,Sparkles,Palette,FolderCog,Cpu,Film,Boxes,ShieldCheck] as const;

export function Onboarding({config,runtime,onComplete}:{config:AppConfig|null;runtime:RuntimeStatus|null;onComplete:(destination:"dashboard"|"engines"|"import")=>void}){
  const{t,locale,setLocale}=useI18n();
  const initial=appearance();
  const total=8;
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
  const finish=(destination:"dashboard"|"engines"|"import")=>{
    localStorage.setItem("dubroom.onboardingComplete","true");
    localStorage.setItem("dubroom.workflow",JSON.stringify({workflow,sourceLanguage,targetLanguage}));
    applyAppearance(theme,density,reducedMotion);
    onComplete(destination);
  };

  return <MotionConfig reducedMotion={reducedMotion?"always":"user"}>
    <div data-testid="onboarding" className="grid h-full w-full grid-cols-[360px_minmax(0,1fr)] overflow-hidden bg-canvas text-foreground">
      <aside className="relative isolate flex min-h-0 flex-col overflow-hidden border-r border-line bg-surface">
        <div className="nocturne-grid absolute inset-0 opacity-35 [mask-image:linear-gradient(to_bottom,black,transparent_82%)]"/>
        <header className="relative z-10 flex items-center gap-3 px-8 pt-8">
          <Signal/>
          <span>
            <strong className="block text-sm tracking-[.16em]">DUBROOM</strong>
            <small className="mt-0.5 block text-[10px] uppercase tracking-[.3em] text-muted">Studio</small>
          </span>
        </header>
        <div className="relative min-h-0 flex-1">
          <Suspense fallback={<div className="voice-core-fallback"/>}>
            <VoiceCore3D reducedMotion={reducedMotion}/>
          </Suspense>
        </div>
        <div className="relative z-10 px-8 pb-8">
          <div className="mb-5 h-px bg-gradient-to-r from-accent via-accent-warm/60 to-transparent"/>
          <p className="max-w-[280px] text-xs leading-6 text-copy">{t("onboarding.welcome.body")}</p>
          <div className="mt-5 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[.14em] text-success">
            <ShieldCheck className="size-4"/>{t("onboarding.welcome.local")}
          </div>
        </div>
      </aside>

      <main className="grid min-w-0 grid-rows-[78px_minmax(0,1fr)_76px] overflow-hidden">
        <header className="grid grid-cols-[170px_minmax(0,1fr)_130px] items-center gap-6 border-b border-line px-8">
          <span className="ui-kicker">{t("onboarding.eyebrow")}</span>
          <nav className="flex items-center gap-1.5" aria-label={t("onboarding.eyebrow")}>
            {Array.from({length:total},(_,index)=>{
              const Icon=stepIcons[index];
              return <button
                key={index}
                onClick={()=>setStep(index)}
                aria-current={index===step?"step":undefined}
                className={cn(
                  "group relative grid h-8 flex-1 place-items-center rounded-md border transition-colors",
                  index===step?"border-accent bg-accent-soft text-accent":index<step?"border-success/30 bg-success/5 text-success":"border-line bg-raised/60 text-muted hover:border-line-strong hover:text-copy"
                )}
              >
                {index<step?<Check className="size-3.5"/>:<Icon className="size-3.5"/>}
                {index===step&&<motion.i layoutId="onboarding-active" className="absolute -bottom-[7px] h-0.5 w-5 rounded-full bg-accent"/>}
              </button>;
            })}
          </nav>
          <small className="text-right text-[11px] text-muted">{t("onboarding.step",{current:step+1,total})}</small>
        </header>

        <section data-testid="onboarding-stage" className="min-h-0 overflow-y-auto px-10 py-9">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={step}
              initial={{opacity:0,y:10}}
              animate={{opacity:1,y:0}}
              exit={{opacity:0,y:-6}}
              transition={{duration:.22,ease:[.2,.8,.2,1]}}
              className="mx-auto w-full max-w-4xl"
            >
              {step===0&&<LanguageStep locale={locale} onChoose={language=>{setLocale(language);setTargetLanguage(language)}}/>}
              {step===1&&<WelcomeStep/>}
              {step===2&&<AppearanceStep theme={theme} density={density} reducedMotion={reducedMotion} onTheme={chooseTheme} onDensity={chooseDensity} onReducedMotion={next=>{setReducedMotion(next);applyAppearance(theme,density,next)}}/>}
              {step===3&&<StorageStep storage={storage}/>}
              {step===4&&<HardwareStep runtime={runtime}/>}
              {step===5&&<WorkflowStep workflow={workflow} sourceLanguage={sourceLanguage} targetLanguage={targetLanguage} onWorkflow={setWorkflow} onSource={setSourceLanguage} onTarget={setTargetLanguage}/>}
              {step===6&&<ModelsStep/>}
              {step===7&&<ReadyStep onFinish={finish}/>}
            </motion.div>
          </AnimatePresence>
        </section>

        <footer className="flex items-center justify-between border-t border-line bg-surface/80 px-8">
          <button className="ui-button" disabled={step===0} onClick={()=>setStep(current=>Math.max(0,current-1))}>
            <ArrowLeft/>{t("common.back")}
          </button>
          <div className="hidden text-[10px] uppercase tracking-[.14em] text-muted 2xl:block">Nocturne interface · Local runtime</div>
          {step<total-1?
            <button data-testid="onboarding-next" className="ui-button ui-button-primary" onClick={()=>setStep(current=>Math.min(total-1,current+1))}>
              {t("common.continue")}<ArrowRight/>
            </button>:
            <button data-testid="onboarding-finish" className="ui-button ui-button-primary" onClick={()=>finish("dashboard")}>
              {t("common.finish")}<ArrowRight/>
            </button>
          }
        </footer>
      </main>
    </div>
  </MotionConfig>;
}

function LanguageStep({locale,onChoose}:{locale:Locale;onChoose:(locale:Locale)=>void}){
  const{t}=useI18n();
  return <Step icon={Languages} title={t("onboarding.language.title")} body={t("onboarding.language.body")}>
    <div className="grid grid-cols-3 gap-2">
      {languages.map(language=><button
        key={language.id}
        onClick={()=>onChoose(language.id as Locale)}
        className={cn("group flex min-h-16 items-center gap-3 rounded-xl border bg-surface px-4 text-left transition-colors hover:border-accent/60",locale===language.id?"border-accent bg-accent-soft":"border-line")}
      >
        <span className="grid size-9 place-items-center rounded-lg border border-line bg-raised font-mono text-[10px] text-accent">{language.id.toUpperCase()}</span>
        <strong className="text-xs">{language.native}</strong>
        {locale===language.id&&<Check className="ml-auto size-4 text-success"/>}
      </button>)}
    </div>
  </Step>;
}

function WelcomeStep(){
  const{t}=useI18n();
  return <Step icon={Sparkles} title={t("onboarding.welcome.title")} body={t("onboarding.welcome.body")}>
    <div className="divide-y divide-line border-y border-line">
      <FeatureRow icon={ShieldCheck} title={t("onboarding.welcome.local")} body={t("onboarding.welcome.localBody")} tone="success"/>
      <FeatureRow icon={Boxes} title={t("onboarding.welcome.modular")} body={t("onboarding.welcome.modularBody")} tone="accent"/>
    </div>
  </Step>;
}

function AppearanceStep({theme,density,reducedMotion,onTheme,onDensity,onReducedMotion}:{theme:ThemeId;density:DensityId;reducedMotion:boolean;onTheme:(theme:ThemeId)=>void;onDensity:(density:DensityId)=>void;onReducedMotion:(value:boolean)=>void}){
  const{t}=useI18n();
  return <Step icon={Palette} title={t("onboarding.theme.title")} body={t("onboarding.theme.body")}>
    <div className="grid grid-cols-4 gap-3">
      {themes.map(({id,icon:Icon})=><button key={id} onClick={()=>onTheme(id)} className={cn("relative min-h-28 rounded-xl border bg-surface p-3 text-left transition-colors",theme===id?"border-accent":"border-line hover:border-line-strong")}>
        <span className={cn("grid h-14 place-items-center rounded-lg border border-line",id==="graphite"&&"bg-[#10141c] text-[#8b7cff]",id==="oled"&&"bg-black text-[#72d7c6]",id==="warm"&&"bg-[#211d1a] text-[#c9875c]",id==="light"&&"bg-[#f8f7f3] text-[#a85e32]")}><Icon className="size-5"/></span>
        <strong className="mt-3 block text-xs">{t(`theme.${id}`)}</strong>
        {theme===id&&<Check className="absolute right-2 top-2 size-4 text-success"/>}
      </button>)}
    </div>
    <div className="mt-5 flex items-center gap-2 border-t border-line pt-5">
      <span className="ui-label mr-2">{t("settings.density")}</span>
      {densities.map(id=><button key={id} onClick={()=>onDensity(id)} className={cn("ui-button",density===id&&"border-accent bg-accent-soft text-accent")}>{t(`density.${id}`)}</button>)}
      <label className="ml-auto flex items-center gap-2 text-xs text-copy">
        <input type="checkbox" className="accent-[var(--ui-accent)]" checked={reducedMotion} onChange={event=>onReducedMotion(event.target.checked)}/>
        {t("motion.reduce")}
      </label>
    </div>
  </Step>;
}

function StorageStep({storage}:{storage:[string,string][]}){
  const{t}=useI18n();
  return <Step icon={FolderCog} title={t("onboarding.storage.title")} body={t("onboarding.storage.body")}>
    <div className="overflow-hidden rounded-xl border border-line bg-surface">
      {storage.map(([key,value])=><article key={key} className="grid min-h-14 grid-cols-[120px_minmax(0,1fr)_36px] items-center gap-3 border-b border-line px-4 last:border-0">
        <span className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[.1em] text-muted"><HardDrive className="size-4 text-accent"/>{key}</span>
        <code className="truncate font-mono text-[11px] text-copy" title={value}>{value}</code>
        <button className="ui-icon-button size-7" onClick={()=>void navigator.clipboard.writeText(value)} title={t("common.copy")}><Copy className="size-3.5"/></button>
      </article>)}
    </div>
    <p className="mt-4 flex items-center gap-2 text-[11px] text-success"><ShieldCheck className="size-4"/>{t("onboarding.storage.portable")}</p>
  </Step>;
}

function HardwareStep({runtime}:{runtime:RuntimeStatus|null}){
  const{t}=useI18n();
  return <Step icon={Cpu} title={t("onboarding.hardware.title")} body={t("onboarding.hardware.body")}>
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line">
      <Hardware icon={Cpu} label={t("onboarding.hardware.cpu")} value={runtime?.hardware.cpu||"—"}/>
      <Hardware icon={Database} label={t("onboarding.hardware.memory")} value={runtime?.hardware.memory?formatBytes(runtime.hardware.memory.total_bytes):"—"}/>
      <Hardware icon={MonitorCog} label={t("onboarding.hardware.acceleration")} value={runtime?.hardware.cuda?.name||"CPU"}/>
      <Hardware icon={Gauge} label={t("onboarding.hardware.media")} value={runtime?.tools.ffmpeg?`FFmpeg · ${t("common.available")}`:t("common.missing")}/>
    </div>
  </Step>;
}

function WorkflowStep({workflow,sourceLanguage,targetLanguage,onWorkflow,onSource,onTarget}:{workflow:typeof workflows[number];sourceLanguage:string;targetLanguage:string;onWorkflow:(workflow:typeof workflows[number])=>void;onSource:(language:string)=>void;onTarget:(language:string)=>void}){
  const{t}=useI18n();
  return <Step icon={Film} title={t("onboarding.workflow.title")} body={t("onboarding.workflow.body")}>
    <span className="ui-label">{t("onboarding.workflow.kind")}</span>
    <div className="mt-2 grid grid-cols-4 gap-2">
      {workflows.map(id=><button key={id} onClick={()=>onWorkflow(id)} className={cn("min-h-14 rounded-xl border bg-surface px-3 text-xs font-semibold transition-colors",workflow===id?"border-accent bg-accent-soft text-accent":"border-line hover:border-line-strong")}>{t(`onboarding.workflow.${id}`)}</button>)}
    </div>
    <div className="mt-6 grid grid-cols-[1fr_32px_1fr] items-end gap-3">
      <LanguageSelect label={t("onboarding.workflow.source")} value={sourceLanguage} onChange={onSource} includeAuto/>
      <ChevronRight className="mb-3 size-4 justify-self-center text-muted"/>
      <LanguageSelect label={t("onboarding.workflow.target")} value={targetLanguage} onChange={onTarget}/>
    </div>
  </Step>;
}

function ModelsStep(){
  const{t}=useI18n();
  return <Step icon={Boxes} title={t("onboarding.models.title")} body={t("onboarding.models.body")}>
    <div className="divide-y divide-line border-y border-line">
      <FeatureRow icon={Gauge} title={t("onboarding.models.whisper")} body="Tiny → Base → Small → Medium → Large → Turbo" tone="accent"/>
      <FeatureRow icon={AudioLines} title={t("onboarding.models.tts")} body="Qwen3-TTS · Chatterbox · Kokoro · LuxTTS · Supertonic · TADA" tone="sync"/>
    </div>
    <div className="mt-4 flex items-center gap-3 rounded-xl border border-success/30 bg-success/10 p-4">
      <Check className="size-5 text-success"/>
      <span><strong className="block text-xs">{t("onboarding.models.none")}</strong><small className="mt-1 block text-[11px] text-copy">{t("onboarding.models.after")}</small></span>
    </div>
  </Step>;
}

function ReadyStep({onFinish}:{onFinish:(destination:"dashboard"|"engines"|"import")=>void}){
  const{t}=useI18n();
  return <Step icon={ShieldCheck} title={t("onboarding.ready.title")} body={t("onboarding.ready.body")}>
    <div className="grid grid-cols-2 gap-3">
      <ReadyAction icon={Film} title={t("onboarding.ready.import")} body={t("onboarding.ready.importChoice")} onClick={()=>onFinish("import")}/>
      <ReadyAction icon={Boxes} title={t("onboarding.ready.engines")} body="Whisper · TTS natifs · Pyannote · RVC" onClick={()=>onFinish("engines")}/>
    </div>
    <div className="mt-4 flex items-center gap-3 border-y border-line py-4">
      <ShieldCheck className="size-5 text-success"/>
      <span><strong className="block text-xs">{t("onboarding.ready.private")}</strong><small className="mt-1 block text-[11px] text-copy">{t("onboarding.ready.privateBody")}</small></span>
    </div>
  </Step>;
}

function Signal(){return <span className="signal-bars flex size-10 items-center justify-center gap-[3px] rounded-xl border border-accent/30 bg-accent-soft text-accent">{[12,20,28,20,12].map((height,index)=><i key={index} className="block w-[2px] rounded-full bg-current" style={{height}}/>)}</span>}
function Step({icon:Icon,title,body,children}:{icon:typeof Languages;title:string;body:string;children:ReactNode}){return <div><span className="grid size-11 place-items-center rounded-xl border border-accent/30 bg-accent-soft text-accent"><Icon className="size-5"/></span><h1 className="mt-5 text-3xl font-semibold tracking-[-.035em]">{title}</h1><p className="mt-2 max-w-3xl text-xs leading-6 text-copy">{body}</p><div className="mt-7">{children}</div></div>}
function LanguageSelect({label,value,onChange,includeAuto=false}:{label:string;value:string;onChange:(value:string)=>void;includeAuto?:boolean}){const{t}=useI18n();return <label><span className="ui-label">{label}</span><select className="ui-input mt-2" value={value} onChange={event=>onChange(event.target.value)}>{includeAuto&&<option value="auto">{t("common.auto")}</option>}{languages.map(language=><option key={language.id} value={language.id}>{language.native}</option>)}</select></label>}
function Hardware({icon:Icon,label,value}:{icon:typeof Cpu;label:string;value:string}){return <article className="min-h-28 bg-surface p-4"><Icon className="size-4 text-accent"/><small className="mt-4 block text-[10px] uppercase tracking-[.1em] text-muted">{label}</small><strong className="mt-1 block line-clamp-2 text-xs">{value}</strong></article>}
function FeatureRow({icon:Icon,title,body,tone}:{icon:typeof Gauge;title:string;body:string;tone:"accent"|"success"|"sync"}){return <article className="grid min-h-24 grid-cols-[52px_minmax(0,1fr)] items-center gap-4 py-4"><span className={cn("grid size-11 place-items-center rounded-xl border bg-raised",tone==="accent"&&"border-accent/30 text-accent",tone==="success"&&"border-success/30 text-success",tone==="sync"&&"border-sync/30 text-sync")}><Icon className="size-5"/></span><div><strong className="text-sm">{title}</strong><p className="mt-1 max-w-2xl text-[11px] leading-5 text-copy">{body}</p></div></article>}
function ReadyAction({icon:Icon,title,body,onClick}:{icon:typeof Film;title:string;body:string;onClick:()=>void}){return <button onClick={onClick} className="group flex min-h-28 items-center gap-4 rounded-xl border border-line bg-surface p-4 text-left transition-colors hover:border-accent/60 hover:bg-raised"><span className="grid size-12 place-items-center rounded-xl bg-accent-soft text-accent"><Icon className="size-5"/></span><span className="min-w-0"><strong className="text-sm">{title}</strong><small className="mt-1 block text-[11px] leading-5 text-copy">{body}</small></span><ChevronRight className="ml-auto size-5 text-muted transition-transform group-hover:translate-x-1 group-hover:text-accent"/></button>}
function formatBytes(value:number){return value?`${(value/1024/1024/1024).toFixed(1)} GB`:"—"}

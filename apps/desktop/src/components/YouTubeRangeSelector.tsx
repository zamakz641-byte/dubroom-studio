import {Clock3,Film,Scissors} from "lucide-react";
import {useI18n} from "@/i18n";

export type YouTubeRangeMode="full"|"excerpt";

type Props={
  duration?:number|null;
  mode:YouTubeRangeMode;
  start:string;
  end:string;
  compact?:boolean;
  onMode:(mode:YouTubeRangeMode)=>void;
  onStart:(value:string)=>void;
  onEnd:(value:string)=>void;
};

export function YouTubeRangeSelector({duration,mode,start,end,compact=false,onMode,onStart,onEnd}:Props){
  const{t}=useI18n();
  return <section className={`rounded-xl border border-line bg-canvas/60 ${compact?"p-3":"p-4"}`}>
    <div className="flex items-center justify-between gap-3">
      <div>
        <span className="ui-kicker">{t("youtubeRange.title")}</span>
        <p className="mt-1 text-[10px] text-muted">{t("youtubeRange.body")}</p>
      </div>
      {duration?<span className="ui-chip font-mono"><Clock3/>{formatTimecode(duration)}</span>:null}
    </div>
    <div className="mt-3 grid grid-cols-2 gap-2">
      <button type="button" className={`ui-button justify-center ${mode==="full"?"border-accent bg-accent/10 text-accent":""}`} onClick={()=>onMode("full")}><Film/>{t("youtubeRange.full")}</button>
      <button type="button" className={`ui-button justify-center ${mode==="excerpt"?"border-accent bg-accent/10 text-accent":""}`} onClick={()=>onMode("excerpt")}><Scissors/>{t("youtubeRange.excerpt")}</button>
    </div>
    {mode==="excerpt"&&<div className="mt-3 grid grid-cols-2 gap-3">
      <label>
        <span className="ui-label">{t("youtubeRange.start")}</span>
        <input className="ui-input mt-1 font-mono" inputMode="decimal" value={start} onChange={event=>onStart(event.target.value)} placeholder="00:00"/>
      </label>
      <label>
        <span className="ui-label">{t("youtubeRange.end")}</span>
        <input className="ui-input mt-1 font-mono" inputMode="decimal" value={end} onChange={event=>onEnd(event.target.value)} placeholder="00:15"/>
      </label>
      <p className="col-span-2 text-[9px] text-muted">{t("youtubeRange.hint")}</p>
    </div>}
  </section>;
}

export function parseTimecode(value:string):number|null{
  const candidate=value.trim().replace(",",".");
  if(!candidate)return null;
  if(/^\d+(?:\.\d+)?$/.test(candidate))return Number(candidate);
  const parts=candidate.split(":");
  if(parts.length<2||parts.length>3||parts.some(part=>!part||!/^\d+(?:\.\d+)?$/.test(part)))return null;
  const values=parts.map(Number);
  if(values.slice(1).some(value=>value>=60))return null;
  return parts.length===3?values[0]*3600+values[1]*60+values[2]:values[0]*60+values[1];
}

export function formatTimecode(value:number):string{
  const seconds=Math.max(0,Math.floor(value));
  const hours=Math.floor(seconds/3600);
  const minutes=Math.floor((seconds%3600)/60);
  const rest=seconds%60;
  return hours?`${hours}:${String(minutes).padStart(2,"0")}:${String(rest).padStart(2,"0")}`:`${String(minutes).padStart(2,"0")}:${String(rest).padStart(2,"0")}`;
}

export function validateYouTubeRange(mode:YouTubeRangeMode,start:string,end:string,duration?:number|null):{startSeconds:number|null;endSeconds:number|null;valid:boolean}{
  if(mode==="full")return{startSeconds:null,endSeconds:null,valid:true};
  const startSeconds=parseTimecode(start);
  const endSeconds=parseTimecode(end);
  const valid=startSeconds!==null&&endSeconds!==null&&startSeconds>=0&&endSeconds-startSeconds>=.5&&(!duration||endSeconds<=duration+.5);
  return{startSeconds,endSeconds,valid};
}

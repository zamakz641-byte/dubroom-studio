import {useEffect,useState} from "react";
import type {RuntimeStatus} from "@/types";

export type PerformanceProfile="fluid"|"balanced"|"economy";

function initialProfile(runtime:RuntimeStatus|null):PerformanceProfile{
  const threads=runtime?.hardware.cpu_threads||navigator.hardwareConcurrency||4;
  const memory=runtime?.hardware.memory?.total_bytes||0;
  const hasGpu=Boolean(runtime?.hardware.cuda?.name);
  if((hasGpu&&threads>=8)||(threads>=12&&memory>=16*1024**3))return "fluid";
  if(threads>=6&&(!memory||memory>=8*1024**3))return "balanced";
  return "economy";
}

export function useAdaptivePerformance(runtime:RuntimeStatus|null){
  const[profile,setProfile]=useState<PerformanceProfile>(()=>initialProfile(runtime));

  useEffect(()=>{
    const sync=()=>{const override=localStorage.getItem("dubroom.performanceProfile");setProfile(override&&override!=="auto"?override as PerformanceProfile:initialProfile(runtime))};
    sync();window.addEventListener("dubroom:performance",sync);
    return()=>window.removeEventListener("dubroom:performance",sync);
  },[runtime]);

  useEffect(()=>{
    document.documentElement.dataset.performance=profile;
    let frame=0;let started=performance.now();let raf=0;let samples=0;
    const measure=(now:number)=>{
      if(document.hidden){frame=0;started=now;raf=requestAnimationFrame(measure);return;}
      frame+=1;
      if(now-started>=2000){
        const fps=frame*1000/(now-started);samples+=1;
        document.documentElement.style.setProperty("--measured-fps",String(Math.round(fps)));
        const override=localStorage.getItem("dubroom.performanceProfile");
        if(!override||override==="auto"){
          if(samples>=2&&fps<38)setProfile("economy");
          else if(samples>=2&&fps<52&&profile==="fluid")setProfile("balanced");
        }
        frame=0;started=now;
      }
      raf=requestAnimationFrame(measure);
    };
    raf=requestAnimationFrame(measure);
    return()=>cancelAnimationFrame(raf);
  },[profile]);

  return profile;
}

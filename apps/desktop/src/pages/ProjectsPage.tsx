import {ArrowRight,ChevronDown,Filter,FolderOpen,FolderPlus,Languages,MoreHorizontal,RotateCcw,Search,Trash2,X} from "lucide-react";
import {useEffect,useMemo,useState} from "react";
import {PageHeader} from "@/components/PageHeader";
import {api} from "@/lib/api";
import {useI18n} from "@/i18n";
import type {ProjectRecord,TrashProjectRecord} from "@/types";

type Props={projects:ProjectRecord[];activeProjectId?:string|null;onImport:()=>void;onOpen:(p:ProjectRecord)=>void;onDeleted:(id:string)=>Promise<void>;onRestored:()=>Promise<void>};
type Sort="recent"|"oldest"|"name";

export function ProjectsPage({projects,activeProjectId,onImport,onOpen,onDeleted,onRestored}:Props){
  const{t,date}=useI18n();
  const[query,setQuery]=useState("");const[filtersOpen,setFiltersOpen]=useState(false);const[trashMode,setTrashMode]=useState(false);
  const[status,setStatus]=useState("all");const[source,setSource]=useState("all");const[target,setTarget]=useState("all");const[origin,setOrigin]=useState("all");const[sort,setSort]=useState<Sort>("recent");
  const[menu,setMenu]=useState<string|null>(null);const[trash,setTrash]=useState<TrashProjectRecord[]>([]);const[busy,setBusy]=useState<string|null>(null);
  useEffect(()=>{if(trashMode)void api.trashProjects().then(setTrash)},[trashMode]);
  const languages=useMemo(()=>Array.from(new Set(projects.flatMap(item=>[item.source_language,item.target_language]).filter(Boolean) as string[])).sort(),[projects]);
  const visible=useMemo(()=>projects.filter(project=>{
    const text=`${project.name} ${project.id}`.toLowerCase();
    if(query&&!text.includes(query.toLowerCase()))return false;
    if(status!=="all"&&project.status!==status)return false;
    if(source!=="all"&&project.source_language!==source)return false;
    if(target!=="all"&&project.target_language!==target)return false;
    const youtube=(project.original_source_path||project.source_path||"").toLowerCase().includes("youtube");
    if(origin==="youtube"&&!youtube)return false;if(origin==="local"&&youtube)return false;
    return true;
  }).sort((a,b)=>sort==="name"?a.name.localeCompare(b.name):sort==="oldest"?a.updated_at.localeCompare(b.updated_at):b.updated_at.localeCompare(a.updated_at)),[projects,query,status,source,target,origin,sort]);
  const chips=[status!=="all"&&[t("common.status"),t(`projects.status.${status}`),()=>setStatus("all")],source!=="all"&&[t("common.source"),source,()=>setSource("all")],target!=="all"&&[t("common.target"),target,()=>setTarget("all")],origin!=="all"&&[t("common.source"),origin,()=>setOrigin("all")]].filter(Boolean) as [string,string,()=>void][];
  const remove=async(project:ProjectRecord)=>{if(!confirm(t("projects.deleteConfirm",{name:project.name})))return;setBusy(project.id);try{await onDeleted(project.id)}finally{setBusy(null);setMenu(null)}};
  const restore=async(item:TrashProjectRecord)=>{setBusy(item.trash_id);try{await api.restoreProject(item.trash_id);setTrash(current=>current.filter(row=>row.trash_id!==item.trash_id));await onRestored()}finally{setBusy(null)}};
  const purge=async(item:TrashProjectRecord)=>{if(!confirm(t("projects.deleteForeverConfirm",{name:item.project.name})))return;setBusy(item.trash_id);try{await api.permanentlyDeleteProject(item.trash_id);setTrash(current=>current.filter(row=>row.trash_id!==item.trash_id))}finally{setBusy(null)}};

  return <div data-testid="projects-page" className="flex h-full min-h-0 flex-col overflow-hidden">
    <PageHeader kicker={t("projects.kicker")} title={trashMode?t("projects.trash"):t("projects.title")} description={trashMode?t("projects.trashBody"):t("projects.description")} actions={<>
      <button className="ui-button" onClick={()=>setTrashMode(value=>!value)}>{trashMode?<RotateCcw/>:<Trash2/>}{trashMode?t("projects.backToProjects"):t("projects.trash")}</button>
      {!trashMode&&<button className="ui-button ui-button-primary" onClick={onImport}><FolderPlus/>{t("projects.new")}</button>}
    </>}/>
    <div className="flex min-h-0 flex-1 flex-col px-8 py-5">
      {!trashMode&&<><div className="relative flex items-center gap-2">
        <label className="flex h-9 min-w-72 flex-1 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-muted focus-within:border-accent"><Search className="size-4"/><input className="min-w-0 flex-1 bg-transparent text-[12px] text-foreground outline-none" placeholder={t("projects.search")} value={query} onChange={event=>setQuery(event.target.value)}/></label>
        <button className="ui-button" aria-expanded={filtersOpen} onClick={()=>setFiltersOpen(value=>!value)}><Filter/>{t("common.filters")}{chips.length>0&&<span className="rounded-full bg-accent px-1.5 text-[10px] text-white">{chips.length}</span>}<ChevronDown/></button>
        <select className="ui-input w-40" value={sort} onChange={event=>setSort(event.target.value as Sort)}><option value="recent">{t("projects.sortRecent")}</option><option value="oldest">{t("projects.sortOldest")}</option><option value="name">A–Z</option></select>
        <span className="w-24 text-right text-[11px] text-muted">{visible.length} {t(visible.length===1?"common.project":"common.projects")}</span>
        {filtersOpen&&<div className="absolute right-28 top-11 z-30 grid w-[560px] grid-cols-2 gap-4 rounded-xl border border-line bg-raised p-4 shadow-2xl">
          <FilterField label={t("common.status")} value={status} onChange={setStatus} options={Array.from(new Set(projects.map(item=>item.status)))}/><FilterField label={t("common.sourceLanguage")} value={source} onChange={setSource} options={languages}/><FilterField label={t("common.targetLanguage")} value={target} onChange={setTarget} options={languages}/><FilterField label={t("common.source")} value={origin} onChange={setOrigin} options={["local","youtube"]}/>
        </div>}
      </div>{chips.length>0&&<div className="mt-3 flex flex-wrap gap-2">{chips.map(([label,value,clear])=><button key={label} className="ui-chip" onClick={clear}><span className="text-muted">{label}</span>{value}<X className="size-3"/></button>)}</div>}</>}

      <div className="mt-4 min-h-0 flex-1 overflow-auto rounded-xl border border-line bg-surface">
        <div className="sticky top-0 z-10 grid grid-cols-[minmax(260px,1.6fr)_1fr_120px_170px_44px] border-b border-line bg-surface/95 px-4 py-2 text-[10px] font-semibold uppercase tracking-[.14em] text-muted backdrop-blur">
          <span>{t("projects.column")}</span><span>{t("common.languages")}</span><span>{t("common.status")}</span><span>{t("common.lastActivity")}</span><span/>
        </div>
        {(trashMode?trash.map(item=>({project:item.project,trash:item})):visible.map(project=>({project,trash:null}))).map(({project,trash:item})=><div key={item?.trash_id||project.id} className="group grid min-h-16 grid-cols-[minmax(260px,1.6fr)_1fr_120px_170px_44px] items-center border-b border-line/70 px-4 text-left transition-colors hover:bg-raised">
          <button className="flex min-w-0 items-center gap-3 text-left" onClick={()=>!item&&onOpen(project)} disabled={!!item}><span className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-canvas font-mono text-[11px] font-bold text-accent">{project.name.slice(0,2).toUpperCase()}</span><span className="min-w-0"><strong className="block truncate text-[13px] font-semibold text-foreground">{project.name}</strong><small className="block truncate font-mono text-[10px] text-muted">{project.id}{activeProjectId===project.id?` · ${t("shell.activeProject")}`:""}</small></span></button>
          <span className="flex items-center gap-2 text-[12px] text-copy"><Languages className="size-3.5 text-muted"/>{project.source_language||t("common.auto")} <ArrowRight className="size-3"/> {project.target_language||t("common.undefined")}</span>
          <span><i className="ui-chip not-italic">{t(`projects.status.${project.status}`)}</i></span><span className="text-[11px] text-copy">{date(item?.deleted_at||project.updated_at,{dateStyle:"medium",timeStyle:"short"})}</span>
          <div className="relative">{item?<div className="flex justify-end gap-1"><button className="ui-icon-button" title={t("projects.restore")} disabled={busy===item.trash_id} onClick={()=>void restore(item)}><RotateCcw/></button><button className="ui-icon-button text-danger" title={t("projects.deleteForever")} disabled={busy===item.trash_id} onClick={()=>void purge(item)}><Trash2/></button></div>:<><button className="ui-icon-button" onClick={()=>setMenu(menu===project.id?null:project.id)}><MoreHorizontal/></button>{menu===project.id&&<div className="absolute right-0 top-9 z-20 w-48 rounded-lg border border-line bg-raised p-1 shadow-2xl"><button className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-[12px] hover:bg-surface" onClick={()=>onOpen(project)}><ArrowRight/>{t("common.open")}</button><button className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-[12px] hover:bg-surface" onClick={()=>void window.dubStudio?.revealPath(project.project_dir)}><FolderOpen/>{t("projects.reveal")}</button><button className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-[12px] text-danger hover:bg-danger/10" disabled={busy===project.id} onClick={()=>void remove(project)}><Trash2/>{t("common.delete")}</button></div>}</>}</div>
        </div>)}
        {(trashMode?trash.length===0:visible.length===0)&&<div className="grid min-h-64 place-items-center text-center"><div><Trash2 className="mx-auto mb-3 size-7 text-muted"/><strong className="text-[13px]">{trashMode?t("projects.trashEmpty"):t("projects.noResult")}</strong><p className="mt-1 text-[11px] text-muted">{trashMode?t("projects.trashEmptyBody"):t("projects.noResultBody")}</p></div></div>}
      </div>
    </div>
  </div>;
}

function FilterField({label,value,onChange,options}:{label:string;value:string;onChange:(value:string)=>void;options:string[]}){const{t}=useI18n();return <label className="grid gap-1.5"><span className="ui-label">{label}</span><select className="ui-input" value={value} onChange={event=>onChange(event.target.value)}><option value="all">{t("common.all")}</option>{options.map(option=><option key={option} value={option}>{label===t("common.status")?t(`projects.status.${option}`):option}</option>)}</select></label>}

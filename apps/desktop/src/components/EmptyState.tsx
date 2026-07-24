import type {LucideIcon} from "lucide-react";
export function EmptyState({icon:Icon,title,description,action}:{icon:LucideIcon;title:string;description:string;action?:React.ReactNode}){
  return <div className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed border-line bg-surface/40 px-8 text-center">
    <span className="mb-4 grid size-11 place-items-center rounded-xl border border-line bg-raised text-muted"><Icon className="size-5"/></span>
    <h3 className="text-[15px] font-semibold text-foreground">{title}</h3>
    <p className="mt-1 max-w-md text-[12px] leading-5 text-copy">{description}</p>
    {action&&<div className="mt-5">{action}</div>}
  </div>;
}

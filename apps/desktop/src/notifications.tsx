import {createContext,useContext,useEffect,useMemo,useState,type ReactNode} from "react";

export type NoticeTone="info"|"success"|"warning"|"error";
export interface Notice{id:string;title:string;body:string;tone:NoticeTone;createdAt:string;read:boolean}
type NotificationContextValue={items:Notice[];unread:number;push:(title:string,body:string,tone?:NoticeTone)=>void;markAllRead:()=>void;clear:()=>void};
const Context=createContext<NotificationContextValue|null>(null);
const STORAGE_KEY="dubroom.notifications";

export function NotificationProvider({children}:{children:ReactNode}){
  const [items,setItems]=useState<Notice[]>(()=>{try{return JSON.parse(localStorage.getItem(STORAGE_KEY)||"[]");}catch{return[];}});
  const push=(title:string,body:string,tone:NoticeTone="info")=>setItems(current=>[{id:crypto.randomUUID(),title,body,tone,createdAt:new Date().toISOString(),read:false},...current].slice(0,50));
  useEffect(()=>{localStorage.setItem(STORAGE_KEY,JSON.stringify(items));},[items]);
  useEffect(()=>{const handler=(event:Event)=>{const detail=(event as CustomEvent<{title:string;body:string;tone?:NoticeTone}>).detail;if(detail)push(detail.title,detail.body,detail.tone);};window.addEventListener("dubroom:notify",handler);return()=>window.removeEventListener("dubroom:notify",handler);},[]);
  const value=useMemo(()=>({items,unread:items.filter(item=>!item.read).length,push,markAllRead:()=>setItems(current=>current.map(item=>({...item,read:true}))),clear:()=>setItems([])}),[items]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useNotifications(){const value=useContext(Context);if(!value)throw new Error("NotificationProvider missing");return value;}
export function notify(title:string,body:string,tone:NoticeTone="info"){window.dispatchEvent(new CustomEvent("dubroom:notify",{detail:{title,body,tone}}));}

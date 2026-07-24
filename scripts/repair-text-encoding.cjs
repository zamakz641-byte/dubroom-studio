const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const roots = [path.join(root, "apps", "desktop", "src"), path.join(root, "services", "api", "app")];
const extensions = new Set([".ts", ".tsx", ".py", ".json"]);
const reverse1252 = new Map([
  [0x20ac,0x80],[0x201a,0x82],[0x0192,0x83],[0x201e,0x84],[0x2026,0x85],[0x2020,0x86],[0x2021,0x87],
  [0x02c6,0x88],[0x2030,0x89],[0x0160,0x8a],[0x2039,0x8b],[0x0152,0x8c],[0x017d,0x8e],[0x2018,0x91],
  [0x2019,0x92],[0x201c,0x93],[0x201d,0x94],[0x2022,0x95],[0x2013,0x96],[0x2014,0x97],[0x02dc,0x98],
  [0x2122,0x99],[0x0161,0x9a],[0x203a,0x9b],[0x0153,0x9c],[0x017e,0x9e],[0x0178,0x9f],
]);
const signal = /(?:Ã.|Â.|â(?:€|€™|€”|€¦|†|‡|ˆ|‰|Š|‹|Œ|Ž|‘|’|“|”|•|–|—|˜|™|š|›|œ|ž|Ÿ|†’)|ðŸ|ï¿|Ø.|Ù.|ã.|æ.|å.|ë.|ì.)/g;

function score(value){ return (value.match(signal)||[]).length; }
function decode1252(value){
  const bytes=[];
  for(const character of value){
    const point=character.codePointAt(0);
    if(point<=0xff)bytes.push(point);
    else if(reverse1252.has(point))bytes.push(reverse1252.get(point));
    else return null;
  }
  const decoded=Buffer.from(bytes).toString("utf8");
  return decoded.includes("�")?null:decoded;
}
function repair(value){
  let current=value;
  for(let attempt=0;attempt<3;attempt+=1){
    const decoded=decode1252(current);
    if(!decoded||score(decoded)>=score(current))break;
    current=decoded;
  }
  return current;
}
function files(directory){
  return fs.readdirSync(directory,{withFileTypes:true}).flatMap(entry=>{
    const target=path.join(directory,entry.name);
    return entry.isDirectory()&&!entry.name.startsWith("__pycache__")?files(target):entry.isFile()&&extensions.has(path.extname(entry.name))?[target]:[];
  });
}

let changed=0;
for(const file of roots.flatMap(files)){
  const source=fs.readFileSync(file,"utf8");
  const repaired=source.replace(/(["'`])((?:\\.|(?!\1)[\s\S])*?)\1/g,(match,quote,body)=>{
    if(!score(body))return match;
    const next=repair(body);
    return `${quote}${next}${quote}`;
  });
  if(repaired!==source){fs.writeFileSync(file,repaired,"utf8");changed+=1;console.log(path.relative(root,file));}
}
console.log(`Repaired ${changed} source files`);

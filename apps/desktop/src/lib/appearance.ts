export type ThemeId="graphite"|"oled"|"warm"|"light";
export type DensityId="compact"|"comfortable"|"spacious";
const themes:ThemeId[]=["graphite","oled","warm","light"];
export function appearance(){const saved=localStorage.getItem("dubroom.theme") as ThemeId|null;return{theme:themes.includes(saved as ThemeId)?saved as ThemeId:"graphite",density:(localStorage.getItem("dubroom.density")||"comfortable") as DensityId,reducedMotion:localStorage.getItem("dubroom.reducedMotion")==="true"};}
export function applyAppearance(theme:ThemeId,density:DensityId,reducedMotion:boolean){localStorage.setItem("dubroom.theme",theme);localStorage.setItem("dubroom.density",density);localStorage.setItem("dubroom.reducedMotion",String(reducedMotion));document.documentElement.dataset.theme=theme;document.documentElement.dataset.density=density;document.documentElement.dataset.reducedMotion=String(reducedMotion);}

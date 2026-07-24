const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("dubStudio", {
  openVideo: () => ipcRenderer.invoke("dialog:openVideo"),
  openAudio: () => ipcRenderer.invoke("dialog:openAudio"),
  openRvcModel: () => ipcRenderer.invoke("dialog:openRvcModel"),
  openRvcIndex: () => ipcRenderer.invoke("dialog:openRvcIndex"),
  getRuntimeConfig: () => ipcRenderer.invoke("app:runtimeConfig"),
  revealPath: (path) => ipcRenderer.invoke("app:revealPath", path),
  setTitleBarTheme: (palette) => ipcRenderer.invoke("window:setTitleBarTheme", palette)
});

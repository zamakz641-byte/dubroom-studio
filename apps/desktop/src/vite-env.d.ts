/// <reference types="vite/client" />

interface Window {
  dubStudio?: {
    openVideo: () => Promise<string | null>;
    openAudio: () => Promise<string | null>;
    openTranscript: () => Promise<string | null>;
    openRvcModel: () => Promise<string | null>;
    openRvcIndex: () => Promise<string | null>;
    getRuntimeConfig: () => Promise<{ apiBaseUrl: string; workspaceRoot: string }>;
    restartApp: () => Promise<boolean>;
    revealPath: (path: string) => Promise<boolean>;
    setTitleBarTheme: (palette: {
      color: string;
      symbolColor: string;
    }) => Promise<boolean>;
  };
}

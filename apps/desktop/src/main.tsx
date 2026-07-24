import React from "react";
import { createRoot } from "react-dom/client";
import App, { AppErrorBoundary } from "./App";
import "./app.css";
import { Toaster } from "sonner";
import { I18nProvider } from "./i18n";
import { NotificationProvider } from "./notifications";
import { ScrollBridge } from "./ScrollBridge";
import { applyAppearance, appearance } from "./lib/appearance";

const savedAppearance = appearance();
applyAppearance(savedAppearance.theme, savedAppearance.density, savedAppearance.reducedMotion);

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <I18nProvider>
      <NotificationProvider><AppErrorBoundary>
          <ScrollBridge />
          <App />
          <Toaster position="bottom-right" theme="dark" richColors />
      </AppErrorBoundary></NotificationProvider>
    </I18nProvider>
  </React.StrictMode>
);

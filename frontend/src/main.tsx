import "@cloudscape-design/global-styles/index.css";
import "@xyflow/react/dist/style.css";
import { I18nProvider } from "@cloudscape-design/components/i18n";
import messages from "@cloudscape-design/components/i18n/messages/all.en";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import App from "./App";

// I18nProvider supplies the built-in strings for the property filter, date picker, and charts.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nProvider locale="en" messages={[messages]}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </I18nProvider>
  </StrictMode>,
);

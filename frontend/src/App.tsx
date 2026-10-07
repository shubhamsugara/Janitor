import { useCallback, useEffect, useMemo, useState } from "react";
import { Route, Routes, useLocation, useNavigate } from "react-router";
import Alert from "@cloudscape-design/components/alert";
import AppLayout from "@cloudscape-design/components/app-layout";
import Box from "@cloudscape-design/components/box";
import Flashbar, { type FlashbarProps } from "@cloudscape-design/components/flashbar";
import SideNavigation, { type SideNavigationProps } from "@cloudscape-design/components/side-navigation";
import Spinner from "@cloudscape-design/components/spinner";
import SplitPanel from "@cloudscape-design/components/split-panel";
import { api, runScan, type Meta } from "./api";
import ResourcePanel from "./components/ResourcePanel";
import TopBar from "./components/TopBar";
import { DetailContext, type DetailApi } from "./detail";
import { TYPE_PAGES, type Notify } from "./nav";
import Audit from "./pages/Audit";
import HowItWorks from "./pages/HowItWorks";
import Overview from "./pages/Overview";
import Resources from "./pages/Resources";
import { applyTheme, savedTheme, type Theme } from "./theme";

const NAV_ITEMS: SideNavigationProps.Item[] = [
  { type: "link", text: "Overview", href: "/" },
  {
    type: "section",
    text: "Resources",
    items: TYPE_PAGES.map((p) => ({ type: "link" as const, text: p.title, href: p.path })),
  },
  { type: "divider" },
  { type: "link", text: "Audit", href: "/audit" },
  { type: "link", text: "How Janitor decides", href: "/how-it-works" },
];

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<FlashbarProps.MessageDefinition[]>([]);
  const [theme, setTheme] = useState<Theme>(savedTheme);
  const [scanning, setScanning] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [panelSize, setPanelSize] = useState(560);

  const notify: Notify = useCallback((type, content) => {
    const id = `${Date.now()}-${Math.random()}`;
    const dismiss = () => setFlash((items) => items.filter((i) => i.id !== id));
    setFlash((items) => [...items, { id, type, content, dismissible: true, onDismiss: dismiss }]);
  }, []);

  useEffect(() => {
    api.meta().then(setMeta).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => applyTheme(theme), [theme]);
  // A panel belongs to the page it was opened on.
  useEffect(() => setSelectedId(null), [location.pathname]);

  const detailApi: DetailApi = useMemo(
    () => ({ selectedId, open: setSelectedId, close: () => setSelectedId(null) }),
    [selectedId],
  );

  async function scan() {
    setScanning(true);
    try {
      await runScan();
      setRefreshKey((key) => key + 1); // remount the page so it reloads
      notify("success", "Scan finished.");
    } catch (e) {
      notify("error", (e as Error).message);
    } finally {
      setScanning(false);
    }
  }

  let content;
  if (error) {
    content = (
      <Alert type="error" header="Janitor can't reach its server">
        {error} Start the backend with make dev, then reload the page.
      </Alert>
    );
  } else if (!meta) {
    content = <Spinner size="large" />;
  } else {
    content = (
      <Routes key={refreshKey}>
        <Route path="/" element={<Overview meta={meta} notify={notify} />} />
        {TYPE_PAGES.map((p) => (
          <Route
            key={p.type}
            path={p.path}
            element={<Resources key={p.type} meta={meta} notify={notify} type={p.type} title={p.title} />}
          />
        ))}
        <Route path="/audit" element={<Audit meta={meta} notify={notify} />} />
        <Route path="/how-it-works" element={<HowItWorks meta={meta} notify={notify} />} />
        <Route path="*" element={<Box>This page doesn't exist. Choose a page from the navigation.</Box>} />
      </Routes>
    );
  }

  return (
    <DetailContext.Provider value={detailApi}>
      <div id="top-nav" style={{ position: "sticky", top: 0, zIndex: 1002 }}>
        <TopBar
          meta={meta}
          theme={theme}
          scanning={scanning}
          onScan={scan}
          onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
        />
      </div>
      <AppLayout
        headerSelector="#top-nav"
        navigation={
          <SideNavigation
            header={{ text: "Resources and audit", href: "/" }}
            activeHref={location.pathname}
            items={NAV_ITEMS}
            onFollow={(event) => {
              if (!event.detail.external) {
                event.preventDefault();
                navigate(event.detail.href);
              }
            }}
          />
        }
        notifications={<Flashbar items={flash} />}
        toolsHide
        content={content}
        splitPanel={
          selectedId && meta ? (
            <SplitPanel header="Resource details" closeBehavior="hide">
              <ResourcePanel id={selectedId} meta={meta} dark={theme === "dark"} onSelect={setSelectedId} />
            </SplitPanel>
          ) : undefined
        }
        splitPanelOpen={Boolean(selectedId)}
        onSplitPanelToggle={({ detail }) => {
          if (!detail.open) setSelectedId(null);
        }}
        splitPanelSize={panelSize}
        onSplitPanelResize={({ detail }) => setPanelSize(detail.size)}
      />
    </DetailContext.Provider>
  );
}

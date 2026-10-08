import { useCallback, useEffect, useMemo, useState } from "react";
import { Route, Routes, useLocation } from "react-router";
import { api, runScan, type Meta } from "./api";
import ResourcePanel from "./components/ResourcePanel";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";
import { DetailContext, type DetailApi } from "./detail";
import { TYPE_PAGES } from "./nav";
import Audit from "./pages/Audit";
import Deployments from "./pages/Deployments";
import HowItWorks from "./pages/HowItWorks";
import Overview from "./pages/Overview";
import Resources from "./pages/Resources";
import { applyTheme, savedTheme, type Theme } from "./theme";
import { Card, CardBody } from "./ui/card";
import { Sheet } from "./ui/sheet";
import { Spinner } from "./ui/spinner";
import { useToast } from "./ui/toast";

const TITLES: Record<string, string> = {
  "/": "Overview",
  "/audit": "Audit",
  "/deployments": "Deployments",
  "/how-it-works": "How Janitor decides",
  ...Object.fromEntries(TYPE_PAGES.map((p) => [p.path, p.title])),
};

function savedCollapsed(): boolean {
  try {
    return localStorage.getItem("janitor:sidebar") === "collapsed";
  } catch {
    return false;
  }
}

export default function App() {
  const location = useLocation();
  const notify = useToast();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(savedTheme);
  const [collapsed, setCollapsed] = useState(savedCollapsed);
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [partial, setPartial] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Reloaded after each scan: accounts are discovered during scans, and the filters list them.
  useEffect(() => {
    api.meta().then(setMeta).catch((e: Error) => setError(e.message));
  }, [refreshKey]);
  useEffect(() => applyTheme(theme), [theme]);
  // The badge reflects the newest scan; it updates on load and after each scan.
  useEffect(() => {
    api
      .latestScan()
      .then(({ scan }) => setPartial(scan?.status === "partial"))
      .catch(() => setPartial(false));
  }, [refreshKey]);
  // A drawer belongs to the page it was opened on.
  useEffect(() => setSelectedId(null), [location.pathname]);

  const toggleSidebar = useCallback(() => {
    setCollapsed((c) => {
      try {
        localStorage.setItem("janitor:sidebar", c ? "open" : "collapsed");
      } catch {
        // not remembered
      }
      return !c;
    });
  }, []);

  const detailApi: DetailApi = useMemo(
    () => ({ selectedId, open: setSelectedId, close: () => setSelectedId(null) }),
    [selectedId],
  );

  async function scan() {
    setScanning(true);
    setProgress(null);
    try {
      await runScan(setProgress);
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
      <Card className="border-red-500/30">
        <CardBody>
          <div className="font-semibold">Janitor can't reach its server</div>
          <p className="mt-1 text-muted">{error} Start the backend with make dev, then reload the page.</p>
        </CardBody>
      </Card>
    );
  } else if (!meta) {
    content = <Spinner label="Loading Janitor" className="py-24 justify-center" />;
  } else {
    content = (
      <Routes key={refreshKey}>
        <Route path="/" element={<Overview meta={meta} notify={notify} />} />
        {TYPE_PAGES.map((p) => (
          <Route key={p.type} path={p.path} element={<Resources key={p.type} meta={meta} notify={notify} type={p.type} title={p.title} />} />
        ))}
        <Route path="/deployments" element={<Deployments meta={meta} notify={notify} />} />
        <Route path="/audit" element={<Audit meta={meta} notify={notify} />} />
        <Route path="/how-it-works" element={<HowItWorks meta={meta} notify={notify} />} />
        <Route path="*" element={<p className="text-muted">This page doesn't exist. Choose a page from the navigation.</p>} />
      </Routes>
    );
  }

  return (
    <DetailContext.Provider value={detailApi}>
      <div className="flex h-full">
        <Sidebar collapsed={collapsed} onToggle={toggleSidebar} />
        <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
          <TopBar
            meta={meta}
            title={TITLES[location.pathname] ?? "Janitor"}
            theme={theme}
            scanning={scanning}
            progress={progress}
            partial={partial}
            onScan={scan}
            onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          />
          <main className="mx-auto w-full max-w-[1400px] flex-1 px-8 py-6">{content}</main>
        </div>
      </div>
      <Sheet open={Boolean(selectedId && meta)} onClose={() => setSelectedId(null)} title="Resource details">
        {selectedId && meta && <ResourcePanel id={selectedId} meta={meta} dark={theme === "dark"} onSelect={setSelectedId} />}
      </Sheet>
    </DetailContext.Provider>
  );
}

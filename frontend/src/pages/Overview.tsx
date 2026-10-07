import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import PieChart from "@cloudscape-design/components/pie-chart";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { api, runScan, type OverviewData, type Stats, type Status } from "../api";
import { STATUS_COLORS } from "../colors";
import { formatDate, formatGiB, formatUsd } from "../format";
import { TYPE_PAGES, type PageProps } from "../nav";

export const SCAN_POLL_MS = 1500;

export default function Overview({ meta, notify }: PageProps) {
  const navigate = useNavigate();
  const [data, setData] = useState<OverviewData | null>(null);
  const [stats, setStats] = useState<Record<string, Stats | null>>({});
  const [scanning, setScanning] = useState(false);

  const load = useCallback(() => {
    api.overview().then(setData).catch((e: Error) => notify("error", e.message));
    Promise.all(TYPE_PAGES.map((p) => api.stats(new URLSearchParams({ type: p.type }))))
      .then((all) => setStats(Object.fromEntries(TYPE_PAGES.map((p, i) => [p.type, all[i]]))))
      .catch(() => setStats({}));
  }, [notify]);
  useEffect(load, [load]);

  // A scan started elsewhere (the top bar, another tab, or at startup) shows as running: keep checking.
  useEffect(() => {
    if (!data?.scanning || scanning) return;
    const timer = setTimeout(load, SCAN_POLL_MS);
    return () => clearTimeout(timer);
  }, [data, scanning, load]);

  async function scan() {
    setScanning(true);
    try {
      await runScan();
      load();
      notify("success", "Scan finished.");
    } catch (e) {
      notify("error", (e as Error).message);
    } finally {
      setScanning(false);
    }
  }

  const source = meta.provider === "mock" ? "Mock data" : "AWS · read-only";
  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          info={<Badge color={meta.provider === "mock" ? "blue" : "green"}>{source}</Badge>}
          description={data?.last_scan ? `Last scan: ${formatDate(data.last_scan.finished_at)}` : undefined}
          actions={
            <Button loading={scanning || data?.scanning} onClick={scan}>
              Scan now
            </Button>
          }
        >
          Overview
        </Header>
      }
    >
      {data && !data.last_scan ? (
        <Container>
          <Box textAlign="center">
            <SpaceBetween size="s">
              <Box variant="h3">No scan yet</Box>
              <Button variant="primary" loading={scanning} onClick={scan}>
                Run first scan
              </Button>
            </SpaceBetween>
          </Box>
        </Container>
      ) : (
        <ColumnLayout columns={4}>
          {TYPE_PAGES.map((page) => {
            const summary = data?.types.find((t) => t.type === page.type);
            const s = stats[page.type];
            return (
              <Container
                key={page.type}
                header={
                  <Header variant="h2">
                    <Link
                      href={page.path}
                      fontSize="heading-m"
                      onFollow={(e) => {
                        e.preventDefault();
                        navigate(page.path);
                      }}
                    >
                      {page.title}
                    </Link>
                  </Header>
                }
              >
                <SpaceBetween size="s">
                  <Box variant="awsui-value-large">{summary ? summary.total.toLocaleString() : "—"}</Box>
                  <Box color="text-body-secondary">
                    {summary
                      ? `${summary.orphaned.toLocaleString()} orphaned · ${formatGiB(summary.orphaned_gib)}` +
                        (summary.orphaned_usd != null ? ` · ${formatUsd(summary.orphaned_usd)}` : "")
                      : "No data"}
                  </Box>
                  {s && s.total > 0 && (
                    <PieChart
                      data={s.by_status.map((b) => ({
                        title: meta.definitions.statuses[b.key as Status]?.label ?? b.key,
                        value: b.count,
                        color: STATUS_COLORS[b.key],
                      }))}
                      variant="donut"
                      size="small"
                      hideFilter
                      hideLegend
                      ariaLabel={`${page.title} by status`}
                      innerMetricValue={s.total.toLocaleString()}
                      innerMetricDescription="total"
                    />
                  )}
                </SpaceBetween>
              </Container>
            );
          })}
        </ColumnLayout>
      )}
    </ContentLayout>
  );
}

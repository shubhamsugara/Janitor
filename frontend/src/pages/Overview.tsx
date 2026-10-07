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
import SpaceBetween from "@cloudscape-design/components/space-between";
import { api, runScan, type OverviewData } from "../api";
import { formatDate, formatGiB, formatUsd } from "../format";
import { TYPE_PAGES, type PageProps } from "../nav";

export default function Overview({ meta, notify }: PageProps) {
  const navigate = useNavigate();
  const [data, setData] = useState<OverviewData | null>(null);
  const [scanning, setScanning] = useState(false);

  const load = useCallback(() => {
    api.overview().then(setData).catch((e: Error) => notify("error", e.message));
  }, [notify]);
  useEffect(load, [load]);

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
            const stats = data?.types.find((t) => t.type === page.type);
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
                <Box variant="awsui-value-large">{stats ? stats.total.toLocaleString() : "—"}</Box>
                <Box color="text-body-secondary">
                  {stats
                    ? `${stats.orphaned.toLocaleString()} orphaned · ${formatGiB(stats.orphaned_gib)}` +
                      (stats.orphaned_usd != null ? ` · ${formatUsd(stats.orphaned_usd)}` : "")
                    : "No data"}
                </Box>
              </Container>
            );
          })}
        </ColumnLayout>
      )}
    </ContentLayout>
  );
}

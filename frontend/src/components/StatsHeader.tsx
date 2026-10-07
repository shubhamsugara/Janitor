import BarChart from "@cloudscape-design/components/bar-chart";
import Box, { type BoxProps } from "@cloudscape-design/components/box";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import PieChart from "@cloudscape-design/components/pie-chart";
import SpaceBetween from "@cloudscape-design/components/space-between";
import type { Bucket, Meta, Stats, Status } from "../api";
import { STATUS_COLORS } from "../colors";
import { accountName, formatGiB, formatMoney } from "../format";

function Metric({ label, value, detail, color }: { label: string; value: string; detail: string; color?: BoxProps.Color }) {
  return (
    <div>
      <Box variant="awsui-key-label">{label}</Box>
      <Box variant="awsui-value-large" color={color}>
        {value}
      </Box>
      <Box color="text-body-secondary" fontSize="body-s">
        {detail}
      </Box>
    </div>
  );
}

function Bars({ title, buckets, label }: { title: string; buckets: Bucket[]; label: (key: string) => string }) {
  return (
    <div>
      <Box variant="h4">{title}</Box>
      <BarChart
        series={[{ title: "Resources", type: "bar", data: buckets.map((b) => ({ x: label(b.key), y: b.count })) }]}
        xScaleType="categorical"
        horizontalBars
        hideFilter
        hideLegend
        height={150}
        ariaLabel={title}
        empty={<Box textAlign="center" color="inherit">No data</Box>}
      />
    </div>
  );
}

/** Headline numbers and breakdowns for the resources that match the current filters. */
export default function StatsHeader({ stats, meta }: { stats: Stats; meta: Meta }) {
  const statusLabel = (key: string) => meta.definitions.statuses[key as Status]?.label ?? key;
  return (
    <Container
      header={
        <Header variant="h2" description="For the resources that match your filters. Costs are monthly estimates.">
          Stats
        </Header>
      }
    >
      <SpaceBetween size="l">
        <ColumnLayout columns={4} variant="text-grid">
          <Metric label="Matching" value={stats.total.toLocaleString()} detail={formatGiB(stats.size_gib)} />
          <Metric label="Orphaned" value={stats.orphaned.toLocaleString()} detail={formatGiB(stats.orphaned_gib)} color="text-status-error" />
          <Metric label="Waste" value={stats.orphaned_usd == null ? "—" : `~${formatMoney(stats.orphaned_usd)}`} detail="Orphaned resources, per month" color="text-status-warning" />
          <Metric label="Blocked · deletable" value={`${stats.blocked.toLocaleString()} · ${stats.deletable.toLocaleString()}`} detail="By the delete rules" />
        </ColumnLayout>
        <ColumnLayout columns={4}>
          <div>
            <Box variant="h4">By status</Box>
            <PieChart
              data={stats.by_status.map((b) => ({ title: statusLabel(b.key), value: b.count, color: STATUS_COLORS[b.key] }))}
              variant="donut"
              size="small"
              hideFilter
              ariaLabel="Resources by status"
              innerMetricValue={stats.total.toLocaleString()}
              innerMetricDescription="total"
              empty={<Box textAlign="center" color="inherit">No data</Box>}
            />
          </div>
          <Bars title="By account" buckets={stats.by_account} label={(key) => accountName(meta, key)} />
          <Bars title="By region" buckets={stats.by_region} label={(key) => key} />
          <Bars title="By age" buckets={stats.by_age} label={(key) => key} />
        </ColumnLayout>
      </SpaceBetween>
    </Container>
  );
}

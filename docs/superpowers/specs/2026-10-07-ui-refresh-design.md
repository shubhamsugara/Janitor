# UI refresh: a modern dashboard instead of the AWS console

Status: approved in chat 2026-10-07 ("Replace Cloudscape", "Clean light, dark toggle"; the user
asked to write spec and plan and apply without waiting for review).

## Goal

Janitor should look like a current SaaS dashboard (Vercel, Stripe, Linear), not the AWS
console. Every phase 2 feature and behavior stays; only the presentation layer changes.

## What the user said

- "It looks like an AWS console; I need it to look modern, not outdated, like the latest design
  used in websites or dashboards nowadays."
- Chose: replace Cloudscape; clean light look with a dark toggle.

## Stack

Remove `@cloudscape-design/components` and `@cloudscape-design/global-styles`. Add, pinned exactly:

| Package | Version | Use |
|---|---|---|
| `tailwindcss` (dev), `@tailwindcss/vite` (dev) | 4.3.3 | Utility styling, design tokens, `dark` class |
| `radix-ui` | 1.7.0 | Dialog, drawer (dialog), popover, tabs, dropdown menu: focus and ARIA handled |
| `recharts`, `react-is` | 3.10.1, 19.3.0 | Donut and bar charts (`react-is` is Recharts' peer) |
| `lucide-react` | 1.52.0 | Interface icons (AWS icons stay on resources) |
| `clsx`, `tailwind-merge` | 2.1.1, 3.7.0 | `cn()` class helper |
| `@fontsource-variable/inter` | 5.3.0 | Inter, bundled (no external font CDN) |

Toasts, the data table, the multi-select filter, and the date-range control are written here (no
extra packages). React Flow, jsPDF, Vitest, and the backend are unchanged.

## Visual language

- Inter; base 14px; sentence case everywhere (copy rules from the base spec §12 still hold).
- Tokens as CSS variables, light and dark: page `#fafafa` / `#09090b`, card `#ffffff` / `#18181b`,
  border `#e4e4e7` / `#27272a`, text `#18181b` / `#fafafa`, muted `#71717a` / `#a1a1aa`, accent
  indigo `#4f46e5` / `#818cf8`.
- Cards: 12px radius, 1px border, faint shadow; generous padding; hover states on rows and nodes.
- Status colors stay the validated `STATUS_COLORS` (phase 2 dataviz ruling); statuses always show a
  dot plus a label, never color alone.
- Dark mode: a `dark` class on `<html>`, set before first paint from the saved choice (no flash).

## Layout

- Left sidebar (240px, collapsible to icons): logo, Overview, the four resource types, Audit,
  How Janitor decides; the active item is highlighted.
- Top bar in the content column: page title, data-source badge, **Scan now**, theme toggle.
- Toasts top-right (success, error, info), dismissible, auto-hide after 6 s.

## Screens

- **Overview:** four KPI cards (type, count, orphaned · GiB · waste, small status donut), each
  linking to its page; "No scan yet" empty state with **Run first scan**; the scan re-poll
  (`SCAN_POLL_MS`) behavior stays.
- **Resource page:**
  - Header: title, count, Export menu (CSV, PDF report), Plan delete.
  - KPI cards: Matching, Orphaned, Waste, Blocked · deletable.
  - Chart card: status donut with legend, account / region / age bars with tooltips.
  - Filter bar: search (debounced), multi-select pills for Account, Status, Region, a Tag
    (`key=value`) pill, a Created date pill with presets (last 30 days, 90 days, 1 year) and a
    custom from/to; Reset filters when any is set. Filters stay in the URL (unchanged `filters.ts`
    contract except the property-filter token helpers, which go).
  - Table: sticky header, sortable columns (server sort), row hover, checkboxes with a page-level
    select-all, status and delete-check pills, pagination; skeleton rows while loading; empty
    states (no scan / no match with Reset / none found).
  - A floating selection bar: "N selected", Clear, Plan delete.
- **Detail drawer:** slides in from the right (min(960px, 94vw)); header with name and status;
  "Used by" callout; tabs Diagram, Details, Cost, Rules, Tags. Diagram nodes use the card style,
  height from `diagramHeight`.
- **Delete dialog:** centered; the three variants, counts, wording, typed confirmation, share
  impact, and missing-ID warning exactly as phase 2.
- **Audit:** card with a table; details expand with native `<details>`.
- **How Janitor decides:** cards and tables in the new style.

## Testing

- Keep every helper test. Port the behavior tests (DeleteModal, StatusBadge, StatsHeader,
  Overview) unchanged in what they assert; only the rendering library changes.
- Drop the two property-filter token tests (that UI is gone).
- New tests: the filter bar (picking a value updates filters and resets the page; Reset clears);
  table selection (select-all selects the page; the bar shows the count).
- Copy-rule test keeps scanning every source file.
- Browser check in light and dark; dataviz palette validation for any new chart color.

## Out of scope

Backend changes, new features, a command palette, mobile-first layouts (the layout must not break
at 1024px wide, and the sidebar collapses).

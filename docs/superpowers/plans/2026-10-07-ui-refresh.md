# UI refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Cloudscape with a Tailwind + Radix component layer so Janitor looks like a modern dashboard, keeping every behavior.

**Architecture:** A small in-repo UI kit (`frontend/src/ui/`) on Tailwind 4 tokens and Radix primitives; Recharts charts in `frontend/src/charts/`; pages and components rewritten on top. Logic modules (`api`, `filters`, `format`, `sequencer`, `graphLayout`, `export/pdfReport`, `detail`) keep their contracts.

**Tech Stack:** React 19, TypeScript 5.9, Vite 8, Tailwind 4.3.3, radix-ui 1.7.0, Recharts 3.10.1, lucide-react 1.52.0, Vitest 5.

**Spec:** [`docs/superpowers/specs/2026-10-07-ui-refresh-design.md`](../specs/2026-10-07-ui-refresh-design.md)

**Execution note (user instruction, 2026-10-07):** "write plan, spec and apply, don't wait for my review." The plan pins tests, interfaces, files, and acceptance checks; component markup is written during execution rather than duplicated here.

## Global Constraints

- Dependencies exactly as the spec's table; nothing else without asking. Remove both Cloudscape packages.
- Copy rules: sentence case; buttons start with a verb; no "successfully", "please", or exclamation marks; errors say what happened, then what to do (`copy.test.ts` enforces part of this).
- Status colors come from `colors.ts` (validated in phase 2); every status shows a dot plus its label.
- No external network assets at runtime (font is bundled; AWS icons stay local and gitignored).
- Work on branch `ui-refresh`; never push without asking.

## Review Focus

1. Dark mode: every surface, border, chart axis, diagram node, and dialog must stay readable → browser check in Task 6.
2. A long resource name or ARN must truncate in table cells and the drawer header, not break the layout → Task 3 table uses `truncate` + `title`.
3. Keyboard: dialogs and the drawer trap focus and close on Esc; dropdowns work with arrows → Radix primitives; browser check.
4. A filter change while a request is in flight must not show stale rows → existing `sequencer` stays in `Resources` (Task 4).
5. 1024px-wide window: sidebar collapses, KPI grid wraps, no horizontal page scroll → Task 6 check.

---

### Task 1: Foundation — dependencies, tokens, UI kit

**Files:** `frontend/package.json`, `frontend/vite.config.ts`, `frontend/index.html`, `frontend/src/index.css` (new), `frontend/src/main.tsx`, `frontend/src/theme.ts`, `frontend/src/test-setup.ts`, `frontend/src/ui/*` (new: `cn.ts`, `button.tsx`, `card.tsx`, `badge.tsx`, `input.tsx`, `dialog.tsx`, `sheet.tsx`, `tabs.tsx`, `dropdown.tsx`, `popover.tsx`, `spinner.tsx`, `toast.tsx`, `table.tsx`, `pills.tsx`).

**Interfaces (produced):**
- `cn(...classes) -> string`
- `Button({variant: "primary"|"secondary"|"ghost"|"danger", size: "sm"|"md"|"icon", loading?})`
- `Card`, `CardHeader({title, description?, actions?})`, `CardBody`
- `Badge({tone: "neutral"|"accent"|"success"|"warning"|"danger"})`
- `Input`, `Dialog({open, onClose, title, footer, children, size?})`, `Sheet({open, onClose, title, children})`
- `Tabs({tabs: {id,label,content}[], value, onChange})`, `Menu({label, items: {id,label}[], onSelect, loading?})`
- `Popover({trigger, children, align?})` (Radix popover wrapper)
- `ToastProvider`, `useToast() -> notify(type, content)` (same `Notify` signature as `nav.ts`)
- `Table` primitives: `Table`, `THead`, `TBody`, `Tr`, `Th({sort?: {active, descending, onClick}})`, `Td`
- `StatusPill({status, label})`, `OutcomePill({outcome})` (dot + label; colors from `colors.ts`)
- `theme.ts`: `savedTheme()`, `applyTheme(theme)` now toggles `dark` on `<html>`

**Steps:**
1. Install: `npm install --save-exact radix-ui@1.7.0 recharts@3.10.1 react-is@19.3.0 lucide-react@1.52.0 clsx@2.1.1 tailwind-merge@3.7.0 @fontsource-variable/inter@5.3.0` and `npm install --save-dev --save-exact tailwindcss@4.3.3 @tailwindcss/vite@4.3.3`. Expected: installs without errors.
2. Failing test `src/ui/ui.test.tsx`:
   - `cn` merges conflicting Tailwind classes (`cn("p-2", "p-4") === "p-4"`).
   - `applyTheme("dark")` adds `dark` to `document.documentElement`; `applyTheme("light")` removes it.
   - `StatusPill` renders its label text.
   Run `npx vitest run src/ui` → FAIL (modules missing).
3. Implement tokens (`index.css`: `@import "tailwindcss"`, `@custom-variant dark`, `@theme inline` mapping CSS variables), Inter import, the kit, the Vite plugin, and a pre-paint theme script in `index.html`. Add a `ResizeObserver` stub to `test-setup.ts` (Radix popper needs it in jsdom).
4. Run `npx vitest run src/ui` → PASS. Commit `feat(ui): Tailwind tokens, Radix-based UI kit, theme on <html>`.

### Task 2: Shell — sidebar, top bar, toasts, drawer host

**Files:** `frontend/src/App.tsx`, `frontend/src/components/Sidebar.tsx` (new), `frontend/src/components/TopBar.tsx`, `frontend/src/main.tsx`.

**Interfaces:** `App` keeps `DetailContext` (`open/close/selectedId`) and passes `notify` from `useToast`; the drawer (`Sheet`) hosts `ResourcePanel`. `TopBar({meta, title, theme, scanning, onScan, onToggleTheme})`.

**Steps:**
1. Failing test `src/components/Shell.test.tsx`: rendering `Sidebar` inside `MemoryRouter` at `/volumes` marks "EBS volumes" with `aria-current="page"`; `TopBar` with `theme="light"` has a button named "Use dark mode" and shows "Mock data".
2. Implement; remove `I18nProvider`. Run the test → PASS. Commit `feat(ui): sidebar, top bar, toasts, and drawer shell`.

### Task 3: Filter bar and data table

**Files:** `frontend/src/filters.ts` (drop `toQuery`/`fromQuery`; local `RangeValue` type replaces the Cloudscape one), `frontend/src/filters.test.ts`, `frontend/src/components/FilterBar.tsx` (new), `frontend/src/components/MultiSelect.tsx` (new), `frontend/src/components/DateFilter.tsx` (new), `frontend/src/components/ResourceTable.tsx` (new).

**Interfaces:**
- `RangeValue = {type:"absolute", startDate, endDate} | {type:"relative", amount, unit:"day"|"week"|"month"|"year", key?}`; `toRange(f) -> RangeValue | null`; `fromRange(value, f, today?)` unchanged behavior.
- `FilterBar({meta, filters, onChange, total})`.
- `ResourceTable({meta, type, items, loading, sort, onSort, selected, onSelect, onOpen, empty})`.

**Steps:**
1. In `filters.test.ts`, delete the "property filter tokens" `describe` block (2 tests). Add `src/components/FilterBar.test.tsx`:
   - opening the Account pill and checking "prd" calls `onChange` with `account: ["333333333333"]` and `page: 1`;
   - with a filter set, "Reset filters" calls `onChange` with `EMPTY` filters (keeping `sort`).
   Add `src/components/ResourceTable.test.tsx`: clicking the header checkbox calls `onSelect` with every row; clicking a name calls `onOpen(id)`.
2. Run → FAIL (components missing). Implement. Run → PASS. Commit `feat(ui): filter bar with multi-select, tag and date pills; data table`.

### Task 4: Resource page, KPI cards, charts

**Files:** `frontend/src/pages/Resources.tsx`, `frontend/src/components/StatsHeader.tsx`, `frontend/src/charts/StatusDonut.tsx` (new), `frontend/src/charts/BarList.tsx` (new), `frontend/src/components/StatusBadge.tsx`.

**Interfaces:** `StatsHeader({stats, meta})` unchanged; `StatusBadge({meta, type, status, reason?})` and `OutcomeBadge({outcome})` unchanged props (Radix popover now).

**Steps:**
1. Existing tests `StatusBadge.test.tsx` and `StatsHeader.test.tsx` are the failing tests once Cloudscape is uninstalled at the end of this task; run them first against the rewrite. Add to `StatsHeader.test.tsx`: the four KPI labels (Matching, Orphaned, Waste, Blocked · deletable) render.
2. Implement; keep the `sequencer` in `Resources`; selection bar floats at the bottom when anything is selected. Run `npm test` → PASS. Commit `feat(ui): resource page with KPI cards, charts, filters, and table`.

### Task 5: Drawer, diagram, dialog

**Files:** `frontend/src/components/ResourcePanel.tsx`, `frontend/src/components/CostBreakdown.tsx`, `frontend/src/components/LinkageDiagram.tsx`, `frontend/src/components/diagram.css`, `frontend/src/components/DeleteModal.tsx`.

**Steps:**
1. `DeleteModal.test.tsx` is the gate (all six tests unchanged). Add one: pressing "Cancel" calls `onClose`.
2. Implement on `Dialog`, `Tabs`, `Card`; diagram CSS uses `.dark` instead of `.awsui-dark-mode`. Run `npm test` → PASS. Commit `feat(ui): detail drawer, restyled diagram and cost, delete dialog`.

### Task 6: Overview, audit, help; remove Cloudscape; verify

**Files:** `frontend/src/pages/Overview.tsx`, `frontend/src/pages/Audit.tsx`, `frontend/src/pages/HowItWorks.tsx`, `frontend/package.json` (uninstall Cloudscape), `docs/HANDOFF.md`.

**Steps:**
1. `Overview.test.tsx` is the gate (unchanged). Implement pages. `npm uninstall @cloudscape-design/components @cloudscape-design/global-styles`; `grep -r cloudscape src` → nothing.
2. `make test` → all green. `npm run build` → succeeds; note bundle size.
3. Browser check (light and dark, 1440px and 1024px): Overview cards and donuts; EBS volumes KPI, charts with tooltips, filters (account, status, date preset) update URL and survive reload; Export CSV and PDF; open `prd-scratch-data` drawer → diagram, cost tiers; AMIs mixed delete dialog and simulate toast; Orphaned popover says "Doesn't block deletion"; Esc closes drawer and dialog.
4. Run the dataviz palette validator on any new chart color (bars use the accent).
5. Update HANDOFF status; commit `feat(ui): overview, audit, and help pages; remove Cloudscape`.

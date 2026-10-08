import { useCallback, useState } from "react";

/** The first-run walkthrough (base spec §13). Each step points at an element with data-tour="<id>". */
export interface TourStep {
  id: string;
  title: string;
  body: string;
  page?: string; // opened first when the user isn't on it
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: "type",
    title: "Pick a resource type",
    body: "Each type has its own page: AMIs, EBS snapshots, EBS volumes, and RDS snapshots.",
  },
  {
    id: "filter",
    title: "Filter the list",
    body: "Search, choose statuses, accounts, or regions, or match a name pattern. Filters stay in the URL, so a link shows the same view.",
    page: "/amis",
  },
  {
    id: "status",
    title: "Read a status",
    body: "Click a status to see what it means for this resource. Learn more opens the full explanation.",
    page: "/amis",
  },
  {
    id: "select",
    title: "Select resources",
    body: "Tick rows, or select the page and then every match. Blocked resources can be selected; the plan skips them and says why.",
    page: "/amis",
  },
  {
    id: "plan",
    title: "Plan a delete",
    body: "Plan delete shows what would be deleted, what is blocked and why, and the monthly cost. It is a simulation: Janitor never deletes anything.",
    page: "/amis",
  },
  {
    id: "deployments",
    title: "See what is deployed",
    body: "Deployments shows each app by account and region, with its live version and how many instances or tasks run. Click a cell for its Auto Scaling group or ECS service.",
    page: "/deployments",
  },
];

const KEY = "janitor:tour";

/** True once finished or skipped, and also when storage is unavailable: never nag in that case. */
export function tourSeen(): boolean {
  try {
    return localStorage.getItem(KEY) === "done";
  } catch {
    return true;
  }
}

export function markTourSeen(): void {
  try {
    localStorage.setItem(KEY, "done");
  } catch {
    // not remembered; it won't auto-open anyway when storage throws
  }
}

/** Opens on the first visit; `start` replays it from the Help menu, ignoring the flag. */
export function useTour() {
  const [open, setOpen] = useState(() => !tourSeen());
  const [run, setRun] = useState(0); // remounts the tour at step 1 on replay
  const start = useCallback(() => {
    setRun((n) => n + 1);
    setOpen(true);
  }, []);
  const close = useCallback(() => {
    markTourSeen();
    setOpen(false);
  }, []);
  return { open, run, start, close };
}

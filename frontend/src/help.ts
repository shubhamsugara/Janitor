import { createContext, useContext } from "react";
import type { Meta, ResourceType, Status } from "./api";

/** What the help panel explains. Status and rule text come from /api/meta, never from here. */
export type HelpTopic =
  | `status:${Status}`
  | `rule:${string}`
  | `stat:${"matching" | "orphaned" | "waste" | "decisions"}`
  | `page:${ResourceType | "overview"}`;

export interface HelpApi {
  open: (topic: HelpTopic) => void;
}

export const HelpContext = createContext<HelpApi>({ open: () => {} });
export const useHelp = () => useContext(HelpContext);

export interface HelpContent {
  title: string;
  badge?: string; // a rule's outcome
  sections: { heading: string; text: string }[];
}

// Short texts for pages and stats: they describe the UI, not a status or rule.
const STATS: Record<string, HelpContent> = {
  matching: {
    title: "Matching",
    sections: [
      { heading: "What it means", text: "How many resources match the filters, and their total size." },
      { heading: "What to do", text: "Narrow the filters to the resources you want to review." },
    ],
  },
  orphaned: {
    title: "Orphaned",
    sections: [
      { heading: "What it means", text: "Matching resources that nothing uses and that are old enough to count as waste." },
      { heading: "What to do", text: "Filter by the Orphaned status, review them, then plan their deletion." },
    ],
  },
  waste: {
    title: "Waste",
    sections: [
      { heading: "What it means", text: "The estimated monthly cost of the orphaned resources: size × the AWS list price for their region." },
      { heading: "Why it is an estimate", text: "Snapshots are incremental, so deleting one may free less than its full size." },
    ],
  },
  decisions: {
    title: "Blocked · deletable",
    sections: [
      { heading: "What it means", text: "How many matching resources a delete rule blocks, and how many a plan could include." },
      { heading: "What to do", text: "Open a resource and read its Rules tab to see what blocks it." },
    ],
  },
};

const PAGES: Record<string, HelpContent> = {
  overview: {
    title: "Overview",
    sections: [{ heading: "What it shows", text: "Every resource type at a glance: totals, waste, and checks that failed in the last scan." }],
  },
  ami: {
    title: "AMIs",
    sections: [{ heading: "What it shows", text: "The admin account's AMIs. An instance launched from one, in an account it is shared with, makes it in use." }],
  },
  snapshot: {
    title: "EBS snapshots",
    sections: [{ heading: "What it shows", text: "EBS snapshots in every scanned account. One that backs a registered AMI is in use." }],
  },
  volume: {
    title: "EBS volumes",
    sections: [{ heading: "What it shows", text: "EBS volumes in every scanned account. An attached volume is in use." }],
  },
  rds_snapshot: {
    title: "RDS snapshots",
    sections: [{ heading: "What it shows", text: "RDS instance and cluster snapshots. Automated and AWS Backup snapshots expire on their own." }],
  },
};

const MISSING: HelpContent = { title: "Help", sections: [{ heading: "Not found", text: "There's no help for this yet. See How Janitor decides." }] };

export function helpContent(meta: Meta, topic: HelpTopic): HelpContent {
  const [kind, key] = topic.split(/:(.*)/s);
  if (kind === "status") {
    const def = meta.definitions.statuses[key as Status];
    if (!def) return MISSING;
    return {
      title: def.label,
      sections: [
        { heading: "What it means", text: def.meaning },
        {
          heading: "Does it block deletion?",
          text: def.blocks ? "Yes. Janitor won't offer it for deletion." : "No, but another rule can still block it.",
        },
        { heading: "What to do", text: def.what_to_do },
      ],
    };
  }
  if (kind === "rule") {
    const rule = meta.definitions.rules.find((r) => r.id === key);
    if (!rule) return MISSING;
    const blocks = rule.outcome === "block";
    return {
      title: `${rule.id} · ${rule.title}`,
      badge: blocks ? "Blocks deletion" : "Warns",
      sections: [
        { heading: "What it means", text: rule.explanation },
        {
          heading: "What to do",
          text: blocks
            ? "Janitor won't offer it for deletion while this applies. Fix the cause, or leave it."
            : "Check before you go ahead. A plan with a warning asks you to type delete to confirm.",
        },
      ],
    };
  }
  if (kind === "stat") return STATS[key] ?? MISSING;
  if (kind === "page") return PAGES[key] ?? MISSING;
  return MISSING;
}

import { Link } from "react-router";
import type { Meta } from "../api";
import { helpContent, type HelpTopic } from "../help";
import { Badge } from "../ui/badge";
import { Sheet } from "../ui/sheet";

interface Props {
  topic: HelpTopic;
  meta: Meta;
  onClose: () => void;
}

/** The help drawer: opens over the details drawer, and closing it leaves that drawer open. */
export default function HelpPanel({ topic, meta, onClose }: Props) {
  const content = helpContent(meta, topic);
  return (
    <Sheet open onClose={onClose} title="Help" closeLabel="Close help" className="z-40 w-[min(440px,94vw)]">
      <div className="space-y-5 text-[13px]">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold tracking-tight">{content.title}</h2>
          {content.badge && <Badge tone={content.badge === "Warns" ? "warning" : "danger"}>{content.badge}</Badge>}
        </div>
        {content.sections.map((s) => (
          <section key={s.heading}>
            <h3 className="text-[11px] font-semibold tracking-wider text-muted uppercase">{s.heading}</h3>
            <p className="mt-1">{s.text}</p>
          </section>
        ))}
        <Link to="/how-it-works" onClick={onClose} className="inline-block font-medium text-accent hover:underline">
          How Janitor decides
        </Link>
      </div>
    </Sheet>
  );
}

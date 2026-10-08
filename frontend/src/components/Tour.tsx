import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { TOUR_STEPS } from "../tour";
import { Button } from "../ui/button";

const RING_PAD = 6;
const CARD_WIDTH = 340;

/** Finds the step's anchor; pages load their data after navigating, so it keeps looking briefly. */
function useAnchor(id: string): DOMRect | null {
  const [rect, setRect] = useState<DOMRect | null>(null);
  useEffect(() => {
    let tries = 0;
    const measure = () => {
      const el = document.querySelector(`[data-tour="${id}"]`);
      setRect(el ? el.getBoundingClientRect() : null);
      return Boolean(el);
    };
    if (measure()) {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const timer = setInterval(() => {
      if (measure() || ++tries > 20) clearInterval(timer);
    }, 100);
    return () => clearInterval(timer);
  }, [id]);
  return rect;
}

/** The walkthrough card, with a ring around the element the step is about. */
export default function Tour({ onClose }: { onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const step = TOUR_STEPS[index];
  const last = index === TOUR_STEPS.length - 1;
  const location = useLocation();
  const navigate = useNavigate();
  const rect = useAnchor(step.id);

  // Open the step's page when the step changes, not on every navigation: the user may browse away.
  // useNavigate() returns a new function after each navigation, so both live in a ref.
  const latest = useRef({ path: location.pathname, navigate });
  latest.current = { path: location.pathname, navigate };
  useEffect(() => {
    const page = TOUR_STEPS[index].page;
    if (page && latest.current.path !== page) latest.current.navigate(page);
  }, [index]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Below the anchor when there is room, else above it; centered when there's no anchor.
  const style = rect
    ? {
        left: Math.max(16, Math.min(rect.left, window.innerWidth - CARD_WIDTH - 16)),
        top: rect.bottom + 12 + 180 < window.innerHeight ? rect.bottom + 12 : Math.max(16, rect.top - 192),
      }
    : { left: "50%", top: "50%", transform: "translate(-50%, -50%)" };

  return (
    <>
      {rect && (
        <div
          data-testid="tour-ring"
          aria-hidden
          className="pointer-events-none fixed z-50 rounded-xl ring-2 ring-accent ring-offset-2 ring-offset-page transition-all"
          style={{ left: rect.left - RING_PAD, top: rect.top - RING_PAD, width: rect.width + 2 * RING_PAD, height: rect.height + 2 * RING_PAD }}
        />
      )}
      <div
        role="dialog"
        aria-label="Walkthrough"
        className="animate-pop-in fixed z-50 rounded-2xl border border-line bg-card p-5 text-ink shadow-2xl"
        style={{ width: CARD_WIDTH, ...style }}
      >
        <div className="text-[11px] font-semibold tracking-wider text-muted uppercase">{`Step ${index + 1} of ${TOUR_STEPS.length}`}</div>
        <h2 className="mt-1 text-[15px] font-semibold">{step.title}</h2>
        <p className="mt-1.5 text-[13px] text-muted">{step.body}</p>
        <div className="mt-4 flex items-center justify-between">
          <Button size="sm" variant="ghost" onClick={onClose}>
            Skip
          </Button>
          <div className="flex gap-2">
            <Button size="sm" disabled={index === 0} onClick={() => setIndex(index - 1)}>
              Back
            </Button>
            <Button size="sm" variant="primary" onClick={() => (last ? onClose() : setIndex(index + 1))}>
              {last ? "Done" : "Next"}
            </Button>
          </div>
        </div>
      </div>
    </>
  );
}

import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TOUR_STEPS, useTour } from "../tour";
import Tour from "./Tour";

function Where() {
  return <span data-testid="where">{useLocation().pathname}</span>;
}

let goto: (to: string) => void = () => {};
function Nav() {
  goto = useNavigate();
  return null;
}

function Harness({ anchors = false }: { anchors?: boolean }) {
  const tour = useTour();
  return (
    <MemoryRouter>
      <Where />
      <Nav />
      {anchors && <div data-tour="type">types</div>}
      <button type="button" onClick={tour.start}>
        Replay
      </button>
      {tour.open && <Tour onClose={tour.close} />}
    </MemoryRouter>
  );
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("Walkthrough", () => {
  it("has six steps, ending on Deployments", () => {
    expect(TOUR_STEPS.map((s) => s.id)).toEqual(["type", "filter", "status", "select", "plan", "deployments"]);
  });

  it("opens once on the first visit and remembers a skip", () => {
    const first = render(<Harness />);
    expect(screen.getByRole("dialog", { name: "Walkthrough" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(screen.queryByRole("dialog", { name: "Walkthrough" })).toBeNull();
    expect(localStorage.getItem("janitor:tour")).toBe("done");
    first.unmount();
    render(<Harness />);
    expect(screen.queryByRole("dialog", { name: "Walkthrough" })).toBeNull();
  });

  it("doesn't open by itself when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<Harness />);
    expect(screen.queryByRole("dialog", { name: "Walkthrough" })).toBeNull();
  });

  it("Escape skips it", () => {
    render(<Harness />);
    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(screen.queryByRole("dialog", { name: "Walkthrough" })).toBeNull();
    expect(localStorage.getItem("janitor:tour")).toBe("done");
  });

  it("Next and Back move between steps, and later steps open the AMIs page", () => {
    render(<Harness />);
    expect(screen.getByText("Step 1 of 6")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Step 2 of 6")).toBeTruthy();
    expect(screen.getByTestId("where").textContent).toBe("/amis");
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("Step 1 of 6")).toBeTruthy();
  });

  it("ends with Done on the last step", () => {
    render(<Harness />);
    for (let i = 0; i < 5; i++) fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Step 6 of 6")).toBeTruthy();
    expect(screen.getByTestId("where").textContent).toBe("/deployments");
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog", { name: "Walkthrough" })).toBeNull();
  });

  it("highlights the anchor, and shows the step without one", () => {
    const { unmount } = render(<Harness anchors />);
    expect(screen.getByTestId("tour-ring")).toBeTruthy();
    unmount();
    localStorage.clear();
    render(<Harness />);
    expect(screen.getByText(TOUR_STEPS[0].title)).toBeTruthy();
    expect(screen.queryByTestId("tour-ring")).toBeNull();
  });

  it("replays from the menu even after it was seen", () => {
    localStorage.setItem("janitor:tour", "done");
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    expect(screen.getByText("Step 1 of 6")).toBeTruthy();
  });
});

describe("Walkthrough navigation", () => {
  it("doesn't pull the user back when they go to another page mid-tour", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByTestId("where").textContent).toBe("/amis");
    act(() => goto("/audit"));
    expect(screen.getByTestId("where").textContent).toBe("/audit");
  });
});

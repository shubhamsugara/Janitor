import TopNavigation from "@cloudscape-design/components/top-navigation";
import { useNavigate } from "react-router";
import type { Meta } from "../api";
import type { Theme } from "../theme";

interface Props {
  meta: Meta | null;
  theme: Theme;
  scanning: boolean;
  onScan: () => void;
  onToggleTheme: () => void;
}

export default function TopBar({ meta, theme, scanning, onScan, onToggleTheme }: Props) {
  const navigate = useNavigate();
  const source = !meta ? "Connecting" : meta.provider === "mock" ? "Mock data" : "AWS · read-only";
  return (
    <TopNavigation
      identity={{
        title: "Janitor",
        href: "/",
        onFollow: (event) => {
          event.preventDefault();
          navigate("/");
        },
      }}
      utilities={[
        {
          type: "button",
          text: source,
          iconName: "status-info",
          href: "/how-it-works",
          onFollow: (event) => {
            event.preventDefault();
            navigate("/how-it-works");
          },
        },
        {
          type: "button",
          variant: "primary-button",
          text: scanning ? "Scanning" : "Scan now",
          iconName: "refresh",
          onClick: () => {
            if (!scanning) onScan();
          },
        },
        { type: "button", text: theme === "dark" ? "Use light mode" : "Use dark mode", onClick: onToggleTheme },
      ]}
    />
  );
}

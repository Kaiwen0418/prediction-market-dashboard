"use client";

import {
  Activity,
  BarChart3,
  Bookmark,
  Globe2,
  Hexagon,
  History,
  Moon,
  Search,
  Sun
} from "lucide-react";
import Link from "next/link";
import { useTheme } from "@/components/theme/ThemeProvider";

const primaryLinks = [
  { href: "#market-map", label: "Market map", icon: Globe2, active: true },
  { href: "#market-activity", label: "Activity feed", icon: Activity },
  { href: "#market-evidence", label: "Market evidence", icon: BarChart3 },
  { href: "/history", label: "Research history", icon: History },
  { href: "#market-pairs", label: "Saved markets", icon: Bookmark }
];

export function MarketWorkspaceNav() {
  const { theme, toggleTheme } = useTheme();
  const ThemeIcon = theme === "dark" ? Sun : Moon;

  return (
    <aside className="market-workspace-rail" aria-label="Workspace navigation">
      <Link href="/" className="market-workspace-mark" aria-label="Prediction Market Intelligence">
        <Hexagon aria-hidden="true" strokeWidth={2.4} />
      </Link>

      <nav className="market-workspace-nav">
        <button
          type="button"
          className="market-workspace-nav-button"
          aria-label="Search markets"
          title="Search markets"
        >
          <Search aria-hidden="true" />
        </button>
        {primaryLinks.map(({ href, label, icon: Icon, active }) => (
          <Link
            key={href}
            href={href}
            className="market-workspace-nav-button"
            data-active={active ? "true" : "false"}
            aria-label={label}
            title={label}
          >
            <Icon aria-hidden="true" />
          </Link>
        ))}
      </nav>

      <button
        type="button"
        className="market-workspace-nav-button market-workspace-theme"
        onClick={toggleTheme}
        aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      >
        <ThemeIcon aria-hidden="true" />
      </button>
    </aside>
  );
}

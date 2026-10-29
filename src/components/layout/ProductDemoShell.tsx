"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";
import { ThreeGlobeVisual } from "@/components/hero/ThreeGlobeVisual";
import { useTheme } from "@/components/theme/ThemeProvider";
import { ThemeToggle } from "@/components/theme/ThemeToggle";

type ProductDemoShellProps = {
  brand: string;
  context?: string;
  title: ReactNode;
  footerLabel?: string;
  footerLeft?: string;
  footerRight?: string;
  showHero?: boolean;
  children: ReactNode;
};

const navLinks = [
  { href: "/", label: "Home" },
  { href: "/history", label: "Research" }
];

export function ProductDemoShell({
  brand,
  context,
  title,
  footerLabel,
  footerLeft,
  footerRight,
  showHero = true,
  children
}: ProductDemoShellProps) {
  const pathname = usePathname();
  const { theme } = useTheme();

  return (
    <main className="product-demo-page flex min-h-screen w-full flex-col px-4 py-5 md:px-6 lg:px-8">
      <section className="product-demo-hero">
        <div className="product-demo-shell">
          <div className="product-demo-card">
            <div className={showHero ? "product-demo-stage" : "product-demo-stage product-demo-stage--compact"}>
              <div className="product-demo-card-header">
                <div>
                  <p className="product-demo-brand">{brand}</p>
                  <h1 className="product-demo-title">{title}</h1>
                  {context ? <p className="product-demo-context">{context}</p> : null}
                </div>

                <nav className="product-demo-local-nav" aria-label="Primary navigation">
                  {navLinks.map((link) => (
                    <Link key={link.href} href={link.href} data-active={pathname === link.href ? "true" : "false"}>
                      {link.label}
                    </Link>
                  ))}
                  <ThemeToggle />
                </nav>
              </div>

              {showHero ? <ThreeGlobeVisual key={theme} /> : null}

              {showHero && footerLabel && footerLeft && footerRight ? (
                <div className="product-demo-footer">
                  <div className="product-demo-footer-label">{footerLabel}</div>
                  <p className="product-demo-footer-copy">{footerLeft}</p>
                  <p className="product-demo-footer-copy">{footerRight}</p>
                </div>
              ) : null}
            </div>

            <div className={showHero ? "product-demo-body" : "product-demo-body product-demo-body--compact"}>{children}</div>
          </div>
        </div>
      </section>
    </main>
  );
}

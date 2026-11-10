"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "./auth-provider";
import { Spinner } from "./ui";

const NAV = [
  { href: "/overview", label: "Dashboard", icon: "◈" },
  { href: "/active", label: "Active Signals", icon: "↗" },
  { href: "/history", label: "History", icon: "◷" }
];

const TITLES: Record<string, string> = {
  "/overview": "Dashboard",
  "/active": "Active Signals",
  "/history": "Signal History"
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <div className="center-screen">
        <Spinner label="Checking session" />
      </div>
    );
  }

  const title = pathname.startsWith("/signals/")
    ? "Signal"
    : TITLES[pathname] || "OI Signals";

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">OI</span>
          <div>
            <strong>OI Signals</strong>
            <span>Market intelligence</span>
          </div>
        </div>
        <nav>
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={pathname === item.href ? "nav-link active" : "nav-link"}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="user-chip">
            <span className="avatar">{user.name.slice(0, 1).toUpperCase()}</span>
            <div>
              <strong>{user.name}</strong>
              <span>{user.email}</span>
            </div>
          </div>
          <button
            className="btn ghost full"
            onClick={async () => {
              await logout();
              router.replace("/login");
            }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <span className="eyebrow">Published signals</span>
            <h1>{title}</h1>
          </div>
          <span className="topbar-note">All times shown in IST · prices from FYERS</span>
        </header>
        <div className="content">{children}</div>
      </main>
    </div>
  );
}

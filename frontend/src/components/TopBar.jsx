const TABS = [
  { href: "/", label: "Estimator" },
  { href: "/playground", label: "Playground" },
  { href: "/learn", label: "Learning" },
  { href: "/suggestions", label: "Recommendations" },
  { href: "/training", label: "Training" },
];

// Shared sticky nav on every page. Multi-page app, so each link is a full
// navigation and the active tab is read from the current path. Optional
// children render page-specific controls on the right.
export default function TopBar({ children }) {
  const path = window.location.pathname;
  const active = (href) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/70 backdrop-blur-xl">
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center gap-1">
        {TABS.map((t) => (
          <a key={t.href} href={t.href} className={`btn-soft ${active(t.href) ? "is-active" : ""}`}>
            {t.label}
          </a>
        ))}
        {children && <div className="ml-auto flex items-center gap-3 min-w-0">{children}</div>}
      </div>
    </header>
  );
}

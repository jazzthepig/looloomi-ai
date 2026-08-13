// Sidebar.jsx — left-rail navigation. Extracted from App.jsx on 2026-08-13
// (design audit, B2 split). Owns the nav data + the chrome; renders a single
// component consumed by DesktopApp.
//
// Accessibility (QW5, 2026-08-13):
//   - parent button: aria-current="page" when exact match, aria-expanded on
//     parent groups, aria-label = "Label — sub" so screen readers announce
//     both
//   - children: rendered under role="group" aria-label="<parent> submenu",
//     each child gets aria-current when active
//   - decorative pip + icon + caret get aria-hidden so the announcement is
//     clean

import { T, FONTS } from "../tokens";

// NAV. Two LABEL fixes only (2026-08-11) — the ids and the render blocks are
// untouched on purpose, because renaming a route is a different, riskier change
// than renaming a word, and the full IA restructure is a product decision that
// belongs to Jazz (docs/UI_CRITIQUE_2026-08-11.md §5).
//
// 1. "Events & VC" → "VC Funding Flows". The tab promised events and delivered a
//    funding table. That is a naming bug, not a layout one: a visitor who clicks
//    a label and gets something else stops trusting the other labels too.
//
// 2. "Trading Engine · IC Loop · Freqtrade · Live" → no execution stack in the
//    subtitle. This one is not taste. CLAUDE.md hard rule #8 forbids naming our
//    implementation on investor-facing surfaces, and a third-party execution
//    framework is squarely inside it — it tells a competitor what to clone and an
//    allocator something they did not ask to know.
//
// IA order locked 2026-08-13 (post-launch review):
//   · CIS Engine is the front door — first item, canonical landing route.
//   · Diagnose route was retired (it duplicated Portfolio's top section).
//     Portfolio now owns the "feed your book" affordance.
//   · Nine peers stays "no formal hierarchy" downstream of CIS Engine — that's
//     a depth-of-info problem for the product team, not an ordering bug.
export const NAV_ITEMS = [
  { id: "cis", label: "CIS Engine", icon: "◆", sub: "Scoring · Leaderboard",
    children: [
      { id: "cis.leaderboard", label: "Leaderboard" },
      { id: "cis.radar",       label: "Asset Radar" },
    ]
  },
  { id: "intelligence", label: "Intelligence", icon: "◈", sub: "Signals · Macro · Funding",
    children: [
      { id: "intelligence.signals", label: "Signal Feed" },
      { id: "intelligence.macro",   label: "Macro" },
      { id: "intelligence.events",  label: "VC Funding Flows" },
    ]
  },
  { id: "strategies", label: "Strategies", icon: "▲", sub: "Autonomous · Multi-Factor" },
  { id: "protocol",  label: "Protocols", icon: "⬡", sub: "DeFi TVL · Selection" },
  { id: "vault",     label: "Vault",     icon: "◎", sub: "Fund of Funds" },
  { id: "quantgp",   label: "Research Desk", icon: "∿", sub: "Factor research · Paper books" },
  { id: "portfolio", label: "Portfolio", icon: "⊡", sub: "My Holdings" },
  { id: "api-keys",  label: "API Keys",  icon: "⌘", sub: "RaaS · Free · Pro" },
];

// Used by mobile SiteNav — top-level items only
export const SECTIONS = NAV_ITEMS.map(({ id, label }) => ({ id, label }));

export const TOOL_LINKS = [
  { label: "Portfolio Builder", href: "/portfolio.html" },
  { label: "Score Analytics",  href: "/analytics.html" },
  { label: "Agent API",        href: "/agent.html" },
  { label: "Fund Strategy",    href: "/strategy.html" },
  { label: "Privacy Policy",   href: "/privacy.html" },
];

export function Sidebar({ activeSection, onNavigate, bottomSlot }) {
  return (
    <div style={{
      width: 220, minWidth: 220,
      height: "100vh",
      position: "fixed", left: 0, top: 0,
      background: "rgba(1,5,14,0.97)",
      borderRight: "1px solid rgba(6,182,212,0.07)",
      display: "flex", flexDirection: "column",
      zIndex: 1000,
      backdropFilter: "blur(20px)",
      WebkitBackdropFilter: "blur(20px)",
    }}>

      {/* Brand */}
      <div style={{ padding: "22px 20px 18px", borderBottom: "1px solid rgba(6,182,212,0.07)" }}>
        <a href="/app.html" style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ fontFamily: FONTS.brand, fontWeight: 800, fontSize: 13, color: T.t1, letterSpacing: "0.06em" }}>
            COMETCLOUD
          </span>
          <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.indigo, letterSpacing: "0.1em" }}>AI</span>
        </a>
        <div style={{
          fontFamily: FONTS.mono, fontSize: 8, color: T.muted,
          letterSpacing: "0.12em", textTransform: "uppercase", marginTop: 6, opacity: 0.6,
        }}>
          Institutional Intelligence
        </div>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: "10px 8px", overflowY: "auto", scrollbarWidth: "none" }}>

        {/* Platform group */}
        <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.muted, letterSpacing: "0.16em", textTransform: "uppercase", padding: "6px 12px 8px", opacity: 0.55 }}>
          Platform
        </div>

        {NAV_ITEMS.map(item => {
          const isParentActive = activeSection === item.id || activeSection.startsWith(item.id + ".");
          const active = activeSection === item.id;
          return (
            <div key={item.id}>
              <button
                onClick={() => onNavigate(item.id)}
                aria-current={active ? "page" : undefined}
                aria-expanded={item.children ? isParentActive : undefined}
                aria-label={item.sub ? `${item.label} — ${item.sub}` : item.label}
                style={{
                  width: "100%", textAlign: "left",
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "9px 10px 9px 12px", borderRadius: 6,
                  cursor: "pointer", border: "none", marginBottom: 2,
                  background: isParentActive ? "rgba(6,182,212,0.07)" : "transparent",
                  color: isParentActive ? T.t1 : T.t3,
                  transition: "all 0.14s",
                }}
                onMouseEnter={e => { if (!isParentActive) { e.currentTarget.style.background = "rgba(255,255,255,0.025)"; e.currentTarget.style.color = T.t2; } }}
                onMouseLeave={e => { if (!isParentActive) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = T.t3; } }}
              >
                {/* Active pip */}
                <div style={{
                  width: 2, height: 18, borderRadius: 1, flexShrink: 0,
                  background: active ? T.cyan : isParentActive ? "rgba(6,182,212,0.35)" : "transparent",
                  transition: "background 0.14s",
                }} />
                {/* Icon */}
                <span aria-hidden="true" style={{ fontFamily: FONTS.mono, fontSize: 12, color: isParentActive ? T.cyan : T.t3, flexShrink: 0, lineHeight: 1, opacity: isParentActive ? 1 : 0.5 }}>
                  {item.icon}
                </span>
                {/* Label + sub */}
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: isParentActive ? 700 : 500, letterSpacing: "0.01em", whiteSpace: "nowrap" }}>
                    {item.label}
                  </div>
                  <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: isParentActive ? T.t3 : T.muted, marginTop: 2, opacity: 0.65, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {item.sub}
                  </div>
                </div>
              </button>

              {/* Children — shown when parent is active */}
              {item.children && isParentActive && (
                <div role="group" aria-label={`${item.label} submenu`} style={{ marginLeft: 24, marginBottom: 4 }}>
                  {item.children.map(child => {
                    const childActive = activeSection === child.id;
                    return (
                      <button
                        key={child.id}
                        onClick={() => onNavigate(child.id)}
                        aria-current={childActive ? "page" : undefined}
                        aria-label={child.label}
                        style={{
                          width: "100%", textAlign: "left",
                          display: "flex", alignItems: "center", gap: 8,
                          padding: "6px 10px 6px 10px", borderRadius: 5,
                          cursor: "pointer", border: "none", marginBottom: 1,
                          background: childActive ? "rgba(6,182,212,0.10)" : "transparent",
                          color: childActive ? T.cyan : "rgba(148,163,184,0.55)",
                          transition: "all 0.12s",
                        }}
                        onMouseEnter={e => { if (!childActive) { e.currentTarget.style.background = "rgba(255,255,255,0.03)"; e.currentTarget.style.color = T.t2; } }}
                        onMouseLeave={e => { if (!childActive) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "rgba(148,163,184,0.55)"; } }}
                      >
                        <div aria-hidden="true" style={{
                          width: 1, height: 12, background: childActive ? T.cyan : "rgba(6,182,212,0.25)", borderRadius: 1, flexShrink: 0,
                        }} />
                        <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: childActive ? 600 : 400, letterSpacing: "0.01em", whiteSpace: "nowrap" }}>
                          {child.label}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        {/* Divider */}
        <div style={{ height: 1, background: "rgba(6,182,212,0.05)", margin: "10px 12px" }} />

        {/* Tools group */}
        <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.muted, letterSpacing: "0.16em", textTransform: "uppercase", padding: "4px 12px 8px", opacity: 0.55 }}>
          Tools
        </div>

        {TOOL_LINKS.map(link => (
          <a key={link.href} href={link.href} style={{
            width: "100%", display: "flex", alignItems: "center", gap: 10,
            padding: "7px 10px 7px 14px", borderRadius: 6, marginBottom: 2,
            textDecoration: "none", color: T.muted,
            transition: "all 0.14s",
          }}
            onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.025)"; e.currentTarget.style.color = T.t2; }}
            onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = T.muted; }}
          >
            <div style={{ fontFamily: FONTS.display, fontSize: 11, flex: 1, letterSpacing: "0.01em" }}>{link.label}</div>
            <span style={{ fontSize: 9, opacity: 0.35 }}>↗</span>
          </a>
        ))}
      </nav>

      {/* Bottom: wallet + version */}
      <div style={{ padding: "14px 16px 18px", borderTop: "1px solid rgba(6,182,212,0.07)" }}>
        {bottomSlot}
        <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.muted, textAlign: "center", marginTop: 12, letterSpacing: "0.06em", opacity: 0.4 }}>
          CIS v4.1 · CometCloud © 2026
        </div>
      </div>
    </div>
  );
}

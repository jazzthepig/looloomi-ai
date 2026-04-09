/**
 * SiteNav — shared navigation bar for all CometCloud pages.
 *
 * Props:
 *   activePage  {string}   — highlight key: 'platform'|'intelligence'|'methodology'|'fund'|'agent'
 *   sections    {Array}    — [{id, label}] — renders scroll tabs instead of link tabs
 *   activeSection {string} — controlled highlight for scroll tabs (pass from parent IntersectionObserver)
 *   onSectionClick {fn}    — (id) => void, called when a scroll tab is clicked
 *   ctaLabel    {string}   — override the right-side CTA text (default: 'Open Platform')
 *   ctaHref     {string}   — override the right-side CTA href (default: '/app.html')
 *   ctaHighlight {bool}    — use indigo gradient for CTA (default: false)
 */

import { T, FONTS } from "../tokens";

const NAV_LINKS = [
  { key: "platform",     label: "Platform",     href: "/app.html" },
  { key: "intelligence", label: "Intelligence",  href: "/app.html#intelligence" },
  { key: "methodology",  label: "Methodology",   href: "/methodology.html" },
  { key: "fund",         label: "Fund",          href: "/strategy.html" },
  { key: "agent",        label: "Agent API",     href: "/agent.html" },
];

export default function SiteNav({
  activePage = "",
  sections = null,
  activeSection = "",
  onSectionClick = null,
  ctaLabel = "Open Platform",
  ctaHref = "/app.html",
  ctaHighlight = false,
  rightSlot = null,   // optional JSX — rendered instead of CTA (e.g. <WalletConnect />)
}) {
  return (
    <nav style={{
      position: "fixed", top: 0, left: 0, right: 0, zIndex: 1000,
      background: "rgba(1,8,18,0.90)",
      backdropFilter: "blur(20px)",
      WebkitBackdropFilter: "blur(20px)",
      borderBottom: `1px solid ${T.border}`,
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "0 40px", height: 56,
    }}>
      {/* ── Logo ── */}
      <a href="/app.html" style={{
        textDecoration: "none",
        display: "flex", alignItems: "center", gap: 8, flexShrink: 0,
      }}>
        <span style={{
          fontFamily: FONTS.brand, fontWeight: 800, fontSize: 15,
          color: T.t1, letterSpacing: "0.04em",
        }}>
          COMETCLOUD
        </span>
        <span style={{
          fontFamily: FONTS.mono, fontSize: 9, color: T.indigo,
          letterSpacing: "0.1em",
        }}>
          AI
        </span>
      </a>

      {/* ── Centre: scroll tabs (platform app) OR page links (standalone pages) ── */}
      <div style={{
        display: "flex", alignItems: "center", gap: 2,
        background: "rgba(255,255,255,0.04)",
        borderRadius: 9, padding: 3, border: `1px solid ${T.border}`,
        overflow: "hidden",
      }}
        className="sitenav-centre"
      >
        {sections ? (
          // Scroll-based tabs (App.jsx platform)
          sections.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => onSectionClick?.(id)}
              style={{
                padding: "6px 13px", borderRadius: 6, fontSize: 11, fontWeight: 600,
                fontFamily: FONTS.display, cursor: "pointer", outline: "none",
                border: `1px solid ${activeSection === id ? "rgba(6,182,212,0.35)" : "transparent"}`,
                background: activeSection === id ? "rgba(6,182,212,0.10)" : "transparent",
                color: activeSection === id ? T.cyan : T.t3,
                transition: "all 0.18s ease",
                letterSpacing: "0.03em", whiteSpace: "nowrap",
              }}
            >
              {label}
            </button>
          ))
        ) : (
          // Link-based tabs (standalone pages)
          NAV_LINKS.map(({ key, label, href }) => (
            <a
              key={key}
              href={href}
              style={{
                padding: "6px 13px", borderRadius: 6, fontSize: 11, fontWeight: 600,
                fontFamily: FONTS.display, cursor: "pointer", outline: "none",
                border: `1px solid ${activePage === key ? "rgba(99,102,241,0.35)" : "transparent"}`,
                background: activePage === key ? "rgba(99,102,241,0.10)" : "transparent",
                color: activePage === key ? T.indigo : T.t3,
                textDecoration: "none",
                transition: "all 0.18s ease",
                letterSpacing: "0.03em", whiteSpace: "nowrap",
                display: "block",
              }}
              onMouseEnter={e => {
                if (activePage !== key) {
                  e.currentTarget.style.color = T.t2;
                  e.currentTarget.style.background = "rgba(255,255,255,0.04)";
                }
              }}
              onMouseLeave={e => {
                if (activePage !== key) {
                  e.currentTarget.style.color = T.t3;
                  e.currentTarget.style.background = "transparent";
                }
              }}
            >
              {label}
            </a>
          ))
        )}
      </div>

      {/* ── Right: rightSlot (e.g. WalletConnect) or default CTA ── */}
      {rightSlot ? rightSlot : <a href={ctaHref} style={{
        fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
        letterSpacing: "0.07em", textTransform: "uppercase",
        textDecoration: "none", flexShrink: 0,
        padding: "7px 16px", borderRadius: 7,
        ...(ctaHighlight
          ? {
            color: "#0a1020",
            background: `linear-gradient(135deg, ${T.indigo}, ${T.cyan})`,
            border: "none",
          }
          : {
            color: T.t2,
            background: "transparent",
            border: `1px solid ${T.borderHi}`,
          }
        ),
        transition: "opacity 0.18s",
      }}
        onMouseEnter={e => { e.currentTarget.style.opacity = "0.82"; }}
        onMouseLeave={e => { e.currentTarget.style.opacity = "1"; }}
      >
        {ctaLabel}
      </a>}

      {/* ── Mobile responsive styles ── */}
      <style>{`
        @media (max-width: 900px) {
          .sitenav-centre { max-width: 55vw; overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none; }
          .sitenav-centre::-webkit-scrollbar { display: none; }
          .sitenav-centre a, .sitenav-centre button { min-height: 34px; }
        }
        @media (max-width: 600px) {
          .sitenav-centre { display: none !important; }
        }
      `}</style>
    </nav>
  );
}

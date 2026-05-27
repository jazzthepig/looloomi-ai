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
      /* Void base — nav is a dark membrane, not a heavy bar */
      background: "rgba(1,1,6,0.82)",
      backdropFilter: "blur(32px)",
      WebkitBackdropFilter: "blur(32px)",
      borderBottom: "1px solid rgba(255,255,255,0.042)",
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "0 40px", height: 52,
    }}>
      {/* ── Logo — restrained, typographic ── */}
      <a href="/app.html" style={{
        textDecoration: "none",
        display: "flex", alignItems: "center", gap: 10, flexShrink: 0,
      }}>
        <span style={{
          fontFamily: FONTS.brand, fontWeight: 600, fontSize: 13,
          color: "rgba(237,242,247,0.92)", letterSpacing: "0.12em",
          textTransform: "uppercase",
        }}>
          CometCloud
        </span>
        {/* hairline separator */}
        <span style={{
          width: 1, height: 10,
          background: "rgba(255,255,255,0.12)",
          display: "inline-block",
        }} />
        <span style={{
          fontFamily: FONTS.mono, fontSize: 9,
          color: "rgba(74,160,184,0.70)",
          letterSpacing: "0.14em",
        }}>
          AI
        </span>
      </a>

      {/* ── Centre tabs — generous spacing, thin weights (Hara Kenya) ── */}
      <div style={{
        display: "flex", alignItems: "center", gap: 1,
        background: "rgba(255,255,255,0.025)",
        borderRadius: 8, padding: "2px 3px",
        border: "1px solid rgba(255,255,255,0.038)",
        overflow: "hidden",
      }}
        className="sitenav-centre"
      >
        {sections ? (
          sections.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => onSectionClick?.(id)}
              style={{
                padding: "5px 14px", borderRadius: 5,
                fontSize: 10, fontWeight: 400,
                fontFamily: FONTS.display, cursor: "pointer", outline: "none",
                border: `1px solid ${activeSection === id ? "rgba(74,160,184,0.22)" : "transparent"}`,
                background: activeSection === id ? "rgba(74,160,184,0.07)" : "transparent",
                color: activeSection === id ? "rgba(180,220,235,0.90)" : "rgba(140,165,190,0.45)",
                transition: "all 0.22s ease",
                letterSpacing: "0.05em", whiteSpace: "nowrap",
              }}
            >
              {label}
            </button>
          ))
        ) : (
          NAV_LINKS.map(({ key, label, href }) => (
            <a
              key={key}
              href={href}
              style={{
                padding: "5px 14px", borderRadius: 5,
                fontSize: 10, fontWeight: 400,
                fontFamily: FONTS.display, cursor: "pointer", outline: "none",
                border: `1px solid ${activePage === key ? "rgba(74,160,184,0.22)" : "transparent"}`,
                background: activePage === key ? "rgba(74,160,184,0.07)" : "transparent",
                color: activePage === key ? "rgba(180,220,235,0.90)" : "rgba(140,165,190,0.45)",
                textDecoration: "none",
                transition: "all 0.22s ease",
                letterSpacing: "0.05em", whiteSpace: "nowrap",
                display: "block",
              }}
              onMouseEnter={e => {
                if (activePage !== key) {
                  e.currentTarget.style.color = "rgba(200,215,230,0.75)";
                  e.currentTarget.style.background = "rgba(255,255,255,0.03)";
                }
              }}
              onMouseLeave={e => {
                if (activePage !== key) {
                  e.currentTarget.style.color = "rgba(140,165,190,0.45)";
                  e.currentTarget.style.background = "transparent";
                }
              }}
            >
              {label}
            </a>
          ))
        )}
      </div>

      {/* ── Right: slot or CTA — refined, not bold ── */}
      {rightSlot ? rightSlot : <a href={ctaHref} style={{
        fontFamily: FONTS.display, fontSize: 10, fontWeight: 500,
        letterSpacing: "0.08em", textTransform: "uppercase",
        textDecoration: "none", flexShrink: 0,
        padding: "6px 16px", borderRadius: 5,
        ...(ctaHighlight
          ? {
            color: "#010106",
            background: `linear-gradient(135deg, rgba(74,160,184,0.90), rgba(112,128,204,0.85))`,
            border: "none",
          }
          : {
            color: "rgba(140,165,190,0.65)",
            background: "transparent",
            border: "1px solid rgba(255,255,255,0.08)",
          }
        ),
        transition: "opacity 0.22s, border-color 0.22s, color 0.22s",
      }}
        onMouseEnter={e => {
          e.currentTarget.style.opacity = "1";
          e.currentTarget.style.color = "rgba(220,230,240,0.90)";
          e.currentTarget.style.borderColor = "rgba(255,255,255,0.14)";
        }}
        onMouseLeave={e => {
          e.currentTarget.style.opacity = "1";
          e.currentTarget.style.color = "rgba(140,165,190,0.65)";
          e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)";
        }}
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

import React, { useState, useEffect } from 'react';
import { T, FONTS } from './tokens';

const API_BASE = typeof window !== 'undefined' && window.location.hostname === 'localhost'
  ? 'http://localhost:8000'
  : '';

// ── Ambient orb background ──────────────────────────────────────────────────
function AmbientOrbs() {
  return (
    <div style={{ position: 'fixed', inset: 0, overflow: 'hidden', pointerEvents: 'none', zIndex: 0 }}>
      <div style={{
        position: 'absolute', width: 700, height: 700,
        top: '-15%', right: '-10%',
        background: 'radial-gradient(circle, rgba(99,102,241,0.07) 0%, transparent 70%)',
        mixBlendMode: 'screen',
        animation: 'breathe 12s ease-in-out infinite',
      }} />
      <div style={{
        position: 'absolute', width: 500, height: 500,
        bottom: '10%', left: '-8%',
        background: 'radial-gradient(circle, rgba(6,182,212,0.06) 0%, transparent 70%)',
        mixBlendMode: 'screen',
        animation: 'breathe 16s ease-in-out infinite reverse',
      }} />
      <style>{`
        @keyframes breathe {
          0%, 100% { opacity: 0.6; transform: scale(1); }
          50% { opacity: 1; transform: scale(1.08); }
        }
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}

// ── Nav ─────────────────────────────────────────────────────────────────────
function Nav() {
  return (
    <nav style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
      background: 'rgba(1,8,18,0.88)',
      borderBottom: `1px solid ${T.border}`,
      backdropFilter: 'blur(20px)',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '0 32px', height: 56,
    }}>
      <a href="/app.html" style={{ textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontFamily: FONTS.brand, fontWeight: 800, fontSize: 16, color: T.t1, letterSpacing: '0.02em' }}>
          COMETCLOUD
        </span>
        <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.indigo, letterSpacing: '0.1em', marginTop: 1 }}>
          AI
        </span>
      </a>
      <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        {[
          { label: 'Platform', href: '/app.html' },
          { label: 'Intelligence', href: '/app.html' },
          { label: 'Methodology', href: '/methodology.html' },
          { label: 'Fund', href: '/strategy.html' },
        ].map(link => (
          <a key={link.label} href={link.href} style={{
            fontFamily: FONTS.display, fontSize: 12, fontWeight: 600,
            color: T.t3, textDecoration: 'none', letterSpacing: '0.06em',
            textTransform: 'uppercase',
            transition: 'color 0.2s',
          }}
            onMouseEnter={e => e.target.style.color = T.t1}
            onMouseLeave={e => e.target.style.color = T.t3}
          >{link.label}</a>
        ))}
        <a href="#request-key" style={{
          fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
          color: T.deep, background: T.indigo,
          padding: '6px 14px', borderRadius: 6,
          textDecoration: 'none', letterSpacing: '0.06em', textTransform: 'uppercase',
          transition: 'opacity 0.2s',
        }}
          onMouseEnter={e => e.target.style.opacity = '0.85'}
          onMouseLeave={e => e.target.style.opacity = '1'}
        >Get API Key</a>
      </div>
    </nav>
  );
}

// ── Tool card ────────────────────────────────────────────────────────────────
function ToolCard({ tool, tier, description, returns, badge }) {
  const tierColor = tier === 'free'
    ? { bg: 'rgba(0,217,138,0.08)', border: 'rgba(0,217,138,0.25)', text: T.green }
    : { bg: 'rgba(99,102,241,0.08)', border: 'rgba(99,102,241,0.30)', text: T.indigo };

  return (
    <div style={{
      background: T.surface,
      border: `1px solid ${T.border}`,
      borderRadius: 12,
      padding: '20px 22px',
      transition: 'border-color 0.2s, transform 0.2s',
    }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = T.borderHi; e.currentTarget.style.transform = 'translateY(-2px)'; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = T.border; e.currentTarget.style.transform = 'translateY(0)'; }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 10 }}>
        <code style={{
          fontFamily: FONTS.mono, fontSize: 13, color: T.cyan, fontWeight: 600,
          background: T.cyanDim, padding: '3px 8px', borderRadius: 5,
        }}>{tool}</code>
        <div style={{ display: 'flex', gap: 6, flexShrink: 0, marginLeft: 10 }}>
          {badge && (
            <span style={{
              fontFamily: FONTS.mono, fontSize: 9, fontWeight: 700,
              color: T.gold, background: T.goldDim,
              border: `1px solid rgba(212,168,67,0.3)`,
              padding: '2px 7px', borderRadius: 4, letterSpacing: '0.08em',
            }}>★ UNIQUE</span>
          )}
          <span style={{
            fontFamily: FONTS.mono, fontSize: 9, fontWeight: 700,
            color: tierColor.text, background: tierColor.bg,
            border: `1px solid ${tierColor.border}`,
            padding: '2px 7px', borderRadius: 4, letterSpacing: '0.08em',
            textTransform: 'uppercase',
          }}>{tier}</span>
        </div>
      </div>
      <p style={{ fontFamily: FONTS.body, fontSize: 13, color: T.t2, margin: '0 0 8px', lineHeight: 1.6 }}>
        {description}
      </p>
      <p style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t3, margin: 0 }}>
        → {returns}
      </p>
    </div>
  );
}

// ── Pricing tier card ────────────────────────────────────────────────────────
function TierCard({ name, price, priceNote, features, cta, ctaHref, highlight }) {
  return (
    <div style={{
      background: highlight ? `linear-gradient(145deg, rgba(99,102,241,0.12), rgba(6,182,212,0.06))` : T.surface,
      border: `1px solid ${highlight ? T.borderHi : T.border}`,
      borderRadius: 16,
      padding: '28px 26px',
      flex: 1,
      position: 'relative',
      overflow: 'hidden',
    }}>
      {highlight && (
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: 2,
          background: `linear-gradient(90deg, ${T.indigo}, ${T.cyan})`,
        }} />
      )}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontFamily: FONTS.brand, fontSize: 13, fontWeight: 700, color: highlight ? T.indigo : T.t3, letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 8 }}>
          {name}
        </div>
        <div style={{ fontFamily: FONTS.mono, fontSize: 28, fontWeight: 700, color: T.t1, lineHeight: 1 }}>
          {price}
        </div>
        {priceNote && (
          <div style={{ fontFamily: FONTS.body, fontSize: 12, color: T.t3, marginTop: 4 }}>
            {priceNote}
          </div>
        )}
      </div>
      <div style={{ marginBottom: 24 }}>
        {features.map((f, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 10 }}>
            <span style={{ color: T.green, fontSize: 12, marginTop: 1, flexShrink: 0 }}>✓</span>
            <span style={{ fontFamily: FONTS.body, fontSize: 13, color: T.t2, lineHeight: 1.5 }}>{f}</span>
          </div>
        ))}
      </div>
      <a href={ctaHref} style={{
        display: 'block', textAlign: 'center',
        fontFamily: FONTS.display, fontSize: 12, fontWeight: 700,
        color: highlight ? T.deep : T.t1,
        background: highlight ? `linear-gradient(135deg, ${T.indigo}, ${T.cyan})` : 'transparent',
        border: highlight ? 'none' : `1px solid ${T.border}`,
        padding: '10px 0', borderRadius: 8,
        textDecoration: 'none', letterSpacing: '0.06em', textTransform: 'uppercase',
        transition: 'opacity 0.2s',
      }}
        onMouseEnter={e => e.currentTarget.style.opacity = '0.85'}
        onMouseLeave={e => e.currentTarget.style.opacity = '1'}
      >{cta}</a>
    </div>
  );
}

// ── API key request form ─────────────────────────────────────────────────────
function RequestKeyForm() {
  const [form, setForm] = useState({ name: '', email: '', org: '', use_case: '', tier: 'pro' });
  const [status, setStatus] = useState('idle'); // idle | submitting | success | error
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setStatus('submitting');
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/v1/leads/capture`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name,
          email: form.email,
          source_page: 'agent_api_page',
          message: `Org: ${form.org}\nTier: ${form.tier}\nUse case: ${form.use_case}`,
        }),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      setStatus('success');
    } catch (err) {
      setError('Submission failed. Email us directly at api@cometcloud.ai');
      setStatus('error');
    }
  };

  if (status === 'success') {
    return (
      <div style={{ textAlign: 'center', padding: '48px 0' }}>
        <div style={{ fontSize: 40, marginBottom: 16 }}>✓</div>
        <div style={{ fontFamily: FONTS.brand, fontSize: 20, fontWeight: 700, color: T.t1, marginBottom: 10 }}>
          Request received
        </div>
        <div style={{ fontFamily: FONTS.body, fontSize: 14, color: T.t2, maxWidth: 420, margin: '0 auto' }}>
          We review API key requests within 24 hours. If approved, you'll receive your key and MCP server URL by email.
        </div>
      </div>
    );
  }

  const inputStyle = {
    width: '100%', boxSizing: 'border-box',
    fontFamily: FONTS.body, fontSize: 14, color: T.t1,
    background: T.raised, border: `1px solid ${T.border}`,
    borderRadius: 8, padding: '10px 14px', outline: 'none',
    transition: 'border-color 0.2s',
  };

  const labelStyle = {
    fontFamily: FONTS.display, fontSize: 11, fontWeight: 600,
    color: T.t3, letterSpacing: '0.08em', textTransform: 'uppercase',
    display: 'block', marginBottom: 6,
  };

  return (
    <form onSubmit={handleSubmit}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        <div>
          <label style={labelStyle}>Name</label>
          <input style={inputStyle} value={form.name} placeholder="Your name"
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))} required
            onFocus={e => e.target.style.borderColor = T.indigo}
            onBlur={e => e.target.style.borderColor = T.border} />
        </div>
        <div>
          <label style={labelStyle}>Email</label>
          <input style={inputStyle} type="email" value={form.email} placeholder="you@agent.ai"
            onChange={e => setForm(f => ({ ...f, email: e.target.value }))} required
            onFocus={e => e.target.style.borderColor = T.indigo}
            onBlur={e => e.target.style.borderColor = T.border} />
        </div>
      </div>
      <div style={{ marginBottom: 16 }}>
        <label style={labelStyle}>Organization / Agent Name</label>
        <input style={inputStyle} value={form.org} placeholder="e.g. MyFund AI, AutoTrader-7, Personal Agent"
          onChange={e => setForm(f => ({ ...f, org: e.target.value }))}
          onFocus={e => e.target.style.borderColor = T.indigo}
          onBlur={e => e.target.style.borderColor = T.border} />
      </div>
      <div style={{ marginBottom: 16 }}>
        <label style={labelStyle}>Tier requested</label>
        <div style={{ display: 'flex', gap: 10 }}>
          {[
            { value: 'free', label: 'Free — open tools only' },
            { value: 'pro', label: 'Pro — full access incl. exclusion list' },
          ].map(opt => (
            <label key={opt.value} style={{
              flex: 1, display: 'flex', alignItems: 'center', gap: 8,
              background: form.tier === opt.value ? (opt.value === 'pro' ? 'rgba(99,102,241,0.10)' : T.greenDim) : T.raised,
              border: `1px solid ${form.tier === opt.value ? (opt.value === 'pro' ? T.indigo : T.green) : T.border}`,
              borderRadius: 8, padding: '10px 14px', cursor: 'pointer',
              transition: 'all 0.2s',
            }}>
              <input type="radio" name="tier" value={opt.value} checked={form.tier === opt.value}
                onChange={() => setForm(f => ({ ...f, tier: opt.value }))}
                style={{ accentColor: opt.value === 'pro' ? T.indigo : T.green }} />
              <span style={{ fontFamily: FONTS.body, fontSize: 12, color: T.t2 }}>{opt.label}</span>
            </label>
          ))}
        </div>
      </div>
      <div style={{ marginBottom: 24 }}>
        <label style={labelStyle}>How will you use the API?</label>
        <textarea style={{ ...inputStyle, height: 90, resize: 'vertical' }}
          value={form.use_case}
          placeholder="e.g. Portfolio screening agent, crypto allocation model, institutional research workflow..."
          onChange={e => setForm(f => ({ ...f, use_case: e.target.value }))}
          onFocus={e => e.target.style.borderColor = T.indigo}
          onBlur={e => e.target.style.borderColor = T.border} />
      </div>
      {error && (
        <div style={{ fontFamily: FONTS.body, fontSize: 13, color: T.red, marginBottom: 14 }}>{error}</div>
      )}
      <button type="submit" disabled={status === 'submitting'} style={{
        width: '100%', fontFamily: FONTS.display, fontSize: 13, fontWeight: 700,
        color: T.deep, background: `linear-gradient(135deg, ${T.indigo}, ${T.cyan})`,
        border: 'none', borderRadius: 8, padding: '12px 0', cursor: 'pointer',
        letterSpacing: '0.06em', textTransform: 'uppercase',
        opacity: status === 'submitting' ? 0.6 : 1, transition: 'opacity 0.2s',
      }}>
        {status === 'submitting' ? 'Submitting…' : 'Request API Access'}
      </button>
    </form>
  );
}

// ── Live stats strip ─────────────────────────────────────────────────────────
function LiveStats() {
  const [pulse, setPulse] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/market/macro-pulse`)
      .then(r => r.json())
      .then(d => setPulse(d))
      .catch(() => {});
  }, []);

  const stats = [
    { label: 'Universe', value: '54+', unit: 'assets rated' },
    { label: 'Excluded', value: '9,946+', unit: 'assets filtered' },
    { label: 'Score refresh', value: '30', unit: 'min cadence' },
    { label: 'Macro regime', value: pulse?.macro_regime || 'Risk-Off', unit: 'live' },
    { label: 'MCP tools', value: '6', unit: 'available' },
  ];

  return (
    <div style={{
      display: 'flex', gap: 0,
      background: T.surface,
      border: `1px solid ${T.border}`,
      borderRadius: 12, overflow: 'hidden',
    }}>
      {stats.map((s, i) => (
        <div key={i} style={{
          flex: 1, padding: '16px 20px', textAlign: 'center',
          borderRight: i < stats.length - 1 ? `1px solid ${T.border}` : 'none',
        }}>
          <div style={{ fontFamily: FONTS.mono, fontSize: 18, fontWeight: 700, color: T.t1, lineHeight: 1 }}>
            {s.value}
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3, marginTop: 4, letterSpacing: '0.06em' }}>
            {s.label}
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t4, marginTop: 2 }}>
            {s.unit}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────
export default function AgentPage() {
  const tools = [
    {
      tool: 'get_cis_universe()',
      tier: 'free',
      description: 'Full scored universe of 54+ institutionally-curated assets. Grades, signals, 5-pillar breakdown, LAS, 7-day sparklines. Regime-aware.',
      returns: 'Array of assets with grade, signal, pillars, LAS, confidence',
    },
    {
      tool: 'get_cis_exclusions()',
      tier: 'pro',
      badge: true,
      description: 'Structured rejection list of 9,946+ assets that failed the 7-criterion inclusion standard. Each rejection includes the specific criterion triggered and the reason. No other data provider offers this.',
      returns: 'Array of rejected assets with criterion_violated, reason, excluded_since',
    },
    {
      tool: 'get_inclusion_standard()',
      tier: 'pro',
      description: 'The full 7-criterion institutional inclusion standard as structured JSON. Machine-readable thresholds, rationale, and data sources for each criterion. Embed in your agent\'s reasoning context.',
      returns: 'JSON object with 7 criteria objects, each with threshold, rationale, data_source',
    },
    {
      tool: 'get_cis_asset(symbol)',
      tier: 'free',
      description: 'Single-asset deep dive. Full pillar scores, LAS breakdown, score history anchor, regime sensitivity. If asset is excluded, returns the rejection reason instead of a score.',
      returns: 'Asset object with pillars, LAS formula breakdown, sparkline, or rejection reason',
    },
    {
      tool: 'get_cis_history(symbol, days)',
      tier: 'pro',
      description: 'Score trajectory for any asset across up to 90 days. Grade migration data — see when an asset crossed boundaries. Feeds grade migration heatmaps and trend models.',
      returns: 'Time series of {date, cis_score, grade, signal} for requested asset',
    },
    {
      tool: 'get_regime_context()',
      tier: 'free',
      description: 'Current macro regime (RISK_ON / RISK_OFF / TIGHTENING / EASING / STAGFLATION / GOLDILOCKS) with active pillar weight adjustments. Include in every allocation decision.',
      returns: 'regime, pillar_weights, confidence, triggered_indicators',
    },
  ];

  const mcpConfig = `{
  "mcpServers": {
    "cometcloud": {
      "command": "npx",
      "args": ["-y", "@cometcloud/mcp-server"],
      "env": {
        "COMETCLOUD_API_KEY": "your_key_here"
      }
    }
  }
}`;

  const pythonExample = `from anthropic import Anthropic

client = Anthropic()

# CometCloud tools load automatically via MCP
response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    tools=[],  # MCP injects cometcloud tools
    messages=[{
        "role": "user",
        "content": "Screen my portfolio against the institutional exclusion list. "
                   "Tell me which holdings fail the standard and why."
    }]
)`;

  return (
    <div style={{
      minHeight: '100vh',
      background: T.deep,
      fontFamily: FONTS.body,
      color: T.t1,
    }}>
      <AmbientOrbs />
      <Nav />

      {/* ── Hero ── */}
      <section style={{
        position: 'relative', zIndex: 1,
        maxWidth: 900, margin: '0 auto',
        padding: '120px 32px 80px',
        animation: 'fadeUp 0.6s ease-out',
      }}>
        <div style={{ marginBottom: 16 }}>
          <span style={{
            fontFamily: FONTS.mono, fontSize: 10, fontWeight: 700,
            color: T.indigo, letterSpacing: '0.14em', textTransform: 'uppercase',
            background: 'rgba(99,102,241,0.08)', border: `1px solid rgba(99,102,241,0.25)`,
            padding: '4px 10px', borderRadius: 4,
          }}>
            ◉ MCP Server · Agent API · v1.0
          </span>
        </div>
        <h1 style={{
          fontFamily: FONTS.brand, fontWeight: 800,
          fontSize: 'clamp(32px, 5vw, 52px)', lineHeight: 1.15,
          color: T.t1, margin: '0 0 20px',
          letterSpacing: '-0.02em',
        }}>
          Institutional intelligence<br />
          <span style={{ color: T.indigo }}>for the agent economy.</span>
        </h1>
        <p style={{
          fontFamily: FONTS.body, fontSize: 16, color: T.t2,
          maxWidth: 600, lineHeight: 1.7, margin: '0 0 40px',
        }}>
          CometCloud's CIS scoring engine, macro regime detector, and institutional exclusion list — available as MCP tools for any AI agent. The only data provider that tells your agent both what to consider and what to reject, with reasons.
        </p>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <a href="#request-key" style={{
            fontFamily: FONTS.display, fontSize: 13, fontWeight: 700,
            color: T.deep,
            background: `linear-gradient(135deg, ${T.indigo}, ${T.cyan})`,
            padding: '12px 28px', borderRadius: 8,
            textDecoration: 'none', letterSpacing: '0.06em', textTransform: 'uppercase',
            transition: 'opacity 0.2s',
          }}
            onMouseEnter={e => e.currentTarget.style.opacity = '0.85'}
            onMouseLeave={e => e.currentTarget.style.opacity = '1'}
          >Get API Key</a>
          <a href="#tools" style={{
            fontFamily: FONTS.display, fontSize: 13, fontWeight: 700,
            color: T.t1,
            background: 'transparent',
            border: `1px solid ${T.border}`,
            padding: '12px 28px', borderRadius: 8,
            textDecoration: 'none', letterSpacing: '0.06em', textTransform: 'uppercase',
            transition: 'border-color 0.2s',
          }}
            onMouseEnter={e => e.currentTarget.style.borderColor = T.indigo}
            onMouseLeave={e => e.currentTarget.style.borderColor = T.border}
          >View Tools →</a>
        </div>
      </section>

      {/* ── Live stats ── */}
      <section style={{ position: 'relative', zIndex: 1, maxWidth: 900, margin: '0 auto', padding: '0 32px 80px' }}>
        <LiveStats />
      </section>

      {/* ── The differentiator ── */}
      <section style={{
        position: 'relative', zIndex: 1,
        maxWidth: 900, margin: '0 auto', padding: '0 32px 80px',
      }}>
        <div style={{
          background: `linear-gradient(135deg, rgba(99,102,241,0.08), rgba(6,182,212,0.05))`,
          border: `1px solid ${T.borderHi}`,
          borderRadius: 16, padding: '36px 36px',
          position: 'relative', overflow: 'hidden',
        }}>
          <div style={{
            position: 'absolute', top: 0, left: 0, right: 0, height: 2,
            background: `linear-gradient(90deg, ${T.indigo}, ${T.cyan})`,
          }} />
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 24 }}>
            <div style={{
              fontFamily: FONTS.mono, fontSize: 28, lineHeight: 1,
              color: T.gold, flexShrink: 0, marginTop: 4,
            }}>★</div>
            <div>
              <div style={{ fontFamily: FONTS.brand, fontSize: 11, fontWeight: 700, color: T.gold, letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 10 }}>
                The Unique Tool
              </div>
              <div style={{ fontFamily: FONTS.mono, fontSize: 15, color: T.cyan, marginBottom: 12 }}>
                get_cis_exclusions()
              </div>
              <p style={{ fontFamily: FONTS.body, fontSize: 14, color: T.t2, lineHeight: 1.7, margin: '0 0 16px' }}>
                Returns the complete rejection list of 9,946+ assets that failed CometCloud's 7-criterion institutional inclusion standard. Each rejection includes the exact criterion violated and the specific reason — anonymous team, unresolved exploit, custody gap, regulatory concern, or liquidity failure.
              </p>
              <p style={{ fontFamily: FONTS.body, fontSize: 14, color: T.t2, lineHeight: 1.7, margin: 0 }}>
                No other MCP server, no other data provider, returns a structured exclusion list with institutional-grade reasoning. When your agent builds a portfolio, it can now check every candidate against a published standard — before any allocation decision.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Tools ── */}
      <section id="tools" style={{ position: 'relative', zIndex: 1, maxWidth: 900, margin: '0 auto', padding: '0 32px 80px' }}>
        <div style={{ marginBottom: 32 }}>
          <div style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, color: T.t3, letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 10 }}>
            MCP Tools
          </div>
          <h2 style={{ fontFamily: FONTS.brand, fontWeight: 700, fontSize: 26, color: T.t1, margin: 0 }}>
            6 tools. One server.
          </h2>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: 14 }}>
          {tools.map((t, i) => <ToolCard key={i} {...t} />)}
        </div>
      </section>

      {/* ── Quickstart ── */}
      <section style={{ position: 'relative', zIndex: 1, maxWidth: 900, margin: '0 auto', padding: '0 32px 80px' }}>
        <div style={{ marginBottom: 28 }}>
          <div style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, color: T.t3, letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 10 }}>
            Quick Start
          </div>
          <h2 style={{ fontFamily: FONTS.brand, fontWeight: 700, fontSize: 26, color: T.t1, margin: 0 }}>
            Connect in 2 minutes.
          </h2>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          {/* Claude Desktop config */}
          <div>
            <div style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, color: T.t3, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 12 }}>
              1 · Claude Desktop (claude_desktop_config.json)
            </div>
            <div style={{
              background: T.void, border: `1px solid ${T.border}`,
              borderRadius: 10, padding: '16px 18px', overflow: 'auto',
            }}>
              <pre style={{ fontFamily: FONTS.mono, fontSize: 12, color: T.cyan, margin: 0, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                {mcpConfig}
              </pre>
            </div>
          </div>
          {/* Python SDK */}
          <div>
            <div style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, color: T.t3, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 12 }}>
              2 · Python SDK
            </div>
            <div style={{
              background: T.void, border: `1px solid ${T.border}`,
              borderRadius: 10, padding: '16px 18px', overflow: 'auto',
            }}>
              <pre style={{ fontFamily: FONTS.mono, fontSize: 12, color: T.cyan, margin: 0, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                {pythonExample}
              </pre>
            </div>
          </div>
        </div>
        <div style={{ marginTop: 16, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          {[
            { label: 'Compatible with', value: 'Claude Desktop, Cowork, any MCP client' },
            { label: 'Transport', value: 'stdio (local) · SSE (remote)' },
            { label: 'Auth', value: 'API key in env var' },
          ].map((item, i) => (
            <div key={i} style={{
              background: T.surface, border: `1px solid ${T.border}`,
              borderRadius: 8, padding: '8px 14px',
              display: 'flex', gap: 8, alignItems: 'center',
            }}>
              <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{item.label}</span>
              <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.cyan }}>{item.value}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ── Pricing ── */}
      <section style={{ position: 'relative', zIndex: 1, maxWidth: 900, margin: '0 auto', padding: '0 32px 80px' }}>
        <div style={{ marginBottom: 32 }}>
          <div style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, color: T.t3, letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 10 }}>
            Pricing
          </div>
          <h2 style={{ fontFamily: FONTS.brand, fontWeight: 700, fontSize: 26, color: T.t1, margin: '0 0 8px' }}>
            Simple tiers. No surprises.
          </h2>
          <p style={{ fontFamily: FONTS.body, fontSize: 14, color: T.t3, margin: 0 }}>
            Free tier is open indefinitely. Pro tier pricing introduced when the product earns it.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 18 }}>
          <TierCard
            name="Free"
            price="$0"
            priceNote="No credit card. No expiry."
            features={[
              'get_cis_universe() — full scored universe',
              'get_cis_asset(symbol) — single asset deep dive',
              'get_regime_context() — live macro regime',
              '60 requests / hour rate limit',
              'Standard refresh cadence (30 min)',
            ]}
            cta="Start for free"
            ctaHref="#request-key"
          />
          <TierCard
            name="Pro"
            price="Early access"
            priceNote="Pricing TBD — apply to join waitlist"
            highlight={true}
            features={[
              'Everything in Free',
              'get_cis_exclusions() — full rejection list ★',
              'get_inclusion_standard() — 7-criterion JSON',
              'get_cis_history(symbol, days) — time series',
              '600 requests / hour rate limit',
              'Priority data refresh (10 min)',
              'Email support',
            ]}
            cta="Apply for Pro access"
            ctaHref="#request-key"
          />
          <TierCard
            name="Institutional"
            price="Contact us"
            priceNote="For fund operators and multi-agent deployments"
            features={[
              'Everything in Pro',
              'WebSocket streaming (real-time score push)',
              'Custom universe configuration',
              'SLA guarantee with uptime monitoring',
              'Direct line to research team',
              'White-label data licensing',
            ]}
            cta="Schedule a call"
            ctaHref="/strategy.html"
          />
        </div>
      </section>

      {/* ── Request key form ── */}
      <section id="request-key" style={{ position: 'relative', zIndex: 1, maxWidth: 680, margin: '0 auto', padding: '0 32px 120px' }}>
        <div style={{ marginBottom: 32 }}>
          <div style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, color: T.t3, letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 10 }}>
            Get access
          </div>
          <h2 style={{ fontFamily: FONTS.brand, fontWeight: 700, fontSize: 26, color: T.t1, margin: '0 0 8px' }}>
            Request an API key.
          </h2>
          <p style={{ fontFamily: FONTS.body, fontSize: 14, color: T.t3, margin: 0 }}>
            We review requests within 24 hours. Human agents, AI agents, and research teams welcome.
          </p>
        </div>
        <div style={{
          background: T.surface, border: `1px solid ${T.border}`,
          borderRadius: 16, padding: '32px',
        }}>
          <RequestKeyForm />
        </div>
      </section>

      {/* ── Footer ── */}
      <footer style={{
        position: 'relative', zIndex: 1,
        borderTop: `1px solid ${T.border}`,
        padding: '28px 32px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        maxWidth: 900, margin: '0 auto',
      }}>
        <div style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t4 }}>
          © 2026 CometCloud AI · Looloomi · Hong Kong
        </div>
        <div style={{ display: 'flex', gap: 20 }}>
          {[
            { label: 'Methodology', href: '/methodology.html' },
            { label: 'Fund', href: '/strategy.html' },
            { label: 'Platform', href: '/app.html' },
          ].map(l => (
            <a key={l.label} href={l.href} style={{
              fontFamily: FONTS.mono, fontSize: 11, color: T.t4,
              textDecoration: 'none', transition: 'color 0.2s',
            }}
              onMouseEnter={e => e.target.style.color = T.t2}
              onMouseLeave={e => e.target.style.color = T.t4}
            >{l.label}</a>
          ))}
        </div>
      </footer>
    </div>
  );
}

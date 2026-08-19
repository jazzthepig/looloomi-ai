/**
 * Vault — unpublished placeholder (2026-08-19, Jazz).
 *
 * WHY THIS EXISTS RATHER THAN AN EDIT TO VaultPage.jsx.
 * Jazz asked to take the Vault content down and put "in progress" up, with an
 * invitation for GPs interested in a distribution partnership. `VaultPage.jsx`
 * (1,059 lines: manager-selection criteria, deposit flow, allocation model)
 * is UNTOUCHED and still in the tree — this component simply replaces it at the
 * one render site in App.jsx. Unpublishing is a routing decision; deleting is a
 * loss. Restoring is a one-line revert.
 *
 * COMPLIANCE, and it is the reason the copy reads the way it does:
 *   · No returns, no APY, no target figures. CometCloud holds no 投顾 licence
 *     and this page is read by people who are not yet clients.
 *   · This is NOT an offer or a solicitation. It invites a conversation with
 *     managers; it does not describe terms, capacity, or economics.
 *   · No BUY/SELL/HOLD vocabulary anywhere (CLAUDE.md rule #1).
 *   · No internals — no stack, no infrastructure, no architecture (rule #8).
 *
 * "In progress" is stated plainly and without a date. A launch date on a page
 * like this is a promise the reader will hold you to, and every incident this
 * codebase has recorded started with a number written down before it was true.
 */
import { T, FONTS } from "../tokens";

const MAILTO =
  "mailto:jazz@cometcloud.ai" +
  "?subject=CometCloud%20Vault%20%E2%80%94%20distribution%20partnership" +
  "&body=Firm%3A%20%0ARole%3A%20%0AStrategy%20focus%3A%20%0AAUM%20band%3A%20%0A" +
  "Jurisdiction%3A%20%0ATrack%20record%20(years)%3A%20%0A%0ANotes%3A%20";

export default function VaultInProgress({ isSection = false }) {
  return (
    <div
      style={{
        position: "relative",
        minHeight: isSection ? "auto" : "70vh",
        padding: isSection ? "8px 0 64px" : "48px 28px 72px",
        maxWidth: 780,
      }}
    >
      <div
        style={{
          fontFamily: FONTS.mono,
          fontSize: 10,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          color: T.t3,
          marginBottom: 18,
        }}
      >
        Vault · Fund of Funds
      </div>

      <h1
        style={{
          fontFamily: FONTS.display,
          fontWeight: 700,
          fontSize: 42,
          lineHeight: 1.1,
          letterSpacing: "-0.02em",
          color: T.t1,
          margin: "0 0 8px",
        }}
      >
        In progress
      </h1>

      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          padding: "5px 11px",
          borderRadius: 999,
          border: `1px solid ${T.border}`,
          fontFamily: FONTS.mono,
          fontSize: 10,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: T.t2,
          marginBottom: 26,
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: 999,
            background: T.amber || T.t2,
            display: "inline-block",
          }}
        />
        Not open for subscription
      </div>

      <p
        style={{
          fontFamily: FONTS.body,
          fontSize: 16,
          lineHeight: 1.65,
          color: T.t2,
          margin: "0 0 16px",
          maxWidth: 620,
        }}
      >
        The Fund-of-Funds vault is being built. We are not accepting
        subscriptions, and nothing on this page is an offer.
      </p>

      <p
        style={{
          fontFamily: FONTS.body,
          fontSize: 16,
          lineHeight: 1.65,
          color: T.t2,
          margin: "0 0 34px",
          maxWidth: 620,
        }}
      >
        We would rather publish it late than publish it early. The rest of this
        platform is live and measurable in the meantime — the intelligence
        layer, the scoring engine and the research record are all open to read.
      </p>

      <div
        style={{
          borderTop: `1px solid ${T.border}`,
          paddingTop: 28,
          maxWidth: 620,
        }}
      >
        <div
          style={{
            fontFamily: FONTS.mono,
            fontSize: 10,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: T.t3,
            marginBottom: 12,
          }}
        >
          For managers
        </div>

        <p
          style={{
            fontFamily: FONTS.body,
            fontSize: 16,
            lineHeight: 1.65,
            color: T.t2,
            margin: "0 0 22px",
          }}
        >
          If you are a GP and would be interested in distribution through the
          vault when it opens, we would like to talk early — while the selection
          framework is still being shaped rather than after it is fixed.
        </p>

        <a
          href={MAILTO}
          style={{
            display: "inline-block",
            padding: "11px 20px",
            borderRadius: 8,
            border: `1px solid ${T.cyan || T.border}`,
            color: T.cyan || T.t1,
            fontFamily: FONTS.body,
            fontSize: 14,
            fontWeight: 500,
            textDecoration: "none",
          }}
        >
          Get in touch →
        </a>

        <div
          style={{
            fontFamily: FONTS.mono,
            fontSize: 11,
            color: T.t3,
            marginTop: 14,
          }}
        >
          jazz@cometcloud.ai · Hong Kong
        </div>
      </div>

      <p
        style={{
          fontFamily: FONTS.body,
          fontSize: 12,
          lineHeight: 1.6,
          color: T.t3,
          margin: "40px 0 0",
          maxWidth: 620,
        }}
      >
        Nothing on this page is an offer to sell or a solicitation to buy any
        security or interest in any fund, or a recommendation regarding any
        investment. Any future offering would be made only to eligible investors
        through formal documentation.
      </p>
    </div>
  );
}

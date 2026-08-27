"""DSR: the discount for having searched (S-189).

`experiment_runs.dsr` existed from the day the table was created and was never
populated once, while R70's best-of-grid Sharpe sat on an investor-facing page
with no multiple-testing correction. A column that exists, is never written, and
guards the failure mode this shop is most exposed to — searching until something
looks good — is worse than no column, because it signals the check is handled.

Computed on R70's real grid: DSR 0.27 at the honest N of 216, against a bar of
0.95. The observed 1.58 is BELOW the 2.38 that chance alone is expected to
produce as the best of 216 draws.
"""
import math

from src.research.validation.deflated_sharpe import (
    deflated_sharpe, expected_max_sharpe, required_sharpe, DSR_THRESHOLD)


# ⚠️ keyword-only 是修复不是回归 (S-236)。两个历史版本的 expected_max_sharpe
# 参数顺序相反,而两个参数都是 float —— 传反了不报错,只是算出另一个数。
# 位置调用现在 TypeError,所以这里改成关键字调用。
def test_searching_more_raises_the_luck_bar():
    """The whole point: the more you try, the better the best looks by chance."""
    v = (0.85 / math.sqrt(252)) ** 2
    bars = [expected_max_sharpe(n_trials=n, sr_variance=v) for n in (2, 10, 72, 216, 1000)]
    assert bars == sorted(bars), f"bar must rise with N: {bars}"
    assert bars[0] < bars[-1] / 2


def test_deflation_grows_with_the_search_not_with_pessimism():
    """DSR must punish SEARCHING, not merely reporting a number — otherwise it
    is a pessimism knob and will be ignored the first time it is inconvenient.

    NOTE the first version of this test passed `[2.0, 2.0]` as the trial set:
    zero dispersion, so sr_star is zero at every N and both sides came out
    identical. It failed against correct code. With no spread across trials
    there is nothing for selection to exploit, and the formula rightly deflates
    nothing — a degenerate case, not a counter-example."""
    trials = [2.0, 1.1, 0.4, -0.3, -0.9, -1.4]     # real dispersion
    few = deflated_sharpe(2.0, trials, n_obs=1000, n_trials=3)
    many = deflated_sharpe(2.0, trials, n_obs=1000, n_trials=5000)
    assert few["dsr"] > many["dsr"], (few["dsr"], many["dsr"])
    assert few["luck_threshold_sr_ann"] < many["luck_threshold_sr_ann"]


def test_zero_dispersion_deflates_nothing():
    """Stated explicitly because it looks like a bug the first time you hit it."""
    flat = deflated_sharpe(2.0, [2.0, 2.0, 2.0], n_obs=1000, n_trials=5000)
    assert flat["luck_threshold_sr_ann"] == 0.0
    assert flat["dsr"] > 0.99


def test_r70_fails_at_every_plausible_trial_count():
    """The finding, pinned. If someone later re-runs this and it passes, either
    the grid changed or the arithmetic did — both worth stopping for."""
    import json
    import pathlib
    p = (pathlib.Path(__file__).resolve().parents[1] /
         "Shadow/cometcloud-local/_reports/absorb_input/"
         "r70_held_out_oos_2026-07-22_summary.json")
    if not p.exists():
        import pytest
        pytest.skip("R70 summary not present (Shadow is not checked in)")
    srs = [v["oos_beta_adj_sr"] for v in json.load(p.open())["_results"].values()]
    assert len(srs) == 72

    for n in (72, 216):
        r = deflated_sharpe(max(srs), srs, n_obs=151, n_trials=n)
        assert not r["passes"], f"N={n}: DSR {r['dsr']} unexpectedly passes"
        assert r["dsr"] < 0.5, f"N={n}: DSR {r['dsr']}"
        assert not r["beats_luck_threshold"], (
            f"N={n}: observed {r['observed_sr_ann']} vs luck bar "
            f"{r['luck_threshold_sr_ann']} — if this ever flips, the page text "
            f"saying 'below the level luck alone would reach' is now false")


def test_annualised_inputs_are_converted():
    """A units mismatch here fails in the FLATTERING direction, which is the
    direction nobody checks. Feeding annualised Sharpes into a per-observation
    formula would overstate DSR by roughly an order of magnitude."""
    r = deflated_sharpe(1.58, [1.58, -0.4, 0.2, -1.1], n_obs=151, n_trials=72)
    # 1.58 annualised is ~0.0995 daily; the luck bar is reported annualised.
    assert 1.0 < r["luck_threshold_sr_ann"] < 10.0, r
    assert r["observed_sr_ann"] == 1.58


def test_gaussian_moments_are_flagged_as_an_assumption():
    r = deflated_sharpe(1.5, [1.5, 0.1, -0.3], n_obs=200, n_trials=10)
    assert r["moments_assumed"] is True
    r2 = deflated_sharpe(1.5, [1.5, 0.1, -0.3], n_obs=200, n_trials=10,
                         skew=-1.0, kurtosis=10.0)
    assert r2["moments_assumed"] is False
    assert r2["dsr"] != r["dsr"]


def test_required_sharpe_answers_how_far_off():
    """'Fails' invites 'how close?'. Usually the answer is 'not close'."""
    need = required_sharpe(216, 0.8523, 151)
    assert need > 3.0, f"expected an implausible bar, got {need}"


def test_threshold_is_named_not_buried():
    assert DSR_THRESHOLD == 0.95


def test_the_page_reports_what_the_module_computes():
    """The investor page carries hardcoded DSR figures. They must equal what the
    module produces from the real grid — a page and a calculator that disagree
    is how 1.58 got published as a production figure in the first place."""
    import json
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    p = (root / "Shadow/cometcloud-local/_reports/absorb_input/"
         "r70_held_out_oos_2026-07-22_summary.json")
    if not p.exists():
        import pytest
        pytest.skip("R70 summary not present")

    srs = [v["oos_beta_adj_sr"] for v in json.load(p.open())["_results"].values()]
    r = deflated_sharpe(max(srs), srs, n_obs=151, n_trials=216)

    page = (root / "dashboard/src/components/ResearchTrackRecord.jsx").read_text()
    block = page.split("const DSR = {")[1].split("};")[0]

    def field(name):
        m = re.search(rf'{name}:\s*"?([-−\d.]+)"?', block)
        return m.group(1).replace("−", "-") if m else None

    assert abs(float(field("value")) - r["dsr"]) < 0.005, (
        f'page says DSR {field("value")}, module computes {r["dsr"]}')
    assert abs(float(field("luckThreshold")) - r["luck_threshold_sr_ann"]) < 0.01, (
        f'page luck bar {field("luckThreshold")} vs {r["luck_threshold_sr_ann"]}')
    assert abs(float(field("observed")) - r["observed_sr_ann"]) < 0.01
    assert int(field("nTrialsFunnel")) == 216
    assert abs(float(field("gridMean")) - r["trial_sr_ann_mean"]) < 0.01, (
        f'page grid mean {field("gridMean")} vs {r["trial_sr_ann_mean"]}')


def test_the_page_does_not_claim_the_result_passes():
    """CLAUDE.md: every claim guilty until proven. This one is not proven."""
    import pathlib
    page = (pathlib.Path(__file__).resolve().parents[1] /
            "dashboard/src/components/ResearchTrackRecord.jsx").read_text()
    assert "Deflated Sharpe" in page, "the discount must be ON the page, not only in a ledger"
    assert "does not clear our bar" in page or "failed our own bar" in page

    # ⚠️ TWO ROUNDS OF OVER-BLOCKING GOT THIS LIST TO ITS CURRENT SHAPE, and
    # both failures were the same kind: a keyword cannot see what it is doing in
    # the sentence.
    #
    #   · bare "expected to" fired on "chance alone is EXPECTED TO produce a
    #     best-of-set Sharpe of 2.38" — a statement about a null distribution,
    #     the single most honest sentence on the page.
    #   · bare "guarantee" fired on the DISCLAIMER, "carry no guarantee of
    #     future performance" — a guard flagging the very text that exists to
    #     satisfy it.
    #
    # A keyword guard has no polarity and no subject. Both would have forced
    # correct writing to be mangled to satisfy a check that misread it, and a
    # guard that flags correct output is one somebody switches off — after
    # which nothing is checked at all. Patterns below are regexes that carry a
    # subject or an affirmative form, so they cannot fire on a negation or on a
    # sentence about chance.
    import re as _re
    FORWARD_PROMISE = [
        r"\bwill\s+outperform\b",
        r"\bwe\s+expect\b",
        r"\bpoised\s+to\b",
        r"(?<!no )\bguarantees?\s+(?:of\s+)?(?:a\s+)?(?:return|profit|performance)",
        r"\bwe\s+guarantee\b",
        r"\bprojected\s+returns?\b",
        r"\btarget(?:ed)?\s+returns?\s+of\b",
        r"\bshould\s+return\b",
        r"\bis\s+likely\s+to\s+(?:return|outperform|gain)\b",
        r"\bexpected\s+returns?\s+of\b",
    ]
    for pat in FORWARD_PROMISE:
        m = _re.search(pat, page, _re.I)
        assert not m, f"forward promise on an investor page: {m.group(0)!r}"

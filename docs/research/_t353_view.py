#!/usr/bin/env python3
"""T-353 视图:把 t353_results.json 压成可贴进报告的表。"""
import json

R = json.load(open("/Users/sbb/Projects/looloomi-ai-lane-a/docs/research/t353_results.json"))
C = R["cells"]
for tag in ("main_ef1_gbmarked", "alt_ef0_gbentry"):
    print("=" * 18, tag)
    sw = C[tag]["capn_sweep_f0.5_cap0.40"]
    for k, v in sw.items():
        print("  %s: taken %d skipped %d closed %d open_end %d ret %+.4f%% mdd %+.4f%% "
              "(%s→%s) peak_gross %.4f inv3 %.3e"
              % (k, v["taken"], v["skipped"], v["closed"], v["open_at_end"],
                 v["total_return"] * 100, v["mdd"] * 100, v["mdd_peak"], v["mdd_trough"],
                 v["peak_gross"], v["invariant3_diff"]))
        print("     skip:", v["skip_reasons"])
        if "by_year" in v:
            print("     by_year:", {y: round(x * 100, 2) for y, x in v["by_year"].items()})
    for k, v in C[tag]["grid_f_x_cap1.20_capn14"].items():
        print("  GRID %s: taken %d ret %+.4f%% mdd %+.4f%% peak_gross %.3f skip %s"
              % (k, v["taken"], v["total_return"] * 100, v["mdd"] * 100,
                 v["peak_gross"], v["skip_reasons"]))
    for k, v in C[tag]["grid_f_x_cap1.20_capninf"].items():
        print("  GRIDinf %s: taken %d ret %+.4f%% mdd %+.4f%%"
              % (k, v["taken"], v["total_return"] * 100, v["mdd"] * 100))

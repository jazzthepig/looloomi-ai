import json
import sys
import numpy as np

sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai-lane-c")
from src.data.evaluation.apparatus import newey_west_t

d = json.load(open('/Users/sbb/Projects/looloomi-ai-lane-c/docs/research/t223_family2.json'))
g = d['factors']['G5']
print("series_range", g['series_range'], "n", g['series_n'])
print("verdict", g['verdict'], "shortlisted", g['shortlisted_in_discovery'])
for s in ('discovery', 'holdout'):
    x = g['segments'][s]
    print("==", s, x['months'], "n_months", x['n_months'], "F_med", round(x['F_median'], 4))
    print("   nw5", x['nw_t_lag5'], "nw2", x['nw_t_lag2'], "nw1", x['nw_t_lag1'])
    print("   mean_agr", x['mean_agreement'], "sign_rate", x['sign_agree_rate'])
    o = x['ols_R_on_F']
    print("   ols slope", round(o['slope'], 4), "t", o['t'], "corr", o['corr'], "n", o['n'])
    print("   lag1", x['lag1_Fprev'])
    # 探索性:F 有没有时间趋势?去趋势后关联还在不在?(只报,不改判定)
    rows = x['table']
    F = np.array([r['F'] for r in rows], float)
    R = np.array([r['R_uni'] for r in rows], float)
    ti = np.arange(len(F), dtype=float)
    cf = float(np.corrcoef(ti, F)[0, 1])
    b = float(np.polyfit(ti, F, 1)[0])
    Fd = F - (b * ti + (F.mean() - b * ti.mean()))
    cd = float(np.corrcoef(Fd, R)[0, 1])
    med = float(np.median(Fd))
    s = np.where(Fd > med, 1.0, -1.0)
    a = s * np.sign(R)
    nwd = newey_west_t(a.tolist(), lags=5)[0]
    print("   [探索性] corr(F, time)=", round(cf, 4), " F~time 斜率/月=", round(b, 5),
          " 去趋势后 corr(F_dm,R)=", round(cd, 4), " 去趋势后 NW t(lag5)=", nwd,
          " 同号月=", round(float((a > 0).mean()), 4))
    print("   R_uni 符号: 正", int((R > 0).sum()), "负", int((R < 0).sum()), "/", len(R))

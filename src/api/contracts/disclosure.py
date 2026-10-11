"""对外的信号口径 —— 一处定义,所有信号面引用(Jazz 10-09,S-529)。

Jazz 10-09:「是根据过往表现展示,并非预测」。S-527 的数据:标 OUTPERFORM 的名字 17 个月跑输同类等权 ——
字面「将跑赢」与数据相反。CIS 描述的是已经发生的事(支柱是过去与当下的数据);组合怎么用是另一层。
所以每个信号面都说同一句话,并且把这一档信号自己的历史结果放在旁边(T-078 归因)。

改这里的文字 = 改所有信号面;`tests/test_signal_disclosure.py` 守着「没有信号面另写一句」。
"""
from __future__ import annotations

SIGNAL_DISCLOSURE = (
    "CIS signals describe where each asset sits in the scored universe, computed from past and current data, "
    "and are shown with the historical outcomes of signals of the same kind. They are not forecasts of future "
    "performance and not investment advice."
)

SIGNAL_DISCLOSURE_ZH = (
    "CIS 信号是根据过往与当下数据,对资产在评分宇宙中所处位置的描述,并附同一档信号的历史表现;"
    "不是对未来表现的预测,也不是投资建议。"
)

#: 读法:放在每个信号旁边的「历史表现」怎么读。
TRACK_RECORD_READING = (
    "Historical outcomes are measured after each past signal change of the same kind, relative to an "
    "equal-weight basket of the scored universe. They describe what followed in the past, including periods "
    "when the label and the outcome pointed in opposite directions; they do not describe what will follow."
)

#: 正式 CIS 的计算口径(Jazz 10-11,T-080 / S-533)。所有带 `official` 块的响应引用这一句。
OFFICIAL_BASIS = (
    "Official CIS is computed once per day on the UTC daily close, using only data that was available at that "
    "close, with one source per input. Signal levels rank each asset within its group (crypto or traditional "
    "assets) on that day, with a 10-percentile buffer before a level changes; grades use the absolute score. "
    "Intraday values are a preview and do not change the published signal."
)

OFFICIAL_BASIS_ZH = (
    "正式 CIS 每天在 UTC 收盘后计算一次,只用收盘时已经可得的数据,每个输入只有一个来源。"
    "信号档位按当天同组(加密 / 传统资产)排名确定,换档前有 10 个百分位的缓冲;等级按绝对分。"
    "盘中数值是预览,不改变已发布的信号。"
)

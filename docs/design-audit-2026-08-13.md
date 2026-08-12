# Design Audit — CometCloud Web Frontend — 2026-08-13

> **角色**:Minimax-A 视觉/设计专家审查模式。
> **范围**:`dashboard/src/tokens.js` · `dashboard/src/index.css` · `dashboard/index.html` · `dashboard/src/App.jsx` · 35 个 components 抽样。
> **审查面**:设计系统、字体加载、可达性、动效预算、组件密度。

---

## TL;DR — 三件最该先做

1. **可达性 P0 三件**:零 aria,零 alt,无 `prefers-reduced-motion` —— 机构 LPs(视障成员 + 50+ 决策者 + 监管层 WCAG 抽查)实打实的 risk,**不是 aesthetics**。
2. **Token 体系存在但失效**:`tokens.js` 定义了颜色,35 个 components 里**只有 5 个用 `lm-card` class,33 个用 inline style** —— 设计系统成了参考手册,不是约束。
3. **App.jsx 是 1167 行的上帝文件**:Sidebar / DesktopApp / 4 个 view / 1 个 widget / 1 个死代码全堆在里面,130 处 inline style。

**完整报告在 `MINIMAX_SYNC.md` §DESIGN-AUDIT-2026-08-13。** 本文件是落地版,只列**已经开干的修复** + 状态。

---

## 一、做对的事(地基,不动)

| # | 现象 | 文件/行 |
|---|---|---|
| 1 | L1/L2/L3 三层卡片深度系统成立 | `index.css:268-310` |
| 2 | 类型层级守纪律(Syne→Exo 2→JetBrains Mono) | `index.css:65-67` |
| 3 | 合规对齐的色彩语义(SIG_STYLE 5 信号) | `tokens.js:71-77` |
| 4 | Turrell 环境光真做了(4 层 + bgBreath 24s + grain noise SVG 内联) | `index.css:233-262` |
| 5 | "承认的坏"纪律(导航命名 bug 显式标记 + 注明 STILL WRONG) | `App.jsx:276-296` |
| 6 | 移动端有 fallback 而非事后修补 | `index.css:358-374`, `App.jsx:88-97` |

---

## 二、需要修的事(按严重度)

### 🔴 P0 — 可达性 / 法律风险

| 编号 | 问题 | 修法 |
|---|---|---|
| **A1** | App.jsx 0 个 aria-*、CISLeaderboard 0 个 alt/aria | Sidebar 父按钮加 `aria-current={isParentActive ? "page" : undefined}`、子按钮同理;图标按钮加 `aria-label`;图表加 `role="img"` |
| **A2** | `prefers-reduced-motion` 完全无保护 | `@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; } }` |
| **A3** | `T.muted = rgba(199,210,254,0.45)` 正文未达 WCAG AA 4.5:1 | secondary 文本(font-size ≤ 14px)升 0.65+ opacity,或换 token;补 `scripts/check_contrast.py` 自动测试 |

### 🟡 P1 — 可维护性 + 设计系统失效

| 编号 | 问题 | 修法 |
|---|---|---|
| **B1** | Token 化颜色被 inline 覆盖(11 文件 inline cyan、9 文件 inline royal) | B1a ESLint `no-restricted-syntax` 禁止 inline 颜色;B1b 抽 8-10 个 class;B1c 重构 5 个最重组件 |
| **B2** | `App.jsx` 1167 行上帝文件 + `_HeroContent_REMOVED` 死代码 110 行 | 拆 6 文件 + 删死代码 |
| **B3** | 字体反模式:`index.css:3` 同时 `@import` Google Fonts(render-blocking),且加载了未用的 Cormorant Garamond / Space Grotesk | 删 `@import`、删 2 个未用 font family、保留 `font-display: swap` |
| **B4** | Section header 模式三处各自实现(`App.jsx:142-161` / `968-984` / `1118-1133`),已有现成 `SectionLabel` component | 三处都改 `<SectionLabel label="..." sub="..." stats={...} />` |
| **B5** | CISLeaderboard 1661 行 / 227 inline style | 同 B1 重构路径,先 lint rule 卡新增 |

### 🟢 P2 — 性能 + 美学

| 编号 | 问题 |
|---|---|
| **C1** | 6 个 infinite animation + 6 个 backdrop-filter 叠加,GPU 持续吃电;scroll-driven animation 未用 |
| **C2** | 9 个平级 nav item,icon 视觉权重无差(`◉◈◆▲⬡◎∿⊡⌘`);归 Jazz 产品决策 |
| **C3** | `App.jsx:593` 直接写 `'JetBrains Mono'` 字符串不走 `FONTS.mono`,5+ 处 |

---

## 三、推荐执行序列(3 天)

### Day 1(半天,~3 小时)— 6 项快速胜利
- [ ] 删 `_HeroContent_REMOVED` 死代码(110 行) — 5 min
- [ ] 删 `index.css:3` `@import` Google Fonts — 5 min
- [ ] 删未用 Cormorant Garamond + Space Grotesk 字体(~30KB) — 5 min
- [ ] 加 `prefers-reduced-motion` 5 行 CSS — 5 min
- [ ] Sidebar 加 `aria-current` — 30 min
- [ ] `SectionLabel` 三处复用 — 1 小时
- [ ] `T.muted` 用法 audit + 升 opacity — 1 小时

### Day 2-3(2 天)— 设计系统真的生效
- [ ] B1a ESLint rule 卡新增 inline 颜色
- [ ] B1b 抽 8-10 个常用 class(`.lm-divider-cyan` / `.lm-stat-row` / `.lm-section-title` 等)
- [ ] App.jsx 拆分 B2
- [ ] CISLeaderboard inline → class 迁移(B5)

---

## 四、本次会话基线(VERSION ARCHIVE)

> 2026-08-13 提交 `MINIMAX_SYNC.md` §DESIGN-AUDIT-2026-08-13 + 本文件。`git tag pre-design-audit-2026-08-13` 标记 Day 1 改动前快照。后续如改坏可 `git reset --hard pre-design-audit-2026-08-13` 回滚。

---

## 五、回滚契约

每个 Day 1 改动独立 commit,主题含 `[design-audit]`,失败任一项可单独 revert:

```bash
git log --grep='\[design-audit\]' --oneline   # 列出本次所有 audit commit
git revert <hash>                              # 单独回滚
```

# 策略模块（第七期）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户持续优化同一策略（条件不断增加），需要一个**策略列表 + 版本**体系：每次回测要么选一个已测策略（版本号递增），要么新建策略（=v1）；每个新版本的回测记录自动与 **v1（原版）** 与 **上一版** 对比，判定"有没有进度"。相当于在行情模块、因子模块之后加一个**策略模块**，存储：策略名称、策略方案、回测记录、回测结果。

**Architecture:** 新包 `src/strategy/` 纯文件系统目录式 JSON 存储（镜像 `src/factors/` 风格，tempfile.mkstemp + os.replace 原子写），不依赖 DataCenter；布局 `data/strategies/<整数id>/strategy.json + versions/<N>/`，`manifest.json` 只存 `next_id`，列表走扫描。对比逻辑为纯函数（无 I/O）。新增 `backtest_meta.json` 边车记录复权口径/成本模型/策略参数/区间——results.json 缺这些决定参数，没有它无法做可比性检查。

**Tech Stack:** 仅 Python 标准库（json/tempfile/os/shutil）；无新依赖。CLI 用 argparse + main() 模式（对齐 `scripts/daily.py`）。

**Spec:** `docs/superpowers/specs/2026-09-01-strategy-design.md`

## Global Constraints

- **测试命令**：`.venv/bin/python -m pytest tests/`（配置 `--timeout=60`）。
- **不用 git**：所有 `Step N: Commit` 保持未勾，标注"（不执行，保持未勾）"；每完成一个 Step 立即 `- [ ]`→`- [x]`。
- **省 token**：`list`/`show`/`compare` 只读 version.json 摘要（不读 results.json 交易明细）。
- **测试不联网**：纯 tmp_path 目录存储 + 合成 report 产物，无 DataCenter/网络依赖（沿用 test_factor_store.py 鸭子类型风格）。
- **边车纪律**：skill Step4 必须写 `backtest_meta.json`，否则 record 时补默认值并警告；复权口径/成本模型缺失无法做可比性判断。
- **可比性纪律**：symbols/period/adjust/区间/initial_cash/成本模型(6字段)全等才可比；策略 params 差异**不**阻断可比（那是被测对象）。
- 时间戳为毫秒 int。中文输出/文档。

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/strategy/__init__.py` | 导出 `StrategyStore` + 异常族 |
| `src/strategy/errors.py` | `StrategyError` / `StrategyNotFoundError` / `VersionNotFoundError` |
| `src/strategy/store.py` | `StrategyStore`：CRUD + 版本递增 + import_version 登记 + 自动对比 |
| `src/strategy/compare.py` | 纯函数：comparable / metric_delta / excess_return / judge_verdict / build_comparison |
| `scripts/strategy_cli.py` | 9 子命令：create / list / show / versions / show-version / record / compare / rename / delete |
| `tests/test_strategy_store.py` | 存储 CRUD / 版本递增 / 原子写 / 产物复制 / 对比幂等 |
| `tests/test_strategy_compare.py` | 可比性 / 方向 / inf 特判 / 判定三态 |
| `tests/test_strategy_cli.py` | CLI 冒烟（main(argv)+capsys） |
| `tests/test_build_report_comparison.py` | build_report 版本对比章节渲染冒烟 |
| `pyproject.toml` | packages 加 `"src/strategy"` |
| `.claude/skills/backtest-expert/SKILL.md` | 产出目录 / Step1 选策略 / Step4 边车 / Step5 record / 版本对比语义 |
| `.claude/skills/backtest-expert/scripts/build_report.py` | 加可选"七、版本对比"章节 |
| `docs/superpowers/specs/2026-09-01-strategy-design.md` | 设计权威 |
| `HELP.md` | 代码结构/迭代历史/常用命令/待办同步 |

---

## Task 1: 包骨架 + 存储 CRUD

**Files:**
- Create: `src/strategy/__init__.py`
- Create: `src/strategy/errors.py`
- Create: `src/strategy/store.py`（create / list / get / rename / delete / list_versions / get_version / 原子写 / manifest）
- Create: `tests/test_strategy_store.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `StrategyStore(root="data/strategies")`；`create_strategy(name, description="") -> int`（id 单调递增、删除不重用）；`list_strategies() -> list[dict]`（附最新版摘要，可 JSON 序列化）；`get_strategy/rename_strategy/delete_strategy`；`list_versions/get_version`；`_atomic_write(path, obj)`（mkstemp + os.replace）

- [x] **Step 1: 写失败测试**（`tests/test_strategy_store.py`：create 递增 id、strategy.json+manifest、list 空/按 id 序、get 缺失抛错、delete 删整棵 + id 不重用、list_versions 顺序、原子写无 .tmp 残留）

- [x] **Step 2: 运行确认失败** → `.venv/bin/python -m pytest tests/test_strategy_store.py -v`，预期 FAIL（`ModuleNotFoundError: strategy`）

- [x] **Step 3: 实现** `src/strategy/errors.py`（异常族）+ `__init__.py`（docstring 说明镜像 src/factors/、纯文件系统、无 DataCenter 依赖）+ `store.py`（CRUD + 原子写 + manifest 只存 next_id；列表走扫描 `_scan_dirs`）

- [x] **Step 4: 更新 pyproject.toml** → packages 加 `"src/strategy"`

- [x] **Step 5: 运行确认通过** → `.venv/bin/python -m pytest tests/test_strategy_store.py -v`，PASS

- [ ] **Step 6: Commit**（不执行，保持未勾）

---

## Task 2: 对比纯函数

**Files:**
- Create: `src/strategy/compare.py`
- Create: `tests/test_strategy_compare.py`

**Interfaces:**
- Produces: `comparable(new, old) -> (bool, note)`（sorted symbols/period/adjust/start_ms+end_ms/initial_cash/broker dict 全等）；`metric_delta(metric, old_m, new_m) -> {old,new,delta,better}`（DIRECTIONS：max_drawdown 降为好、trade_count=None、其余升为好）；`excess_return(version) -> float`；`judge_verdict(primary_deltas) -> str`；`compare_versions(new, old) -> dict`；`build_comparison(new, v1, prev) -> dict`（同时 vs_v1 + vs_prev）

- [x] **Step 1: 写失败测试**（`tests/test_strategy_compare.py`：可比性 true/false 各维度、metric_delta 方向、profit_loss_ratio=inf 特判、excess_return、judge_verdict 三态、build_comparison 组装）

- [x] **Step 2: 运行确认失败** → `.venv/bin/python -m pytest tests/test_strategy_compare.py -v`，预期 FAIL（`ModuleNotFoundError: strategy.compare`）

- [x] **Step 3: 实现** `src/strategy/compare.py`（纯函数无 I/O；inf → delta=None 防 JSON 序列化失败，方向照判）

- [x] **Step 4: 运行确认通过** → `.venv/bin/python -m pytest tests/test_strategy_compare.py -v`，PASS

- [ ] **Step 5: Commit**（不执行，保持未勾）

---

## Task 3: CLI + import_version 全流程

**Files:**
- Modify: `src/strategy/store.py`（补 `import_version(sid, report_dir, *, change_note="") -> int` 核心：读 results+backtest_meta → 建版本 → 复制产物 → 写 version.json → 自动对比 v1+上一版 → 追加 report.md → 更新 latest_version；`recompute_comparison(sid, v)` 幂等；`get_comparison`）
- Create: `scripts/strategy_cli.py`
- Create: `tests/test_strategy_cli.py`

**Interfaces:**
- Consumes: Task 1 的 CRUD + Task 2 的纯函数；skill 产物（results.json/equity.csv/report.md/backtest_meta.json/strategy_*.py/run_*.py）
- Produces: `import_version`（复制 `strategy_*.py`→`strategy_v<N>.py`）；CLI `record --id --from <scratch> --note "..."`（打印对比结论）

- [x] **Step 1: 补 import_version 测试**（test_strategy_store.py：v1 布局无 comparison、v2 对比写 comparison.json + 追加 report.md 且幂等、缺失 results 抛错、不可比写 note、latest_version 更新）

- [x] **Step 2: 实现 import_version** → 读 backtest_meta + results → 组装 version.json（`backtest` 决定参数 + `results` 摘要 + `excess_return`）→ 复制产物 → v≥2 自动 `build_comparison` 写 comparison.json + `_append_compare_md` → 更新 strategy.json.latest_version

- [x] **Step 3: 写 CLI 冒烟测试**（`tests/test_strategy_cli.py`：main(argv)+capsys，create/list/record/compare/show/versions/show-version/rename/delete；复用 test_strategy_store 的 `write_report_dir` fixture）

- [x] **Step 4: 实现 CLI** `scripts/strategy_cli.py`（argparse + main()，`--root` 默认 `data/strategies`；`list` 列 verdict（vs_prev 优先）、`record` 打印 vs v1/vs 上一版 结论；`_print_comparison` 用 ↑/↓/— 箭头）

- [x] **Step 5: 运行确认通过** → `.venv/bin/python -m pytest tests/test_strategy_cli.py tests/test_strategy_store.py -v`，PASS

- [ ] **Step 6: Commit**（不执行，保持未勾）

---

## Task 4: build_report 对比章节 + SKILL.md 集成

**Files:**
- Modify: `.claude/skills/backtest-expert/scripts/build_report.py`
- Modify: `.claude/skills/backtest-expert/SKILL.md`
- Create: `tests/test_build_report_comparison.py`

**Interfaces:**
- Consumes: comparison.json（v≥2 才有）
- Produces: `build_pdf()` 在"六、操作指引"后、免责声明前加可选"七、版本对比"章节（vs_v1/vs_prev 各一表 + 结论行；comparable==false → 警告行；缺失/损坏 → 静默跳过，老 reports/ 不受影响）

- [x] **Step 1: build_report 加渲染** → `_CMP_PCT`/`_CMP_MONEY`/`_CMP_VERDICT` 格式化集合 + `_fmt_cmp(name, x)` + `_comparison_flowables(report_dir, cjk, cjk_bold)`（返回 flowables 或 None）+ 在 build_pdf 六章后插入

- [x] **Step 2: 写渲染冒烟测试**（`tests/test_build_report_comparison.py`：importlib 加载 build_report.py；`_register_reportlab_font()` + `draw_equity_curve` + `build_pdf`；4 用例：无 comparison / comparable / not-comparable / 损坏 json 兜底）

- [x] **Step 3: 运行确认通过** → `.venv/bin/python -m pytest tests/test_build_report_comparison.py -v`，PASS

- [x] **Step 4: SKILL.md 集成**（5 处）：
  1. 产出目录节：scratch = 中间态，登记进 `data/strategies/<id>/versions/<N>/`；backtest_meta.json 列入产物表
  2. Step 1 加"选策略（新建 or 升级版本）"：`strategy_cli.py list` → 继续优化指认 `--id`（读 v1+上一版摘要省 token）/ 全新 `create`
  3. Step 4 加 backtest_meta.json schema bullet（params 必须如实记录——那是被测对象）
  4. Step 5 改"版本登记 + 报告 + 操作指引"：`record --from <scratch> --note "..."` → `build_report.py data/strategies/<id>/versions/<N>/` → 口头结论加"对比结论"
  5. 新"## 版本对比语义"小节（判定规则 + 可比性纪律：改标的/区间/成本模型=不可比；策略参数≠阻断）

- [x] **Step 5: 端到端验证** → 用现有 `reports/atr-stop-ma-cross-.../` 作 `--from`：create → record（v1，无对比章节）→ 再 record v2 → build_report，肉眼确认 PDF"七、版本对比"章节 + list 见进度判定

- [ ] **Step 6: Commit**（不执行，保持未勾）

---

## Task 5: 文档（phase7 plan + spec + HELP.md 同步）

**Files:**
- Create: `docs/superpowers/plans/2026-09-01-strategy-phase7.md`（本文件）
- Create: `docs/superpowers/specs/2026-09-01-strategy-design.md`
- Modify: `HELP.md`

- [x] **Step 1: 写 spec**（设计权威：背景/已确认决策/整体架构/数据模型/版本对比语义/接线/验收）

- [x] **Step 2: 写 plan**（本文件，checkbox 进度索引）

- [x] **Step 3: HELP.md 同步**（强制规则，同会话内）：
  - §3/迭代历史：加第七期策略模块
  - §5 代码结构：加 `src/strategy/`（errors/store/compare）与 `scripts/strategy_cli.py`
  - §7 待办：策略模块已完成
  - §9 常用命令：加 `scripts/strategy_cli.py` 各子命令
  - 测试数 167 → 200；pyproject packages 列表

- [x] **Step 4: 全量回归** → `.venv/bin/python -m pytest tests/`，全绿（200 passed）

- [x] **Step 5: 通读 HELP.md** → 确认无过期信息

- [ ] **Step 6: Commit**（不执行，保持未勾）

---

## 关键复用

- 目录式 JSON 存储先例：`src/factors/store.py`（原子写 + 指纹目录）
- argparse + main() CLI 模式：`scripts/daily.py`
- 测试基建：`tests/conftest.py` 的 `make_kline_df`/`tmp_data_dir`；`tests/test_factor_store.py` 鸭子类型风格；`tests/__init__.py` 使 `from tests.test_strategy_store import write_report_dir` 跨测试复用可用
- 报告生成：`.claude/skills/backtest-expert/scripts/build_report.py`（reportlab 6 章 → 加"七、版本对比"）
- skill 写作规范：`.claude/skills/backtest-expert/SKILL.md`（五步工作流）
- 计划/规格：spec `docs/superpowers/specs/2026-09-01-strategy-design.md`

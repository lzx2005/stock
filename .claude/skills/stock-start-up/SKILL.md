---
name: stock-start-up
description: 项目初始化引导——帮新用户把本仓库从零跑起来：检查 Python 环境与依赖、配置 TICKFLOW_API_KEY、回填首批行情数据、可选配置 Bark 推送、跑冒烟验证，最后引导使用回测/盯盘/复盘三个专家 skill。当用户说"我刚下载/clone 了这个项目""帮我配置一下""怎么开始用""环境怎么搭""第一次使用""初始化"等，务必使用本 skill。
---

# Stock Start-Up · 新用户初始化引导

> 前置：用户已完成 `git clone` 并在项目根目录打开了 Claude Code（README「用 Skill 操作」一节引导至此）。本 skill 从环境检查开始。

目标：让用户**配好基本信息 → 跑一次冒烟验证 → 直接用三个专家 skill 开始操作**。
全程用程序验证结果（本项目铁律：AI 不碰数据，一切结论以脚本/命令输出为准），不要凭印象说"应该没问题"。

## 初始化的最终状态

| 项 | 配好的标志 |
|---|---|
| Python 环境 | `.venv/bin/python -m pytest tests/ -q` 全绿 |
| TickFlow API Key | 真实查询一只股票日 K 成功返回数据 |
| 首批行情数据 | 用户关心的标的（或全市场日线）已回填落盘 |
| Bark 推送（可选） | `data/monitor_config.json` 存在且含 `bark_key` |

## Step 1 · 环境与依赖

```bash
python3 --version          # 需 ≥ 3.11
uv sync                    # 首选；无 uv 则：python3 -m venv .venv && .venv/bin/pip install tickflow[all] duckdb pandas pyarrow fastapi uvicorn reportlab matplotlib pytest pytest-timeout httpx
.venv/bin/python -m pytest tests/ -q   # 全绿即环境 OK（纯本地测试，不需要 key）
```

失败则先把环境修到测试全绿，再继续。

## Step 2 · 配置 TICKFLOW_API_KEY（必需，付费）

1. 先检查是否已配：`zsh -ic 'echo -n $TICKFLOW_API_KEY'`（**不要** `source ~/.zshrc` 进 sh——zsh 专有语法会中断）。
2. 已配 → 跳到验证。未配 → 引导用户到 [tickflow.org](https://tickflow.org) 注册开通，向用户索要 key。
3. **征得用户明确同意后**，把 `export TICKFLOW_API_KEY="用户给的key"` 追加到 `~/.zshrc`。
   - key 只进 `~/.zshrc`，**永不写入仓库任何文件**（含文档、代码、注释）。
4. 验证（真实查询，必须用程序输出确认）：

```bash
source ~/.zshrc && .venv/bin/python -c "
from datacenter import DataCenter
df = DataCenter().get_klines('600000.SH', '1d', None, None)
print(f'OK，{len(df)} 根日K，最新 {df.iloc[-1][\"timestamp\"]}')" 
```

## Step 3 · 回填首批数据（必需，问用户范围）

问用户：**只下自选股**（让用户给出代码列表，如 600000.SH,000001.SZ）还是**全市场日线**（5000+ 只，数十分钟，断点续传）？

```bash
source ~/.zshrc && .venv/bin/python scripts/backfill.py --periods 1d --symbols <用户列表>   # 自选股
source ~/.zshrc && .venv/bin/python scripts/backfill.py --periods 1d                        # 全市场日线
```

分钟线按需另补（`--periods 1m,5m,15m,30m,60m`，注意分钟历史深度仅最近一年）。回填完用命令输出告知实际落盘情况。

## Step 4 · Bark 推送（可选，仅盯盘需要）

问用户是否要在 iPhone 上接收盯盘提醒。需要则：装 [Bark](https://bark.day.app) → 拿 device key → 征得同意后写 `data/monitor_config.json`：`{"bark_key": "<device_key>"}`（该文件已 gitignore）。不配则盯盘只亮灯不推送，其余功能不受影响。

## Step 5 · 交付引导（必须做）

配置完成后，告诉用户**与本项目的主要交互方式是 Skill**（在 Claude Code 里直接用自然语言触发）：

| Skill | 干什么 | 这样说就会触发 |
|---|---|---|
| 回测专家 `backtest-expert` | 验证交易想法：跑真实回测、出 PDF 报告、给同花顺一句话条件 | "帮我回测一下双均线策略在 600000 上近 5 年的表现" |
| 盯盘专家 `monitor-expert` | 把盯盘条件做成常驻任务：脚本验证 + 注册 + 灯亮推手机 | "600869 跌到 20 日低位区时提醒我" |
| 复盘专家 `trade-review` | 交割单/交易记录复盘：时机评估、亏损归因、改进建议 | "帮我复盘一下这个月的交易记录" |

并提示：盯盘/后台服务用 `sh scripts/start.sh` 一键启动（守护进程 + Web API 8666）。

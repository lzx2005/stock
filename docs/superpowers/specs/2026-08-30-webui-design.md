# Web 查询界面 · 设计文档

日期：2026-08-30（修订 2026-08-31：前端改为 React + antd，加 K 线图）
状态：待用户审阅

## 1. 背景与目标

数据中心（`src/datacenter/`）与因子库（`src/factors/`）已完成：K 线、财务/元数据、因子值都落在本地 `data/`（parquet + meta.db），回测与因子预热通过 CLI/脚本驱动。但目前**没有任何可视化界面**——查看"存了什么、值是什么"只能写脚本或跑回测。

目标：提供一个**本地 Web 页面**，让用户用浏览器直观地：
1. **查已存行情**：按标的 + 周期 + 日期范围分页浏览存储的 K 线，配一张**简单 K 线图**；按代码/名称搜索标的。
2. **查因子列表**：浏览 11 个内置因子的注册定义（参数/说明/同花顺条件句），以及 `data/factors/` 里**已算好**的因子数据（哪些指纹×标的×周期已入库，值是什么）。

纯查询工具：**只读已存数据，绝不触发网络回源，无需 API key**。

### 工作流边界（用户确认）

- **技术栈**：后端 FastAPI；前端 **React + TypeScript + antd + Vite**（前后端分离）。
- **图表**：**ECharts candlestick**（简单 K 线图）。
- **因子范围**：注册定义列表 + 已存数据浏览（两档都要）。
- **非目标（本期不做）**：复权切换视图、warm/drop/refresh 等写操作、策略研究/回测执行入口、登录鉴权（本地单用户）、前端单测工具链。

## 2. 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 后端 | `fastapi` + `uvicorn`，只暴露 `/api/*` JSON |
| 前端 | `frontend/` 独立 React 应用：`react` + `typescript` + `antd` + `@ant-design/icons` + `echarts`，Vite 构建 |
| 前后端分离 | 开发：Vite dev（5173，proxy `/api` → 8666）+ FastAPI（8666）；使用：`npm run build` 后 FastAPI 服务 `frontend/dist`，单进程访问 `localhost:8666` |
| K 线图 | ECharts candlestick，自写 ~20 行 React 封装（只引 `echarts`，不引 echarts-for-react） |
| 只读离线 | 后端直接读存储层（KlineStore/MetaStore/FactorStore），**不构造 TickFlowClient、不调 DataCenter.get_klines**，永不触发网络回源 → 启动无需 `TICKFLOW_API_KEY` |
| 页面结构 | 单页两 tab：**行情**（K 线浏览 + 图）/ **因子** |
| 分页 | 服务端分页，默认 50 行/页，`size` 上限 **2000**（图表可一次取全窗口） |
| 端口 | `127.0.0.1:8666`（仅本机） |
| 行情显示 | 显示存储**原始值**（未复权）——诚实呈现"存的就是什么"；复权视图后续迭代 |
| 搜索 | 标的按 `symbol`/`code` 匹配（`instruments.name` 当前多为 NULL，代码按名搜索逻辑照写，数据到位即生效） |
| 依赖 | 后端新增 `fastapi`、`uvicorn`（运行）、`httpx`（dev）；前端依赖见 §9 的 `frontend/package.json` |

## 3. 整体架构

```
┌─ 前端 frontend/（React + antd + ECharts，Vite 构建）─┐
│  pages/KlineBrowser.tsx   行情 tab（Table + 搜索 + K线图）│
│  pages/FactorBrowser.tsx  因子 tab（Table 下钻）        │
│  api.ts                   fetch /api/*（JSON）         │
└────────────────────┬──────────────────────────────────┘
        │  /api/*（fetch，开发时经 Vite proxy → 8666）
        ▼
┌─ 后端 src/webui/（FastAPI，离线只读）─────────────┐
│  app.py   create_app(data_dir="data") -> FastAPI  │
│           /api 路由；生产环境挂载 frontend/dist    │
│  api.py   全部 /api 端点（读操作）                 │
└──────────────┬────────────────────────────────────┘
        │ 直接读存储层（各自已有类，零网络）
        ▼
   data/klines/        KlineStore.read / count     （parquet，纯读）
   data/meta.db        MetaStore.list_coverage     （sqlite）
   data/factors/       FactorStore.list_stored / load_stored（parquet，纯读）
```

要点：
- **离线保障**：webui 只 import `datacenter.store.klines.KlineStore`、`datacenter.store.meta.MetaStore`、`factors.store.FactorStore`，不 import `datacenter.api.DataCenter` 与 `datacenter.client.*`。FactorStore 构造传 `dc=None`（其只读方法不触碰 `self.dc`）。
- 数据目录可注入（`create_app(data_dir=...)`），测试用 tmp 目录。
- 后端入口 `scripts/serve.py`：uvicorn 起 `webui.app`，host `127.0.0.1`、port `8666`。
- 开发工作流：`scripts/serve.py`（后端）+ `cd frontend && npm run dev`（Vite proxy `/api`）。

## 4. API 设计（全部 GET，JSON，服务端分页）

统一约定：`page`（1 起）、`size`（默认 50，上限 2000）；`q` 为搜索串；响应 `{ total, page, size, items, ... }`。

| 端点 | 参数 | 返回 items 内容 |
|---|---|---|
| `GET /api/coverage` | `q`, `period`, `page`, `size` | 已存行情索引：`symbol/code/name/period/start_ms/end_ms/updated_at`（join `kline_coverage`×`instruments`；`q` 匹配 symbol/code/name） |
| `GET /api/klines` | `symbol`(必填), `period`(默认 1d), `start_ms`, `end_ms`, `page`, `size` | 已存 K 线分页：`{ symbol, period, total, page, size, rows:[[ts,o,h,l,c,v,amount]] }`（`KlineStore.read` 纯读 + `KlineStore.count` 总数） |
| `GET /api/factors` | `q`, `page`, `size` | 注册因子定义：`name/category/period/version/default_params/doc/stored_dir_count`（`q` 匹配 name/doc） |
| `GET /api/factor-dirs` | `q`, `page`, `size` | 已存因子枚举：`fingerprint/name/params/version/adjust/period/category/doc/cells/total_rows`；`cells: [{symbol, period, rows}]` 为该指纹下**实际存在**的 parquet 组合（扫 `data/factors/*/factor.json`；`q` 匹配 name/params） |
| `GET /api/factor-values` | `fingerprint`(必填), `symbol`(必填), `period`(必填), `page`, `size` | 某已存因子值分页：`{ fingerprint, symbol, period, total, page, size, rows:[[ts,value]] }` |
| `GET /api/periods` | — | 可选周期列表（`datacenter.constants.ALL_PERIODS`），供前端下拉 |

细节：
- `coverage` 排序：`symbol ASC, period ASC`；`klines` 排序：`timestamp ASC`；`factors` 按 `name`；`factor-dirs` 按 `name, params`；`factor-values` 按 `timestamp ASC`。
- `klines` 缺省日期范围 = 该 symbol×period 的已存覆盖区间（取 `MetaStore.get_coverage`）；无覆盖记录 → 空结果（200 + total=0），不报错。
- `factor-dirs` 的 `cells` 与 `total_rows` 全量统计（因子数据量小，用 pyarrow parquet **metadata** 的 `num_rows` 读行数、不读数据块，全库扫描代价可忽略）；API 层再按分页切片。
- 404 场景：`/api/klines` 的 period 非法（不在 ALL_PERIODS）；`/api/factor-values` 的 fingerprint×symbol×period 无对应 parquet → 404 JSON `{detail}`。

## 5. 页面设计（React + antd）

`App.tsx`：`ConfigProvider`（中文 locale）+ `Tabs`，两 tab。所有组件用 antd，分页控件用 `Table` 自带 `pagination`（服务端模式 `total`/`current`/`pageSize`）。

**行情 tab（`KlineBrowser.tsx`）**：
1. 过滤行：`Input.Search`（代码/名称）+ `Select`（周期，`/api/periods`）。
2. 已存行情索引表（`/api/coverage`）：symbol | 名称 | 周期 | 起始 | 截止 | 更新时间。`Table` 行点击选中。
3. 选中某行 → 下方展示该 symbol×period 的 **K 线详情**：上半 `EChartsKline`（ECharts candlestick，取请求区间内最多 2000 根，`/api/klines?size=2000`，timestamp 升序、超出取前 2000——想看更早缩小日期范围），下半 `Table` 分页明细（时间 | 开 | 高 | 低 | 收 | 量 | 额，默认 50/页）。1d 时间显示 `YYYY-MM-DD`，分钟周期显示 `YYYY-MM-DD HH:MM`。
4. 日期范围：`RangePicker`（可选，缺省 = 该行覆盖区间）。

**因子 tab（`FactorBrowser.tsx`）**：
1. 因子定义表（`/api/factors`，搜索分页）：名称 | 参数 | 版本 | 类别 | 同花顺条件句（doc，`Typography.Text` ellipsis） | 已存目录数。
2. 点击某因子 → 已存数据目录表（`/api/factor-dirs?q=<name>`）：指纹 | 参数 | 版本 | 复权 | 组合数 | 行数。
3. 点击某目录行 → `cells` 表（实际存在的 symbol×period）：标的 | 周期 | 行数 → 点击某行 → 因子值分页表（`/api/factor-values`）：时间 | 值。

状态处理：`Table` `loading`；空态 `Empty`；错误 `message.error(detail)`；K 线图空数据时展示占位文案。

## 6. 数据层新增（各自模块内，带测试）

| 方法 | 位置 | 语义 |
|---|---|---|
| `MetaStore.list_coverage(q=None, period=None, page=1, size=50) -> (total, rows)` | `src/datacenter/store/meta.py` | 分页查已存覆盖索引，join instruments 取 code/name；`q` LIKE 匹配 symbol/code/name |
| `KlineStore.count(symbols, period, start_ms, end_ms) -> int` | `src/datacenter/store/klines.py` | 与 `read` 同过滤/去重语义的 `SELECT count(*)`，供分页总数 |
| `FactorStore.list_stored() -> list[dict]` | `src/factors/store.py` | 扫 `root/*/factor.json` → 每指纹 `{fingerprint, name, params, version, adjust, period, category, doc, cells, total_rows}`；`cells: [{symbol, period, rows}]` 只列实际存在 parquet 的组合（total_rows = cells 行数求和） |
| `FactorStore.load_stored(fingerprint, symbol, period) -> pd.Series` | `src/factors/store.py` | 纯读 `root/<fp>/symbol=*/period=*/part.parquet` 为 Series（索引=timestamp ms，值=value）；无文件返回空 Series，**不走 `get()` 的计算/回源路径** |

`MetaStore.list_coverage` 直接用现有 `kline_coverage` 表与 `instruments` 表 JOIN，不改表结构。

## 7. 错误处理

| 场景 | 行为 |
|---|---|
| 非法 `period` | `/api/klines` → 404 JSON `{detail}` |
| 未知 symbol / 无覆盖 | `/api/klines` → 200 + total=0（空数据不是错误） |
| fingerprint×symbol×period 无 parquet | `/api/factor-values` → 404 JSON `{detail}` |
| `page`/`size` 越界 | 服务端钳制（size ≤ 2000、page ≥ 1），不报错 |
| 存储目录不存在 | 各端点返回空结果（total=0），前端空态 |
| 前端 fetch 失败 | `message.error(detail)` |

## 8. 测试策略

- **后端**：`tests/test_webui.py`，`fastapi.testclient.TestClient` + **合成 tmp 存储**（不依赖真实数据、不联网）。夹具：`KlineStore.write` 写合成 K 线 parquet；`MetaStore` 建 tmp sqlite（`upsert_instruments` + `extend_coverage`）；`FactorStore._save` 写因子 parquet + factor.json。用例：
  - `coverage`：分页切页、`q` 按代码命中、`period` 过滤、空库 total=0
  - `klines`：分页总数、行内容与写入一致、缺省范围取覆盖区间、非法 period → 404、无覆盖 → total=0、`size` 上限钳制
  - `factors`：返回 11 个内置因子、`q` 命中、`stored_dir_count` 与 tmp 落盘一致
  - `factor-dirs`：枚举指纹、`cells`/`total_rows` 求和、分页、`q` 过滤
  - `factor-values`：分页值正确、未知 fingerprint → 404
  - `periods`：返回 ALL_PERIODS
- **前端**：本期**不做单测**（避免 vitest 工具链），交付前手动冒烟：`npm run build` + `serve.py` 起单进程，走一遍两 tab / 分页 / 搜索 / 下钻 / K 线图。
- 回归：`.venv/bin/python -m pytest tests/` 全绿（既有 ~149 + 新增 webui 用例）。

## 9. 项目结构

```
src/webui/
├── app.py            # create_app(data_dir="data") -> FastAPI；/api 路由；生产挂载 frontend/dist
├── api.py            # APIRouter：全部 /api 端点
scripts/
└── serve.py          # 启动后端 127.0.0.1:8666（生产服务 dist，打印存储目录与端口）
frontend/             # 前端独立应用（Node 工具链，与后端分离）
├── package.json / vite.config.ts / tsconfig.json / index.html
└── src/
    ├── main.tsx / App.tsx        # antd ConfigProvider(zhCN) + Tabs
    ├── api.ts                    # fetch 封装
    ├── components/EChartsKline.tsx  # echarts candlestick 轻封装
    └── pages/KlineBrowser.tsx / FactorBrowser.tsx
tests/test_webui.py
docs/superpowers/plans/2026-08-31-webui-phase6.md   # 实施计划（checkbox，Commit 步不勾）
```

`pyproject.toml`：`dependencies` 加 `fastapi>=0.110`、`uvicorn>=0.29`；`[dependency-groups].dev` 加 `httpx`；`[tool.hatch.build.targets.wheel].packages` 加 `src/webui`。

`frontend/package.json` 依赖：`react` `react-dom` `antd` `@ant-design/icons` `echarts`；dev：`vite` `@vitejs/plugin-react` `typescript` `@types/react` `@types/react-dom`。`vite.config.ts` 配 `server.proxy['/api'] = 'http://127.0.0.1:8666'`，`build.outDir = 'dist'`。

## 10. 实施分期

- **P1 数据层**：`MetaStore.list_coverage`、`KlineStore.count`、`FactorStore.list_stored/load_stored` + 各自单测
- **P2 API**：`src/webui/app.py` + `api.py` 全部端点 + `tests/test_webui.py`（TestClient 合成存储）
- **P3 前端**：`frontend/` 脚手架（Vite + React + TS + antd）+ 两 tab 页面 + `EChartsKline` + `scripts/serve.py`；`npm run build` 后 `localhost:8666` 冒烟（两 tab、分页、搜索、下钻、K 线图）
- **P4 收尾**：README/HELP.md 补充、全量回归、计划 checkbox 入库（Commit 步按用户规则保持未勾）

后续迭代方向（本期不做，架构已预留）：复权视图切换、因子页展示覆盖区间与统计、接入 warm/refresh 管理操作、回测入口、前端单测工具链。

# 观澜 Stock · frontend-gpt

独立的 React 前端设计版本，连接本仓库的本地行情、因子和盯盘 API。

## 启动

需要 Node.js 20.19+，以及仓库已有的 Python 环境。

先在仓库根目录启动后端：

```bash
source ~/.zshrc
.venv/bin/python scripts/serve.py
```

在另一个终端启动本工程：

```bash
cd frontend-gpt
npm ci
npm run dev
```

打开 **http://127.0.0.1:5178**。开发服务器将 `/api` 代理到 `http://127.0.0.1:8666`。页面显示真实后端数据；后端未启动时显示错误及重试入口，不会用模拟行情代替。初次进入请在行情列表选择标的。

构建与本地生产预览：

```bash
npm run build
npm run preview
```

预览地址为 **http://127.0.0.1:4178**，同样包含 `/api` 代理。若用其他静态服务器部署 `dist/`，需自行配置同源 `/api` 反向代理；直接双击 HTML 不可用。

## 已实现

- 行情：完整覆盖索引按标的归组、50 标的分页、搜索和周期筛选、详情周期切换、折叠列表、选中即回源、日期范围、K 线/MA5/MA10/MA20/成交量与缩放、服务器分页明细、回源失败缓存提示。
- 因子：注册表 → 参数目录 → 标的与周期 → 已存值，支持路径返回、搜索、分页和 null 值。
- 盯盘：单信号灯 `lamp_on`、`on/off` 事件，历史未知事件原文兜底；任务创建/编辑/启停/删除确认，Python 编辑器、字段校验、错误提示、任务筛选、每页 50 条信号。
- 三页常驻，切页保留选择、页码与滚动位置；盯盘默认 10 秒刷新，隐藏标签页或浏览器页面时暂停。
- 暖白纸感、Outfit 本地字体、红涨绿跌、独立琥珀灯；GSAP 入场、滚动文字显现和图片缩放淡出，响应式布局与 reduced-motion 支持。
- 图片为非必要的远程装饰，加载失败自动使用本地 SVG；操作和字体不依赖 CDN。

## API 兼容细节

接口规格见 `../docs/FRONTEND.md`。此版本已对齐 2026-09-06 的单灯与标的归组变更。

- `/coverage` 的分页单位是标的×周期。前端按每批 2,000 条读取完整索引后归组，筛选及分页单位为标的。
- K 线图分批读取完整区间，每批最多 2,000 根；均线只使用当前与历史值。
- 现有 `refresh=1` 忽略 `end_ms`。前端按北京时间结束日末过滤回源结果，保留区间内盘中 bar。明细仍从服务器分页读取，并应用相同边界。
- 信号 API 只有 `limit`，没有 total/offset。前端按页增加读取上限并多读一条判断后续页，界面明确标记“已读取最近 N 条”，不伪装总历史数量。
- 新建任务会按现有后端行为默认启用；默认脚本 `{"on": False, "msg": ""}` 不产生亮灯信号。

## 验证

```bash
npm test
npm run test:e2e
node tests/real-smoke.mjs
npm run build
```

浏览器测试需要本机安装 Google Chrome，并先运行 `npm run dev`。测试使用独立浏览器会话和拦截的 API fixtures，不写入真实盯盘任务。`real-smoke.mjs` 需要后端同时运行，使用真实只读 API，并移除自动回源参数；截图写入已忽略的 `test-results/`。

## 目录

```text
src/
  App.tsx                       常驻页面、导航与首页
  api.ts / types.ts / domain.ts  API、数据类型、日期与均线逻辑
  pages/                        行情、因子、盯盘
  components/                   图表、抽屉、通用控件、研究导览
  style.css                     响应式样式
public/                         图标与离线装饰图
tests/                          单元、浏览器回归与真实只读冒烟
```

`npm run format` 格式化源代码。`node_modules/`、`dist/` 和测试截图已在此目录的 `.gitignore` 中排除。

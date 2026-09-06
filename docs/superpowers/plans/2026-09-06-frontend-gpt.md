# frontend-gpt 实施计划

目标：在独立 frontend-gpt 目录实现 docs/FRONTEND.md 的行情、因子、盯盘三页，连接现有 /api。

设计：Outfit 字体、暖白纸感、墨黑导航、酸橙操作色；红涨绿跌、琥珀信号灯。Editorial Split 首屏，工作区优先；研究导览使用横向手风琴、文字走马灯与说明轮播，GSAP 图片缩放淡出和滚动文字显现。尊重 reduced-motion。

架构：React + TypeScript + Vite；ECharts 按需加载；GSAP + @gsap/react；页面常驻、各自保存滚动状态；相对路径 /api，经 Vite dev/preview 代理至 8666。远程装饰图片失败不影响功能，字体本地打包。无模拟行情兜底。

- [x] Step 1：建立工程、API 类型与请求辅助函数；测试时间范围、均线和多页查询。
- [x] Step 2：行情页，实现覆盖索引、自动回源、完整区间图表、日期与分页。
- [x] Step 3：因子四级下钻与盯盘 CRUD、轮询、信号历史、表单校验。
- [x] Step 4：视觉样式、响应式与 GSAP 导览，完成构建及浏览器功能检查。
- [x] Step 5：同步 HELP.md、docs/FRONTEND.md 与启动说明，记录验证结果。

验证：npm test、npm run build；Playwright 隔离 API fixtures 验证状态保持、行情失败缓存提示、因子下钻、盯盘操作和隐藏轮询；真实后端只读冒烟；检查桌面和手机截图。浏览器写入测试使用拦截 API，不修改用户真实盯盘任务。

已同步会话中更新的规格：coverage 按 symbol 归组并在详情切周期；盯盘使用 lamp_on 与 on/off，未知历史 kind 原文显示。验证完成：5 项 Vitest 单元、8 项 Playwright 场景通过；生产构建通过；真实只读 API 冒烟无浏览器错误。已检查 1440/768/390/320 像素宽度，手机标题两行，远程装饰图失效有本地替代。两轮独立代码复查确认接口修复有效。

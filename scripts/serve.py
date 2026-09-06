"""本地行情/因子查询服务（纯 API，无内置前端）。

用法：
  uv run python scripts/serve.py                 # 后端 127.0.0.1:8666（仅 /api）
前端已迁移到独立工程，经 dev server 代理 /api → 8666 对接（见 docs/FRONTEND.md §5.0）。
"""
from pathlib import Path

import uvicorn

from webui.app import create_app

if __name__ == "__main__":
    print(f"[webui] 数据目录: {Path('data').resolve()}")
    print("[webui] 访问 http://127.0.0.1:8666")
    app = create_app(data_dir="data")
    uvicorn.run(app, host="127.0.0.1", port=8666, log_level="info")

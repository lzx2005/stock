"""本地行情/因子查询服务。

用法：
  uv run python scripts/serve.py                 # 后端 8666（仅 /api）
  若需前端页面：先 cd frontend && npm run build，再启动本脚本（服务 dist，单进程访问 localhost:8666）
"""
from pathlib import Path

import uvicorn

from webui.app import create_app

if __name__ == "__main__":
    print(f"[webui] 数据目录: {Path('data').resolve()}")
    print("[webui] 访问 http://127.0.0.1:8666")
    app = create_app(data_dir="data")
    uvicorn.run(app, host="127.0.0.1", port=8666, log_level="info")

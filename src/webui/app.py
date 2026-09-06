"""Web 查询界面：FastAPI 应用工厂（默认离线只读）。

默认只读已存数据，启动时不构造 TickFlowClient、不调 DataCenter——无需 API key、不触发网络回源。
例外：/api/klines?refresh=1 会懒构造 DataCenter 回源补最新（需要 TICKFLOW_API_KEY，失败自动退回缓存）。
前端已迁移到独立工程（见 docs/FRONTEND.md §5.0）；若 frontend/dist 存在仍会自动挂载（兼容旧布局）。
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from datacenter.store.klines import KlineStore
from datacenter.store.meta import MetaStore
from factors.store import FactorStore
from monitor.store import MonitorStore


class AppStores:
    """后端持有的三个只读存储 + 盯盘存储。DataCenter 仅在 refresh=1 时懒构造（见 api._get_dc）。"""

    def __init__(self, data_dir: Path):
        self.klines = KlineStore(data_dir / "klines")
        self.meta = MetaStore(data_dir / "meta.db")
        self.factors = FactorStore(None, root=data_dir / "factors")
        self.monitor = MonitorStore(data_dir / "monitor.db")


def create_app(data_dir: str | Path = "data") -> FastAPI:
    from webui.api import router  # 局部 import：api 内会注册内置因子
    from webui.monitor_api import router as monitor_router

    app = FastAPI(title="本地行情/因子查询")
    app.state.data_dir = Path(data_dir)
    app.state.stores = AppStores(Path(data_dir))
    app.include_router(router)
    app.include_router(monitor_router)

    dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(dist / "index.html")

    return app

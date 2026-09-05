"""Web 查询界面：FastAPI 应用工厂（离线只读）。

只读已存数据，不构造 TickFlowClient、不调 DataCenter——无需 API key、不触发网络回源。
生产模式：若 frontend/dist 存在，挂载静态资源并返回 index.html（需先 cd frontend && npm run build）。
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from datacenter.store.klines import KlineStore
from datacenter.store.meta import MetaStore
from factors.store import FactorStore


class AppStores:
    """后端持有的三个只读存储。webui 不 import DataCenter / datacenter.client。"""

    def __init__(self, data_dir: Path):
        self.klines = KlineStore(data_dir / "klines")
        self.meta = MetaStore(data_dir / "meta.db")
        self.factors = FactorStore(None, root=data_dir / "factors")


def create_app(data_dir: str | Path = "data") -> FastAPI:
    from webui.api import router  # 局部 import：api 内会注册内置因子

    app = FastAPI(title="本地行情/因子查询")
    app.state.stores = AppStores(Path(data_dir))
    app.include_router(router)

    dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(dist / "index.html")

    return app

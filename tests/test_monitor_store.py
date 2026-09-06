from monitor.store import MonitorStore


def test_task_crud_and_toggle(tmp_path):
    st = MonitorStore(tmp_path / "m.db")
    tid = st.add_task("600869 低位区", "600869.SH", "def check(ctx): ...",
                      interval_sec=60, notify=1, description="20日低位区，回放3年51次")
    t = st.get_task(tid)
    assert t["symbol"] == "600869.SH" and t["enabled"] == 1 and t["lamp_on"] == 0
    assert t["description"] == "20日低位区，回放3年51次"
    st.update_task(tid, interval_sec=120, script="def check(ctx): return {}",
                   description="改后的说明")
    t = st.get_task(tid)
    assert t["interval_sec"] == 120 and t["description"] == "改后的说明"
    st.set_enabled(tid, 0)
    assert st.get_task(tid)["enabled"] == 0
    assert len(st.list_tasks()) == 1
    st.delete_task(tid)
    assert st.list_tasks() == []


def test_lamp_poll_error_signal(tmp_path):
    st = MonitorStore(tmp_path / "m.db")
    tid = st.add_task("t", "600869.SH", "def check(ctx): ...")
    st.set_lamp(tid, "lamp_on", 1)
    st.bump_poll(tid, 1000)
    st.record_error(tid, "boom")
    st.add_signal(tid, 1000, "on", 12.34, "进入低位区")
    t = st.get_task(tid)
    assert (t["lamp_on"], t["poll_count"], t["error_count"]) == (1, 1, 1)
    assert t["last_error"] == "boom" and t["last_run_at"] == 1000
    sigs = st.list_signals(tid)
    assert sigs[0]["kind"] == "on" and sigs[0]["price"] == 12.34


def test_schema_idempotent(tmp_path):
    MonitorStore(tmp_path / "m.db")
    MonitorStore(tmp_path / "m.db")  # 第二次初始化不报错


def test_migrate_adds_description_to_old_db(tmp_path):
    """老库（无 description 列）打开时自动 ALTER 补列，旧行默认空串。"""
    import sqlite3
    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
        " symbol TEXT NOT NULL, script TEXT NOT NULL,"
        " interval_sec INTEGER NOT NULL DEFAULT 60, enabled INTEGER NOT NULL DEFAULT 1,"
        " notify INTEGER NOT NULL DEFAULT 1, lamp_on INTEGER NOT NULL DEFAULT 0,"
        " poll_count INTEGER NOT NULL DEFAULT 0,"
        " signal_count INTEGER NOT NULL DEFAULT 0, last_run_at INTEGER,"
        " error_count INTEGER NOT NULL DEFAULT 0, last_error TEXT,"
        " created_at INTEGER NOT NULL)")
    conn.execute("INSERT INTO tasks (name, symbol, script, created_at)"
                 " VALUES ('old', '600869.SH', 's', 1)")
    conn.commit()
    conn.close()
    st = MonitorStore(db)
    t = st.get_task(1)
    assert t["name"] == "old" and t["description"] == ""
    st.update_task(1, description="补上的说明")
    assert st.get_task(1)["description"] == "补上的说明"


def test_migrate_dual_lamp_to_single(tmp_path):
    """双灯老库（buy_on/sell_on）打开时：补 lamp_on 并继承 buy_on 值，DROP 旧列。"""
    import sqlite3
    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
        " symbol TEXT NOT NULL, script TEXT NOT NULL,"
        " interval_sec INTEGER NOT NULL DEFAULT 60, enabled INTEGER NOT NULL DEFAULT 1,"
        " notify INTEGER NOT NULL DEFAULT 1, buy_on INTEGER NOT NULL DEFAULT 0,"
        " sell_on INTEGER NOT NULL DEFAULT 0, poll_count INTEGER NOT NULL DEFAULT 0,"
        " signal_count INTEGER NOT NULL DEFAULT 0, last_run_at INTEGER,"
        " error_count INTEGER NOT NULL DEFAULT 0, last_error TEXT,"
        " description TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL)")
    conn.execute("INSERT INTO tasks (name, symbol, script, buy_on, sell_on, created_at)"
                 " VALUES ('a', '600869.SH', 's', 1, 0, 1)")
    conn.execute("INSERT INTO tasks (name, symbol, script, buy_on, sell_on, created_at)"
                 " VALUES ('b', '000001.SZ', 's', 0, 1, 1)")
    conn.commit()
    conn.close()
    st = MonitorStore(db)
    cols = {r[1] for r in st._conn.execute("PRAGMA table_info(tasks)")}
    assert "lamp_on" in cols and "buy_on" not in cols and "sell_on" not in cols
    assert st.get_task(1)["lamp_on"] == 1   # 继承 buy_on
    assert st.get_task(2)["lamp_on"] == 0   # 只亮卖出灯 → 单灯语义下无继承，回到灭

from monitor.store import MonitorStore


def test_task_crud_and_toggle(tmp_path):
    st = MonitorStore(tmp_path / "m.db")
    tid = st.add_task("600869 低位区", "600869.SH", "def check(ctx): ...",
                      interval_sec=60, notify=1)
    t = st.get_task(tid)
    assert t["symbol"] == "600869.SH" and t["enabled"] == 1 and t["buy_on"] == 0
    st.update_task(tid, interval_sec=120, script="def check(ctx): return {}")
    assert st.get_task(tid)["interval_sec"] == 120
    st.set_enabled(tid, 0)
    assert st.get_task(tid)["enabled"] == 0
    assert len(st.list_tasks()) == 1
    st.delete_task(tid)
    assert st.list_tasks() == []


def test_lamp_poll_error_signal(tmp_path):
    st = MonitorStore(tmp_path / "m.db")
    tid = st.add_task("t", "600869.SH", "def check(ctx): ...")
    st.set_lamp(tid, "buy_on", 1)
    st.bump_poll(tid, 1000)
    st.record_error(tid, "boom")
    st.add_signal(tid, 1000, "buy_on", 12.34, "进入低位区")
    t = st.get_task(tid)
    assert (t["buy_on"], t["poll_count"], t["error_count"]) == (1, 1, 1)
    assert t["last_error"] == "boom" and t["last_run_at"] == 1000
    sigs = st.list_signals(tid)
    assert sigs[0]["kind"] == "buy_on" and sigs[0]["price"] == 12.34


def test_schema_idempotent(tmp_path):
    MonitorStore(tmp_path / "m.db")
    MonitorStore(tmp_path / "m.db")  # 第二次初始化不报错

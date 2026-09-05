"""策略模块 CLI 冒烟测试（main(argv) + capsys，纯本地无网络）。"""

import json

from scripts.strategy_cli import main

from tests.test_strategy_store import write_report_dir  # 复用产物构造

BROKER = {"commission": 0.0003, "min_commission": 5.0, "stamp_tax": 0.0005,
          "slippage": 0.0, "lot_size": 100, "t_plus_1": True}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def run(capsys, *argv):
    main([*argv])
    return capsys.readouterr().out


def test_cli_create_and_list(tmp_path, capsys):
    out = run(capsys, "--root", str(tmp_path / "strategies"),
              "create", "--name", "测试策略", "--desc", "描述")
    assert "已创建策略 #1" in out
    out = run(capsys, "--root", str(tmp_path / "strategies"), "list")
    assert "测试策略" in out and "无回测" in out


def test_cli_record_flow(tmp_path, capsys):
    root = str(tmp_path / "strategies")
    run(capsys, "--root", root, "create", "--name", "策略A")
    src1 = write_report_dir(tmp_path, name="r1", total_return=-0.05)
    out = run(capsys, "--root", root, "record", "--id", "1", "--from", str(src1), "--note", "v1")
    assert "版本 1" in out and "v1（原始版）：无对比基线" in out

    src2 = write_report_dir(tmp_path, name="r2", total_return=-0.02)
    out = run(capsys, "--root", root, "record", "--id", "1", "--from", str(src2), "--note", "v2")
    assert "版本 2" in out and "vs v1" in out and "进步" in out

    # v1 无 comparison，v2 有
    assert not (tmp_path / "strategies" / "1" / "versions" / "1" / "comparison.json").exists()
    cmp = load(tmp_path / "strategies" / "1" / "versions" / "2" / "comparison.json")
    assert cmp["comparable"] is True

    # report.md 追加对比节且幂等
    md = (tmp_path / "strategies" / "1" / "versions" / "2" / "report.md").read_text(encoding="utf-8")
    assert "## 版本对比" in md
    run(capsys, "--root", root, "compare", "--id", "1", "--version", "2")
    md2 = (tmp_path / "strategies" / "1" / "versions" / "2" / "report.md").read_text(encoding="utf-8")
    assert md2.count("## 版本对比") == 1


def test_cli_show_and_versions(tmp_path, capsys):
    root = str(tmp_path / "strategies")
    run(capsys, "--root", root, "create", "--name", "策略A")
    src1 = write_report_dir(tmp_path, name="r1", total_return=-0.05)
    run(capsys, "--root", root, "record", "--id", "1", "--from", str(src1))
    out = run(capsys, "--root", root, "show", "--id", "1")
    assert "策略A" in out and "v1" in out
    out = run(capsys, "--root", root, "versions", "--id", "1")
    assert "v1" in out
    out = run(capsys, "--root", root, "show-version", "--id", "1", "--version", "1")
    assert '"strategy_class": "MaCrossAtrStop"' in out


def test_cli_rename_delete(tmp_path, capsys):
    root = str(tmp_path / "strategies")
    run(capsys, "--root", root, "create", "--name", "策略A")
    out = run(capsys, "--root", root, "rename", "--id", "1", "--name", "策略B")
    assert "策略B" in out
    out = run(capsys, "--root", root, "list")
    assert "策略B" in out
    run(capsys, "--root", root, "delete", "--id", "1", "--yes")
    out = run(capsys, "--root", root, "list")
    assert "策略B" not in out

from scripts.monitor_cli import main


def test_cli_roundtrip(tmp_path, capsys):
    db = str(tmp_path / "m.db")
    sf = tmp_path / "s.py"
    sf.write_text('def check(ctx):\n    return {"on": True}\n')
    main(["register", "--name", "t", "--symbol", "600869.SH",
          "--script-file", str(sf)], db_path=db)
    out = capsys.readouterr().out
    assert "task_id=" in out
    main(["list"], db_path=db)
    assert "600869.SH" in capsys.readouterr().out
    main(["toggle", "1"], db_path=db)
    assert "enabled=0" in capsys.readouterr().out
    main(["delete", "1", "--yes"], db_path=db)
    main(["list"], db_path=db)
    assert "600869.SH" not in capsys.readouterr().out

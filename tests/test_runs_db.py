from app import runs_db


def test_save_and_list_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(runs_db, "_DB", tmp_path / "runs.db")
    runs_db.save_run("RP1", "gemini-3.5-flash", "medium", None, "v1", "PROMPT",
                     {"Renovations": []})
    runs_db.save_run("RP1", "gemini-3.5-flash", "high", 0.0, "v2", "PROMPT2",
                     {"Renovations": [{"_id": "a"}]})
    runs_db.save_run("RP2", "x", None, None, None, "P", {"ok": True})

    rows = runs_db.list_runs("RP1")
    assert [r["label"] for r in rows] == ["v2", "v1"]  # newest first
    assert rows[0]["response"] == {"Renovations": [{"_id": "a"}]}
    assert rows[0]["reasoning_effort"] == "high"
    assert rows[0]["prompt"] == "PROMPT2"
    assert len(runs_db.list_runs("RP2")) == 1
    assert runs_db.list_runs("UNKNOWN") == []

    # No rp_id → every run across all properties, newest first.
    every = runs_db.list_runs()
    assert [r["rp_id"] for r in every] == ["RP2", "RP1", "RP1"]

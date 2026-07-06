"""W&B logger: table schema, scalar flattening, no secret leakage, artifact write.

All runs use `mode="disabled"` → wandb is a full no-op (no network, no ./wandb dir)."""

import json

import pytest

from cot_mon import metrics
from cot_mon.logging import wandb_logger as wl


@pytest.fixture(autouse=True)
def _silence_wandb(monkeypatch):
    monkeypatch.setenv("WANDB_SILENT", "true")
    monkeypatch.setenv("WANDB_MODE", "disabled")


def _run(**kw):
    kw.setdefault("experiment", "exp_hints")
    kw.setdefault("actor", "gemini_2_5_flash")
    kw.setdefault("mode", "disabled")
    return wl.WandbRun(**kw)


def _full_row(**over):
    row = {c: f"v_{c}" for c in wl.COT_TABLE_COLUMNS}
    row.update(sample_idx=0, seed=7, engaged_hint=True, mentions_hint=False)
    row.update(over)
    return row


def test_cot_table_matches_spec_schema():
    run = _run()
    run.log_rollout(**_full_row(item_id="gpqa:abc", cot_text_full="step... <answer>C"))
    table = run.build_table()
    assert tuple(table.columns) == wl.COT_TABLE_COLUMNS         # exact schema + order
    assert len(table.data) == 1
    assert table.data[0][wl.COT_TABLE_COLUMNS.index("item_id")] == "gpqa:abc"
    assert table.data[0][wl.COT_TABLE_COLUMNS.index("engaged_hint")] is True  # bools preserved
    run.finish()


def test_log_rollout_rejects_unknown_column():
    run = _run()
    with pytest.raises(KeyError):
        run.log_rollout(item_id="x", not_a_column="boom")
    run.finish()


def test_no_secret_leakage_in_config_or_tags(monkeypatch):
    secret = "sk-or-LIVEKEY-must-not-appear-1234567890"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    monkeypatch.setenv("WANDB_API_KEY", secret)
    monkeypatch.setenv("HF_TOKEN", secret)
    cfg = wl.run_config(describe={"name": "gemini_2_5_flash", "id": "openrouter/google/gemini-2.5-flash",
                                  "provider": "google-vertex", "cot_access": "body_channel"},
                        n_items=5, n_samples=4, dataset="gpqa")
    run = _run(config=cfg, gate="gate1")
    blob = json.dumps(run.config) + " ".join(str(t) for t in [run.experiment, run.actor])
    assert secret not in blob                                   # we never dump os.environ into config
    assert "provider" in run.config and run.config["cot_access"] == "body_channel"
    run.finish()


def test_run_config_drops_none_and_adds_sampling():
    cfg = wl.run_config(describe={"name": "m", "id": "openrouter/x/y", "provider": None,
                                  "cot_access": "disabled", "reasoning_enabled": False},
                        n_items=60, n_samples=10, seed=None, sampling={"temperature": 0.7})
    assert "seed" not in cfg and "provider" not in cfg          # Nones dropped
    assert cfg["reasoning_enabled"] is False                    # but False is kept
    assert cfg["sampling_temperature"] == 0.7
    assert cfg["n_items"] == 60


def test_log_scalars_flattens_summary_with_cis():
    summary = {
        "baseline_pick_target": metrics.stat(0, 28),
        "simple": {"follow_rate": metrics.stat(5, 28), "unfaithful_rate": metrics.stat(4, 28),
                   "used_rate_among_followers": metrics.stat(1, 5), "follow_minus_baseline": 0.18},
        "complex": {"follow_rate": metrics.stat(0, 28), "unfaithful_rate": metrics.stat(0, 28),
                    "used_rate_among_followers": metrics.stat(0, 0), "follow_minus_baseline": None},
    }
    flat = metrics.flatten_for_logging(summary)
    assert "unfaithful_simple" in flat and "unfaithful_simple_lo" in flat and "unfaithful_simple_hi" in flat
    assert "follow_rate_complex" in flat and "baseline_pick_target" in flat
    assert flat["follow_minus_baseline_simple"] == 0.18
    assert "follow_minus_baseline_complex" not in flat          # None is dropped
    run = _run()
    run.log_scalars(flat)
    assert run.scalars["unfaithful_simple"] == flat["unfaithful_simple"]
    run.finish()


def test_transcripts_jsonl_written_with_full_text(tmp_path):
    run = _run()
    run.log_rollout(**_full_row(item_id="gpqa:1", prompt_full="PROMPT TEXT", cot_text_full="FULL COT"))
    out = tmp_path / "t.jsonl"
    written = run.finish(transcripts_path=out)
    assert written == out and out.exists()
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["cot_text_full"] == "FULL COT"
    assert set(rows[0]) == set(wl.COT_TABLE_COLUMNS)            # archive carries the full schema


def test_dataset_hash_is_stable_and_order_sensitive():
    a = wl.dataset_hash(["gpqa:1", "gpqa:2", "gpqa:3"])
    assert a == wl.dataset_hash(["gpqa:1", "gpqa:2", "gpqa:3"])
    assert a != wl.dataset_hash(["gpqa:2", "gpqa:1", "gpqa:3"])
    assert len(a) == 12


def test_git_info_present():
    gi = wl.git_info()
    assert set(gi) == {"git_sha", "git_branch"}

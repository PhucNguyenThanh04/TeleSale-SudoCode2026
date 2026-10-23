import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from eval.trace_audit import audit_pair, audit_trace, build_manifest, source_snapshot_digest


SCHEMA = (Path(__file__).resolve().parents[2] / "BTC-Data-Vong1-TEAMS" /
          "schemas" / "trace_log.schema.json")


class TraceAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        btc = self.root / "BTC"
        (btc / "schemas").mkdir(parents=True)
        (btc / "schemas" / "trace_log.schema.json").write_bytes(SCHEMA.read_bytes())
        self.scenarios = btc / "test_set" / "public_sample"
        self.scenarios.mkdir(parents=True)
        (self.scenarios / "case.json").write_text(json.dumps({
            "scenario_id": "CASE-X", "calls": {
                "call_1": {"customer_turns": ["A", "B"]},
                "call_2": {"customer_turns": ["C"]}}}), encoding="utf-8")
        self.trace = self.root / "full.jsonl"
        self.rows = [self.row("call_1", 1), self.row("call_1", 2),
                     self.row("call_2", 1)]

    @staticmethod
    def row(call, turn, config="full", run_id="run-a"):
        return {"run_id": run_id, "config": config, "scenario_id": "CASE-X",
                "call": call, "turn": turn, "customer_text": "safe",
                "agent_text": "safe", "questions": [], "claims": [],
                "tool_calls": [], "latency": {"ttft_ms": 2, "total_ms": 3}}

    def write_rows(self, rows):
        self.trace.write_text("".join(json.dumps(row) + "\n" for row in rows),
                              encoding="utf-8")

    def test_audit_detects_coverage_order_and_schema_errors(self):
        self.write_rows(self.rows)
        self.assertEqual(audit_trace(self.scenarios, self.trace, "full")["errors"], [])
        for rows, expected in (
            (self.rows[:-1], "missing"),
            (self.rows + [self.rows[0]], "duplicate"),
            ([self.rows[1], self.rows[0], self.rows[2]], "out_of_order"),
            ([{**self.rows[0], "config": "baseline_no_memory"}, *self.rows[1:]], "config"),
            ([{**self.rows[0], "run_id": "other"}, *self.rows[1:]], "run_id"),
            ([{**self.rows[0], "questions": None}, *self.rows[1:]], "schema"),
            ([{**self.rows[0], "run_id": {"bad": "shape"}}, *self.rows[1:]], "schema"),
            ([{**self.rows[0], "turn": [1]}, *self.rows[1:]], "schema"),
        ):
            with self.subTest(expected=expected):
                self.write_rows(rows)
                self.assertIn(expected, " ".join(audit_trace(
                    self.scenarios, self.trace, "full")["errors"]))

    def test_dirty_source_change_affects_digest(self):
        source = self.root / "ai-services" / "app"
        source.mkdir(parents=True)
        (source / "logic.py").write_text("x = 1\n", encoding="utf-8")
        before = source_snapshot_digest(self.root)
        (source / "logic.py").write_text("x = 2\n", encoding="utf-8")
        self.assertNotEqual(before, source_snapshot_digest(self.root))

    def test_manifest_and_pair_reject_secret_and_configuration_drift(self):
        self.write_rows(self.rows)
        report = self.root / "score.json"
        report.write_text(json.dumps({"n_scenarios": 1, "system": {
            "task_success_rate": {"failures": []}}, "baseline": {
            "task_success_rate": {"failures": []}}}), encoding="utf-8")
        baseline_trace = self.root / "baseline.jsonl"
        baseline_trace.write_text("baseline", encoding="utf-8")
        scorer = self.scenarios.parents[1] / "eval" / "reference_eval.py"
        scorer.parent.mkdir()
        scorer.write_text("# scorer fixture\n", encoding="utf-8")
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        report.with_suffix(".inputs.json").write_text(json.dumps({
            "full_trace_sha256": digest(self.trace),
            "baseline_trace_sha256": digest(baseline_trace),
            "scorer_sha256": digest(scorer),
            "score_sha256": digest(report)}), encoding="utf-8")
        self.trace.with_suffix(".report.json").write_text(json.dumps({
            "run_id": "run-a", "config": "full", "database_identity": {
                "database": "telesale_eval_full", "host": "localhost", "port": 5432}}),
            encoding="utf-8")
        inputs = dict(trace_path=self.trace, scenarios_dir=self.scenarios,
                      config="full", source_digest="src-hash", seed_id="seed-1",
                      seed_digest="seed-hash", model_id="model-A",
                      model_params={"temperature": 0}, tool_mode="mcp",
                      guardrails={"enabled": True},
                      database_identity={"database": "telesale_eval_full",
                                         "host": "localhost", "port": 5432},
                      hardware={"cpu": "test"},
                      started_at_utc="2026-10-22T00:00:00Z",
                      scorer_report_path=report)
        full = build_manifest(**inputs)
        self.assertEqual(full["run_id"], "run-a")
        self.assertEqual(audit_pair(full, {**full, "config": "baseline_no_memory",
                                           "run_id": "run-b"}), [])
        self.assertIn("seed", " ".join(audit_pair(full, {
            **full, "config": "baseline_no_memory", "run_id": "run-b",
            "seed_digest": "different"})))
        self.assertIn("model", " ".join(audit_pair(full, {
            **full, "config": "baseline_no_memory", "run_id": "run-b",
            "model_id": "model-B"})))
        with self.assertRaises(ValueError):
            build_manifest(**{**inputs, "model_params": {"api_key": "secret"}})
        with self.assertRaises(ValueError):
            build_manifest(**{**inputs, "model_id": "postgresql://user:password@localhost/db"})
        with self.assertRaisesRegex(ValueError, "database_identity"):
            build_manifest(**{**inputs, "database_identity": {
                "database": "telesale_eval_other", "host": "localhost", "port": 5432}})
        inputs_sidecar = report.with_suffix(".inputs.json")
        saved = inputs_sidecar.read_text()
        inputs_sidecar.unlink()
        with self.assertRaisesRegex(ValueError, "score.*provenance"):
            build_manifest(**inputs)
        inputs_sidecar.write_text(saved)
        self.write_rows([{**self.rows[0], "agent_text": "changed"}, *self.rows[1:]])
        with self.assertRaisesRegex(ValueError, "score.*provenance"):
            build_manifest(**inputs)


if __name__ == "__main__":
    unittest.main()

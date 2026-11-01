import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eval.score_pair import score_pair


ROOT = Path(__file__).resolve().parents[1]


class ScorePairTest(unittest.TestCase):
    def test_changed_scenario_file_during_scoring_is_rejected(self):
        btc = ROOT.parent / "BTC-Data-Vong1-TEAMS"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scenarios = root / "scenarios"
            scenarios.mkdir()
            case = scenarios / "case.json"
            case.write_text('{"scenario_id":"A"}', encoding="utf-8")
            full, baseline = root / "full.jsonl", root / "baseline.jsonl"
            full.write_text("{}\n")
            baseline.write_text("{}\n")
            def mutate(*args, **kwargs):
                case.write_text('{"scenario_id":"B"}', encoding="utf-8")
                (root / "score.json").write_text('{"system":{},"baseline":{}}')
            with patch("eval.score_pair.subprocess.run", side_effect=mutate):
                with self.assertRaisesRegex(RuntimeError, "changed"):
                    score_pair(scenarios, full, baseline, root / "score.json", btc_root=btc)

    def test_local_scenarios_can_use_explicit_btc_scorer(self):
        btc = ROOT.parent / "BTC-Data-Vong1-TEAMS"
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder) / "scenarios"
            local.mkdir()
            (local / "case.json").write_text(json.dumps({
                "scenario_id": "LOCAL-01", "calls": {"call_1": {
                    "customer_turns": ["Xin chào"]}}}), encoding="utf-8")
            full = Path(folder) / "full.jsonl"
            baseline = Path(folder) / "baseline.jsonl"
            row = {"run_id": "run-1", "scenario_id": "LOCAL-01",
                   "call": "call_1", "turn": 1, "customer_text": "Xin chào",
                   "agent_text": "Dạ chào anh/chị", "questions": [], "claims": [],
                   "tool_calls": [], "latency": {"ttft_ms": 4, "total_ms": 4}}
            full.write_text(json.dumps({**row, "config": "full"}) + "\n")
            baseline.write_text(json.dumps({**row, "config": "baseline_no_memory"}) + "\n")
            score = Path(folder) / "score.json"
            score_pair(local, full, baseline, score, btc_root=btc)
            self.assertEqual(json.loads(score.read_text())["n_scenarios"], 1)

    def test_real_btc_scorer_records_exact_historical_input_hashes(self):
        scenarios = ROOT.parent / "BTC-Data-Vong1-TEAMS" / "test_set" / "public_sample"
        full = ROOT / "eval" / "runs" / "full.jsonl"
        baseline = ROOT / "eval" / "runs" / "baseline_no_memory.jsonl"
        with tempfile.TemporaryDirectory() as folder:
            score = Path(folder) / "score.json"
            provenance = score_pair(scenarios, full, baseline, score)
            actual = json.loads(score.with_suffix(".inputs.json").read_text())
            report = json.loads(score.read_text())
            score_digest = hashlib.sha256(score.read_bytes()).hexdigest()
        self.assertEqual(report["n_scenarios"], 7)
        self.assertEqual(provenance, actual)
        self.assertEqual(actual["full_trace_sha256"],
                         hashlib.sha256(full.read_bytes()).hexdigest())
        self.assertEqual(actual["baseline_trace_sha256"],
                         hashlib.sha256(baseline.read_bytes()).hexdigest())
        self.assertEqual(actual["score_sha256"], score_digest)


if __name__ == "__main__":
    unittest.main()

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from eval.score_pair import score_pair


ROOT = Path(__file__).resolve().parents[1]


class ScorePairTest(unittest.TestCase):
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

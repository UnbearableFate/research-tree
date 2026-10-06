"""Tests for tools/evidence.py, ported from ARIS tests/test_evidence_check.py (@ 3b19a22), plus the document
evidence block."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import evidence as ec  # noqa: E402


def _write(d, rel, text):
    p = Path(d) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def status(value, text):
    with tempfile.TemporaryDirectory() as d:
        _write(d, "f.txt", text)
        return ec.check_claim(value, "f.txt", Path(d))["status"]


class EvidenceCheckTest(unittest.TestCase):
    def test_verified_string_value(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "results/eval.md", "Our method reaches SOTA on COCO with a 4-point gain.")
            self.assertEqual(ec.check_claim("4-point gain", "results/eval.md", Path(d))["status"], "verified")

    def test_numeric_equality_and_substrings(self):
        self.assertEqual(status("73.2", '{"mAP": 73.20}'), "verified")
        self.assertEqual(status("0.912%", '{"acc": "0.912%"}'), "verified")
        self.assertEqual(status("73", "baseline accuracy was 73.5 percent"), "value_not_found")
        self.assertEqual(status("73.5", "baseline accuracy was 73.5 percent"), "verified")

    def test_path_missing_glob_and_batch(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(ec.check_claim("1", "nope.json", root)["status"], "path_missing")
            _write(d, "results/seed1/metrics.json", '{"f1": 0.88}')
            _write(d, "results/seed2/metrics.json", '{"f1": 0.91}')
            self.assertEqual(ec.check_claim("0.91", "results/*/metrics.json", root)["status"], "verified")
            self.assertEqual(ec.check_claim("0.77", "results/*/metrics.json", root)["status"], "value_not_found")
            _write(d, "r.json", '{"x": 12.5, "bias": 0}')
            out = ec.check_batch([{"id": "c1", "value": "12.5", "source": "r.json"},
                                  {"id": "c2", "value": "99", "source": "r.json"},
                                  {"id": "c3", "value": "1", "source": "gone.json"},
                                  {"id": "c4"}, {"id": "c5", "value": 0, "source": "r.json"},
                                  {"id": "c6", "value": "", "source": "r.json"}], root)
            got = {r["id"]: r["status"] for r in out["results"]}
            self.assertEqual(got, {"c1": "verified", "c2": "value_not_found", "c3": "path_missing",
                                   "c4": "unparseable", "c5": "verified", "c6": "unparseable"})

    def test_sources_stay_inside_the_allowed_root(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ec.check_claim("1", "/etc/hostname", Path(d))["status"], "path_missing")
            self.assertEqual(ec.check_claim("1", "../x", Path(d))["status"], "path_missing")

    def test_no_false_verified_adversarial(self):
        cases = [
            ("1", "decay = 1e-5", False), ("-5", "lr range 1-5 and 1e-5", False), ("1e-5", "value 11e-5 here", False),
            ("5%", "seed = 5", False), ("50", "we use resnet50", False), ("5", "abc5def token", False),
            ("1.0000000001", "x = 1.0000000002", False), ("10000000000000001", "n=10000000000000000", False),
            ("1", "n = 1,000", False), ("0", "n = 1,000", False), ("234.5", "loss = 1,234.5", False),
            ("1", "count 1 000 items", False), (".5", "acc = 10.5", False), ("1.", "x = 11.", False),
            ("1", "ratio 1/2", False), ("2", "ratio 1/2", False), ("2026", "run date 2026-05-30", False),
            ("5", "run date 2026-05-30", False), ("30", "run date 2026-05-30", False), ("12", "at 12:30 utc", False),
            ("1.2", "version 1.2.3", False), ("1", "euro 1.000,5 eur", False),
            ("73.2", '{"mAP": 73.20}', True), ("1e-5", "decay = 1e-5", True), ("5%", "dropout = 5%", True),
            ("0", "bias = 0", True), ("1,000", "n = 1,000", True), ("1000", "n = 1,000", True),
            (".5", "acc = 0.5", True), ("73.2", "mAP: 73.2 on the test set", True),
            ("0.91", "f1 = 0.91, acc = 0.93", True), ("100", "(100 epochs)", True),
        ]
        for value, text, want in cases:
            with self.subTest(value=value, text=text):
                self.assertEqual(status(value, text) == "verified", want)

    def test_no_false_verified_unicode_and_whitespace(self):
        cases = [("5.2", "loss −5.2 here", False), ("20", "range 10–20 ok", False), ("20", "range 10—20 ok", False),
                 ("1", "n 1 234.5 x", False), ("1", "id 1，000 x", False), ("1", "t 1：2 x", False),
                 ("2", "t 1／2 x", False), ("1", "n 1 000 x", False), ("1", "n 1 234 x", False),
                 ("234", "n 1  234 x", False), ("1", "n 1\n234 x", False), ("2345", "n 1  2345 x", True),
                 ("1", "got 1 and 50", True)]
        for value, text, want in cases:
            with self.subTest(value=value, text=text):
                self.assertEqual(status(value, text) == "verified", want)


class CompactJsonTest(unittest.TestCase):
    def test_compact_json_and_times(self):
        self.assertEqual(status("0.9075", '{"acc":0.9075,"loss":0.27}'), "verified")
        self.assertEqual(status("0.27", '{"acc":0.9075,"loss":0.27}'), "verified")
        self.assertEqual(status("30", "at 12:30 utc"), "value_not_found")  # a time, not a JSON value
        self.assertEqual(status("2", "ratio 1:2"), "value_not_found")


class DocumentBlockTest(unittest.TestCase):
    def test_block(self):
        self.assertIsNone(ec.document_claims("no block here"))
        claims = ec.document_claims('x\n```evidence\n[{"id": "a", "value": "1", "source": "f"}]\n```\n')
        self.assertEqual(claims, [{"id": "a", "value": "1", "source": "f"}])
        self.assertEqual(ec.document_claims("```evidence\nnot json\n```\n")[0]["value"], None)
        self.assertEqual(ec.document_claims('```evidence\n{"id": 1}\n```\n')[0]["error"], "the block is a JSON list")


if __name__ == "__main__":
    unittest.main()

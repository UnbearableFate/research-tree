"""Tests for tools/literature.py (port of ARIS verify_papers.py, arxiv_fetch.py, semantic_scholar_fetch.py and
openalex_fetch.py @ 3b19a22). Fully offline: `literature.fetch` is replaced by canned responses."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import literature as lit

ARXIV_ATTENTION = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <title>arXiv Query</title>
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <published>2017-06-12T17:57:34Z</published>
    <title>Attention Is All
      You Need</title>
    <summary>  The dominant sequence transduction models
      are based on recurrent networks.</summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <arxiv:doi>10.48550/arXiv.1706.03762</arxiv:doi>
  </entry>
</feed>"""

ARXIV_EMPTY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>arXiv Query</title></feed>"""

S2_SEARCH = {
    "total": 2,
    "data": [
        {"paperId": "204e3073", "title": "Attention is All you Need", "year": 2017, "venue": "NeurIPS",
         "url": "https://www.semanticscholar.org/paper/204e3073", "abstract": None,
         "authors": [{"authorId": "1", "name": "Ashish Vaswani"}, {"authorId": "2", "name": "Noam Shazeer"}],
         "externalIds": {"ArXiv": "1706.03762", "DOI": "10.48550/arXiv.1706.03762", "CorpusId": 13756489}},
        {"paperId": "df2b0e26", "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language "
                                         "Understanding", "year": 2019, "venue": "NAACL",
         "url": "https://www.semanticscholar.org/paper/df2b0e26", "abstract": "We introduce BERT.",
         "authors": [{"authorId": "3", "name": "Jacob Devlin"}],
         "externalIds": {"DOI": "10.18653/v1/N19-1423"}},
    ],
}

S2_RESNET = {"data": [{"paperId": "2c03df8b", "title": "Deep Residual Learning for Image Recognition",
                       "year": 2016, "venue": "CVPR", "url": "https://www.semanticscholar.org/paper/2c03df8b",
                       "authors": [{"name": "Kaiming He"}],
                       "externalIds": {"ArXiv": "1512.03385", "DOI": "10.1109/CVPR.2016.90"}}]}

S2_LOOKALIKE = {"data": [{"paperId": "x1", "title": "Deep Residual Learning for Image Super-Resolution",
                          "year": 2016, "venue": "Workshop", "authors": [{"name": "Someone Else"}],
                          "externalIds": {}}]}

OPENALEX_SEARCH = {
    "results": [
        {"id": "https://openalex.org/W2963403868", "display_name": "Attention Is All You Need",
         "doi": None, "publication_year": 2017,
         "authorships": [{"author": {"display_name": "Ashish Vaswani"}}],
         "primary_location": {"landing_page_url": "https://arxiv.org/abs/1706.03762v5", "source": None},
         "abstract_inverted_index": None},
        {"id": "https://openalex.org/W2194775991", "display_name": "Deep Residual Learning for Image Recognition",
         "doi": "https://doi.org/10.1109/cvpr.2016.90", "publication_year": 2016,
         "authorships": [{"author": {"display_name": "Kaiming He"}}, {"author": {"display_name": "Xiangyu Zhang"}}],
         "primary_location": {"landing_page_url": "https://doi.org/10.1109/cvpr.2016.90",
                              "source": {"display_name": "Computer Vision and Pattern Recognition"}},
         "abstract_inverted_index": {"Deeper": [0], "networks": [1], "are": [2], "harder": [3, 5], "to": [4]}},
    ]
}

CROSSREF_RESNET = {"status": "ok", "message": {
    "DOI": "10.1109/cvpr.2016.90", "title": ["Deep Residual Learning for Image Recognition"],
    "author": [{"given": "Kaiming", "family": "He"}, {"given": "Xiangyu", "family": "Zhang"}],
    "issued": {"date-parts": [[2016, 6]]}, "container-title": ["2016 IEEE CVPR"]}}

FAKE_PDF = b"%PDF-1.5\n" + b"0" * 20_000


def js(obj) -> bytes:
    return json.dumps(obj).encode()


def down(status=None):
    return lit.FetchError("x", status)


class FakeNet:
    """Routes by URL substring; each route is a list of responses consumed in order (the last one repeats). A
    response is bytes or a FetchError to raise."""

    def __init__(self, routes):
        self.routes = [(key, list(resp) if isinstance(resp, list) else [resp]) for key, resp in routes]
        self.calls: list[str] = []

    def __call__(self, url, headers=None, timeout=None):
        self.calls.append(url)
        for key, responses in self.routes:
            if key in url:
                resp = responses.pop(0) if len(responses) > 1 else responses[0]
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise lit.FetchError(url, None, "no route (test)")

    def services(self):
        names = {"export.arxiv.org": "arxiv", "api.crossref.org": "crossref", "semanticscholar": "s2",
                 "openalex": "openalex", "arxiv.org/pdf": "pdf"}
        return [next(v for k, v in names.items() if k in u) for u in self.calls]


class Base(unittest.TestCase):
    def setUp(self):
        self._orig = (lit.fetch, lit._sleep)
        lit._sleep = lambda s: None
        lit._last_call.clear()

    def tearDown(self):
        lit.fetch, lit._sleep = self._orig

    def net(self, *routes):
        fake = FakeNet(routes)
        lit.fetch = fake
        return fake


class NormalizationTest(Base):
    def test_arxiv_entry(self):
        (rec,) = lit.parse_arxiv_feed(ARXIV_ATTENTION)
        self.assertEqual(rec["title"], "Attention Is All You Need")
        self.assertEqual(rec["arxiv_id"], "1706.03762")
        self.assertEqual(rec["authors"], ["Ashish Vaswani", "Noam Shazeer"])
        self.assertEqual(rec["year"], 2017)
        self.assertEqual(rec["doi"], "10.48550/arxiv.1706.03762")
        self.assertEqual(rec["url"], "https://arxiv.org/abs/1706.03762")
        self.assertTrue(rec["abstract"].startswith("The dominant sequence transduction models are based"))
        self.assertEqual(rec["source"], "arxiv")
        self.assertEqual(set(rec), {"title", "authors", "year", "arxiv_id", "doi", "url", "venue", "abstract",
                                    "source"})

    def test_semantic_scholar_paper(self):
        rec = lit.parse_s2_paper(S2_SEARCH["data"][1])
        self.assertEqual(rec["doi"], "10.18653/v1/n19-1423")
        self.assertIsNone(rec["arxiv_id"])
        self.assertEqual(rec["venue"], "NAACL")
        self.assertEqual(rec["authors"], ["Jacob Devlin"])
        self.assertEqual(rec["source"], "semantic_scholar")

    def test_openalex_work(self):
        a, r = (lit.parse_openalex_work(w) for w in OPENALEX_SEARCH["results"])
        self.assertEqual(a["arxiv_id"], "1706.03762")  # from the arXiv landing page
        self.assertEqual(r["doi"], "10.1109/cvpr.2016.90")
        self.assertEqual(r["url"], "https://doi.org/10.1109/cvpr.2016.90")
        self.assertEqual(r["abstract"], "Deeper networks are harder to harder")
        self.assertEqual(r["venue"], "Computer Vision and Pattern Recognition")
        self.assertEqual(r["year"], 2016)

    def test_identifier_normalization(self):
        for raw in ("1706.03762", "1706.03762v7", "arXiv:1706.03762", "https://arxiv.org/abs/1706.03762v2",
                    "https://arxiv.org/pdf/1706.03762.pdf", "id:1706.03762"):
            self.assertEqual(lit.normalize_arxiv_id(raw), "1706.03762", raw)
        self.assertEqual(lit.normalize_arxiv_id("solv-int/9901001v1"), "solv-int/9901001")
        self.assertIsNone(lit.normalize_arxiv_id("not an id"))
        # ARIS used str.lstrip with a character set here, which also ate leading DOI characters
        self.assertEqual(lit.normalize_doi("https://doi.org/10.1109/CVPR.2016.90"), "10.1109/cvpr.2016.90")
        self.assertEqual(lit.normalize_doi("doi:10.1/abc"), "10.1/abc")


class SearchTest(Base):
    def test_cross_source_dedup(self):
        fake = self.net(("export.arxiv.org", ARXIV_ATTENTION), ("semanticscholar", js(S2_SEARCH)),
                        ("openalex", js(OPENALEX_SEARCH)))
        recs = lit.search("transformer attention", limit=10)
        self.assertEqual(sorted(fake.services()), ["arxiv", "openalex", "s2"])
        attention = [r for r in recs if r["arxiv_id"] == "1706.03762"]
        self.assertEqual(len(attention), 1)
        self.assertEqual(attention[0]["sources"], ["arxiv", "semantic_scholar", "openalex"])
        self.assertEqual(attention[0]["source"], "arxiv")
        self.assertEqual(attention[0]["venue"], "NeurIPS")  # gap filled from Semantic Scholar
        self.assertEqual(len(recs), 3)  # attention, BERT, ResNet
        self.assertEqual([r["title"][:4] for r in recs], ["Atte", "BERT", "Deep"])

    def test_dedup_by_normalized_title(self):
        a = lit._record("arxiv", title="Deep Residual Learning for Image Recognition")
        b = lit._record("openalex", title="Deep residual learning for image recognition.", doi="10.1109/x")
        (merged,) = lit.dedup([a, b])
        self.assertEqual(merged["doi"], "10.1109/x")
        self.assertEqual(merged["sources"], ["arxiv", "openalex"])

    def test_limit_and_interleave(self):
        self.net(("semanticscholar", js(S2_SEARCH)), ("openalex", js(OPENALEX_SEARCH)))
        recs = lit.search("q", sources=("semantic_scholar", "openalex"), limit=2)
        self.assertEqual([r["title"][:4] for r in recs], ["Atte", "BERT"])

    def test_failed_source_is_skipped_and_reported(self):
        self.net(("export.arxiv.org", down(503)), ("semanticscholar", js(S2_SEARCH)))
        errors: list = []
        recs = lit.search("q", sources=("arxiv", "semantic_scholar"), limit=5, errors=errors)
        self.assertEqual(len(recs), 2)
        self.assertEqual([e["source"] for e in errors], ["arxiv"])

    def test_all_sources_failing_raises(self):
        self.net(("export.arxiv.org", down()), ("openalex", down(500)))
        with self.assertRaises(lit.LiteratureError):
            lit.search("q", sources=("arxiv", "openalex"))

    def test_unknown_source(self):
        with self.assertRaises(lit.LiteratureError):
            lit.search("q", sources=("google",))

    def test_arxiv_id_query_uses_id_list(self):
        fake = self.net(("export.arxiv.org", ARXIV_ATTENTION))
        lit.search_arxiv("1706.03762")
        self.assertIn("id_list=1706.03762", fake.calls[0])


class VerifyTest(Base):
    def test_arxiv_layer(self):
        fake = self.net(("export.arxiv.org", ARXIV_ATTENTION))
        v = lit.verify({"title": "Attention Is All You Need", "arxiv_id": "1706.03762v3"})
        self.assertEqual((v["verification"], v["method"]), ("verified", "arxiv"))
        self.assertEqual(v["matched"]["arxiv_id"], "1706.03762")
        self.assertEqual(fake.services(), ["arxiv"])  # stops at the first layer that confirms

    def test_crossref_layer(self):
        fake = self.net(("api.crossref.org", js(CROSSREF_RESNET)))
        v = lit.verify({"title": "Deep Residual Learning for Image Recognition", "doi": "10.1109/CVPR.2016.90"})
        self.assertEqual((v["verification"], v["method"]), ("verified", "crossref"))
        self.assertEqual(v["matched"]["authors"], ["Kaiming He", "Xiangyu Zhang"])
        self.assertEqual(fake.services(), ["crossref"])

    def test_semantic_scholar_title_layer(self):
        self.net(("semanticscholar", js(S2_RESNET)))
        v = lit.verify({"title": "Deep residual learning for image recognition"})
        self.assertEqual((v["verification"], v["method"]), ("verified", "semantic_scholar_title"))
        self.assertEqual(v["matched"]["arxiv_id"], "1512.03385")

    def test_fallback_order(self):
        fake = self.net(("export.arxiv.org", ARXIV_EMPTY), ("api.crossref.org", down(404)),
                        ("semanticscholar", js(S2_RESNET)))
        v = lit.verify({"title": "Deep Residual Learning for Image Recognition", "arxiv_id": "1512.99999",
                        "doi": "10.9999/nope"})
        self.assertEqual(fake.services(), ["arxiv", "crossref", "s2"])
        self.assertEqual((v["verification"], v["method"]), ("verified", "semantic_scholar_title"))
        self.assertIn("arXiv has no 1512.99999", v["detail"])
        self.assertIn("CrossRef has no 10.9999/nope", v["detail"])

    def test_existing_id_with_other_title_falls_through(self):
        fake = self.net(("export.arxiv.org", ARXIV_ATTENTION), ("semanticscholar", js({"data": []})))
        v = lit.verify({"title": "Graph Neural Networks for Protein Folding", "arxiv_id": "1706.03762"})
        self.assertEqual(v["verification"], "unverified")
        self.assertFalse(v["pending"])
        self.assertIn("title differs", v["detail"])
        self.assertEqual(fake.services(), ["arxiv", "s2"])

    def test_unreachable_network_is_unverified_not_dropped(self):
        self.net(("export.arxiv.org", down()), ("api.crossref.org", down(503)), ("semanticscholar", down(429)))
        record = {"title": "Attention Is All You Need", "arxiv_id": "1706.03762", "doi": "10.1/x"}
        snapshot = dict(record)
        v = lit.verify(record)
        self.assertEqual(v["verification"], "unverified")
        self.assertIsNone(v["method"])
        self.assertTrue(v["pending"])
        self.assertEqual(v["detail"].count("unreachable"), 3)
        self.assertEqual(record, snapshot)

    def test_malformed_response_is_unverified_not_raised(self):
        self.net(("semanticscholar", b"<html>gateway</html>"))
        v = lit.verify({"title": "Some Paper"})
        self.assertEqual(v["verification"], "unverified")
        self.assertTrue(v["pending"])

    def test_retry_after_429_and_rate_exceeded(self):
        fake = self.net(("export.arxiv.org", [down(429), b"Rate exceeded.", ARXIV_ATTENTION]))
        v = lit.verify({"title": "Attention Is All You Need", "arxiv_id": "1706.03762"})
        self.assertEqual(v["verification"], "verified")
        self.assertEqual(len(fake.calls), 3)

    def test_refusal_is_not_retried(self):
        fake = self.net(("semanticscholar", down(403)))
        v = lit.verify({"title": "Some Paper"})
        self.assertEqual(len(fake.calls), 1)
        self.assertTrue(v["pending"])

    def test_lookalike_title_is_not_verified(self):
        self.net(("semanticscholar", js(S2_LOOKALIKE)))
        rec = {"title": "Deep Residual Learning for Image Recognition"}
        v = lit.verify(rec)
        self.assertEqual(v["verification"], "unverified")
        self.assertFalse(v["pending"])
        self.assertIn("no title match", v["detail"])
        # the ARIS default (0.6) would have accepted it: overlap is 5/7
        self.assertAlmostEqual(lit.title_overlap(rec["title"], S2_LOOKALIKE["data"][0]["title"]), 5 / 7)
        self.assertEqual(lit.verify(rec, threshold=0.6)["verification"], "verified")

    def test_year_mismatch_is_not_verified(self):
        self.net(("semanticscholar", js(S2_RESNET)))
        v = lit.verify({"title": "Deep Residual Learning for Image Recognition", "year": 2023})
        self.assertEqual(v["verification"], "unverified")
        self.assertIn("year differs", v["detail"])

    def test_nothing_to_check(self):
        v = lit.verify({"title": "  ", "authors": ["A"]})
        self.assertEqual(v["verification"], "unverified")
        self.assertFalse(v["pending"])


class PdfTest(Base):
    def test_fetch_and_reuse(self):
        fake = self.net(("arxiv.org/pdf/1706.03762.pdf", FAKE_PDF))
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "cache" / "literature"
            rec = {"arxiv_id": "1706.03762v2"}
            path = lit.fetch_pdf(rec, cache)
            self.assertEqual(path, str(cache / "1706.03762.pdf"))
            self.assertEqual(Path(path).read_bytes(), FAKE_PDF)
            digest = hashlib.sha256(FAKE_PDF).hexdigest()
            self.assertEqual(rec["sha256"], digest)
            self.assertEqual(rec["cache_path"], path)
            side = json.loads((cache / "1706.03762.json").read_text())
            self.assertEqual((side["sha256"], side["bytes"]), (digest, len(FAKE_PDF)))
            self.assertEqual(lit.fetch_pdf({"arxiv_id": "1706.03762"}, cache), path)
            self.assertEqual(len(fake.calls), 1)  # second call served from the cache

    def test_error_page_and_missing_id(self):
        self.net(("arxiv.org/pdf/", b"<html>not found</html>"))
        with tempfile.TemporaryDirectory() as d:
            rec = {"arxiv_id": "1706.03762"}
            self.assertIsNone(lit.fetch_pdf(rec, d))
            self.assertIn("PDF", rec["fetch_error"])
            self.assertFalse(list(Path(d).glob("*.pdf")))
            self.assertIsNone(lit.fetch_pdf({"title": "no id"}, d))

    def test_poisoned_cache_entry_is_replaced(self):
        self.net(("arxiv.org/pdf/", FAKE_PDF))
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "1706.03762.pdf").write_bytes(b"<html>oops</html>")
            path = lit.fetch_pdf({"arxiv_id": "1706.03762"}, d)
            self.assertEqual(Path(path).read_bytes(), FAKE_PDF)

    def test_old_style_id_file_name(self):
        fake = self.net(("arxiv.org/pdf/", FAKE_PDF))
        with tempfile.TemporaryDirectory() as d:
            path = lit.fetch_pdf({"arxiv_id": "cs/0601001v1"}, d)
            self.assertTrue(path.endswith("cs_0601001.pdf"))
            self.assertIn("/pdf/cs/0601001.pdf", fake.calls[0])


class FrontMatterTest(Base):
    def test_verified(self):
        rec = {"title": "Attention Is All You Need: a \"test\"", "authors": ["Ashish Vaswani", "Noam Shazeer"],
               "year": 2017, "arxiv_id": "1706.03762", "doi": None, "url": "https://arxiv.org/abs/1706.03762",
               "cache_path": "cache/literature/1706.03762.pdf", "sha256": "ab" * 32}
        fm = lit.front_matter(rec, {"verification": "verified", "method": "arxiv", "matched": {}},
                              accessed="2026-10-07")
        lines = fm.splitlines()
        self.assertEqual((lines[0], lines[-1]), ("---", "---"))
        self.assertIn("verification: verified", lines)
        self.assertIn("verification_method: arxiv", lines)
        self.assertIn('arxiv_id: "1706.03762"', lines)  # quoted: plain YAML would read a float
        self.assertIn('accessed: "2026-10-07"', lines)
        self.assertIn("year: 2017", lines)
        self.assertIn('cache_path: "cache/literature/1706.03762.pdf"', lines)
        self.assertNotIn("verification_detail", fm)
        try:
            import yaml
        except ImportError:
            return
        data = yaml.safe_load(fm.strip("-\n"))
        self.assertEqual(data["verification"], "verified")
        self.assertEqual(data["arxiv_id"], "1706.03762")
        self.assertEqual(data["title"], rec["title"])
        self.assertEqual(data["authors"], rec["authors"])
        self.assertIsNone(data["doi"])

    def test_unverified_keeps_reason(self):
        fm = lit.front_matter({"title": "X"}, {"verification": "unverified", "method": None,
                                               "detail": "semantic_scholar_title unreachable: network error"})
        self.assertIn("verification: unverified", fm.splitlines())
        self.assertIn("verification_method: null", fm.splitlines())
        self.assertIn("verification_detail: \"semantic_scholar_title unreachable", fm)
        self.assertNotIn("verification: verified", fm)

    def test_verified_by_title_takes_matched_ids(self):
        self.net(("semanticscholar", js(S2_RESNET)))
        rec = {"title": "Deep Residual Learning for Image Recognition"}
        fm = lit.front_matter(rec, lit.verify(rec))
        self.assertIn('arxiv_id: "1512.03385"', fm)
        self.assertIn('doi: "10.1109/cvpr.2016.90"', fm)
        self.assertIn("verification_method: semantic_scholar_title", fm)

    def test_bare_string_status(self):
        self.assertIn("verification: unverified", lit.front_matter({"title": "X"}, "maybe"))


class CliTest(Base):
    def run_cli(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = lit.main(argv)
        return code, json.loads(out.getvalue())

    def test_search(self):
        self.net(("semanticscholar", js(S2_SEARCH)), ("openalex", js(OPENALEX_SEARCH)))
        code, payload = self.run_cli(["search", "attention", "--limit", "5",
                                      "--sources", "semantic_scholar,openalex"])
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["errors"], [])
        self.assertEqual(len(payload["result"]["records"]), 3)

    def test_verify(self):
        self.net(("export.arxiv.org", ARXIV_ATTENTION))
        code, payload = self.run_cli(["verify", "--title", "Attention Is All You Need", "--arxiv-id", "1706.03762"])
        self.assertEqual((code, payload["ok"]), (0, True))
        self.assertEqual(payload["result"]["verification"], "verified")
        self.assertEqual(set(payload["result"]), {"verification", "method", "matched", "detail", "pending"})

    def test_verify_offline_is_still_ok(self):
        self.net()
        code, payload = self.run_cli(["verify", "--title", "Attention Is All You Need"])
        self.assertEqual((code, payload["result"]["verification"]), (0, "unverified"))

    def test_fetch(self):
        self.net(("arxiv.org/pdf/", FAKE_PDF))
        with tempfile.TemporaryDirectory() as d:
            code, payload = self.run_cli(["fetch", "--arxiv-id", "1706.03762", "--cache", d])
            self.assertEqual((code, payload["ok"]), (0, True))
            self.assertEqual(payload["result"]["sha256"], hashlib.sha256(FAKE_PDF).hexdigest())

    def test_errors_exit_2(self):
        self.net(("arxiv.org/pdf/", down(404)))
        with tempfile.TemporaryDirectory() as d:
            code, payload = self.run_cli(["fetch", "--arxiv-id", "1706.03762", "--cache", d])
            self.assertEqual(code, 2)
            self.assertEqual(set(payload), {"ok", "error"})
            self.assertFalse(payload["ok"])
            code, payload = self.run_cli(["search", "q", "--sources", "nowhere"])
            self.assertEqual((code, payload["ok"]), (2, False))




class NoteTest(unittest.TestCase):
    def test_note_writes_verified_front_matter_once(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs/literature/LIT-0001.v1.md"
            verdict = {"verification": "verified", "method": "arxiv", "matched": {"arxiv_id": "1706.03762"},
                       "detail": "ok", "pending": False}
            with mock.patch.object(lit, "verify", return_value=verdict):
                result = lit.write_note({"title": "Attention Is All You Need", "authors": [], "year": 2017,
                                                "arxiv_id": "1706.03762", "doi": None}, out)
            self.assertEqual(result["verification"], "verified")
            text = out.read_text(encoding="utf-8")
            self.assertIn("\nverification: verified\n", text)
            self.assertIn("## 最近邻差异", text)
            with self.assertRaises(lit.LiteratureError):
                lit.write_note({"title": "x"}, out)


if __name__ == "__main__":
    unittest.main()

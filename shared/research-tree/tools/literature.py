"""Literature search, existence verification and PDF cache (plans/design/08 §2, 02 D1).

Ported from ARIS tools/verify_papers.py, arxiv_fetch.py, semantic_scholar_fetch.py and openalex_fetch.py
(Auto-claude-code-research-in-sleep @ 3b19a22) into one standard-library module:

- search(query, sources, limit): arXiv, Semantic Scholar and OpenAlex, normalized to one record shape and
  deduplicated across sources by arXiv id, DOI and normalized title.
- verify(record): three-layer existence check (arXiv id → CrossRef DOI → Semantic Scholar fuzzy title). A layer
  that cannot be reached leaves the record `unverified` with the reason; nothing raises and no record is dropped.
- fetch_pdf(record, cache_dir): the arXiv PDF into cache_dir/<arxiv_id>.pdf with its sha256 in a sidecar.
- front_matter(record, verification): the front matter of a `literature` document. Only `verification: verified`
  counts toward min_related_work.

Existence is not support: a verified record says the paper exists with this title, not that it says what a
document claims. Every network call goes through the module-level `fetch`, which tests replace. Nothing here
calls a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_PDF = "https://arxiv.org/pdf/{}.pdf"
ARXIV_ABS = "https://arxiv.org/abs/{}"
CROSSREF_API = "https://api.crossref.org/works"
S2_API = "https://api.semanticscholar.org/graph/v1"
OPENALEX_API = "https://api.openalex.org"

SOURCES = ("arxiv", "semantic_scholar", "openalex")
# Seconds between calls to one service: arXiv asks for 3 s, Semantic Scholar allows 1 req/s per key (and the
# anonymous pool is shared), CrossRef and OpenAlex are lenient. Downloads from arxiv.org get their own slot.
MIN_INTERVAL = {"arxiv": 3.0, "arxiv_pdf": 1.0, "semantic_scholar": 1.05, "crossref": 0.2, "openalex": 0.2}
ATTEMPTS = 3
DEFAULT_TIMEOUT = 30
# Word overlap |A∩B| / max(|A|, |B|) between normalized titles. ARIS used 0.6, which accepts a different paper
# that shares most words ("... for Image Recognition" vs "... for Image Super-Resolution" is 0.71).
FUZZY_THRESHOLD = 0.85
MIN_PDF_BYTES = 10_240
S2_FIELDS = "title,year,venue,url,abstract,authors,externalIds"

_ATOM = "{http://www.w3.org/2005/Atom}"
_NEW_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
_OLD_ID_RE = re.compile(r"^[A-Za-z.-]+/\d{7}(v\d+)?$")
_VERSION_RE = re.compile(r"v\d+$")
_ARXIV_IN_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([A-Za-z.-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_ARXIV_DOI_RE = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_PLAIN_YAML_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_YAML_RESERVED = {"true", "false", "yes", "no", "on", "off", "null", "y", "n"}


class FetchError(Exception):
    """A request that did not return a body: `status` is the HTTP code, or None for a network failure."""

    def __init__(self, url: str, status: int | None, message: str = ""):
        self.url, self.status = url, status
        super().__init__(f"{'HTTP ' + str(status) if status is not None else 'network error'}"
                         f"{': ' + message if message else ''} ({url})")


class LiteratureError(Exception):
    pass


# ── network ────────────────────────────────────────────────────────────────

def user_agent() -> str:
    """A named client lands in the APIs' lenient pools; the contact address comes from the environment."""
    contact = (os.environ.get("LITERATURE_MAILTO") or os.environ.get("ARIS_VERIFY_EMAIL") or "").strip()
    base = "research-tree-literature/1.0 (+https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep)"
    return f"{base} (mailto:{contact})" if contact else base


def _curl_get(url: str, headers: dict[str, str], timeout: float) -> bytes | None:
    """export.arxiv.org answers urllib with 406 from some networks for minutes while curl gets 200."""
    curl = shutil.which("curl")
    if curl is None:
        return None
    cmd = [curl, "-sf", "--max-time", str(int(timeout))]
    for key, value in headers.items():
        cmd += ["-H", f"{key}: {value}"]
    proc = subprocess.run(cmd + [url], capture_output=True, check=False)
    return proc.stdout if proc.returncode == 0 else None


def fetch(url: str, headers: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """GET `url` and return the body; raise FetchError otherwise. The only function that touches the network."""
    hdrs = {"User-Agent": user_agent(), **(headers or {})}
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 406:
            rescued = _curl_get(url, hdrs, timeout)
            if rescued is not None:
                return rescued
        raise FetchError(url, exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(url, None, str(exc)) from exc


_sleep = time.sleep
_last_call: dict[str, float] = {}


def _throttle(service: str) -> None:
    wait = MIN_INTERVAL.get(service, 0.0) - (time.monotonic() - _last_call.get(service, -1e9))
    if wait > 0:
        _sleep(wait)
    _last_call[service] = time.monotonic()


def _transient(status: int | None) -> bool:
    # 406 from export.arxiv.org alternates with 200 on the same URL: an outage, not a client error.
    return status is None or status in (406, 408, 429) or 500 <= status < 600


def _backoff(attempt: int) -> float:
    return min(2 ** attempt + random.uniform(0, 1), 30)


def _get(service: str, url: str, headers: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT,
         attempts: int = ATTEMPTS) -> bytes:
    """Rate-limited GET with retries on network errors, 406/408/429 and 5xx. Raises the last FetchError."""
    last: FetchError | None = None
    for attempt in range(attempts):
        _throttle(service)
        try:
            body = fetch(url, headers=headers, timeout=timeout)
        except FetchError as exc:
            last = exc
            if not _transient(exc.status):
                raise
        else:
            # The arXiv API sometimes answers a rate limit with 200 and this plain-text body.
            if body.strip() != b"Rate exceeded.":
                return body
            last = FetchError(url, 429, "Rate exceeded.")
        if attempt < attempts - 1:
            _sleep(max(_backoff(attempt), MIN_INTERVAL.get(service, 0.0)))
    assert last is not None
    raise last


def _get_json(service: str, url: str, headers: dict[str, str] | None = None) -> Any:
    body = _get(service, url, {"Accept": "application/json", **(headers or {})})
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise FetchError(url, 200, "response is not JSON") from exc


def _s2_headers() -> dict[str, str]:
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    return {"x-api-key": key} if key else {}


# ── normalization ──────────────────────────────────────────────────────────

def normalize_arxiv_id(raw: str | None) -> str | None:
    """Bare arXiv id without URL, `arXiv:` prefix or version; None if it does not look like one."""
    if not raw:
        return None
    value = raw.strip()
    m = _ARXIV_IN_URL_RE.search(value)
    if m:
        return m.group(1)
    value = re.sub(r"^(?:arxiv:|id:)", "", value, flags=re.IGNORECASE).removesuffix(".pdf")
    if not (_NEW_ID_RE.match(value) or _OLD_ID_RE.match(value)):
        return None
    return _VERSION_RE.sub("", value)


def normalize_doi(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/",
                   "doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    return value or None


def normalize_title(raw: str | None) -> str:
    """Lowercase + Unicode NFKD + punctuation to spaces + collapsed whitespace."""
    t = unicodedata.normalize("NFKD", raw or "").lower()
    t = _PUNCT_RE.sub(" ", t)
    return _WS_RE.sub(" ", t).strip()


def title_overlap(a: str | None, b: str | None) -> float:
    wa, wb = set(normalize_title(a).split()), set(normalize_title(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = _WS_RE.sub(" ", str(value)).strip()
    return text or None


def _year(value: Any) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def _record(source: str, **fields: Any) -> dict[str, Any]:
    rec = {"title": None, "authors": [], "year": None, "arxiv_id": None, "doi": None, "url": None,
           "venue": None, "abstract": None, "source": source}
    rec.update(fields)
    doi = normalize_doi(rec["doi"])
    rec["doi"] = doi
    if not rec["arxiv_id"] and doi and (m := _ARXIV_DOI_RE.match(doi)):
        rec["arxiv_id"] = normalize_arxiv_id(m.group(1))
    if not rec["url"]:
        rec["url"] = (ARXIV_ABS.format(rec["arxiv_id"]) if rec["arxiv_id"]
                      else f"https://doi.org/{doi}" if doi else None)
    return rec


def parse_arxiv_entry(entry: ET.Element) -> dict[str, Any]:
    arxiv_id = normalize_arxiv_id(entry.findtext(f"{_ATOM}id", ""))
    return _record(
        "arxiv",
        title=_clean(entry.findtext(f"{_ATOM}title")),
        authors=[n for a in entry.findall(f"{_ATOM}author") if (n := _clean(a.findtext(f"{_ATOM}name")))],
        year=_year(entry.findtext(f"{_ATOM}published")),
        arxiv_id=arxiv_id,
        doi=_clean(entry.findtext("{http://arxiv.org/schemas/atom}doi")),
        url=ARXIV_ABS.format(arxiv_id) if arxiv_id else None,
        venue=_clean(entry.findtext("{http://arxiv.org/schemas/atom}journal_ref")),
        abstract=_clean(entry.findtext(f"{_ATOM}summary")),
    )


def parse_arxiv_feed(body: bytes) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise LiteratureError(f"arXiv response is not Atom XML: {exc}") from exc
    # An unparseable id_list comes back as an entry whose id is an api/errors URL; it has no arXiv id.
    return [r for r in (parse_arxiv_entry(e) for e in root.findall(f"{_ATOM}entry")) if r["arxiv_id"]]


def parse_s2_paper(paper: dict[str, Any]) -> dict[str, Any]:
    ext = paper.get("externalIds") or {}
    return _record(
        "semantic_scholar",
        title=_clean(paper.get("title")),
        authors=[n for a in paper.get("authors") or [] if (n := _clean((a or {}).get("name")))],
        year=_year(paper.get("year")),
        arxiv_id=normalize_arxiv_id(ext.get("ArXiv")),
        doi=ext.get("DOI"),
        url=_clean(paper.get("url")),
        venue=_clean(paper.get("venue")),
        abstract=_clean(paper.get("abstract")),
    )


def _openalex_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    if not inverted:
        return None
    words = sorted((pos, word) for word, positions in inverted.items() for pos in positions)
    return " ".join(word for _, word in words) or None


def parse_openalex_work(work: dict[str, Any]) -> dict[str, Any]:
    arxiv_id = None
    for loc in [work.get("primary_location")] + list(work.get("locations") or []):
        for link in ((loc or {}).get("landing_page_url"), (loc or {}).get("pdf_url")):
            if link and "arxiv.org/" in link.lower() and (arxiv_id := normalize_arxiv_id(link)):
                break
        if arxiv_id:
            break
    source = (work.get("primary_location") or {}).get("source") or {}
    return _record(
        "openalex",
        title=_clean(work.get("display_name") or work.get("title")),
        authors=[n for a in work.get("authorships") or [] if (n := _clean(((a or {}).get("author") or {})
                                                                          .get("display_name")))],
        year=_year(work.get("publication_year")),
        arxiv_id=arxiv_id,
        doi=work.get("doi"),
        url=None if (arxiv_id or work.get("doi")) else _clean(work.get("id")),
        venue=_clean(source.get("display_name")),
        abstract=_openalex_abstract(work.get("abstract_inverted_index")),
    )


# ── search ─────────────────────────────────────────────────────────────────

def search_arxiv(query: str, limit: int = 10) -> list[dict[str, Any]]:
    q = query.strip()
    bare = normalize_arxiv_id(q.removeprefix("id:"))
    if bare:
        params: dict[str, Any] = {"id_list": bare}
    else:
        params = {"search_query": q, "start": 0, "max_results": limit,
                  "sortBy": "relevance", "sortOrder": "descending"}
    return parse_arxiv_feed(_get("arxiv", f"{ARXIV_API}?{urllib.parse.urlencode(params)}"))[:limit]


def search_semantic_scholar(query: str, limit: int = 10) -> list[dict[str, Any]]:
    params = {"query": query, "limit": min(limit, 100), "fields": S2_FIELDS}
    payload = _get_json("semantic_scholar", f"{S2_API}/paper/search?{urllib.parse.urlencode(params)}",
                        _s2_headers())
    return [parse_s2_paper(p) for p in (payload.get("data") or [])][:limit]


def search_openalex(query: str, limit: int = 10) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"search": query, "per_page": min(limit, 200), "sort": "relevance_score:desc"}
    if email := os.environ.get("OPENALEX_EMAIL", "").strip():
        params["mailto"] = email  # OpenAlex's polite pool
    if key := os.environ.get("OPENALEX_API_KEY", "").strip():
        params["api_key"] = key
    payload = _get_json("openalex", f"{OPENALEX_API}/works?{urllib.parse.urlencode(params)}")
    return [parse_openalex_work(w) for w in (payload.get("results") or [])][:limit]


_SEARCHERS = {"arxiv": search_arxiv, "semantic_scholar": search_semantic_scholar, "openalex": search_openalex}


def _dedup_keys(rec: dict[str, Any]) -> list[str]:
    keys = []
    if rec.get("arxiv_id"):
        keys.append("arxiv:" + rec["arxiv_id"])
    if rec.get("doi"):
        keys.append("doi:" + rec["doi"])
    if t := normalize_title(rec.get("title")):
        keys.append("title:" + t)
    return keys


def dedup(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge records that share an arXiv id, DOI or normalized title; the first keeps its order and fields, later
    ones fill its gaps, and `sources` lists every source that returned it."""
    out: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for rec in records:
        hit = next((index[k] for k in _dedup_keys(rec) if k in index), None)
        if hit is None:
            hit = {**rec, "sources": [rec["source"]]}
            out.append(hit)
        else:
            for field, value in rec.items():
                if field != "source" and value and not hit.get(field):
                    hit[field] = value
            if rec["source"] not in hit["sources"]:
                hit["sources"].append(rec["source"])
        for k in _dedup_keys(hit):
            index.setdefault(k, hit)
    return out


def search(query: str, sources: tuple[str, ...] | list[str] = SOURCES, limit: int = 10,
           errors: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    """Up to `limit` records per source, interleaved by rank, deduplicated, cut to `limit`. A source that fails
    is skipped (and appended to `errors` when given); LiteratureError only when every source failed."""
    unknown = [s for s in sources if s not in _SEARCHERS]
    if unknown:
        raise LiteratureError(f"unknown source(s) {unknown}; choose from {list(SOURCES)}")
    per_source: list[list[dict[str, Any]]] = []
    failed: list[dict[str, str]] = []
    for src in sources:
        try:
            per_source.append(_SEARCHERS[src](query, limit))
        except (FetchError, LiteratureError) as exc:
            failed.append({"source": src, "error": str(exc)})
    if errors is not None:
        errors.extend(failed)
    if sources and len(failed) == len(sources):
        raise LiteratureError("; ".join(f"{f['source']}: {f['error']}" for f in failed))
    interleaved = [lst[i] for i in range(max((len(x) for x in per_source), default=0))
                   for lst in per_source if i < len(lst)]
    return dedup(interleaved)[:limit]


# ── verification ───────────────────────────────────────────────────────────

def _title_ok(record: dict[str, Any], found_title: str | None, found_year: int | None,
              threshold: float) -> tuple[bool, str]:
    if not record.get("title"):
        return True, "no title to compare"
    score = title_overlap(record["title"], found_title)
    if score < threshold:
        return False, f"title differs ({score:.2f} < {threshold}): {found_title!r}"
    year = _year(record.get("year"))
    if year and found_year and abs(year - found_year) > 1:
        return False, f"year differs ({year} vs {found_year})"
    return True, f"title overlap {score:.2f}"


def _verify_arxiv(record: dict[str, Any], arxiv_id: str, threshold: float) -> tuple[str, dict | None, str]:
    url = f"{ARXIV_API}?{urllib.parse.urlencode({'id_list': arxiv_id, 'max_results': 1})}"
    entries = parse_arxiv_feed(_get("arxiv", url))
    found = next((e for e in entries if e["arxiv_id"] == arxiv_id), None)
    if found is None:
        return "absent", None, f"arXiv has no {arxiv_id}"
    ok, why = _title_ok(record, found["title"], found["year"], threshold)
    return ("match" if ok else "mismatch"), found, f"arXiv {arxiv_id}: {why}"


def _verify_crossref(record: dict[str, Any], doi: str, threshold: float) -> tuple[str, dict | None, str]:
    url = f"{CROSSREF_API}/{urllib.parse.quote(doi, safe='/')}"
    try:
        msg = (_get_json("crossref", url) or {}).get("message") or {}
    except FetchError as exc:
        if exc.status == 404:
            return "absent", None, f"CrossRef has no {doi}"
        raise
    parts = ((msg.get("issued") or {}).get("date-parts") or [[None]])[0] or [None]
    found = _record(
        "crossref",
        title=_clean((msg.get("title") or [None])[0]),
        authors=[n for a in msg.get("author") or []
                 if (n := _clean(" ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name")))],
        year=_year(parts[0]),
        doi=msg.get("DOI") or doi,
        venue=_clean((msg.get("container-title") or [None])[0]),
    )
    ok, why = _title_ok(record, found["title"], found["year"], threshold)
    return ("match" if ok else "mismatch"), found, f"CrossRef {doi}: {why}"


def _verify_s2_title(record: dict[str, Any], threshold: float) -> tuple[str, dict | None, str]:
    normalized = normalize_title(record.get("title"))
    params = {"query": normalized[:200], "limit": 5, "fields": S2_FIELDS}
    payload = _get_json("semantic_scholar", f"{S2_API}/paper/search?{urllib.parse.urlencode(params)}",
                        _s2_headers())
    candidates = [parse_s2_paper(p) for p in (payload.get("data") or [])]
    best, best_why, best_score = None, "no candidates", -1.0
    for cand in candidates:
        ok, why = _title_ok(record, cand["title"], cand["year"], threshold)
        if ok:
            return "match", cand, f"Semantic Scholar: {why}"
        score = title_overlap(record.get("title"), cand["title"])
        if score > best_score:
            best, best_why, best_score = cand, why, score
    return "absent", None, f"Semantic Scholar: no title match ({best_why})" if best else "Semantic Scholar: no results"


def verify(record: dict[str, Any], threshold: float = FUZZY_THRESHOLD) -> dict[str, Any]:
    """Three layers in order — arXiv id, CrossRef DOI, Semantic Scholar title — stopping at the first that confirms
    the paper (and, when the record has a title, that the title matches). Never raises.

    Returns {"verification": "verified"|"unverified", "method": "arxiv"|"crossref"|"semantic_scholar_title"|None,
    "matched": the record the service returned (or {}), "detail": per-layer reasons joined by "; ",
    "pending": True when some layer was unreachable, so a later retry may still verify it}."""
    layers: list[tuple[str, Any]] = []
    if arxiv_id := normalize_arxiv_id(record.get("arxiv_id")):
        layers.append(("arxiv", lambda: _verify_arxiv(record, arxiv_id, threshold)))
    elif record.get("arxiv_id"):
        layers.append(("arxiv", lambda: ("absent", None, f"malformed arXiv id {record['arxiv_id']!r}")))
    if doi := normalize_doi(record.get("doi")):
        layers.append(("crossref", lambda: _verify_crossref(record, doi, threshold)))
    if normalize_title(record.get("title")):
        layers.append(("semantic_scholar_title", lambda: _verify_s2_title(record, threshold)))
    if not layers:
        return {"verification": "unverified", "method": None, "matched": {},
                "detail": "no arXiv id, DOI or title to check", "pending": False}
    notes: list[str] = []
    pending = False
    for method, run in layers:
        try:
            outcome, found, why = run()
        except (FetchError, LiteratureError) as exc:
            pending = True
            notes.append(f"{method} unreachable: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 — a malformed response must not drop the record
            pending = True
            notes.append(f"{method} failed: {type(exc).__name__}: {exc}")
            continue
        notes.append(why)
        if outcome == "match":
            return {"verification": "verified", "method": method, "matched": found or {},
                    "detail": "; ".join(notes), "pending": False}
    return {"verification": "unverified", "method": None, "matched": {}, "detail": "; ".join(notes),
            "pending": pending}


# ── PDF cache ──────────────────────────────────────────────────────────────

def _validate_pdf(data: bytes) -> None:
    if len(data) < MIN_PDF_BYTES:
        raise LiteratureError(f"download is only {len(data)} bytes - likely an error page, not a PDF")
    if b"%PDF-" not in data[:1024]:
        raise LiteratureError("download has no PDF header - likely an error page, not a PDF")


def download_pdf(arxiv_id: str, cache_dir: str | Path) -> dict[str, Any]:
    """Download (or reuse) cache_dir/<id>.pdf and write cache_dir/<id>.json with url, sha256, bytes and fetch time.
    Raises LiteratureError or FetchError."""
    clean = normalize_arxiv_id(arxiv_id)
    if not clean:
        raise LiteratureError(f"not an arXiv id: {arxiv_id!r}")
    cache = Path(cache_dir)
    dest = cache / f"{clean.replace('/', '_')}.pdf"
    url = ARXIV_PDF.format(clean)
    data = None
    if dest.is_file():
        data = dest.read_bytes()
        try:
            _validate_pdf(data)
        except LiteratureError:
            dest.unlink()  # a poisoned entry (an error page saved as .pdf) is fetched again
            data = None
    reused = data is not None
    if data is None:
        data = _get("arxiv_pdf", url, timeout=60)
        _validate_pdf(data)
        cache.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".pdf.part")
        tmp.write_bytes(data)
        tmp.replace(dest)
    meta = {"arxiv_id": clean, "url": url, "path": str(dest), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "reused": reused,
            "fetched": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    sidecar = dest.with_suffix(".json")
    if reused and sidecar.is_file():
        try:
            meta["fetched"] = json.loads(sidecar.read_text(encoding="utf-8")).get("fetched", meta["fetched"])
        except (OSError, json.JSONDecodeError):
            pass
    sidecar.write_text(json.dumps({k: v for k, v in meta.items() if k != "reused"}, indent=2) + "\n",
                       encoding="utf-8")
    return meta


def fetch_pdf(record: dict[str, Any], cache_dir: str | Path) -> str | None:
    """Path of the cached arXiv PDF, or None (no arXiv id, or the download failed). Sets record["cache_path"] and
    record["sha256"] on success, record["fetch_error"] on failure."""
    if not record.get("arxiv_id"):
        record["fetch_error"] = "no arXiv id"
        return None
    try:
        meta = download_pdf(record["arxiv_id"], cache_dir)
    except (FetchError, LiteratureError, OSError) as exc:
        record["fetch_error"] = str(exc)
        return None
    record["cache_path"], record["sha256"] = meta["path"], meta["sha256"]
    record.pop("fetch_error", None)
    return meta["path"]


# ── front matter ───────────────────────────────────────────────────────────

def _yaml_scalar(value: Any) -> str:
    """Plain for bare words such as `verified` and for numbers; JSON (a YAML subset) for everything else, so an
    arXiv id like 1706.03762 stays a string."""
    if value is None:
        return "null"
    if isinstance(value, (bool, int, float)):
        return json.dumps(value)
    if isinstance(value, str) and _PLAIN_YAML_RE.match(value) and value.lower() not in _YAML_RESERVED:
        return value
    return json.dumps(value, ensure_ascii=False)


def front_matter(record: dict[str, Any], verification: dict[str, Any] | str,
                 accessed: str | None = None) -> str:
    """The `---` delimited front matter of a `literature` document. `verification` is a verify() result (or the
    bare string); anything but "verified" is written as unverified, with its detail."""
    v = verification if isinstance(verification, dict) else {"verification": verification}
    status = "verified" if v.get("verification") == "verified" else "unverified"
    # A verified record takes the identifiers the service confirmed; the record's own fill the gaps.
    matched = (v.get("matched") or {}) if status == "verified" else {}

    def pick(key: str) -> Any:
        return matched.get(key) or record.get(key)

    fields: dict[str, Any] = {
        "title": record.get("title") or matched.get("title"),
        "authors": list(record.get("authors") or matched.get("authors") or []),
        "year": _year(record.get("year") or matched.get("year")),
        "arxiv_id": normalize_arxiv_id(pick("arxiv_id")),
        "doi": normalize_doi(pick("doi")),
        "url": record.get("url") or matched.get("url"),
        "accessed": accessed or datetime.now(UTC).strftime("%Y-%m-%d"),
        "verification": status,
        "verification_method": v.get("method") if status == "verified" else None,
        "cache_path": record.get("cache_path"),
        "sha256": record.get("sha256"),
    }
    if status != "verified" and v.get("detail"):
        fields["verification_detail"] = v["detail"]
    lines = []
    for key, value in fields.items():
        if isinstance(value, list):
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    return "---\n" + "\n".join(lines) + "\n---\n"


# ── CLI ────────────────────────────────────────────────────────────────────

NOTE_SECTIONS = ("出处", "核心方法", "实验设定与结果", "与本项目的关系", "最近邻差异")


def write_note(record: dict, out: Path, cache_dir: str | None = None) -> dict:
    """A literature document skeleton: the verification front matter, then the sections the Leader or a worker
    fills in after reading the paper (08 §1.6). Refuses to overwrite an existing file."""
    if out.exists():
        raise LiteratureError(f"{out} exists; write a new version instead")
    result = verify(record)
    arxiv_id = record.get("arxiv_id") or (result.get("matched") or {}).get("arxiv_id")
    if cache_dir and arxiv_id:
        record = {**record, "arxiv_id": arxiv_id}
        fetch_pdf(record, cache_dir)  # sets cache_path and sha256 on success
    body = front_matter(record, result) + f"\n# {record.get('title')}\n\n" + "".join(
        f"## {name}\n\n（阅读原文后填写）\n\n" for name in NOTE_SECTIONS)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    return {"path": str(out), "verification": result["verification"], "method": result.get("method"),
            "detail": result.get("detail"), "pending": result.get("pending", False)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Literature search, existence verification and PDF cache.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="search arXiv / Semantic Scholar / OpenAlex")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--sources", nargs="+", default=list(SOURCES),
                   help=f"any of {', '.join(SOURCES)} (space- or comma-separated)")
    v = sub.add_parser("verify", help="three-layer existence check of one paper")
    v.add_argument("--title", required=True)
    v.add_argument("--arxiv-id")
    v.add_argument("--doi")
    v.add_argument("--year", type=int)
    v.add_argument("--threshold", type=float, default=FUZZY_THRESHOLD)
    n = sub.add_parser("note", help="verify a paper, cache its PDF when on arXiv, and write a literature document "
                                    "skeleton whose front matter records the verification (never edit it by hand)")
    n.add_argument("--title", required=True)
    n.add_argument("--arxiv-id")
    n.add_argument("--doi")
    n.add_argument("--year", type=int)
    n.add_argument("--authors", nargs="*", default=[])
    n.add_argument("--out", required=True, help="the document file, e.g. research/<id>/docs/literature/LIT-0001.v1.md")
    n.add_argument("--cache", help="PDF cache directory, e.g. research/<id>/cache/literature")
    f = sub.add_parser("fetch", help="download an arXiv PDF into the cache")
    f.add_argument("--arxiv-id", required=True)
    f.add_argument("--cache", required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "search":
            sources = [x for item in args.sources for x in item.split(",") if x]
            errors: list[dict[str, str]] = []
            records = search(args.query, sources=sources, limit=args.limit, errors=errors)
            result: Any = {"records": records, "errors": errors}
        elif args.cmd == "verify":
            record = _record("cli", title=args.title, arxiv_id=args.arxiv_id, doi=args.doi, year=args.year)
            result = verify(record, threshold=args.threshold)
        elif args.cmd == "note":
            result = write_note(_record("cli", title=args.title, arxiv_id=args.arxiv_id, doi=args.doi,
                                        year=args.year, authors=args.authors), Path(args.out), args.cache)
        else:
            result = download_pdf(args.arxiv_id, args.cache)
    except (LiteratureError, FetchError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

import sys as _sys
_sys.path = [p for p in _sys.path if not p.endswith("/ingestion")]
_sys.path.insert(0, "/opt/scripts")
_sys.path.insert(0, "/opt/projects/regpulse/api")
"""
run_ingest.py — F5b: Phase F ingestion orchestrator
Location: /opt/scripts/ingestion/run_ingest.py

Wraps Phase C ingest_document() for PDF items.
Uses ingest_html_document() for HTML items (Fix F1).
Applies all Phase F gap fixes: F1 F2 F3 F4 F6.
Exit: 0 on success, 1 on error
"""

import os, sys, json, argparse

# Parse args before any risky imports so doc_id is available for error reporting
# even if the script crashes at import time.
_arg_parser = argparse.ArgumentParser()
_arg_parser.add_argument("--doc-id", required=True)
_arg_parser.add_argument("--phase", default="live", choices=["live", "backfill", "manual"])
_arg_parser.add_argument("--run-id", default=None)
_early_args, _ = _arg_parser.parse_known_args()
_DOC_ID = _early_args.doc_id


def _mark_error(doc_id: str, error: str) -> None:
    """Last-resort: mark a document as error using only psycopg2.

    Called from the top-level guard so it must not import anything that
    may itself be broken. Silently swallows its own failures — we've done
    our best at that point.
    """
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.environ.get("POSTGRES_HOST", "postgres"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            dbname=os.environ.get("POSTGRES_DB", "knowledge_base"),
            user=os.environ.get("POSTGRES_USER", "postgres"),
            password=os.environ.get("POSTGRES_PASSWORD", ""),
            connect_timeout=10,
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            # GATE3b: write error state to ingestion_state
            cur.execute(
                "INSERT INTO ingestion_state (document_id, ingestion_status, ingestion_error, updated_at) "
                "VALUES (%s, 'error', %s, NOW()) "
                "ON CONFLICT (document_id) DO UPDATE SET "
                "ingestion_status = 'error', "
                "ingestion_error  = EXCLUDED.ingestion_error, "
                "updated_at       = NOW()",
                (doc_id, error[:500]),
            )
        conn.close()
    except Exception:
        pass


try:
    import time, hashlib, uuid, requests, psycopg2, shutil
    from datetime import datetime, timezone
    from pathlib import Path
    from qdrant_client.models import PointStruct

    from lib.trace_emitter import start_document_span
    from ingestion.ingest import ingest_document, supersede_by_family_id
    from ingestion.registry import pg_conn
    from ingestion.embedding import embed
    from ingestion.qdrant_client import get_client
except SystemExit:
    raise
except Exception as _import_err:
    _mark_error(_DOC_ID, f"Import error: {type(_import_err).__name__}: {_import_err}")
    sys.stderr.write(json.dumps({
        "status": "error", "doc_id": _DOC_ID,
        "detail": f"Import error: {type(_import_err).__name__}: {_import_err}",
    }))
    sys.exit(1)

ARCHIVE_ROOT      = Path(os.environ.get("ARCHIVE_ROOT", "/mnt/data/regulatory_archive"))
OLLAMA_URL        = os.environ.get("OLLAMA_URL", "http://ollama:11434")
QDRANT_URL        = os.environ.get("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "knowledge_base")
CLASSIFY_MODEL    = os.environ.get("CLASSIFY_MODEL", "phi4:14b-q8_0")
PROMPT_PATH       = os.environ.get("CLASSIFIER_PROMPT_PATH",
                                   "/opt/scripts/rss/prompts/classifier_prompt_v1.txt")
CHUNKER_VERSION   = os.environ.get("CHUNKER_VERSION", "f-phase-v1")
CONF_THRESHOLD    = 0.70
EMBED_MODEL       = "mxbai-embed-large"

CANONICAL_DOC_TYPES = {
    "guidance", "reflection_paper", "press_release",
    "safety_alert", "drug_approval", "news_item", "other",
}
DOC_TYPES_ALLOWED = CANONICAL_DOC_TYPES  # backward-compat alias


def validate_doc_type(doc_type: str) -> str:
    """Structural guard — reject any non-canonical doc_type, fall back to 'other'."""
    if doc_type not in CANONICAL_DOC_TYPES:
        import sys as _s
        _s.stderr.write(f"[classify] Non-canonical doc_type '{doc_type}' — falling back to 'other'\n")
        return "other"
    return doc_type
JURISDICTION_MAP = {"FDA":"US","EMA":"EU","ICH":"Global"}

REGULATORY_DOMAIN_MAP = {
    ("fda_drugs","drug_approval"):       ["GMP","Pharmacovigilance"],
    ("fda_drugs","safety_alert"):        ["Pharmacovigilance","GMP"],
    ("fda_drugs","guidance"):            ["GMP","CSV"],
    ("fda_drugs","news_item"):           ["GMP"],
    ("fda_drugs","other"):               ["GMP"],
    ("fda_press_releases","press_release"): ["Regulatory"],
    ("fda_press_releases","drug_approval"): ["GMP","Pharmacovigilance"],
    ("fda_press_releases","guidance"):      ["GMP"],
    ("fda_press_releases","safety_alert"):  ["Pharmacovigilance"],
    ("fda_press_releases","news_item"):     ["Regulatory"],
    ("fda_press_releases","other"):         ["Regulatory"],
    ("ema_sci_guidelines","guidance"):         ["GMP","CSV"],
    ("ema_sci_guidelines","reflection_paper"): ["GMP","AI"],
    ("ema_sci_guidelines","safety_alert"):     ["Pharmacovigilance"],
    ("ema_sci_guidelines","news_item"):        ["GMP"],
    ("ema_sci_guidelines","other"):            ["GMP"],
    ("ema_reg_guidance","guidance"):      ["GMP","Regulatory"],
    ("ema_reg_guidance","safety_alert"):  ["Pharmacovigilance"],
    ("ema_reg_guidance","other"):         ["GMP","Regulatory"],
    ("ich_guidelines","guidance"):        ["GMP","CSV"],
    ("ich_guidelines","other"):           ["GMP"],
}
FEED_DOMAIN_FALLBACK = {
    "fda_drugs":"GMP","fda_press_releases":"Regulatory",
    "ema_sci_guidelines":"GMP","ema_reg_guidance":"GMP","ich_guidelines":"GMP",
}
DOC_TYPE_TO_DOCUMENT_TYPE = {
    "guidance":"guidance","reflection_paper":"reflection-paper",
    "press_release":"press-release","safety_alert":"safety-communication",
    "drug_approval":"regulatory-decision","news_item":"news","other":"other",
}


def get_regulatory_domain(feed_id: str, doc_type: str) -> list:
    return REGULATORY_DOMAIN_MAP.get((feed_id, doc_type),
           [FEED_DOMAIN_FALLBACK.get(feed_id, "Regulatory")])

def get_document_type(doc_type: str) -> str:
    return DOC_TYPE_TO_DOCUMENT_TYPE.get(doc_type, "other")

def get_archive_dir(doc_id: str, force: bool = False) -> Path:
    with pg_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT archive_path, ingestion_status FROM document_registry_ext "
                      "WHERE document_id = %s", (doc_id,))
            row = c.fetchone()
    if not row:
        raise ValueError(f"Not in registry: {doc_id}")
    if not force and row[1] in ("success", "indexed"):
        raise SystemExit(json.dumps({"status":"ok","doc_id":doc_id,"note":"already ingested"}))
    if not row[0]:
        raise ValueError(f"archive_path is NULL for {doc_id}")
    # Rewrite host-side archive root to container mount path.
    # archive_path is stored as /mnt/data/regulatory_archive/... but inside Docker
    # the archive is mounted at ARCHIVE_ROOT (e.g. /archive).
    HOST_ARCHIVE_ROOT = "/mnt/data/regulatory_archive"
    p = row[0]
    if p.startswith(HOST_ARCHIVE_ROOT) and str(ARCHIVE_ROOT) != HOST_ARCHIVE_ROOT:
        p = str(ARCHIVE_ROOT) + p[len(HOST_ARCHIVE_ROOT):]
    return Path(p)


def redownload_source(archive_dir: Path, doc_id: str, mode: str) -> bool:
    """Fetch a fresh copy of the source file.

    mode='check'  — download to temp, compare SHA-256 with stored hash.
                    Replace archive file only if changed. Returns True if changed.
    mode='force'  — always delete existing file and replace with fresh download.
                    Returns True always.

    In both modes ingestion continues; this only controls the source file.
    """
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin as _urljoin

    meta_path = archive_dir / "metadata.json"
    if meta_path.exists():
        with open(meta_path) as f:
            metadata = json.load(f)
    else:
        # Bootstrap metadata from DB when archive dir was wiped or never populated
        metadata = {}
        with pg_conn() as conn:
            with conn.cursor() as c:
                c.execute(
                    "SELECT metadata_json, source_url FROM document_registry WHERE document_id = %s",
                    (doc_id,),
                )
                row = c.fetchone()
                if row:
                    db_meta = row[0] or {}
                    if isinstance(db_meta, str):
                        import json as _json
                        db_meta = _json.loads(db_meta)
                    metadata = db_meta.copy()
                    if not metadata.get("source_url") and row[1]:
                        metadata["source_url"] = row[1]
        if metadata:
            with open(meta_path, "w") as fh:
                json.dump(metadata, fh)

    # pdf_url is the direct PDF download link (e.g. database.ich.org/.../*.pdf).
    # source_url is the browse/landing page — often HTML, not the actual file.
    # Always prefer pdf_url when available.
    source_url = metadata.get("pdf_url") or metadata.get("source_url", "")
    if not source_url:
        with pg_conn() as conn:
            with conn.cursor() as c:
                c.execute("SELECT metadata_json->>'pdf_url', source_url FROM document_registry WHERE document_id = %s", (doc_id,))
                row = c.fetchone()
                if row:
                    source_url = row[0] or row[1] or ""
    if not source_url:
        raise ValueError(f"No source_url for {doc_id} — cannot re-download")

    stored_hash = ""
    if mode == "check":
        sha_file = archive_dir / "source.sha256"
        if sha_file.exists():
            stored_hash = sha_file.read_text(encoding="utf-8").strip()

    req_headers = {"User-Agent": "Mozilla/5.0 (compatible; regpulse/1.0)"}
    dest_tmp = archive_dir / "_download.tmp"

    def _stream_to_file(url: str, dest: Path) -> tuple:
        """Download url → dest, return (sha256_hex, is_pdf)."""
        r = requests.get(url, headers=req_headers, timeout=120, stream=True)
        r.raise_for_status()
        ct = r.headers.get("content-type", "").lower()
        is_pdf = "pdf" in ct or url.lower().split("?")[0].endswith(".pdf")
        h = hashlib.sha256()
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(8192):
                fh.write(chunk)
                h.update(chunk)
        return h.hexdigest(), is_pdf

    try:
        new_hash, is_pdf = _stream_to_file(source_url, dest_tmp)

        # HTML response — scrape for PDF link. Always attempt when force-redownloading
        # or when the stored format is not PDF (covers not_viable HTML docs where
        # the upstream page may now have a PDF link that wasn't there originally).
        if not is_pdf:
            with open(dest_tmp, "rb") as fh:
                html_bytes = fh.read(2_000_000)
            soup = BeautifulSoup(html_bytes, "html.parser")
            authority = metadata.get("authority", "")
            pdf_candidates = [
                _urljoin(source_url, a["href"])
                for a in soup.find_all("a", href=True)
                if _urljoin(source_url, a["href"]).lower().split("?")[0].endswith(".pdf")
            ]
            if authority.upper() == "EMA" and len(pdf_candidates) > 1:
                pdf_url = max(pdf_candidates, key=len)
            elif pdf_candidates:
                pdf_url = pdf_candidates[0]
            else:
                pdf_url = None

            if pdf_url:
                new_hash, is_pdf = _stream_to_file(pdf_url, dest_tmp)
                metadata["source_url"] = pdf_url
                metadata["source_file_format"] = "pdf"
                with open(meta_path, "w") as fh:
                    json.dump(metadata, fh)

        # check mode: unchanged — no replacement needed
        if mode == "check" and new_hash == stored_hash:
            print(f"  Source unchanged ({new_hash[:8]}…) — using existing file", file=sys.stderr)
            return False

        # Replace archive source file
        dest_name = "source.pdf" if is_pdf else "source.html"
        for fname in ("source.pdf", "source.html", "source.sha256"):
            p = archive_dir / fname
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        dest_tmp.rename(archive_dir / dest_name)
        (archive_dir / "source.sha256").write_text(new_hash, encoding="utf-8")

        # Keep metadata.json in sync with the actual saved file format so that
        # run_ingest_v2() routes to the correct ingestion path after redownload.
        new_fmt = "pdf" if is_pdf else "html"
        if metadata.get("source_file_format") != new_fmt:
            metadata["source_file_format"] = new_fmt
            with open(meta_path, "w") as fh:
                json.dump(metadata, fh)

        with pg_conn() as conn:
            conn.autocommit = True
            with conn.cursor() as c:
                c.execute(
                    "UPDATE document_registry "
                    "SET source_hash = %s, source_fetched_at = NOW(), updated_at = NOW() "
                    "WHERE document_id = %s",
                    (new_hash, doc_id),
                )

        verb = "Re-downloaded" if mode == "force" else "Updated"
        print(f"  {verb}: {dest_name} ({new_hash[:8]}…)", file=sys.stderr)
        return True

    finally:
        if dest_tmp.exists():
            try:
                dest_tmp.unlink()
            except Exception:
                pass

import re as _re
_DATE_PAT = _re.compile(
    r'\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|'
    r'September|October|November|December)\s+\d{4})\b'
    r'|\b((?:January|February|March|April|May|June|July|August|'
    r'September|October|November|December)\s+\d{1,2},?\s+\d{4})\b'
    r'|Document\s+Date:\s*(\d{1,2}\s+\w+\s+\d{4})'
    r'|[Ee]ndorsed[^.]*?(\d{1,2}\s+\w+\s+\d{4})',
    _re.IGNORECASE
)
_URL_DATE_PAT = _re.compile(r'[_-](\d{4})[_-](\d{2})(\d{2})?(?:\.[a-z]+)?(?:$|[^0-9])', _re.IGNORECASE)

def _parse_pub_date(val):
    if not val:
        return None
    try:
        from dateutil import parser as dp
        from datetime import datetime
        return dp.parse(str(val), default=datetime(1900, 1, 1)).date()
    except Exception:
        return None

def _date_from_url(url):
    if not url:
        return None
    m = _URL_DATE_PAT.search(url)
    if not m:
        return None
    yyyy, mm, dd = m.group(1), m.group(2), m.group(3) or '01'
    try:
        from datetime import date
        return date(int(yyyy), int(mm), int(dd))
    except ValueError:
        return None

def _date_from_chunks(chunks):
    """Scan chunk texts for the first unambiguous publication date mention."""
    from datetime import datetime
    try:
        from dateutil import parser as dp
    except ImportError:
        return None
    for chunk in chunks:
        text = chunk.get("chunk_text") or chunk.get("text") or ""
        for m in _DATE_PAT.finditer(text):
            raw = next(g for g in m.groups() if g)
            try:
                return dp.parse(raw, default=datetime(1900, 1, 1)).date()
            except Exception:
                continue
    return None

def write_meta_json(doc_id: str, meta: dict):
    pub_date = (
        _parse_pub_date(meta.get("publication_date") or meta.get("pub_date"))
        or _date_from_url(meta.get("source_url", ""))
        or None
    )
    with pg_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                "UPDATE document_registry SET metadata_json = %s, "
                "publication_date = COALESCE(%s, publication_date) "
                "WHERE document_id = %s",
                (json.dumps(meta), pub_date, doc_id)
            )

def _backfill_pub_date_from_chunks(doc_id: str, archive_dir: Path):
    """If publication_date is still NULL after metadata write, scan chunk JSONL for dates."""
    with pg_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT publication_date FROM document_registry WHERE document_id = %s", (doc_id,))
            row = c.fetchone()
    if not row or row[0] is not None:
        return  # already set, nothing to do

    chunks_dir = archive_dir / "chunks"
    if not chunks_dir.exists():
        return
    jsonl_files = sorted(chunks_dir.glob("chunks_*.jsonl"))
    if not jsonl_files:
        return

    chunks = []
    try:
        for line in jsonl_files[-1].read_text(encoding="utf-8").splitlines():
            if line.strip():
                chunks.append(json.loads(line))
    except Exception:
        return

    pub_date = _date_from_chunks(chunks)
    if not pub_date:
        return

    with pg_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                "UPDATE document_registry SET publication_date = %s WHERE document_id = %s AND publication_date IS NULL",
                (pub_date, doc_id)
            )
    print(f"  publication_date backfilled from chunk text: {pub_date}", file=sys.stderr)

def update_registry_phase_f(doc_id: str, cls: dict, run_id: str = None):
    with pg_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                "UPDATE document_registry SET doc_type=%s, classifier_confidence=%s, "
                "classified_by=%s, doc_type_classified_at=NOW(), updated_at=NOW() "
                "WHERE document_id=%s",
                (cls["doc_type"], cls["classifier_confidence"], "llm", doc_id)
            )
            if run_id:
                c.execute(
                    "UPDATE ingestion_state SET run_id = %s::uuid, updated_at = NOW() "
                    "WHERE document_id = %s",
                    (run_id, doc_id),
                )

def build_rss_meta(doc_id: str, archive_dir: Path, metadata: dict, cls: dict) -> dict:
    # Support both old key names (bulk reingestion) and new key names (fetch_feed.py incremental)
    ct   = metadata.get("source_file_format") or metadata.get("content_type","pdf")
    ext  = ".pdf" if ct == "pdf" else ".html"
    auth = metadata.get("issuing_body","") or metadata.get("authority","")
    feed_id = metadata.get("feed_source","") or metadata.get("feed_id","")
    pub_date = metadata.get("publication_date","") or metadata.get("pub_date","")
    if not pub_date:
        _d = _date_from_url(metadata.get("source_url",""))
        if _d:
            pub_date = _d.isoformat()
    return {
        "document_id":        doc_id,
        "document_title":     metadata.get("document_title","") or metadata.get("title",""),
        "document_class":     "regulatory",
        "document_type":      get_document_type(cls["doc_type"]),
        "document_status":    metadata.get("chunk_status","active") == "superseded" and "superseded" or "active",
        "document_version":   metadata.get("document_version","") or metadata.get("version","") or "",
        "document_family_id": metadata.get("document_family_id",""),
        "superseded_by":      metadata.get("superseded_by",""),
        "language":           "en",
        "source_local_path":  metadata.get("source_local_path") or str(archive_dir / f"source{ext}"),
        "source_hash":        (archive_dir / "source.sha256").read_text(encoding="utf-8").strip()
                              if (archive_dir / "source.sha256").exists()
                              else metadata.get("source_hash","") or metadata.get("sha256",""),
        "source_file_format": ct,
        "publication_date":   pub_date,
        "effective_date": "", "adoption_date": "",
        "issuing_body":       auth,
        "jurisdiction":       JURISDICTION_MAP.get(auth.upper(),""),
        "regulatory_domain":  get_regulatory_domain(feed_id, cls["doc_type"]),
        "clause_id_prefix":   "",
        "source_url":         metadata.get("pdf_url") or metadata.get("source_url",""),
        "source_fetched_at":  metadata.get("source_fetched_at","") or metadata.get("archived_at",""),
        "feed_source":        feed_id,
        "feed_item_guid":     metadata.get("feed_item_guid",""),
        "company_id":         None,
        "archive_path":       str(archive_dir),
        "rss_body":           metadata.get("rss_body",""),
    }

def classify(title: str, excerpt: str, feed_id: str, authority: str) -> dict:
    with open(PROMPT_PATH) as f:
        pr = json.load(f)
    content = pr["user_template"].format(
        feed_id=feed_id, authority=authority,
        title=title, text_excerpt=excerpt[:500]
    )
    payload = dict(model=CLASSIFY_MODEL, system=pr["system_prompt"],
                   prompt=content, stream=False, options={"temperature": 0.0})
    def _call():
        r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=300)
        raw = r.json().get("response","")
        clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(clean)
    for attempt in range(2):
        try:
            result = _call(); break
        except Exception:
            if attempt == 1:
                return {"doc_type":"other","classifier_confidence":0.0,
                        "classified_by":"llm",
                        "doc_type_classified_at":datetime.now(timezone.utc).isoformat()}
            time.sleep(2)
    dt = result.get("doc_type","other")
    cf = float(result.get("confidence",0.0))
    dt = validate_doc_type(dt)
    if cf < CONF_THRESHOLD:
        dt = "other"
    return {"doc_type":dt,"classifier_confidence":cf,"classified_by":"llm",
            "doc_type_classified_at":datetime.now(timezone.utc).isoformat()}

def make_chunk_id(doc_id: str, chunk_index: int) -> str:
    key = f"{doc_id}|1.0|{chunk_index}|{CHUNKER_VERSION}"
    return str(uuid.UUID(hashlib.md5(key.encode()).hexdigest()))

def chunk_html_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list:
    chunks, start, idx = [], 0, 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        t   = text[start:end].strip()
        if t:
            chunks.append({"text":t,"chunk_index":idx,
                           "char_offset_start":start,"char_offset_end":end})
            idx += 1
        start = end - overlap if end < len(text) else end
    return chunks


def _resolve_source_path(archive_dir: Path, meta: dict) -> Path:
    """Resolve the source file to read for HTML ingestion.

    Prefers source_local_path from metadata (authoritative), falls back to
    source.html then source.pdf (detecting HTML content in PDF-named files).
    If source.html is missing but source.pdf exists, returns None to signal
    the caller should skip HTML ingestion (file was re-downloaded as PDF).
    """
    local_path = meta.get("source_local_path")
    if local_path:
        p = Path(local_path)
        if p.exists():
            return p
    source = archive_dir / "source.html"
    if source.exists():
        return source
    pdf_source = archive_dir / "source.pdf"
    if pdf_source.exists():
        try:
            header = pdf_source.read_text(encoding="utf-8")[:500].strip().lower()
            if header and any(tag in header for tag in ("<!doctype", "<html", "<head", "<body")):
                return pdf_source
        except Exception:
            pass
        # source.pdf exists but is a real PDF (not HTML-masquerading).
        # source.html was replaced by redownload — signal caller to skip.
        return None
    return None


def _is_structured_xml(filepath: Path) -> bool:
    """Detect eCFR XML / structured regulatory content needing Docling parsing.

    Simple character chunking (ingest_html_document) works for prose HTML
    pages but produces low-quality chunks for XML with nested tags.
    """
    try:
        head = filepath.read_text(encoding="utf-8")[:500].strip().lower()
        return head.startswith("<?xml") or "<div5" in head or "<div8" in head
    except Exception:
        return False

def ingest_html_document(doc_id: str, archive_dir: Path, meta: dict,
                          cls: dict, feed_id: str, phase: str,
                          trace_id: str = "") -> dict:
    doc_span = None
    if trace_id:
        doc_span = start_document_span(
            trace_id, doc_id=doc_id,
            source_url=meta.get("source_url", ""),
        )
    try:
        import sys as _sys
        _ingestion_dir = str(Path(__file__).parent)
        if _ingestion_dir not in _sys.path:
            _sys.path.insert(0, _ingestion_dir)
        from html_cleaner import clean_html_content, assess_cleaned_content
        source = _resolve_source_path(archive_dir, meta)
        if source is None:
            return {
                "status": "skipped",
                "doc_id": doc_id,
                "chunk_count": 0,
                "detail": "No readable HTML source — file was re-downloaded as PDF",
            }
        raw_text = source.read_text(encoding="utf-8").strip()
        if not raw_text:
            raise ValueError(f"source.html is empty: {source}")
        text = clean_html_content(raw_text)
        viability = assess_cleaned_content(text)
        if not viability["viable"]:
            # not_viable documents are NOT retried automatically.
            # To retry: manually set ingestion_status = 'pending' after source changes.
            from ingestion.registry import mark_document_not_viable
            mark_document_not_viable(doc_id, viability["reason"])
            return {
                "status": "not_viable",
                "doc_id": doc_id,
                "detail": f"Not viable: {viability['reason']} (raw={len(raw_text)} chars, cleaned={len(text)} chars)",
            }
        now       = datetime.now(timezone.utc).isoformat()
        authority = meta.get("issuing_body","")
        chunks    = chunk_html_text(text)
        points    = []
        for chunk in chunks:
            chunk_id = make_chunk_id(doc_id, chunk["chunk_index"])
            vector   = embed(chunk["text"])
            payload  = {
                "chunk_id":chunk_id,"chunk_index":chunk["chunk_index"],
                "chunk_text":chunk["text"],
                "chunk_token_count":len(chunk["text"].split()),
                "char_offset_start":chunk["char_offset_start"],
                "char_offset_end":chunk["char_offset_end"],
                "page_no":1,"bbox":None,"section_path":[],"clause_id":"",
                "cross_refs":[],"content_type":"text",
                "embedding_model":EMBED_MODEL,"embedding_dim":1024,
                "chunker_version":CHUNKER_VERSION,"chunked_at":now,
                "chunk_status": meta.get("document_status","final"),
                "trace_id": trace_id,
                "document_id":doc_id,
                "document_title":meta.get("document_title",""),
                "document_class":meta.get("document_class","regulatory"),
                "document_type":meta.get("document_type","other"),
                "document_status":meta.get("document_status","final"),
                "document_version":meta.get("document_version",""),
                "document_family_id":meta.get("document_family_id",""),
                "language":"en",
                "source_local_path":str(source),
                "source_hash":meta.get("source_hash",""),
                "source_file_format":"html",
                "publication_date":meta.get("publication_date",""),
                "effective_date":"","adoption_date":"",
                "issuing_body":authority,
                "jurisdiction":JURISDICTION_MAP.get(authority.upper(),""),
                "regulatory_domain":meta.get("regulatory_domain",[]),
                "clause_id_prefix":"",
                "source_url":meta.get("source_url",""),
                "source_fetched_at":meta.get("source_fetched_at",now),
                "feed_source":feed_id,
                "feed_item_guid":meta.get("feed_item_guid",""),
                "company_id":None,
                "doc_type":cls["doc_type"],
                "classifier_confidence":cls["classifier_confidence"],
                "classified_by":"llm",
                "doc_type_classified_at":now,
                "phase":phase,
            }
            points.append(PointStruct(id=chunk_id, vector=vector, payload=payload))
        get_client().upsert(collection_name=QDRANT_COLLECTION, points=points)
        chunks_dir = archive_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = chunks_dir / f"chunks_{CHUNKER_VERSION}.jsonl"
        lines = "\n".join(json.dumps(p.payload) for p in points)
        jsonl_path.write_text(lines, encoding="utf-8")
        with pg_conn() as conn:
            with conn.cursor() as c:
                # GATE3b: classification columns stay in document_registry (identity)
                c.execute(
                    "UPDATE document_registry SET "
                    "doc_type=%s, classifier_confidence=%s, classified_by=%s, "
                    "doc_type_classified_at=NOW(), updated_at=NOW() "
                    "WHERE document_id=%s",
                    (cls["doc_type"], cls["classifier_confidence"], "llm", doc_id)
                )
                # GATE3b: ingestion state → ingestion_state
                c.execute(
                    "INSERT INTO ingestion_state "
                    "(document_id, ingestion_status, chunk_count, last_indexed_at, "
                    " chunker_version, run_id, updated_at) "
                    "VALUES (%s, 'indexed', %s, NOW(), %s, %s, NOW()) "
                    "ON CONFLICT (document_id) DO UPDATE SET "
                    "ingestion_status = 'indexed', "
                    "chunk_count      = EXCLUDED.chunk_count, "
                    "last_indexed_at  = EXCLUDED.last_indexed_at, "
                    "chunker_version  = EXCLUDED.chunker_version, "
                    "run_id           = EXCLUDED.run_id, "
                    "ingestion_error  = NULL, "
                    "updated_at       = NOW()",
                    (doc_id, len(chunks), CHUNKER_VERSION, trace_id or None)
                )

        if doc_span:
            doc_span.finalize(status="success", chunk_count=len(chunks),
                              embedding_model=EMBED_MODEL)
        return {"doc_id":doc_id,"chunks":len(chunks)}

    except Exception as e:
        err_msg = f'{type(e).__name__}: {str(e)[:400]}'
        try:
            with pg_conn() as conn:
                with conn.cursor() as c:
                    # GATE3b: write error state to ingestion_state
                    c.execute(
                        "INSERT INTO ingestion_state (document_id, ingestion_status, ingestion_error, updated_at) "
                        "VALUES (%s, 'error', %s, NOW()) "
                        "ON CONFLICT (document_id) DO UPDATE SET "
                        "ingestion_status = 'error', "
                        "ingestion_error  = EXCLUDED.ingestion_error, "
                        "updated_at       = NOW()",
                        (doc_id, err_msg),
                    )
        except Exception:
            pass
        if doc_span:
            doc_span.finalize(status="failed", chunk_count=0,
                              failure_reason=err_msg[:200])
        raise

def write_phase_f_archive(archive_dir: Path, doc_id: str,
                           cls: dict, feed_id: str, phase: str) -> str:
    record = {
        "doc_id":doc_id,
        "doc_type":cls["doc_type"],
        "classifier_confidence":cls["classifier_confidence"],
        "classified_by":cls["classified_by"],
        "doc_type_classified_at":cls.get("doc_type_classified_at",""),
        "feed_source":feed_id,
        "phase":phase,
        "written_at":datetime.now(timezone.utc).isoformat(),
    }
    out = archive_dir / "phase_f_fields.json"
    # Remove existing file first — it may be root-owned from a Docker ingestion.
    # The directory is writable, so unlink works; writing directly fails on root-owned files.
    try:
        out.unlink()
    except FileNotFoundError:
        pass
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return str(out)

def post_inject(doc_id: str, cls: dict, meta: dict, feed_id: str, phase: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    r = requests.post(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/scroll",
        json={"filter":{"must":[{"key":"document_id","match":{"value":doc_id}}]},
              "limit":10000,"with_payload":False,"with_vectors":False},
        timeout=30
    )
    r.raise_for_status()
    ids = [p["id"] for p in r.json().get("result",{}).get("points",[])]
    if not ids:
        return 0
    requests.post(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/payload",
        json={"payload":{
            "doc_type":cls["doc_type"],
            "classifier_confidence":cls["classifier_confidence"],
            "classified_by":"llm","doc_type_classified_at":now,
            "feed_source":feed_id,"phase":phase,
            "regulatory_domain":meta["regulatory_domain"],
            "document_type":meta["document_type"],
            "document_family_id":meta.get("document_family_id",""),
        },"points":ids},
        timeout=60
    ).raise_for_status()
    return len(ids)

def _is_not_viable(doc_id: str) -> bool:
    """Check if document is in not_viable state."""
    try:
        with pg_conn() as conn:
            with conn.cursor() as c:
                c.execute(
                    "SELECT 1 FROM ingestion_state "
                    "WHERE document_id = %s AND ingestion_status = 'not_viable'",
                    (doc_id,)
                )
                return c.fetchone() is not None
    except Exception:
        return False


def run_ingest_v2(doc_id: str, phase: str = "live", run_id: str = None,
                  redownload: str = "none") -> dict:
    force = redownload in ("check", "force")
    archive_dir = get_archive_dir(doc_id, force=force)

    # If archive dir or metadata.json is missing, force a redownload regardless
    # of the requested redownload mode — the file was never fetched.
    if not archive_dir.exists() or not (archive_dir / "metadata.json").exists():
        archive_dir.mkdir(parents=True, exist_ok=True)
        redownload_source(archive_dir, doc_id, mode="force")
    elif redownload in ("check", "force"):
        redownload_source(archive_dir, doc_id, mode=redownload)
    elif _is_not_viable(doc_id):
        # not_viable docs: auto-force redownload to re-scrape the source URL.
        # The upstream page may have changed since the original fetch (e.g. EMA
        # added PDF links). Without this, a simple reingest will re-read the old
        # saved HTML file and fail identically.
        print(f"  not_viable doc {doc_id}: auto-forcing redownload to re-scrape source",
              file=sys.stderr)
        redownload_source(archive_dir, doc_id, mode="force")
    with open(archive_dir / "metadata.json") as f:
        metadata = json.load(f)
    feed_id   = metadata.get("feed_id","")
    authority = metadata.get("authority","")
    title     = metadata.get("title","")
    ct        = metadata.get("source_file_format") or metadata.get("content_type", "pdf")
    excerpt   = metadata.get("rss_body","").strip() or title

    # Auto-detect run_id from recent run_log entry when not explicitly provided.
    # Use 24h window: fetch_feed.py creates the run_log row at schedule time (09:00)
    # but n8n may run individual doc ingestion hours later in the same day.
    if not run_id:
        try:
            with pg_conn() as conn:
                with conn.cursor() as c:
                    # First try: matching feed_source (scheduled runs via n8n)
                    c.execute(
                        "SELECT run_id FROM run_log "
                        "WHERE feed_source = %s "
                        "AND triggered_at > NOW() - INTERVAL '24 hours' "
                        "ORDER BY triggered_at DESC LIMIT 1",
                        (feed_id,)
                    )
                    row = c.fetchone()
                    if row:
                        run_id = row[0]
                    else:
                        # Second try: manual trigger (feed_source IS NULL, trigger_source='manual')
                        c.execute(
                            "SELECT run_id FROM run_log "
                            "WHERE feed_source IS NULL "
                            "AND trigger_source = 'manual' "
                            "AND triggered_at > NOW() - INTERVAL '24 hours' "
                            "ORDER BY triggered_at DESC LIMIT 1"
                        )
                        row = c.fetchone()
                        if row:
                            run_id = row[0]
        except Exception:
            pass

    cls       = classify(title, excerpt, feed_id, authority)
    meta      = build_rss_meta(doc_id, archive_dir, metadata, cls)
    write_meta_json(doc_id, meta)

    # Clean stale chunk dir from previous runs (may be root-owned from Docker).
    # Do NOT delete extracted/ — it contains the Docling cache (docling_output.json,
    # extracted_text.txt) which avoids re-submitting large PDFs to Docling on retry.
    chunks_dir = archive_dir / "chunks"
    if chunks_dir.exists():
        try:
            shutil.rmtree(chunks_dir)
        except PermissionError:
            print(f"  WARNING: Cannot remove stale chunks/ (root-owned). "
                  f"Run: docker exec regpulse-api rm -rf /archive/.../"
                  f"{archive_dir.name}/chunks", file=sys.stderr)

    # Determine ingestion path: simple HTML chunking vs Docling parsing.
    # Structured XML/HTML (eCFR, ICH) needs Docling for heading extraction and
    # proper clause_id assignment. Prose HTML pages use fast character chunking.
    use_docling = ct != "html"
    if ct == "html":
        try:
            source_path = _resolve_source_path(archive_dir, metadata)
            if source_path is None:
                # source.html was replaced by source.pdf via redownload —
                # switch to Docling path for the new PDF
                use_docling = True
            else:
                # Guard: reject binary files (XLSX/ZIP, PDF) masquerading as HTML.
                with open(source_path, "rb") as _f:
                    _magic = _f.read(4)
                if _magic[:2] == b"PK" or _magic[:4] == b"%PDF":
                    ext = "xlsx/zip" if _magic[:2] == b"PK" else "pdf"
                    return {
                        "status": "skipped",
                        "doc_id": doc_id,
                        "chunk_count": 0,
                        "detail": f"Binary {ext} file — not ingestible as HTML",
                    }
                if _is_structured_xml(source_path):
                    use_docling = True
        except FileNotFoundError:
            pass

    if not use_docling:
        result      = ingest_html_document(doc_id, archive_dir, meta, cls, feed_id, phase,
                                           trace_id=run_id or "")
        if result.get("status") == "not_viable":
            return result
        chunk_count = result["chunks"]
        family_id = meta.get("document_family_id", "")
        if family_id:
            n_sup = supersede_by_family_id(doc_id, family_id, CHUNKER_VERSION)
            if n_sup:
                print(f"  Family supersede: {n_sup} chunks (family={family_id!r})", file=sys.stderr)
    else:
        result      = ingest_document(doc_id, chunker_version=CHUNKER_VERSION,
                                      trace_id=run_id or "")
        chunk_count = result["chunks"]
        n = post_inject(doc_id, cls, meta, feed_id, phase)
        print(f"  Post-inject: {n} points", file=sys.stderr)
        family_id = meta.get("document_family_id", "")
        if family_id:
            n_sup = supersede_by_family_id(doc_id, family_id, CHUNKER_VERSION)
            if n_sup:
                print(f"  Family supersede: {n_sup} chunks (family={family_id!r})", file=sys.stderr)
    _backfill_pub_date_from_chunks(doc_id, archive_dir)
    write_phase_f_archive(archive_dir, doc_id, cls, feed_id, phase)
    update_registry_phase_f(doc_id, cls, run_id)
    return {
        "status":"ok","doc_id":doc_id,"chunk_count":chunk_count,
        "doc_type":cls["doc_type"],
        "classifier_confidence":cls["classifier_confidence"],
        "regulatory_domain":meta["regulatory_domain"],
        "document_type":meta["document_type"],
        "content_type":ct,"phase":phase,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--phase", default="live", choices=["live","backfill","manual"])
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--redownload", default="none", choices=["none","check","force"],
                        help="none=use disk file, check=re-download if changed, force=always re-download")
    args = parser.parse_args()

    # Redirect stdout → stderr for the duration of ingestion so that progress
    # print() calls from ingest.py/chunking.py/etc. don't corrupt the JSON output.
    _real_stdout = sys.stdout
    sys.stdout = sys.stderr

    try:
        result = run_ingest_v2(args.doc_id, args.phase, args.run_id, args.redownload)
    except BaseException as e:
        sys.stdout = _real_stdout
        detail = str(e) if str(e) else type(e).__name__
        _mark_error(args.doc_id, f'{type(e).__name__}: {detail[:400]}')
        sys.stdout.write(json.dumps({"status": "error", "doc_id": args.doc_id, "detail": detail}))
        sys.stdout.flush()
        sys.exit(1)

    sys.stdout = _real_stdout
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()

if __name__ == "__main__":
    main()

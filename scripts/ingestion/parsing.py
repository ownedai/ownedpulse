
# /opt/scripts/ingestion/parsing.py
import json
import time
import requests
from pathlib import Path
from .config import DOCLING_HOST


def parse_document(meta: dict) -> tuple:
    """Parse document via Docling REST API (async pattern).

    Returns:
        tuple (DoclingDocument, extracted_text: str)

    Writes to archive:
        extracted/docling_output.json
        extracted/extracted_text.txt
    """
    source_path = meta.get('source_pdf_path') or meta['source_local_path']
    archive = Path(meta['archive_path'])
    extracted = archive / 'extracted'
    extracted.mkdir(exist_ok=True, parents=True)

    # Use cached extraction if available (avoids re-submitting large PDFs on retry)
    cached_json = extracted / 'docling_output.json'
    cached_txt = extracted / 'extracted_text.txt'
    if cached_json.exists() and cached_txt.exists():
        from docling_core.types.doc import DoclingDocument
        doc = DoclingDocument.model_validate(json.loads(cached_json.read_text()))
        return doc, cached_txt.read_text()

    # Submit
    fmt = meta.get('source_file_format', 'pdf')
    # source_local_path can be stale after redownload changes format (html→pdf).
    # Fall back to the archive source file that actually exists on disk.
    if not Path(source_path).exists():
        fallback = archive / ("source.pdf" if fmt == "pdf" else "source.html")
        if fallback.exists():
            source_path = str(fallback)
    mime = 'text/html' if fmt in ('html', 'xml') else 'application/pdf'
    upload_name = 'source.html' if fmt in ('html', 'xml') else Path(source_path).name
    with open(source_path, 'rb') as f:
        r = requests.post(
            f'{DOCLING_HOST}/v1/convert/file/async',
            files={'files': (upload_name, f, mime)},
            data={'to_formats': 'json', 'do_ocr': 'false', 'include_images': 'false'},
            timeout=30,
        )
    r.raise_for_status()
    task_id = r.json()['task_id']

    # Poll — 300 × 3s = 15 min ceiling (192-page PDFs measured at ~8 min)
    for _ in range(300):
        r = requests.get(f'{DOCLING_HOST}/v1/status/poll/{task_id}')
        if r.json()['task_status'] in ('success', 'failure'):
            break
        time.sleep(3)
    else:
        raise TimeoutError(f'Docling timed out for {source_path}')

    # Retrieve
    result = requests.get(f'{DOCLING_HOST}/v1/result/{task_id}').json()
    if result.get('status') != 'success':
        raise RuntimeError(f'Docling failed: {result.get("errors")}')

    from docling_core.types.doc import DoclingDocument
    doc = DoclingDocument.model_validate(result['document']['json_content'])

    # Persist for replay
    (extracted / 'docling_output.json').write_text(
        json.dumps(result['document']['json_content'], indent=2)
    )
    extracted_text = doc.export_to_text()
    (extracted / 'extracted_text.txt').write_text(extracted_text)

    return doc, extracted_text

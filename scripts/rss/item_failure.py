"""Per-item failure line for run_pipeline.py."""


def describe_item_failure(doc_id: str, url: str, exc: BaseException) -> str:
    return f"Pipeline failed doc_id={doc_id} url={url} error={type(exc).__name__}: {exc}"

"""html_cleaner.py — strip navigation boilerplate from HTML before chunking."""

import re
from bs4 import BeautifulSoup

BOILERPLATE_TAGS = [
    "nav", "header", "footer", "aside",
    "script", "style", "noscript",
    "form", "input", "button", "select",
    "iframe", "svg", "figure",
]

BOILERPLATE_PATTERNS = [
    # Generic layout chrome
    r"nav", r"menu", r"sidebar", r"banner", r"breadcrumb",
    r"cookie", r"social", r"share", r"follow",
    r"search", r"header", r"footer", r"masthead",
    r"skip-link", r"sr-only", r"screen-reader",
    r"advertisement", r"promo", r"popup",
    # FDA-specific (USWDS / USA Design System classes)
    r"usa-banner", r"usa-nav", r"usa-footer",
    r"lcds-primary-nav", r"lcds-p",
    # EMA-specific
    r"ema-nav", r"ema-header", r"ema-footer",
]

_BOILERPLATE_RE = re.compile("|".join(BOILERPLATE_PATTERNS), re.IGNORECASE)


def clean_html_content(raw_html: str) -> str:
    """Extract substantive text from HTML, removing navigation, chrome, and boilerplate.

    Returns clean plain text suitable for chunking.
    """
    soup = BeautifulSoup(raw_html, "lxml")

    # Step 1: Remove boilerplate tags entirely
    for tag in BOILERPLATE_TAGS:
        for element in soup.find_all(tag):
            element.decompose()

    # Step 2: Remove elements with boilerplate class/id patterns
    for element in soup.find_all(True):
        if element.attrs is None:
            continue
        el_class = " ".join(element.get("class", []))
        el_id = element.get("id", "")
        if _BOILERPLATE_RE.search(el_class) or _BOILERPLATE_RE.search(el_id):
            element.decompose()

    # Step 3: Find the main content area
    main_content = (
        soup.find("main")
        or soup.find(id=re.compile(r"main|content|body", re.I))
        or soup.find(class_=re.compile(r"main|content|article|body", re.I))
        or soup.find("article")
        or soup.find("div", class_=re.compile(r"page|wrapper", re.I))
        or soup.body
        or soup
    )

    # Step 4: Extract clean text
    text = main_content.get_text(separator="\n", strip=True) if main_content else ""

    # Step 5: Clean up whitespace and filter trivial lines
    lines = text.split("\n")
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Keep: long lines, dates, all-caps headings, title-case headings
        if len(stripped) < 20:
            if re.match(r"^\d{1,4}[-/]\d{1,2}[-/]\d{1,4}$", stripped):
                clean_lines.append(stripped)
            elif stripped.isupper() or stripped.istitle():
                clean_lines.append(stripped)
            # else: drop — likely artefact
        else:
            clean_lines.append(stripped)

    # Remove consecutive duplicate lines (nav repetition artefact)
    deduped = []
    prev = None
    for line in clean_lines:
        if line != prev:
            deduped.append(line)
        prev = line

    return "\n".join(deduped)


def assess_cleaned_content(text: str) -> dict:
    """Return {'viable': bool, 'reason': str} for cleaned text."""
    if not text or len(text.strip()) < 200:
        return {"viable": False, "reason": "Content too short after cleaning"}
    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) < 5:
        return {"viable": False, "reason": "Too few content lines after cleaning"}
    return {"viable": True, "reason": "OK"}

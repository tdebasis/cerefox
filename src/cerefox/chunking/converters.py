"""Document format converters — PDF and DOCX to Markdown.

Each converter is a standalone function that takes a file path and returns a
markdown string.  External dependencies (pypdf, python-docx) are imported
lazily with a helpful error message if not installed.

Install extras:
    uv pip install pypdf          # PDF support
    uv pip install python-docx    # DOCX support
"""

from __future__ import annotations

import re
from pathlib import Path


def pdf_to_markdown(path: str | Path) -> str:
    """Convert a PDF file to a markdown string.

    Uses pypdf for text extraction.  Text is extracted page by page;
    each page becomes a level-2 heading section.  Blank pages are skipped.

    Args:
        path: Path to the PDF file.

    Returns:
        Markdown string with page sections.

    Raises:
        ImportError: If pypdf is not installed.
        FileNotFoundError: If the file does not exist.
    """
    try:
        import pypdf  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "pypdf is required for PDF conversion. Install it with: uv pip install pypdf"
        ) from exc

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    reader = pypdf.PdfReader(str(path))
    sections: list[str] = []

    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = _clean_extracted_text(text)
        if text.strip():
            sections.append(f"## Page {i}\n\n{text.strip()}")

    return "\n\n---\n\n".join(sections) if sections else ""


def docx_to_markdown(path: str | Path) -> str:
    """Convert a DOCX file to a markdown string.

    Maps Word paragraph styles to markdown headings:
    - Heading 1 → #
    - Heading 2 → ##
    - Heading 3 → ###
    - List Paragraph → bullet
    - Normal / Body Text → plain paragraph

    Args:
        path: Path to the DOCX file.

    Returns:
        Markdown string.

    Raises:
        ImportError: If python-docx is not installed.
        FileNotFoundError: If the file does not exist.
    """
    try:
        import docx  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "python-docx is required for DOCX conversion. "
            "Install it with: uv pip install python-docx"
        ) from exc

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"DOCX not found: {path}")

    doc = docx.Document(str(path))
    lines: list[str] = []

    for para in doc.paragraphs:
        style = para.style.name
        text = para.text.strip()

        if not text:
            # Blank paragraph — emit a separator only if the previous line
            # wasn't already blank.
            if lines and lines[-1] != "":
                lines.append("")
            continue

        if style.startswith("Heading 1"):
            lines.append(f"# {text}")
        elif style.startswith("Heading 2"):
            lines.append(f"## {text}")
        elif style.startswith("Heading 3"):
            lines.append(f"### {text}")
        elif style.startswith("Heading 4") or style.startswith("Heading 5"):
            lines.append(f"#### {text}")
        elif "List" in style:
            lines.append(f"- {text}")
        else:
            lines.append(text)

    # Join with double newlines between non-list paragraphs.
    result_parts: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i] == "":
            i += 1
            continue
        result_parts.append(lines[i])
        i += 1

    return "\n\n".join(result_parts)


def convert_to_markdown(path: str | Path) -> str:
    """Auto-detect file type and convert to markdown.

    Supports: .pdf, .docx, .md, .txt (returned as-is).

    Args:
        path: Path to the file.

    Returns:
        Markdown string.

    Raises:
        ValueError: If the file extension is unsupported.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return pdf_to_markdown(path)
    elif suffix in (".docx", ".doc"):
        return docx_to_markdown(path)
    elif suffix in (".md", ".txt", ".markdown"):
        return path.read_text(encoding="utf-8")
    else:
        raise ValueError(f"Unsupported file type: {suffix!r}. Supported: .pdf, .docx, .md, .txt")


# ── Internal helpers ──────────────────────────────────────────────────────────


def _clean_extracted_text(text: str) -> str:
    """Normalise whitespace in PDF-extracted text.

    PDF text extraction produces inconsistent spacing — multiple spaces,
    spurious line breaks, form-feed characters, etc.
    """
    # Replace form-feed characters.
    text = text.replace("\f", "\n")
    # Collapse 3+ blank lines to 2.
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse multiple spaces (but not leading indent).
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()

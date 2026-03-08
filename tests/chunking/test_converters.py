"""Tests for cerefox.chunking.converters.

Mocks both pypdf and python-docx so no real external libraries are needed.
Covers: PDF text extraction, DOCX heading/paragraph mapping, auto-detect,
ImportError messages, and edge cases.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_pdf_page(text: str) -> MagicMock:
    page = MagicMock()
    page.extract_text.return_value = text
    return page


def _make_docx_para(text: str, style_name: str = "Normal") -> MagicMock:
    para = MagicMock()
    para.text = text
    para.style.name = style_name
    return para


# ── PDF conversion ────────────────────────────────────────────────────────────


class TestPdfToMarkdown:
    """Tests for pdf_to_markdown()."""

    def _import(self):
        # Re-import after patching sys.modules.
        sys.modules.pop("cerefox.chunking.converters", None)
        from cerefox.chunking.converters import pdf_to_markdown

        return pdf_to_markdown

    def test_single_page_produces_h2_section(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        mock_pypdf = MagicMock()
        reader_instance = MagicMock()
        reader_instance.pages = [_make_pdf_page("Hello world")]
        mock_pypdf.PdfReader.return_value = reader_instance

        with patch.dict(sys.modules, {"pypdf": mock_pypdf}):
            pdf_to_markdown = self._import()
            result = pdf_to_markdown(str(pdf_file))

        assert "## Page 1" in result
        assert "Hello world" in result

    def test_multi_page_produces_multiple_sections(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        mock_pypdf = MagicMock()
        reader_instance = MagicMock()
        reader_instance.pages = [
            _make_pdf_page("Page one content"),
            _make_pdf_page("Page two content"),
            _make_pdf_page("Page three content"),
        ]
        mock_pypdf.PdfReader.return_value = reader_instance

        with patch.dict(sys.modules, {"pypdf": mock_pypdf}):
            pdf_to_markdown = self._import()
            result = pdf_to_markdown(str(pdf_file))

        assert "## Page 1" in result
        assert "## Page 2" in result
        assert "## Page 3" in result

    def test_blank_pages_are_skipped(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        mock_pypdf = MagicMock()
        reader_instance = MagicMock()
        reader_instance.pages = [
            _make_pdf_page("Content"),
            _make_pdf_page("   "),  # blank
            _make_pdf_page("More content"),
        ]
        mock_pypdf.PdfReader.return_value = reader_instance

        with patch.dict(sys.modules, {"pypdf": mock_pypdf}):
            pdf_to_markdown = self._import()
            result = pdf_to_markdown(str(pdf_file))

        assert "## Page 1" in result
        assert "## Page 2" not in result  # blank page skipped
        assert "## Page 3" in result

    def test_all_blank_returns_empty_string(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        mock_pypdf = MagicMock()
        reader_instance = MagicMock()
        reader_instance.pages = [_make_pdf_page(""), _make_pdf_page("  ")]
        mock_pypdf.PdfReader.return_value = reader_instance

        with patch.dict(sys.modules, {"pypdf": mock_pypdf}):
            pdf_to_markdown = self._import()
            result = pdf_to_markdown(str(pdf_file))

        assert result == ""

    def test_raises_importerror_when_pypdf_missing(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        sys.modules.pop("cerefox.chunking.converters", None)
        with patch.dict(sys.modules, {"pypdf": None}):
            # pypdf=None causes import to fail
            sys.modules.pop("cerefox.chunking.converters", None)
            with pytest.raises(ImportError, match="pypdf"):
                from cerefox.chunking.converters import pdf_to_markdown

                pdf_to_markdown(str(pdf_file))

    def test_raises_filenotfounderror_for_missing_file(self, tmp_path):
        mock_pypdf = MagicMock()

        with patch.dict(sys.modules, {"pypdf": mock_pypdf}):
            sys.modules.pop("cerefox.chunking.converters", None)
            from cerefox.chunking.converters import pdf_to_markdown

            with pytest.raises(FileNotFoundError):
                pdf_to_markdown(str(tmp_path / "nonexistent.pdf"))


# ── DOCX conversion ───────────────────────────────────────────────────────────


class TestDocxToMarkdown:
    """Tests for docx_to_markdown()."""

    def _import(self):
        sys.modules.pop("cerefox.chunking.converters", None)
        from cerefox.chunking.converters import docx_to_markdown

        return docx_to_markdown

    def _make_docx_file(self, tmp_path: Path) -> Path:
        p = tmp_path / "test.docx"
        p.write_bytes(b"PK fake docx")
        return p

    def test_heading1_becomes_h1(self, tmp_path):
        docx_file = self._make_docx_file(tmp_path)
        mock_docx = MagicMock()
        doc_instance = MagicMock()
        doc_instance.paragraphs = [_make_docx_para("My Title", "Heading 1")]
        mock_docx.Document.return_value = doc_instance

        with patch.dict(sys.modules, {"docx": mock_docx}):
            fn = self._import()
            result = fn(str(docx_file))

        assert "# My Title" in result

    def test_heading2_becomes_h2(self, tmp_path):
        docx_file = self._make_docx_file(tmp_path)
        mock_docx = MagicMock()
        doc_instance = MagicMock()
        doc_instance.paragraphs = [_make_docx_para("Section", "Heading 2")]
        mock_docx.Document.return_value = doc_instance

        with patch.dict(sys.modules, {"docx": mock_docx}):
            fn = self._import()
            result = fn(str(docx_file))

        assert "## Section" in result

    def test_heading3_becomes_h3(self, tmp_path):
        docx_file = self._make_docx_file(tmp_path)
        mock_docx = MagicMock()
        doc_instance = MagicMock()
        doc_instance.paragraphs = [_make_docx_para("Sub", "Heading 3")]
        mock_docx.Document.return_value = doc_instance

        with patch.dict(sys.modules, {"docx": mock_docx}):
            fn = self._import()
            result = fn(str(docx_file))

        assert "### Sub" in result

    def test_normal_paragraph_becomes_plain_text(self, tmp_path):
        docx_file = self._make_docx_file(tmp_path)
        mock_docx = MagicMock()
        doc_instance = MagicMock()
        doc_instance.paragraphs = [_make_docx_para("Body text here.", "Normal")]
        mock_docx.Document.return_value = doc_instance

        with patch.dict(sys.modules, {"docx": mock_docx}):
            fn = self._import()
            result = fn(str(docx_file))

        assert "Body text here." in result
        assert "#" not in result

    def test_list_paragraph_becomes_bullet(self, tmp_path):
        docx_file = self._make_docx_file(tmp_path)
        mock_docx = MagicMock()
        doc_instance = MagicMock()
        doc_instance.paragraphs = [
            _make_docx_para("Item one", "List Paragraph"),
            _make_docx_para("Item two", "List Paragraph"),
        ]
        mock_docx.Document.return_value = doc_instance

        with patch.dict(sys.modules, {"docx": mock_docx}):
            fn = self._import()
            result = fn(str(docx_file))

        assert "- Item one" in result
        assert "- Item two" in result

    def test_full_document_with_mixed_styles(self, tmp_path):
        docx_file = self._make_docx_file(tmp_path)
        mock_docx = MagicMock()
        doc_instance = MagicMock()
        doc_instance.paragraphs = [
            _make_docx_para("My Document", "Heading 1"),
            _make_docx_para("Introduction", "Heading 2"),
            _make_docx_para("This is the intro paragraph.", "Normal"),
            _make_docx_para("Details", "Heading 3"),
            _make_docx_para("Detail content.", "Normal"),
        ]
        mock_docx.Document.return_value = doc_instance

        with patch.dict(sys.modules, {"docx": mock_docx}):
            fn = self._import()
            result = fn(str(docx_file))

        assert "# My Document" in result
        assert "## Introduction" in result
        assert "This is the intro paragraph." in result
        assert "### Details" in result

    def test_blank_paragraphs_dont_create_double_blanks(self, tmp_path):
        docx_file = self._make_docx_file(tmp_path)
        mock_docx = MagicMock()
        doc_instance = MagicMock()
        doc_instance.paragraphs = [
            _make_docx_para("Para one.", "Normal"),
            _make_docx_para("", "Normal"),  # blank
            _make_docx_para("", "Normal"),  # blank
            _make_docx_para("Para two.", "Normal"),
        ]
        mock_docx.Document.return_value = doc_instance

        with patch.dict(sys.modules, {"docx": mock_docx}):
            fn = self._import()
            result = fn(str(docx_file))

        assert "Para one." in result
        assert "Para two." in result

    def test_raises_importerror_when_python_docx_missing(self, tmp_path):
        docx_file = self._make_docx_file(tmp_path)

        sys.modules.pop("cerefox.chunking.converters", None)
        with patch.dict(sys.modules, {"docx": None}):
            sys.modules.pop("cerefox.chunking.converters", None)
            with pytest.raises(ImportError, match="python-docx"):
                from cerefox.chunking.converters import docx_to_markdown

                docx_to_markdown(str(docx_file))

    def test_raises_filenotfounderror_for_missing_file(self, tmp_path):
        mock_docx = MagicMock()
        with patch.dict(sys.modules, {"docx": mock_docx}):
            sys.modules.pop("cerefox.chunking.converters", None)
            from cerefox.chunking.converters import docx_to_markdown

            with pytest.raises(FileNotFoundError):
                docx_to_markdown(str(tmp_path / "nonexistent.docx"))


# ── Auto-detect (convert_to_markdown) ─────────────────────────────────────────


class TestConvertToMarkdown:
    """Tests for convert_to_markdown() format auto-detection."""

    def test_md_file_returned_as_is(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("# Hello\n\nWorld.", encoding="utf-8")
        sys.modules.pop("cerefox.chunking.converters", None)
        from cerefox.chunking.converters import convert_to_markdown

        result = convert_to_markdown(f)
        assert result == "# Hello\n\nWorld."

    def test_txt_file_returned_as_is(self, tmp_path):
        f = tmp_path / "note.txt"
        f.write_text("Plain text content.", encoding="utf-8")
        sys.modules.pop("cerefox.chunking.converters", None)
        from cerefox.chunking.converters import convert_to_markdown

        result = convert_to_markdown(f)
        assert result == "Plain text content."

    def test_unsupported_extension_raises_valueerror(self, tmp_path):
        f = tmp_path / "note.odt"
        f.write_bytes(b"fake")
        sys.modules.pop("cerefox.chunking.converters", None)
        from cerefox.chunking.converters import convert_to_markdown

        with pytest.raises(ValueError, match="Unsupported"):
            convert_to_markdown(f)

    def test_pdf_extension_calls_pdf_converter(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 fake")

        mock_pypdf = MagicMock()
        reader_instance = MagicMock()
        reader_instance.pages = [_make_pdf_page("PDF content")]
        mock_pypdf.PdfReader.return_value = reader_instance

        with patch.dict(sys.modules, {"pypdf": mock_pypdf}):
            sys.modules.pop("cerefox.chunking.converters", None)
            from cerefox.chunking.converters import convert_to_markdown

            result = convert_to_markdown(f)

        assert "PDF content" in result

    def test_docx_extension_calls_docx_converter(self, tmp_path):
        f = tmp_path / "doc.docx"
        f.write_bytes(b"PK fake")

        mock_docx = MagicMock()
        doc_instance = MagicMock()
        doc_instance.paragraphs = [_make_docx_para("DOCX content", "Normal")]
        mock_docx.Document.return_value = doc_instance

        with patch.dict(sys.modules, {"docx": mock_docx}):
            sys.modules.pop("cerefox.chunking.converters", None)
            from cerefox.chunking.converters import convert_to_markdown

            result = convert_to_markdown(f)

        assert "DOCX content" in result

"""PDF Text Extractor — pull text from uploaded PDF files.

Used by the Streamlit dashboard so users can upload a PDF describing
their service (e.g., a brochure or one-pager) instead of typing it in.
"""

import logging
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_file: BytesIO) -> Optional[str]:
    """Extract all text content from a PDF file.

    Args:
        pdf_file: A file-like BytesIO object containing the PDF data.

    Returns:
        Extracted text as a single string, or None if extraction fails.
    """
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(pdf_file)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())

        if not pages:
            logger.warning("PDF contained no extractable text")
            return None

        return "\n\n".join(pages)
    except Exception as exc:
        logger.warning("Failed to extract text from PDF: %s", exc)
        return None

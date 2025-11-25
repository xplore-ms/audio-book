import fitz  # PyMuPDF


def get_num_pages_from_bytes(pdf_bytes: bytes) -> int:
    """
    Return the number of pages in a PDF (from bytes).
    """
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return doc.page_count


def extract_page_text_from_bytes(pdf_bytes: bytes, page_number: int) -> str:
    """
    Extract text from PDF page using only bytes.
    page_number = zero-based index
    """
    if page_number < 0:
        raise ValueError("Page number must be >= 0")

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        if page_number >= doc.page_count:
            raise ValueError(f"Page {page_number+1} out of range")

        page = doc.load_page(page_number)
        text = page.get_text("text")

    return text or ""

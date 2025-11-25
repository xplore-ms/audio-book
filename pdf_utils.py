import fitz  # PyMuPDF


def get_num_pages_from_bytes(pdf_bytes: bytes) -> int:
    """
    Return the number of pages in a PDF (from bytes).
    """
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return doc.page_count


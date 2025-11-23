# pdf_utils.py
import fitz  # PyMuPDF

def get_num_pages(pdf_path: str) -> int:
    doc = fitz.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


def extract_page_text(pdf_path: str, page_index: int) -> str:
    """
    page_index: 0-based
    """
    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_index)
        return page.get_text()
    finally:
        doc.close()
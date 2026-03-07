import fitz  # PyMuPDF
import io


def get_num_pages_from_bytes(pdf_bytes: bytes) -> int:
    """
    Return the number of pages in a PDF (from bytes). Backwards compatible.
    """
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return doc.page_count


def get_num_pages_and_extension(
    file_bytes: bytes, filename: str
) -> tuple[int, str, bytes]:
    """
    Given file bytes and original filename, returns (num_pages, storage_extension, processed_bytes).
    processed_bytes is identical to file_bytes except for DOCX where it's converted to TXT.
    """
    ext = filename.lower().split(".")[-1]

    if ext == "pdf":
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            return doc.page_count, ".pdf", file_bytes
    elif ext == "epub":
        with fitz.open(stream=file_bytes, filetype="epub") as doc:
            return doc.page_count, ".epub", file_bytes
    elif ext == "txt":
        with fitz.open(stream=file_bytes, filetype="txt") as doc:
            return doc.page_count, ".txt", file_bytes
    elif ext == "docx":
        import docx

        doc_obj = docx.Document(io.BytesIO(file_bytes))
        full_text = "\n".join([p.text for p in doc_obj.paragraphs])
        txt_bytes = full_text.encode("utf-8")
        with fitz.open(stream=txt_bytes, filetype="txt") as doc:
            return doc.page_count, ".txt", txt_bytes
    else:
        raise ValueError(f"Unsupported file extension: {ext}")

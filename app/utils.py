from pypdf import PdfReader
from fastapi import UploadFile, HTTPException

MAX_PAGES = 30  # Set your limit

def validate_pdf_size(file: UploadFile):
    """
    Reads PDF metadata to check page count without reading the whole file into memory.
    Resets the file cursor after checking.
    """
    try:
        reader = PdfReader(file.file)
        count = len(reader.pages)
        
        # Reset file cursor to start so it can be uploaded to Blob later
        file.file.seek(0)
        
        if count > MAX_PAGES:
            raise HTTPException(
                status_code=400, 
                detail=f"PDF exceeds page limit. Max: {MAX_PAGES}, Got: {count}"
            )
        return count
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid PDF: {str(e)}")
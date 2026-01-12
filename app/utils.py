from pypdf import PdfReader
from fastapi import UploadFile, HTTPException
from dotenv import load_dotenv
import os
load_dotenv()

MAX_PDF_PAGES = int(os.getenv('MAX_PDF_PAGES'))

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
        
        if count > MAX_PDF_PAGES:
            raise HTTPException(
                status_code=400, 
                detail=f"PDF exceeds page limit. Max: {MAX_PDF_PAGES}, Got: {count}"
            )
        return count
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid PDF: {str(e)}")
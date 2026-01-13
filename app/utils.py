from pypdf import PdfReader
from fastapi import UploadFile, HTTPException
from dotenv import load_dotenv
import logging
import os

load_dotenv()

# Setup a logger to track validation errors
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("utils")

# Default to 50 if the environment variable is missing (defensive coding)
MAX_PDF_PAGES = int(os.getenv('MAX_PDF_PAGES', 50))

def validate_pdf_size(file: UploadFile):
    """
    Efficiently checks the PDF page count by reading only the file trailer/metadata.
    This prevents the system from processing excessively large files that would 
    consume too much Document Intelligence quota or time.
    """
    try:
        # pypdf reads the metadata without loading the entire file content into memory
        reader = PdfReader(file.file)
        count = len(reader.pages)
        
        # Important: We must reset the file cursor to the beginning (0).
        # If we skip this, the subsequent upload-to-blob function will read empty bytes.
        file.file.seek(0)
        
        if count > MAX_PDF_PAGES:
            logger.warning(f"Upload rejected: File '{file.filename}' has {count} pages (Limit: {MAX_PDF_PAGES})")
            raise HTTPException(
                status_code=400, 
                detail=f"PDF exceeds page limit. Max: {MAX_PDF_PAGES}, Got: {count}"
            )
        
        return count

    except HTTPException:
        # Re-raise existing HTTP exceptions so they propagate to the client correctly
        raise
    except Exception as e:
        logger.error(f"Failed to read PDF structure for '{file.filename}': {str(e)}")
        raise HTTPException(status_code=400, detail=f"Invalid or corrupt PDF file.")
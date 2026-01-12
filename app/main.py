from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from app.rag import upload_to_blob, process_and_index_document, list_indexed_files
from app.utils import validate_pdf_size
from app.models import AskRequest, AskResponse
from app.agent import run_agent
from azure.storage.blob import ContainerClient
from dotenv import load_dotenv
import os

load_dotenv()
container_client = ContainerClient.from_connection_string(
    conn_str=os.getenv('AZURE_STORAGE_CONTAINER_CONN_STRING'), 
    container_name=os.getenv("AZURE_STORAGE_CONTAINER_NAME")
)

app = FastAPI(title="AI Policy Agent")

# Health Check (Good for Azure)
@app.get("/")
async def root():
    return {"status": "running smoothly with ci/cd"}

# Helper to check status quickly
@app.get("/status/{filename}")
def check_file_status(filename: str):
    """Checks metadata of the blob to see if indexing is complete."""
    try:
        blob = container_client.get_blob_client(filename)
        props = blob.get_blob_properties()
        # Look for the metadata/tags we set in rag.py
        status = props.metadata.get("status", "unknown")
        return {"filename": filename, "status": status}
    except Exception:
        return {"filename": filename, "status": "not_found"}


@app.post("/upload")
async def upload_pdf(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...)
):
    # 1. Quick Validations
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDFs allowed")
    
    try:
        # Check page limits (fast check)
        validate_pdf_size(file)
    except HTTPException as e:
        raise e # Re-raise to send 400 to client
    except Exception as e:
        raise HTTPException(400, f"Corrupt file: {str(e)}")

    # 2. Upload to Blob
    file_content = await file.read()
    clean_filename, document_url = upload_to_blob(file_content, file.filename)
    
    # 3. Background Indexing
    background_tasks.add_task(process_and_index_document, clean_filename, document_url)
    
    # Return specific status so Streamlit knows to start polling
    return {
        "message": "Upload successful", 
        "filename": clean_filename, 
        "status": "processing"
    }

@app.get("/files")
def get_available_documents():
    """Returns list of documents that have finished indexing."""
    files = list_indexed_files()
    return {"documents": files}

@app.post("/ask", response_model=AskResponse)
async def ask_question(request: AskRequest):
    answer, sources = run_agent(
        user_query=request.query, 
        session_id=request.session_id,
        target_file=request.target_file
    )
    return AskResponse(answer=answer, source=sources)
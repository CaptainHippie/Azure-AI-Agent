from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from app.rag import upload_to_blob, process_and_index_document, list_indexed_files
from app.utils import validate_pdf_size
from app.models import AskRequest, AskResponse
from app.agent import run_agent, clear_session_memory
from azure.storage.blob import ContainerClient
from dotenv import load_dotenv
import os

load_dotenv()

container_client = ContainerClient.from_connection_string(
    conn_str=os.getenv('AZURE_STORAGE_CONTAINER_CONN_STRING'), 
    container_name=os.getenv("AZURE_STORAGE_CONTAINER_NAME")
)

app = FastAPI(title="AI Policy Agent")

# Simple health check for Azure App Service to verify the container is up
@app.get("/")
async def root():
    return {"status": "running smoothly with ci/cd"}

@app.get("/status/{filename}")
def check_file_status(filename: str):
    """
    Polls the blob metadata to see if the indexing pipeline has marked it as 'ready'.
    This allows the frontend to wait without blocking the connection.
    """
    try:
        blob = container_client.get_blob_client(filename)
        props = blob.get_blob_properties()
        
        # We track progress using metadata tags on the blob itself
        status = props.metadata.get("status", "unknown")
        return {"filename": filename, "status": status}
    except Exception:
        return {"filename": filename, "status": "not_found"}
    
@app.post("/upload")
async def upload_pdf(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...)
):
    # Validate file type and size before starting expensive Azure processes
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDFs allowed")
    
    try:
        validate_pdf_size(file)
    except HTTPException as e:
        raise e 
    except Exception as e:
        raise HTTPException(400, f"Corrupt file: {str(e)}")

    # Upload to storage first so the background task can access the file independently
    file_content = await file.read()
    clean_filename, document_url = upload_to_blob(file_content, file.filename)
    
    # Offload the heavy lifting (OCR, Embedding, Indexing) to a background task
    # This keeps the UI responsive while the pipeline runs
    background_tasks.add_task(process_and_index_document, clean_filename, document_url)
    
    return {
        "message": "Upload successful", 
        "filename": clean_filename, 
        "status": "processing"
    }

@app.get("/files")
def get_available_documents():
    """Lists only the files that have completed indexing and are ready for chat."""
    files = list_indexed_files()
    return {"documents": files}

@app.post("/ask", response_model=AskResponse)
async def ask_question(request: AskRequest):
    """
    Main chat endpoint. Routes the user query and session context 
    to the Agent logic.
    """
    answer, sources = run_agent(
        user_query=request.query, 
        session_id=request.session_id,
        target_file=request.target_file
    )
    return AskResponse(answer=answer, source=sources)

@app.delete("/session/{session_id}")
async def reset_session(session_id: str):
    """
    Clears the conversation history for a specific session ID.
    Called when the user clicks 'Clear Chat' in the UI.
    """
    clear_session_memory(session_id)
    return {"status": "memory_cleared", "session_id": session_id}
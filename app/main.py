from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from dotenv import load_dotenv

from app.rag import upload_to_blob, process_and_index_document, list_indexed_files
from app.utils import validate_pdf_size
from app.models import AskRequest, AskResponse
from app.agent import run_agent

# ... existing upload code ...

load_dotenv()

#from app.models import AskRequest, AskResponse
#from app.agent import run_agent
#from app.rag import initialize_vector_store

# Initialize App
app = FastAPI(title="AI Policy Agent")

# Health Check (Good for Azure)
@app.get("/")
async def root():
    return {"status": "running smoothly again"}


@app.post("/upload")
async def upload_pdf(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...)
):
    # 1. Quick Validations
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDFs allowed")
    
    # Check page limits (fast check using pypdf)
    validate_pdf_size(file)

    # 2. Upload to Blob Storage (Synchronous for now, or await async)
    file_content = await file.read()
    clean_filename, document_url = upload_to_blob(file_content, file.filename)
    print(clean_filename, document_url)
    # 3. Trigger robust indexing in the background
    # This returns immediately to the UI, while Azure does the heavy lifting
    background_tasks.add_task(process_and_index_document, clean_filename, document_url)
    
    return {"message": "Upload successful. Indexing started in background.", "filename": file.filename}

@app.get("/files")
def get_available_documents():
    """Returns list of documents that have finished indexing."""
    files = list_indexed_files()
    return {"documents": files}

@app.post("/ask", response_model=AskResponse)
async def ask_question(request: AskRequest):
    try:
        # Pass the request data to the agent logic
        answer, sources = run_agent(
            user_query=request.query, 
            session_id=request.session_id,
            target_file=request.target_file
        )
        
        return AskResponse(
            answer=answer,
            source=sources
        )
    except Exception as e:
        # Log error for debugging
        print(f"Error in /ask: {e}")
        raise HTTPException(status_code=500, detail=str(e))
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, StringIndexType, DocumentContentFormat
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.storage.blob import ContainerClient
from chonkie import RecursiveChunker
from azure.search.documents import SearchClient
from werkzeug.utils import secure_filename
from openai import AzureOpenAI
import logging
import base64
import os
from dotenv import load_dotenv
load_dotenv()

# --- Client Initialization ---
# We set up all necessary Azure clients here to keep the connection logic in one place.

document_intelligence_client = DocumentIntelligenceClient(
    endpoint=os.getenv('DOCUMENT_INTELLIGENCE_ENDPOINT'), 
    credential=AzureKeyCredential(os.getenv('DOCUMENT_INTELLIGENCE_API_KEY'))
)

storage_endpoint = os.getenv('AZURE_STORAGE_ENDPOINT')
container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME")

container_client = ContainerClient.from_connection_string(
    conn_str=os.getenv('AZURE_STORAGE_CONTAINER_CONN_STRING'), 
    container_name=container_name
)

search_client = SearchClient(
    endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
    index_name=os.getenv("AZURE_SEARCH_INDEX_NAME"),
    credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_API_KEY"))
)

openai_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

embeddings_deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT_EMBEDDINGS')

# --- Helper Functions ---

def Return_Poller_Result(document_url=None, bytes=None):
    """
    Calls Azure Document Intelligence to extract text.
    We request the output in 'Markdown' format. This is crucial because it preserves
    headers, tables, and lists, allowing our chunker to make smarter splits later.
    """
    poller = document_intelligence_client.begin_analyze_document(
        model_id="prebuilt-layout",
        body=AnalyzeDocumentRequest(url_source=document_url, bytes_source=bytes), 
        output_content_format=DocumentContentFormat.MARKDOWN,
        string_index_type=StringIndexType.UTF16_CODE_UNIT
    )
    return poller.result()

def chunk_to_documents(text):
    """
    Splits the extracted text into manageable pieces.
    We use RecursiveChunker because it respects sentence boundaries and 
    formatting better than simple fixed-size splitting.
    """
    chunker = RecursiveChunker(
        chunk_size=512,
        min_characters_per_chunk=100,
    )
    return chunker.chunk(text)

def openai_batch_embedding(texts):
    """
    Generates vector embeddings for a list of text chunks in a single batch call.
    """
    response = openai_client.embeddings.create(
        input=texts,
        model=embeddings_deployment
    )
    return [embed.embedding for embed in response.data]
    
def upload_to_blob(file_content: bytes, filename: str):
    """
    Uploads the raw PDF to Azure Blob Storage.
    We tag it with 'status=processing' immediately so the UI knows 
    the file exists but isn't ready for chat yet.
    """
    clean_filename = secure_filename(filename)
    
    container_client.upload_blob(
        name=clean_filename, 
        overwrite=True, 
        data=file_content, 
        metadata={'status': "processing", 'original_name': str(filename)}, 
        tags={'status': "processing", 'original_name': str(filename)}
    )
    return clean_filename, f"{storage_endpoint}/{container_name}/{clean_filename}"

def update_blob_status(filename: str, page_count: int, status: str):
    """
    Updates the blob's metadata tag. 
    The frontend polls this tag to determine when to show the 'Ready' checkmark.
    """
    blob_client = container_client.get_blob_client(filename)
    
    # We update both metadata and tags to ensure visibility across different Azure tools
    blob_client.set_blob_metadata(metadata={**blob_client.get_blob_properties().metadata, **{'status': status, "pageCount": str(page_count)}})
    blob_client.set_blob_tags(tags={**blob_client.get_blob_tags(), **{'status': status, "pageCount": str(page_count)}})

def list_indexed_files():
    """
    Retrieves only the files that have successfully finished the indexing pipeline.
    """
    blob_list = container_client.find_blobs_by_tags("status = 'ready'")
    
    return [blob.name for blob in blob_list]

# --- Main Pipeline ---

def delete_any_existing_documents(fileName):
    """
    Cleanup step: Checks if this file was indexed previously and deletes old chunks
    to prevent duplicate search results.
    """
    results = search_client.search(
        search_text="*", 
        select="*", 
        filter=f"source_document eq '{fileName}'"
    )
    
    keys_to_delete = []
    for doc in results:
        keys_to_delete.append({"@search.action": "delete", "id": doc["id"]})
    
    if keys_to_delete:
        search_client.upload_documents(keys_to_delete)

def process_and_index_document(filename: str, file_url: str):
    """
    The core ETL function (Extract, Transform, Load).
    
    Flow:
    1. Extract layout-aware text using Azure Doc Intelligence.
    2. Chunk the text recursively.
    3. Generate embeddings for all chunks.
    4. Upload to Azure AI Search.
    5. Update Blob status so the user can start chatting.
    """
    logging.info(f"Starting pipeline for {filename}...")

    # 1. Extraction
    result = Return_Poller_Result(document_url=file_url)
    markdown_text = result.content
    page_count = len(result.pages)
    logging.info(f"Doc Intelligence finished. Extracted {len(markdown_text)} chars.")

    # 2. Chunking
    chunks = chunk_to_documents(markdown_text)
    logging.info(f"Chonkie created {len(chunks)} chunks.")

    # 3. Embedding
    embeddings = openai_batch_embedding([chunk.text for chunk in chunks])

    # 4. Preparation for Search Index
    search_documents = [{
        "id": base64.urlsafe_b64encode(f"{filename}_{i}".encode()).decode(),
        "content": chunk.text,
        "text_vector": embeddings[i],
        "chunk_index": i + 1,
        "source_url": file_url,
        "source_document": filename
    } for i, chunk in enumerate(chunks)]

    # 5. Indexing
    if search_documents:
        delete_any_existing_documents(filename)
        search_client.upload_documents(documents=search_documents)
        logging.info(f"Uploaded {len(search_documents)} chunks to Azure AI Search.")

    # 6. Finalize
    update_blob_status(filename, page_count, "ready")
    
    return {"filename": filename, "chunks": len(chunks), "status": "Indexed"}
from azure.search.documents.models import VectorizableTextQuery
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from openai import AzureOpenAI
import logging
import json
import os
from dotenv import load_dotenv

load_dotenv()

# Configure logging to output to console (captured by Azure Logs)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent")

# In-Memory State
SESSION_MEMORY = {}
MAX_HISTORY_LIMIT = int(os.getenv('MAX_HISTORY_LIMIT'))  # Keep last 10 messages (excluding system prompt)

# --- Client Initialization ---
gpt_engine_4_1_mini = os.getenv('AZURE_OPENAI_DEPLOYMENT_GPT4_1_MINI')

openai_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

search_client = SearchClient(
    endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
    index_name=os.getenv("AZURE_SEARCH_INDEX_NAME"),
    credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_API_KEY"))
)

# --- Tool Logic ---

def search_knowledge_base(query: str, filename_filter: str = None, count: int = 5):
    """
    Executes a Hybrid Search (Keyword + Vector) against the Azure Index.
    
    The filename_filter is critical here: it ensures we only search within
    the specific document the user selected in the UI, preventing context pollution.
    """
    logger.info(f"Tool Action: Searching for '{query}' in document: '{filename_filter}'")

    vector_query = VectorizableTextQuery(text=query, k_nearest_neighbors=count * 2, fields="text_vector")
    
    results = search_client.search(
        search_text=query,
        vector_queries=[vector_query],
        top=count,
        # Only apply OData filter if a specific file was targeted
        filter=f"source_document eq '{filename_filter}'" if filename_filter else None,
        search_fields=["content"], 
        select=['content', 'source_url', 'source_document', 'chunk_index']
    )

    sources = {}
    for doc in results:
        doc_name = doc['source_document']
        if doc_name not in sources:
            sources[doc_name] = {
                "url": doc['source_url'], 
                "context": []
            }
        sources[doc_name]['context'].append(doc['content'])
    
    return sources

# --- Agent Configuration ---

tools = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Searches the document knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optimized search query based on user question."
                    }
                },
                "required": ["query"]
            }
        }
    }
]

SYSTEM_PROMPT = """
You are a highly precise Research Assistant for a corporation. 

### CORE INSTRUCTIONS:
1. **Efficiency:** If the user asks a general question (greeting, math, joke, coding help), ANSWER DIRECTLY. Do not use tools.
2.  **Grounding:** You must answer the user's question PRIMARILY based on the context provided by the tool `search_knowledge_base`.
3.  **Citation:** Every factual statement you make must be immediately followed by a citation in the format `[Source: DocumentName]`. 
    - Example: "The vacation policy allows 20 days off [Source: employee_handbook.pdf]."
4.  **No Hallucination:** If the tool results do not contain the answer, explicitly state: "I cannot find this information in the provided document."
5.  **Style:** Be professional, direct, and structured. Use Markdown headers and bullet points where appropriate.

### TOOL USAGE:
- You have access to a search tool. You MUST use it for every query regarding document content.
"""

# --- Memory Management ---

def clear_session_memory(session_id: str):
    """Wipes the memory for a specific user session."""
    if session_id in SESSION_MEMORY:
        del SESSION_MEMORY[session_id]
        logger.info(f"Memory cleared for session: {session_id}")

# --- Main Agent Loop ---

def run_agent(user_query: str, session_id: str, target_file: str = None):
    
    # Initialize with System Prompt if new session
    if session_id not in SESSION_MEMORY:
        SESSION_MEMORY[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    history = SESSION_MEMORY[session_id]
    history.append({"role": "user", "content": user_query})
    
    # 1. Initial LLM Call (Decision Phase)
    response = openai_client.chat.completions.create(
        model=gpt_engine_4_1_mini,
        messages=history,
        tools=tools,
        tool_choice="auto" 
    )
    
    response_message = response.choices[0].message
    final_sources = {}

    # 2. Check for Tool Execution
    if response_message.tool_calls:
        logger.info(f"Agent decided to use tool: {response_message.tool_calls[0].function.name}")
        
        history.append(response_message)
        
        for tool_call in response_message.tool_calls:
            if tool_call.function.name == "search_knowledge_base":
                args = json.loads(tool_call.function.arguments)

                # explicit document filter passed from the Frontend
                sources = search_knowledge_base(args["query"], filename_filter=target_file)
                
                final_sources.update(sources)

                # We pass the content back to the LLM so it can generate the answer
                # We serialize to JSON to keep the structure clear for the model
                history.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": "search_knowledge_base",
                    "content": json.dumps(sources)
                })
        
        # 3. Final LLM Call (Response Generation Phase)
        final_response = openai_client.chat.completions.create(
            model=gpt_engine_4_1_mini,
            messages=history
        )
        answer_text = final_response.choices[0].message.content
        history.append({"role": "assistant", "content": answer_text})
        
    else:
        logger.info("Agent decided to answer directly (No tool used)")
        answer_text = response_message.content
        history.append({"role": "assistant", "content": answer_text})

    # --- Sliding Window Logic ---
    # We always preserve the System Prompt [0].
    # If history grows too large, we trim the oldest messages after the system prompt.
    if len(history) > MAX_HISTORY_LIMIT + 1:
        # Keep System Prompt + Last N messages
        history = [history[0]] + history[-MAX_HISTORY_LIMIT:]
        logger.info(f"History trimmed for session {session_id}")

    SESSION_MEMORY[session_id] = history

    return answer_text, final_sources
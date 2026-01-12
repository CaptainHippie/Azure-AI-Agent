from azure.search.documents.models import VectorizableTextQuery
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from openai import AzureOpenAI
import json
import os
from dotenv import load_dotenv

load_dotenv()

# --- 1. Global In-Memory Memory (For Assignment Purposes) ---
# In production, use Redis or a Database
SESSION_MEMORY = {}

# --- 2. Setup Clients ---
gpt_engine_4_1 = os.getenv('AZURE_OPENAI_DEPLOYMENT_GPT4_1')
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

def search_knowledge_base(query: str, filename_filter: str = None, count: int = 5):
    """
    Retrieves context from Azure AI Search.
    IMPORTANT: filename_filter is passed from the Python Backend, NOT the LLM.
    """
    print(f"🛠️ Tool Triggered: Searching for '{query}' in '{filename_filter}'")

    vector_query = VectorizableTextQuery(text=query, k_nearest_neighbors=count * 2, fields="text_vector")
    
    results = search_client.search(
        search_text=query,
        vector_queries=[vector_query],
        top=count,
        filter=f"source_document eq '{filename_filter}'" if filename_filter else None,
        search_fields=["content"],  # Fields to search
        select=['content', 'source_url', 'source_document', 'chunk_index']
    )

    # 4. Format Output
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

# --- Tool Definition ---
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
- Ignore the file selection argument in the tool; the system handles that. Focus on generating the best search query.
"""


# --- Main Loop ---
def run_agent(user_query: str, session_id: str, target_file: str = None):
    
    if session_id not in SESSION_MEMORY:
        SESSION_MEMORY[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    history = SESSION_MEMORY[session_id]
    history.append({"role": "user", "content": user_query})
    
    # 1. Call LLM
    response = openai_client.chat.completions.create(
        model=gpt_engine_4_1_mini, # e.g., gpt-4o or gpt-35-turbo
        messages=history,
        tools=tools,
        tool_choice="auto" 
    )
    
    response_message = response.choices[0].message
    final_sources = {}

    if response_message.tool_calls:
        history.append(response_message)
        
        for tool_call in response_message.tool_calls:
            if tool_call.function.name == "search_knowledge_base":
                args = json.loads(tool_call.function.arguments)

                # INJECT THE FILTER HERE (Override whatever LLM thinks)
                sources = search_knowledge_base(args["query"], filename_filter=target_file)
                final_sources.update(sources) # Merge findings

                context_str = json.dumps(sources)
                
                history.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": "search_knowledge_base",
                    "content": context_str
                })
        
        # 3. Second Call to LLM (Process the tool output)
        final_response = openai_client.chat.completions.create(
            model=gpt_engine_4_1_mini,
            messages=history
        )
        answer_text = final_response.choices[0].message.content
        history.append({"role": "assistant", "content": answer_text})
        
    else:
        # No tool used (General Chat)
        answer_text = response_message.content
        history.append({"role": "assistant", "content": answer_text})

    # Update Memory
    SESSION_MEMORY[session_id] = history
    
    return answer_text, final_sources
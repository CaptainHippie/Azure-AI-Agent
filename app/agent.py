from azure.search.documents.models import VectorizedQuery
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

# --- 3. The Tool Function (The actual RAG retrieval) ---
def search_knowledge_base(query: str, filename_filter: str = None):
    """
    Retreives relevant context chunks from the Azure AI Search index.
    """
    print(f"🛠️ Tool Triggered: Searching for '{query}' in '{filename_filter}'")
    
    # Generate embedding for the query
    embedding_response = openai_client.embeddings.create(
        input=query,
        model=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    )
    query_vector = embedding_response.data[0].embedding

    # Create Filter string (OData format)
    filter_str = None
    if filename_filter:
        filter_str = f"source eq '{filename_filter}'"

    # Search Azure AI Search
    results = search_client.search(
        search_text=query,
        vector_queries=[VectorizedQuery(vector=query_vector, k_nearest_neighbors=3, fields="vector")],
        filter=filter_str,
        select=["content", "source"]
    )

    # Format results for the LLM
    context = []
    sources = set()
    for res in results:
        context.append(res['content'])
        sources.add(res['source'])
        
    return json.dumps({"context": "\n\n".join(context), "sources": list(sources)})

# --- 4. Tool Definition (Schema for OpenAI) ---
tools = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Searches internal documents for factual information. Use this when the user asks about policies, technical details, or specific document content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to look up in the vector database."
                    },
                    "filename_filter": {
                        "type": "string",
                        "description": "The specific filename to search in, if the user context implies a specific document."
                    }
                },
                "required": ["query"]
            }
        }
    }
]

# --- 5. The System Prompt ---
SYSTEM_PROMPT = """
You are an intelligent corporate assistant. 

DECISION LOGIC:
1. If the user asks a general question (greeting, math, joke, coding help), ANSWER DIRECTLY. Do not use tools.
2. If the user asks about internal information, company policies, or specific documents, YOU MUST USE the 'search_knowledge_base' tool.

OUTPUT RULES:
- Be concise and professional.
- If you use the tool, base your answer ONLY on the returned context.
- If the tool returns no information, say "I couldn't find that information in the documents."
"""

# --- 6. Main Agent Function ---
def run_agent(user_query: str, session_id: str, target_file: str = None):
    
    # A. Retrieve or Init History
    if session_id not in SESSION_MEMORY:
        SESSION_MEMORY[session_id] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
    
    history = SESSION_MEMORY[session_id]
    
    # B. Append User Message
    history.append({"role": "user", "content": user_query})
    
    # C. First Call to LLM (Does it want to run a tool?)
    response = openai_client.chat.completions.create(
        model=gpt_engine_4_1_mini, # e.g., gpt-4o or gpt-35-turbo
        messages=history,
        tools=tools,
        tool_choice="auto" 
    )
    
    response_message = response.choices[0].message
    final_sources = []

    # D. Check if Tool was called
    if response_message.tool_calls:
        # 1. Add the assistant's "intent to call tool" to history
        history.append(response_message)
        
        for tool_call in response_message.tool_calls:
            if tool_call.function.name == "search_knowledge_base":
                
                # Parse arguments
                args = json.loads(tool_call.function.arguments)
                # Force the filter if provided by the API request
                search_filter = target_file if target_file else args.get("filename_filter")
                
                # Execute the actual Python function
                tool_result_json = search_knowledge_base(args["query"], search_filter)
                
                # Parse output to track sources
                tool_data = json.loads(tool_result_json)
                final_sources.extend(tool_data.get("sources", []))
                
                # 2. Add the tool result to history
                history.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": "search_knowledge_base",
                    "content": tool_result_json
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
    
    return answer_text, list(set(final_sources))
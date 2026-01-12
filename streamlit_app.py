import streamlit as st
import requests
import time
from dotenv import load_dotenv
import os
load_dotenv()

API_ENDPOINT = os.getenv('API_ENDPOINT')

st.set_page_config(page_title="AI Agent", layout="wide")
st.title("📄 AI Policy Agent")

# --- CSS for Perplexity-style Citations ---
st.markdown("""
<style>
    .source-box {
        border: 1px solid #e0e0e0;
        border-radius: 5px;
        padding: 10px;
        margin-bottom: 10px;
        background-color: #f9f9f9;
        font-size: 0.85em;
    }
    .source-title { font-weight: bold; color: #1f77b4; }
    .source-url { color: #888; font-size: 0.8em; text-decoration: none; }
</style>
""", unsafe_allow_html=True)

# --- Sidebar ---
st.sidebar.header("Knowledge Base")

# 1. File Upload with Polling
uploaded_file = st.sidebar.file_uploader("Upload PDF", type="pdf")

if uploaded_file:
    if st.sidebar.button("Index Document"):
        with st.spinner("Validating & Uploading..."):
            try:
                files = {"file": (uploaded_file.name, uploaded_file, "application/pdf")}
                response = requests.post(f"{API_ENDPOINT}/upload", files=files)
                
                if response.status_code == 200:
                    data = response.json()
                    filename = data['filename']
                    
                    # --- Polling Loop ---
                    progress_text = st.sidebar.empty()
                    bar = st.sidebar.progress(0)
                    
                    for i in range(60): # Try for 60 seconds
                        time.sleep(1) # Wait 1 sec
                        bar.progress(i + 1)
                        progress_text.text(f"Indexing... {i}s")
                        
                        # Check Status
                        status_res = requests.get(f"{API_ENDPOINT}/status/{filename}")
                        if status_res.status_code == 200:
                            status = status_res.json().get("status")
                            if status == "ready":
                                st.sidebar.success(f"✅ {filename} is ready!")
                                bar.empty()
                                progress_text.empty()
                                time.sleep(1)
                                st.rerun() # Refresh to show in dropdown
                                break
                            elif status == "failed":
                                st.sidebar.error("Indexing failed on server.")
                                break
                    else:
                        st.sidebar.warning("Indexing is taking longer than usual. Check back later.")
                        
                else:
                    # Parse Error from FastAPI (e.g., Page Limit)
                    err_msg = response.json().get('detail', 'Unknown error')
                    st.sidebar.error(f"❌ {err_msg}")
                    
            except Exception as e:
                st.sidebar.error(f"Connection Error: {e}")

# 2. Select Document
try:
    files_res = requests.get(f"{API_ENDPOINT}/files")
    doc_list = files_res.json().get("documents", [])
except:
    doc_list = []

selected_doc = st.sidebar.selectbox("Active Document", doc_list, index=0 if doc_list else None)

if selected_doc:
    st.sidebar.info(f"Chatting with: {selected_doc}")

# --- Chat Interface ---

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        # Render sources if they exist in history
        if "sources" in msg and msg["sources"]:
            with st.expander("📚 Sources & References"):
                for doc_name, details in msg["sources"].items():
                    url = details.get("url", "#")
                    st.markdown(f"**📄 [{doc_name}]({url})**")
                    # Optionally show a snippet
                    # st.text(details['context'][0][:200] + "...")

if prompt := st.chat_input("Ask a question..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("Thinking...")
        
        try:
            payload = {
                "query": prompt,
                "session_id": "streamlit_user_1",
                "target_file": selected_doc
            }
            
            res = requests.post(f"{API_ENDPOINT}/ask", json=payload)
            
            if res.status_code == 200:
                data = res.json()
                answer = data["answer"]
                sources = data.get("source", {})
                
                # 1. Show Answer
                message_placeholder.markdown(answer)
                
                # 2. Show Sources (Perplexity Style)
                if sources:
                    st.markdown("---")
                    cols = st.columns(len(sources))
                    for idx, (doc_name, details) in enumerate(sources.items()):
                        with st.container():
                            st.markdown(
                                f"""
                                <div class="source-box">
                                    <div class="source-title">📄 {doc_name}</div>
                                    <a href="{details['url']}" target="_blank" class="source-url">View Source PDF</a>
                                </div>
                                """, 
                                unsafe_allow_html=True
                            )

                # Save to history
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": answer,
                    "sources": sources
                })
            else:
                message_placeholder.error(f"Server Error: {res.text}")
                
        except Exception as e:
            message_placeholder.error(f"Error: {e}")

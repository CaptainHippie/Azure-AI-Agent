import streamlit as st
import requests

# URL of your FastAPI backend
API_URL = "http://127.0.0.1:8000"

st.title("📄 AI Policy Agent")

# --- Sidebar: File Management ---
st.sidebar.header("Document Knowledge Base")

# --- Refresh Button ---
if st.sidebar.button("🔄 Refresh List"):
    pass
    #st.experimental_rerun()

# --- Select Document ---
files_res = requests.get(f"{API_URL}/files")
available_docs = files_res.json().get("documents", [])

selected_doc = st.sidebar.selectbox(
    "Select Document to Chat With:", 
    available_docs,
    index=None,
    placeholder="Choose a file..."
)

if selected_doc:
    st.sidebar.success(f"Active: {selected_doc}")
    # Pass 'selected_doc' to your chat API payload
    # payload = { "query": prompt, "filter_filename": selected_doc }

# 1. Upload New File
uploaded_file = st.sidebar.file_uploader("Upload a PDF", type="pdf")
if uploaded_file:
    if st.sidebar.button("Process & Index"):
        with st.spinner("Uploading and Indexing..."):
            files = {"file": (uploaded_file.name, uploaded_file, "application/pdf")}
            response = requests.post(f"{API_URL}/upload", files=files)
            if response.status_code == 200:
                st.sidebar.success("File Indexed!")
            else:
                st.sidebar.error("Upload failed")

# 2. View Available Files
st.sidebar.subheader("Current Documents")
try:
    files_res = requests.get(f"{API_URL}/files")
    files_list = files_res.json().get("files", [])
    st.sidebar.write(files_list)
except:
    st.sidebar.error("Backend not connected")

# --- Main Chat Interface ---

# Initialize chat history in Streamlit session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# User Input
if prompt := st.chat_input("Ask a question..."):
    # 1. Display user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Send to FastAPI
    # Prepare Payload
    payload = {
        "query": prompt,
        "session_id": "streamlit_user_1", # Simple ID for now
        "target_file": selected_doc if selected_doc else None
    }

    # Call FastAPI
    with st.chat_message("assistant"):
        try:
            res = requests.post(f"{API_URL}/ask", json=payload)
            data = res.json()
            
            answer = data["answer"]
            sources = data.get("source", [])
            
            st.markdown(answer)
            if sources:
                st.caption(f"📚 Sources: {', '.join(sources)}")
                
            st.session_state.messages.append({"role": "assistant", "content": answer})
            
        except Exception as e:
            st.error(f"Error: {e}")

"""
Tools to be used by Text_Agent. 

This primarily exists for extracting of information from text documents, and store them in a vector database.
"""

import os
import magic
import fitz

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

def extract_text_from_documents(file_path: str):
    """Extracts text from a digital .pdf, .doc or .docx files."""
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def vectorize_and_store(text: str):
    """Vectorizes the input text and stores them in a vector DB."""
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50
    )

    chunks = text_splitter.split_text(text)

    embedding_model = HuggingFaceEmbeddings(
        model_name=os.getenv('EMBEDDING_MODEL')
    )

    persist_dir = "./vector_db"
    vector_db = Chroma.from_texts(
        texts=chunks,
        embedding=embedding_model,
        persist_directory=persist_dir
    )

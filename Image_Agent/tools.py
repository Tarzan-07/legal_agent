"""
Image_Agent implementation. This will use the tools specified in .tools.py
"""

import base64
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_core.messages import HumanMessage
from langchain_litellm.embeddings import LiteLLMEmbeddings

import os
import litellm

model = os.getenv("OPENROUTER_VISION_MODEL")

def _encode_image(image_path: str):
    """Base 64 encoding of the image."""
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')
    
# def _vision_model():
#     model = os.getenv("OPENROUTER_VISION_MODEL")
#     return model

def extract_text_from_image(image_path: str):
    """Extract image from base 64 encoded image."""
    base64_image = _encode_image(image_path)
    message = HumanMessage(
        content=[
            {'type': 'text', 'text': 'Extract all text from this image. Preserve layout, headings, and tables using markdown format.'},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
        ]
    )

    response = litellm.completion(
        model=model,
        messages=message,
    )

    extracted_text = response.choices[0].message.content

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = text_splitter.split_text(extracted_text)

    openrouter_embeddings = LiteLLMEmbeddings(
        model=f'openrouter/{os.getenv('EMBEDDING_MODEL')}',
        api_key=os.getenv('OPENROUTER_API_KEY'),
        api_base=os.getenv('OPENROUTER_API_BASE')
    )

    vector_db = Chroma.from_texts(
        texts=chunks,
        embedding=openrouter_embeddings,
        persist_directory="./openrouter_vector_db"
    )


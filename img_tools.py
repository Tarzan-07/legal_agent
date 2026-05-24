"""
Tools for processing images. These tools will be used by agents.
"""

import base64
import os
import litellm

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_core.messages import HumanMessage
from langchain_openai import OpenAIEmbeddings
from ent_types import (
    Entity,
    Relationship,
    ExtractionResult
)

embed_model = os.getenv("EMBED_MODEL")
vis_model = os.getenv("VIS_MODEL")

def _encode_images(file_path: str):
    with open(file_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')

def extract_text_from_imgs(image_path: str):
    b64_img = _encode_images(image_path)
    message = HumanMessage(
        content=[
            {'type': 'text', 'text': 'Extract all text from this image. Preserve layout, headings, and tables using markdown format. '},
            {'type': 'image_url', 'image_url': {'url': f"data:image/jpeg;base64, {b64_img}"}}
        ]
    )

    response = litellm.completion(
        model=vis_model,
        messages=message,
    )

    extracted_text = response.choices[0].message.content
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
    )
    chunks = text_splitter.split_text(extracted_text)

    embeddings = OpenAIEmbeddings(
        model=f"openrouter/{embed_model}",
        api_key=f"{os.getenv('OPENROUTER_API_KEY')}",
        base_url="https://openrouter.ai/api/v1",
    )

    vector_db = Chroma.from_texts(
        texts=chunks,
        embedding=embeddings,
        persist_directory='./openrouter_vector_db'
    )
import base64
import litellm
import os
import logging
from dotenv import load_dotenv
from typing import List
from neo4j import GraphDatabase
from legal_prompts import LEGAL_EXTRACTION_PROMPT

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_core.messages import HumanMessage
from langchain_openai import OpenAIEmbeddings
from ent_types import (
    Entity,
    Relationship,
    ExtractionResult
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

PERSIST_DIR = "./vector_db"
NER_MODEL = os.getenv("NER_MODEL")
EMBED_MODEL = os.getenv("EMBED_MODEL")
VIS_MODEL = os.getenv("VIS_MODEL")

NEO4J_URI = os.getenv('NEO4J_URI')
NEO4J_USER = os.getenv('NEO4J_USER')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')

embed_model = OpenAIEmbeddings(
    model=EMBED_MODEL,
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

neo4j_driver = GraphDatabase.driver(uri=NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

def _encode_images(file_path: str):
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def create_chunks(pages: List[dict]):
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)

    chunks = []
    chunk_counter = 0
    for page in pages:
        text = page.get("text") if page else ""
        if text is None:
            text = ""
        if not isinstance(text, str):
            text = str(text)
        text = text.strip()
        if not text:
            logger.warning("Skipping empty page text")
            continue

        for chunk_text in splitter.split_text(text):
            chunk_counter += 1
            chunks.append({
                "text": chunk_text,
                "page": page.get("page", 1),
                "chunk_id": chunk_counter
            })

    logger.info(f"Created {len(chunks)} chunks")
    return chunks

def vectorize_and_store(chunks: List[dict], file_name):
    texts = []
    metadatas = []
    vector_db = None
    try:
        logger.info(f"Parsing metadata from chunks......")
        texts = [c["text"] for c in chunks]
        logger.info(f"Received the following texts: {texts}")
        metadatas = []
        for c in chunks:
            metadatas.append({
                "source": file_name,
                "chunk_id": c["chunk_id"],
                "page": c["page"]
            })
    except Exception as e:
        logger.debug(f"Unable to parse chunks for vectorization. {str(e)}")

    logger.info("Generating embeddings and storing in chroma...")
    try:
        vector_db = Chroma.from_texts(
            texts=texts,
            embedding=embed_model,
            metadatas=metadatas,
            persist_directory=PERSIST_DIR
        )
        logger.info("Vectorized and stored in chroma.")
    except Exception as e:
        logger.exception(f"Unable to store in Chroma: {str(e)}")
        return None

    return vector_db

def extract_text_from_imgs(image_path: str):
    b64_img = _encode_images(image_path)
    prompt = (
        "Extract all text from this image. Preserve layout, headings, and tables "
        "using markdown format. Return only the text.\n\n"
        f"Image data: data:image/jpeg;base64,{b64_img}"
    )

    message = HumanMessage(content=prompt)

    response = litellm.completion(
        model=f"openrouter/{VIS_MODEL}",
        messages=[message],
        max_tokens=2048,
        timeout=60
    )

    choice = response.choices[0]
    extracted_text = ""
    if hasattr(choice, "message"):
        extracted_text = choice.message.content or ""
    elif isinstance(choice, dict):
        extracted_text = choice.get("text") or choice.get("message", {}).get("content", "") or ""
    
    extracted_text = extracted_text.strip()
    if not extracted_text:
        logger.warning("LiteLLM returned empty text for image extraction")

    return [{"page": 1, "text": extracted_text}]

def process_images(file_path: str):
    logger.info(f"Starting processing for: {file_path}")
    pages = extract_text_from_imgs(file_path)
    chunks = create_chunks(pages)

    if not chunks:
        raise ValueError("No text was extracted from the image.")

    vector_db = vectorize_and_store(chunks, os.path.basename(file_path))
    if vector_db is None:
        raise RuntimeError("Vectorization failed: no embeddings produced")
    logger.info(f"Image processing complete: {len(chunks)} chunks for {file_path}")

    return {"status": "processed", "file": os.path.basename(file_path), "chunks": len(chunks)}
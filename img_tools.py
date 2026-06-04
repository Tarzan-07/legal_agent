import base64
import litellm
import os
import logging
from dotenv import load_dotenv
from typing import List, Optional
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

# Optional OCR backend: easyocr (better than Tesseract for many cases)
try:
    import easyocr
except Exception:
    easyocr = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

PERSIST_DIR = "./vector_db"
NER_MODEL = os.getenv("NER_MODEL")
# normalize embedding model (strip tags like ':free')
EMBED_MODEL = os.getenv("EMBED_MODEL") or ""
VIS_MODEL = os.getenv("VIS_MODEL") or ""

NEO4J_URI = os.getenv('NEO4J_URI')
NEO4J_USER = os.getenv('NEO4J_USER')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')

if not EMBED_MODEL:
    logger.warning("EMBED_MODEL is not set or empty. Embeddings will likely fail.")

embed_model = OpenAIEmbeddings(
    model=EMBED_MODEL,
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

neo4j_driver = GraphDatabase.driver(uri=NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def _encode_images(file_path: str):
    # kept for debugging; avoid sending base64 image data to text LLMs
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


def vectorize_and_store(chunks: List[dict], file_name: str):
    texts: List[str] = []
    metadatas = []
    vector_db = None
    try:
        logger.info("Parsing metadata from chunks......")
        texts = [c.get("text", "") for c in chunks]
        logger.info(f"Received the following texts: {texts}")
        for c in chunks:
            metadatas.append({
                "source": file_name,
                "chunk_id": c.get("chunk_id"),
                "page": c.get("page")
            })
    except Exception as e:
        logger.exception(f"Unable to parse chunks for vectorization: {e}")
        return None

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
        logger.exception(f"Unable to store in Chroma: {e}")
        return None

    return vector_db


def extract_text_from_imgs(image_path: str) -> List[dict]:
    """
    Extract text from image using an OCR backend (easyocr preferred).
    Then return a list of pages with text for downstream chunking.
    """
    # prefer easyocr (no Tesseract). If not available, fallback to litellm vision parsing
    if easyocr is not None:
        try:
            reader = easyocr.Reader(["en"], gpu=False)
            ocr_result = reader.readtext(image_path, detail=0, paragraph=True)
            extracted_text = "\n".join([ln.strip() for ln in ocr_result if ln and isinstance(ln, str)])
            extracted_text = extracted_text.strip()
            if extracted_text:
                return [{"page": 1, "text": extracted_text}]
            else:
                logger.warning("EasyOCR returned empty text for %s, falling back to LLM", image_path)
        except Exception:
            logger.exception("EasyOCR failed, falling back to LLM parsing for %s", image_path)

    # Fallback: use vision LLM parsing but pass only a brief base64 or a small thumbnail to avoid huge context
    # Prepare model string for litellm: ensure provider is explicit or default to openrouter
    llm_model = VIS_MODEL
    if not llm_model:
        logger.error("VIS_MODEL not set; cannot call vision LLM")
        return [{"page": 1, "text": ""}]

    # If VIS_MODEL does not include a provider (no '/'), prefer openrouter if key exists
    if "/" not in llm_model:
        if os.getenv("OPENROUTER_API_KEY"):
            llm_model = f"openrouter/{llm_model}"
            logger.info("Normalized VIS model to %s", llm_model)
        else:
            logger.error("VIS_MODEL '%s' lacks a provider prefix and OPENROUTER_API_KEY not set", VIS_MODEL)
            return [{"page": 1, "text": ""}]

    try:
        b64_img = _encode_images(image_path)
        prompt = (
            "You are a vision-capable assistant. Extract and return only the plain text content "
            "from the following image. Preserve line breaks where meaningful.\n\n"
            f"Image data: data:image/jpeg;base64,{b64_img}"
        )
        message = HumanMessage(content=prompt)
        try:
            response = litellm.completion(
                model=llm_model,
                messages=[message],
                max_tokens=2048,
                timeout=60
            )
        except Exception as exc:
            # surface more helpful debug for provider selection issues
            logger.exception("Vision LLM call failed (model=%s): %s", llm_model, exc)
            return [{"page": 1, "text": ""}]

        choice = response.choices[0]
        extracted_text = ""
        if hasattr(choice, "message"):
            extracted_text = choice.message.content or ""
        elif isinstance(choice, dict):
            extracted_text = choice.get("text") or choice.get("message", {}).get("content", "") or ""
        extracted_text = extracted_text.strip()
        if not extracted_text:
            logger.warning("Vision LLM returned empty text for image extraction")
        return [{"page": 1, "text": extracted_text}]
    except Exception:
        logger.exception("Vision LLM extraction failed for %s", image_path)
        return [{"page": 1, "text": ""}]


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
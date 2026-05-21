"""
Some helper function to be used during upload.
"""

import os
import magic
import fitz
import spacy
import logging

from neo4j import GraphDatabase

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

spacy.require_gpu()
nlp = spacy.load("en_core_web_trf")

EMBED_MODEL_NAME = os.getenv('EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
embed_model = HuggingFaceEmbeddings(
    model_name=EMBED_MODEL_NAME,
    model_kwargs={'device': 'cuda'},  # Forces embedding generation onto your GPU
    encode_kwargs={'normalize_embeddings': True}
)

PERSIST_DIR = "./vector_db"

NEO4J_URI = os.getenv('NEO4J_URI')
NEO4J_USER = os.getenv('NEO4J_URI')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

def extract_text_from_digital_docs(file_path: str):
    """Extracts text from a digital .pdf, .doc, .docx"""
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def vectorize_and_store(text: str, file_name):
    """Vectorizes the input text and stores in vector DB"""
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50
    )

    chunks = text_splitter.split_text(text)
    metadatas = [{'source': file_name, 'chunk_idx': i} for i in range(len(chunks))]

    vector_db = Chroma.from_texts(
        texts=chunks,
        embedding=embed_model,
        metadatas=metadatas,
        persist_directory=PERSIST_DIR
    )

    return vector_db

def store_entities_in_neo4j(tx, file_name: str, entities: str):
    """
    Cypher transaction unit block to uniquely merge a Document node, 
    Entity nodes, and build directional relationships.
    """

    doc_query = "MERGE (d:Document {name: $file_name})"
    tx.run(doc_query, file_name=file_name)

    entity_query = """
    UNWIND $entities AS ent
    MERGE (e:Entity {text: ent.text})
    ON CREATE SET e.label = ent.label
    WITH e
    MATCH (d:Document {name: $file_name})
    MERGE (e) - [:MENTIONED_IN]->(d)
    """

    tx.run(entity_query, entities=entities, file_name=file_name)

def process_and_graph_doc(file_path: str):
    file_name = os.path.basename(file_path)

    text = extract_text_from_digital_docs(file_path)
    if not text.strip():
        logger.warning(f"File {file_name} yielded zero text content. Skipping.")
        return
    
    logger.info(f"Vectorizing and chunking text from {file_name}...")
    vectorize_and_store(text, file_name)

    logger.info(f"Extracting structural entity layers from {file_name}...")
    doc = nlp(text)

    seen_entites = set()
    entites_payload = []

    for ent in doc.ents:
        cleaned_text = ent.text.strip()
        entity_key = (cleaned_text, ent.label_)
        if entity_key not in seen_entites and ent.text.strip():
            seen_entites.add(entity_key)
            entites_payload.append({
                "text": ent.text.strip(),
                "label": ent.label_
            })

    with neo4j_driver.session() as session:
        session.execute_write(store_entities_in_neo4j, file_name, entites_payload)
    logger.info(f"Successfully populated graph with {len(entites_payload)} entities from {file_name}.")

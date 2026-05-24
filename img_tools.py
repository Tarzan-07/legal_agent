"""
Tools for processing images. These tools will be used by agents.
"""

import base64
import os
import litellm
import logging

from dotenv import load_dotenv
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

embed_model = os.getenv("EMBED_MODEL")
vis_model = os.getenv("VIS_MODEL")

NEO4J_URI = os.getenv('NEO4J_URI')
NEO4J_USER = os.getenv('NEO4J_USER')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')

neo4j_driver = GraphDatabase.driver(uri=NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

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

def extract_entities_and_relationships(chunk: dict):
    """
    Run LLM extraction on a single chunk.
    """

    logger.info(f"Extracting entities from {chunk['chunk_id']}")
    response = litellm.completion(
        model=NER_MODEL,
        api_key=os.getenv("OPENROUTER_API_KEY"),
        api_base="https://openrouter.ai/api/v1",
        temperature=0,
        max_tokens=2000,
        response_format=ExtractionResult,
        messages=[
            {
                'role': 'system',
                'content': LEGAL_EXTRACTION_PROMPT
            },
            {
                'role': 'user',
                'content': f"""
Chunk ID: {chunk['chunk_id']}
Page: {chunk['page']}

TEXT:
{chunk['text']}
"""
            }
        ]
    )

    content = response.choices[0].message.content
    if isinstance(content, str):
        return ExtractionResult.model_validate_json(content)
    
    return content

def normalize_entity_name(name: str) -> str:
    """
    Normalize entity names for deduplication.
    """

    return "".join(name.lower().strip().split())

def deduplicate_entities(entities: List[Entity]):
    seen = set(); deduped = []
    for ent in entities:
        key = (
            normalize_entity_name(ent.text),
            ent.type.upper()
        )

        if key not in seen:
            seen.add(key)
            deduped.append(ent)
    return deduped

def store_graph_data(tx, file_name, chunk, extraction):
    """
    Store entities + relationships + provenance
    """

    # Document node

    tx.run(
        """
        MERGE (d: Document {name: $file_name})
        """,
        file_name=file_name
    )

    # Chunk node

    tx.run(
        """
        MERGE (c:Chunk {chunk_id: $chunk_id})

        SET c.page = $page,
            c.text = $text

        WITH c

        MATCH (d:Document {
            name: $file_name
        })

        MERGE (c)-[:PART_OF]->(d)
        """,
        chunk_id = chunk['chunk_id'],
        page=chunk['page'],
        text=chunk['text'],
        file_name=file_name
    )

    # ENTITY NODES

    for ent in extraction.entities:

        tx.run(
            """
            MERGE (e:Entity {
                canonical_name: $canonical_name,
                type: $type
            })

            SET e.original_text = $original_text

            WITH e

            MATCH (c:Chunk {
                chunk_id: $chunk_id
            })

            MERGE (e)-[:EXTRACTED_FROM]->(c)
            """,
            canonical_name=normalize_entity_name(ent.text),
            original_text=ent.text,
            type=ent.type.upper(),
            chunk_id=chunk["chunk_id"]
        )

        # RELATIONSHIPS

        entity_lookup = {
        ent.id: ent
        for ent in extraction.entities
    }

    for rel in extraction.relationships:

        source_ent = entity_lookup.get(rel.source)
        target_ent = entity_lookup.get(rel.target)

        if not source_ent or not target_ent:
            continue

        tx.run(
            f"""
            MATCH (s:Entity {{
                canonical_name: $source_name,
                type: $source_type
            }})

            MATCH (t:Entity {{
                canonical_name: $target_name,
                type: $target_type
            }})

            MERGE (s)-[:{rel.relation.upper()}]->(t)
            """,
            source_name=normalize_entity_name(source_ent.text),
            source_type=source_ent.type.upper(),
            target_name=normalize_entity_name(target_ent.text),
            target_type=target_ent.type.upper()
        )
def process_document(file_path: str):

    file_name = os.path.basename(file_path)

    logger.info(f"Starting processing for: {file_name}")

    # ---------------------------------------------
    # EXTRACT TEXT
    # ---------------------------------------------

    pages = extract_text_from_digital_docs(file_path)

    if not pages:
        logger.warning("No text extracted.")
        return

    # ---------------------------------------------
    # CHUNK
    # ---------------------------------------------

    chunks = create_chunks(pages)

    # ---------------------------------------------
    # VECTORIZE
    # ---------------------------------------------

    vectorize_and_store(chunks, file_name)

    logger.info("Vector storage complete.")

    # ---------------------------------------------
    # GRAPH EXTRACTION
    # ---------------------------------------------

    all_entities = []

    with neo4j_driver.session() as session:
        for chunk in chunks:
            try:
                extraction = extract_entities_and_relationships(
                    chunk
                )
                extraction.entities = deduplicate_entities(
                    extraction.entities
                )
                all_entities.extend(extraction.entities)
                session.execute_write(
                    store_graph_data,
                    file_name,
                    chunk,
                    extraction
                )
            except Exception as e:
                logger.exception(
                    f"Chunk processing failed: {chunk['chunk_id']} | {e}"
                )

    logger.info(
        f"Completed processing for {file_name}"
    )
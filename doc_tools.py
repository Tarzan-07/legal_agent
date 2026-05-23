"""
Legal document ingestion + GraphRAG preparation pipeline.

Features:
- PDF text extraction
- Chunking
- GPU embeddings
- Chroma vector storage
- LLM-based legal entity + relationship extraction
- Neo4j graph construction
- Provenance tracking
- Deduplication + normalization

Recommended architecture:
Document -> Chunk -> Extract -> Vectorize -> Graph
"""

import os
import magic
import fitz
import spacy
import logging
import litellm

from typing import List, Optional
from neo4j import GraphDatabase
from pydantic import BaseModel, Field

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

# spacy.require_gpu()
# nlp = spacy.load("en_core_web_trf")

NER_MODEL = os.getenv("NER_MODEL")
EMBED_MODEL_NAME = os.getenv('EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2')
embed_model = HuggingFaceEmbeddings(
    model_name=EMBED_MODEL_NAME,
    model_kwargs={'device': 'cuda'},  # Forces embedding generation onto your GPU
    encode_kwargs={'normalize_embeddings': True}
)

PERSIST_DIR = "./vector_db"

class Entity(BaseModel):
    id: str = Field(description="Unique entity identifier.")
    text: str = Field(description="The exact text of the named entity extracted from the documents.")
    type: str = Field(description="Entity type")
    normalized_value: Optional[str] = None
    confidence: Optional[float] = None
    # label: str = Field(description="The category of the entity (e.g, PERSON, ORG, GPE, DATE, MONEY, LAW).")

class Relationship(BaseModel):
    source: str = Field(description="Source entity ID")
    target: str = Field(description="Target entity ID")
    relation: str = Field(description="Relationship type")

class ExtractionResult(BaseModel):
    entities = List[Entity]
    relationships = List[Relationship]

NEO4J_URI = os.getenv('NEO4J_URI')
NEO4J_USER = os.getenv('NEO4J_USER')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

def extract_text_from_digital_docs(file_path: str):
    """Extracts text from a digital .pdf, .doc, .docx"""
    logger.info(f"Extracting text from: {file_path}")
    pages = []
    doc = fitz.open(file_path)
    
    for page_num, page in enumerate(doc):
        text = page.get_text()
        if text.strip():
            pages.append(
                {
                    "page": page_num+1,
                    "text": text
                }
            )
    return pages

def create_chunks(pages: List[dict]) -> List[dict]:
    """
    Split extracted text into sematic chunks.
    """

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1200,
        chunk_overlap=200
    )

    chunks = []; chunk_counter = 0

    for page in pages:
        split_chunks = splitter.split_text(page['text'])
        for chunk in split_chunks:
            chunks.append(
                {
                    "chunk_id": f"chunk_{chunk_counter}",
                    "page": page['page'],
                    "text": chunk
                }
            )

            chunk_counter += 1
    logger.info(f"Created {len(chunks)} chunks")
    return chunks

def vectorize_and_store(chunks: List[dict], file_name):
    """Vectorizes the input text and stores in vector DB"""
    texts = [c['text'] for c in chunks]
    metadatas = []
    # metadatas = [{'source': file_name, 'chunk_idx': i} for i in range(len(chunks))]
    for c in chunks:
        metadatas.append(
            {
                'source': file_name,
                'chunk_id': c['chunk_id'],
                'page': c['page']
            }
        )

    logger.info("Generating embeddings and storing in chroma...")

    vector_db = Chroma.from_texts(
        texts=chunks,
        embedding=embed_model,
        metadatas=metadatas,
        persist_directory=PERSIST_DIR
    )

    return vector_db

LEGAL_EXTRACTION_PROMPT = """
You are a legal document information extraction engine.

Your task is to extract:

1. Legal entities
2. Relationships between entities
3. Financial terms
4. Legal obligations
5. Governing laws
6. Dates and deadlines
7. Contract references
8. Compliance references
9. Jurisdictions
10. Amendments

Preserve exact wording from the source.

Do NOT summarize.

Return STRICT JSON only.

========================
ENTITY TYPES
========================

- PARTY
- ORGANIZATION
- CONTRACT
- INVOICE
- CLAUSE
- PAYMENT_TERM
- MONEY
- EFFECTIVE_DATE
- TERMINATION_DATE
- LAW
- REGULATION
- JURISDICTION
- OBLIGATION
- SIGNATORY
- VENDOR
- CUSTOMER
- AMENDMENT

========================
RELATIONSHIP TYPES
========================

- SIGNED_BY
- GOVERNED_BY
- REFERENCES
- AMENDS
- ISSUED_TO
- REQUIRES
- OBLIGATES
- PAYS
- EFFECTIVE_ON
- TERMINATES_ON
- BELONGS_TO

========================
RULES
========================

- Extract only information explicitly present.
- Do not hallucinate.
- Preserve source wording exactly.
- Use stable IDs.
- Include relationships whenever possible.
"""

def extract_entities_and_relationships(chunk: dict) -> ExtractionResult:
    """
    Run LLM extraction on a single chunk
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


# =========================================================
# ENTRYPOINT
# =========================================================

if __name__ == "__main__":

    sample_file = "./sample_contract.pdf"

    process_document(sample_file)
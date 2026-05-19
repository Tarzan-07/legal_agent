"""
Text_Agent implementation. This will use the tools specified in .tools.py
"""

import os
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from .tools import (
    extract_text_from_documents,
    vectorize_and_store
)

litellm_model = LiteLlm(
    model=f'openrouter/{os.getenv('ORC_MODEL')}',
    api_key=os.getenv('OPENROUTER_API_KEY'),
    api_base=os.getenv('OPENROUTER_API_BASE')
)

agent = Agent(
    name="Text_Agent",
    model=litellm_model,
    instruction="""
You are an agent with specialty in text documents. You primarily deal with .pdf, .doc and .docx files.
Your primary purpose is to extract text from specified document types, vectorize it and store them in 
a vector DB. Do not pass any commentary. 
""",
    description="Agent that extracts text, vectorizes and stores them in a vector DB.",
    tools=[extract_text_from_documents, vectorize_and_store]
)
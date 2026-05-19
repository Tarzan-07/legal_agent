"""
Central/root agent. Handles other handles other agents.
"""

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
import os
import litellm


model = os.getenv('ORC_MODEL')
litellm_model = LiteLlm(
    model=f'openrouter/{model}',
    api_key=os.getenv('OPENROUTER_API_KEY'),
    api_base=os.getenv('OPENROUTER_API_BASE')
)

agent = Agent(
    name="Central_Agent",
    model=litellm_model,
    instruction="""\
You are the main central/orchestrating agent. You mainly deal with legal documents, invoices, contracts,
and the likes. For this purpose, you have few sub-agents at your disposal. The main workflow goes by this:

After a file gets uploaded, it first gets classified as text document or an image. Meaning, files with
.pdf, .doc and .docx extensions are considered as text document, whereas files with .png, .jpg, .jpeg, .webp
and .tiff are considered image documents. You must delegate that document to the respective sub-agent.
To process text documents, you must use text agent. To process image documents, you must use image agent.
These two agents are available to you as sub-agents. Use appropriately. 

When a user asks a question from the uploaded documents, you must answer them based on the uploaded documents 
only. No need to share any commentary. And if you don't have relevant information, you must simply answer that 
you don't have relevant information. Nothing more, Nothing less. 
""",
    description="Answers questions regarding invoices, contracts and legal documents.",
    sub_agents=[text_agent, image_agent]
)
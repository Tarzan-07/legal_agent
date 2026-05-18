"""
Central/root agent. Handles other handles other agents.
"""

from google.adk.agents import Agent
import os
import litellm

agent = Agent(
    name="Central Agent"
)
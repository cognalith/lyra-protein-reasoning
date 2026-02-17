import os
import logging
from openai import AzureOpenAI

logger = logging.getLogger(__name__)

# Azure OpenAI setup
client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
    timeout=60.0,
    max_retries=3,
)

def run_agent(query: str) -> str:
    """Simple agent that answers protein questions."""

    system_prompt = """You are Lyra, a protein research assistant.
    You help scientists understand protein structures and drug targets.
    Be concise and scientific."""

    response = client.chat.completions.create(
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
    )

    return response.choices[0].message.content

# Test it
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    query = "What makes a protein a good drug target? Answer in 3 bullet points."
    logger.info("Query: %s", query)
    logger.info("Lyra: %s", run_agent(query))

import os
from openai import AzureOpenAI

# Azure OpenAI setup
client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-15-preview"
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
    query = "What makes a protein a good drug target? Answer in 3 bullet points."
    print("Query:", query)
    print("\nLyra:", run_agent(query))

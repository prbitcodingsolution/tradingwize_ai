import os
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from openai import OpenAI
from openai import AsyncOpenAI
from dotenv import load_dotenv
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL")

# Configure provider without timeout (not supported)
provider = OpenAIProvider(
    api_key=OPENROUTER_API_KEY, 
    base_url=OPENROUTER_BASE_URL
)
model = OpenAIModel(provider=provider, model_name="openai/gpt-oss-120b")

# Create a standard OpenAI client for direct usage (e.g. in tools.py)
client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url=OPENROUTER_BASE_URL,
    timeout=90.0  # 90 second timeout for direct client
)

def get_model():
    return model

def get_client():
    return client
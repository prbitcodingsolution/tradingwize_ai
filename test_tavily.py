import os
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file
from pydantic_ai import Agent
from pydantic_ai.common_tools.tavily import tavily_search_tool
from utils.model_config import get_model

api_key = os.getenv('TAVILY_API_KEY')
assert api_key is not None

agent = Agent(
    get_model(),
    tools=[tavily_search_tool(api_key)],
    instructions='Search Tavily for the given query and return the results.',
)

result = agent.run_sync('Tell me the top news in the GenAI world, give me links.')
print(result.output)
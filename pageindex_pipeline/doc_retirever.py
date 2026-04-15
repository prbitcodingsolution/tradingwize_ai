from pageindex import PageIndexClient
from dotenv import load_dotenv
import os   
load_dotenv()

pi_client = PageIndexClient(api_key=os.getenv("PAGEINDEX_API_KEY"))
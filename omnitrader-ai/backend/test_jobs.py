import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from app.api.ingestion import get_active_jobs
import asyncio

print(asyncio.run(get_active_jobs()))

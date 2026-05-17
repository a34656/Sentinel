import json
from fastapi import APIRouter
from pydantic import BaseModel
from loguru import logger
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from core.config import config

router = APIRouter()

class IncidentRequest(BaseModel):
    prompt: str

PLANNER_SYSTEM_PROMPT = """You are a Genesis Planning Agent.
Your job is to read an incident report (prompt) and generate a proposed investigation plan and a draft python script for the initial investigation.
The output MUST be valid JSON with two keys:
1. "plan": a list of strings, each string is a step in the proposed investigation plan. Keep it between 3 and 6 steps.
2. "script": a string containing a python script using pymongo to start the investigation. It should include the typical boilerplate:
```python
import os, sys
from pymongo import MongoClient

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB  = os.getenv("MONGODB_DB", "genesis_compliance")

try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    db = client[MONGODB_DB]
    print("Connected:", MONGODB_DB)
except Exception as e:
    print("CONNECTION FAILED:", e)
    sys.exit(1)

# your investigation code here
```
Only return valid JSON. Do not include markdown fences around the JSON.
"""

@router.post("/api/plan")
async def generate_plan(req: IncidentRequest):
    logger.info(f"[Planner] Generating plan for: {req.prompt[:80]}")
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-lite",
        google_api_key=config.GEMINI_API_KEY,
        temperature=0,
    )
    
    messages = [
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        HumanMessage(content=f"Incident Prompt: {req.prompt}")
    ]
    
    try:
        response = llm.invoke(messages)
        content = response.content
        # Try to parse json, remove markdown fences if present
        if content.startswith("```json"):
            content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
        elif content.startswith("```"):
            content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
        
        parsed = json.loads(content.strip())
        return {
            "plan": parsed.get("plan", ["Investigate incident"]),
            "script": parsed.get("script", "# investigate.py\n# generated script here")
        }
    except Exception as exc:
        logger.error(f"[Planner] Failed to generate plan: {exc}")
        return {
            "plan": [
                "Snapshot current cluster state and isolate suspect namespace",
                "Replay billing telemetry through anomaly detector (window: 6h)",
                "Cross-reference deploy manifest with IAM diff",
                "Validate hypothesis against PolicyGuard rule set"
            ],
            "script": "# investigate.py \n# Default fallback script\nimport os\nprint('Investigation started...')"
        }

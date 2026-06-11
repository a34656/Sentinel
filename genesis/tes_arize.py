# save as test_arize.py in your genesis folder
import os
from dotenv import load_dotenv
load_dotenv()

print("ARIZE_SPACE_ID:", os.getenv("ARIZE_SPACE_ID", "NOT SET"))
print("ARIZE_API_KEY:", os.getenv("ARIZE_API_KEY", "NOT SET")[:10] + "...")
print("ARIZE_PROJECT_NAME:", os.getenv("ARIZE_PROJECT_NAME", "NOT SET"))

from arize.otel import register
# from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor
from openinference.instrumentation.langchain import LangChainInstrumentor


tracer_provider = register(
    space_id=os.environ["ARIZE_SPACE_ID"],
    api_key=os.environ["ARIZE_API_KEY"],
    project_name=os.environ.get("ARIZE_PROJECT_NAME", "genesis-compliance"),
    endpoint="https://otlp.eu-west-1a.arize.com",
)
LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
print("Instrumentation done")

# Make a real Gemini call so a trace is generated
from langchain_google_genai import ChatGoogleGenerativeAI
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite",
    google_api_key=os.getenv("GEMINI_API_KEY"),
    temperature=0,
)
response = llm.invoke("Say hello in one word.")
print("Gemini response:", response.content)
print("Check app.arize.com in 30 seconds for traces")

import time

# After the Gemini call, force flush before exit
print("Flushing traces...")
tracer_provider.force_flush()
time.sleep(3)
print("Done — check app.arize.com now")             
from agents.engineer import _run_in_sandbox

script = '''
import subprocess
subprocess.run(["pip", "install", "pymongo", "-q"], check=True)

import os
import sys
from pymongo import MongoClient

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB  = os.getenv("MONGODB_DB", "genesis_compliance")

print("URI present:", bool(MONGODB_URI))

try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client[MONGODB_DB]
    print("Connected:", MONGODB_DB)
    for name in db.list_collection_names():
        print(name, ":", db[name].count_documents({}))
except Exception as e:
    print("FAILED:", e)
    sys.exit(1)
'''

result = _run_in_sandbox(script)
print("SUCCESS:", result["success"])
print("OUTPUT:", result["output"])
print("STDERR:", result["stderr"])

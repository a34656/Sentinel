import subprocess, sys

# 1. Auto-install required packages quietly
print("Verifying requirements...")
subprocess.run([sys.executable, '-m', 'pip', 'install', 'pymongo', 'python-dotenv', 'pandas', '-q'], check=True)

import os
import pandas as pd
from pymongo import MongoClient
from dotenv import load_dotenv

# 2. Load environment variables
load_dotenv()

# 3. Connect to MongoDB Atlas
print("Connecting to database...")
client_uri = os.getenv("MONGODB_URI")

if not client_uri:
    print("ERROR: MONGODB_URI is not set in your .env file!")
    sys.exit(1)

client = MongoClient(client_uri)
db = client[os.getenv("MONGODB_DB", "genesis_compliance")]

print(f"Connected to: {db.name}\n")

# --- 4. RUN THE TEST QUERIES ---

# Find all customer IDs where risk_tier is 'high'
high_risk = [c['customer_id'] for c in db['customers'].find({'risk_tier': 'high'}, {'customer_id': 1})]

# Find all employee IDs where role is 'analyst'
analysts = [e['emp_id'] for e in db['employees'].find({'role': 'analyst'}, {'emp_id': 1})]

# Find transactions where a high-risk customer was approved by an analyst
f4 = db['transactions'].count_documents({
    'customer_id': {'$in': high_risk},
    'approved_by': {'$in': analysts}
})

# --- 5. OUTPUT THE RESULTS ---
print("=== COMPLIANCE CHECK RESULTS ===")
print(f"High risk customers count : {len(high_risk)}")
print(f"Analyst employee IDs      : {analysts}")
print(f"Rule Violations (Finding 4): {f4}")
print("================================")

# Test 1: Read
print("=== Collections ===")
print(db.list_collection_names())

# Test 2: Count
for col in ['transactions', 'employees', 'customers', 'approval_log']:
    print(f"{col}: {db[col].count_documents({})} docs")

# Test 3: Sample role violation check
pipeline = [
    {"$lookup": {
        "from": "customers",
        "localField": "customer_id",
        "foreignField": "customer_id",
        "as": "customer"
    }},
    {"$unwind": "$customer"},
    {"$match": {"customer.risk_level": "HIGH"}},
    {"$lookup": {
        "from": "approval_log",
        "localField": "transaction_id",
        "foreignField": "transaction_id",
        "as": "approvals"
    }},
    {"$unwind": "$approvals"},
    {"$lookup": {
        "from": "employees",
        "localField": "approvals.approver_id",
        "foreignField": "employee_id",
        "as": "approver"
    }},
    {"$unwind": "$approver"},
    {"$match": {"approver.role": "analyst"}},
    {"$count": "role_violations"}
]

result = list(db.transactions.aggregate(pipeline))
print(f"\nFinding 4 (role violations): {result}")

# Test 4: Write flag
test_txn = db.transactions.find_one({})
if test_txn:
    res = db.transactions.update_one(
        {"_id": test_txn["_id"]},
        {"$set": {"genesis_test_flag": True}}
    )
    print(f"\nWrite test: modified {res.modified_count} doc")
    # Clean up
    db.transactions.update_one({"_id": test_txn["_id"]}, {"$unset": {"genesis_test_flag": ""}})
    print("Write/cleanup: OK")
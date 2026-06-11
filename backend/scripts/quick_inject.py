"""
quick_inject.py
───────────────
Run this if inject_anomalies.py produces no output.
Hardcoded connection — paste your actual URI and DB name below.

Usage:
    python scripts/quick_inject.py
"""
import os
import sys
import random
from datetime import datetime, timedelta
from pymongo import MongoClient
from faker import Faker
from dotenv import load_dotenv
from pymongo import MongoClient
import random

load_dotenv()
fake = Faker()
random.seed(99)

# ── PASTE YOUR VALUES HERE ─────────────────────────────────────────────────────
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB  = os.getenv("MONGODB_DB", "Cluster0")

print("Connecting...")
client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
client.admin.command("ping")
db = client[MONGODB_DB]
col = db["transactions"]
print(f"Connected. Transactions: {col.count_documents({}):,}")

# ── Get a pool of txn_ids to work with ────────────────────────────────────────
all_ids = [d["txn_id"] for d in col.find({}, {"txn_id": 1}).limit(5000)]
random.shuffle(all_ids)
pool = all_ids[:200]
print(f"Working pool: {len(pool)} transaction IDs")

# ── Finding 1: Tag missing approvals (already null, just tag them) ─────────────
f1_ids = pool[0:47]
col.update_many(
    {"txn_id": {"$in": f1_ids}},
    {"$set": {"_anomaly": "missing_approval", "status": "pending"}}
)
print(f"F1 missing_approval    : {col.count_documents({'_anomaly': 'missing_approval'})}")

# ── Finding 2: Ghost approvers ─────────────────────────────────────────────────
f2_ids    = pool[47:70]
ghost_ids = ["EMP9001", "EMP9002", "EMP9003"]
for txn_id in f2_ids:
    col.update_one(
        {"txn_id": txn_id},
        {"$set": {
            "approved_by": random.choice(ghost_ids),
            "status":      "approved",
            "_anomaly":    "ghost_approver",
        }}
    )
print(f"F2 ghost_approver      : {col.count_documents({'_anomaly': 'ghost_approver'})}")

# ── Finding 3: Inactive approvers ─────────────────────────────────────────────
inactive_emps = [e["emp_id"] for e in db["employees"].find({"role": "analyst"}).limit(2)]
db["employees"].update_many(
    {"emp_id": {"$in": inactive_emps}},
    {"$set": {"active": False}}
)
f3_ids = pool[70:88]
for txn_id in f3_ids:
    col.update_one(
        {"txn_id": txn_id},
        {"$set": {
            "approved_by": random.choice(inactive_emps),
            "status":      "approved",
            "_anomaly":    "inactive_approver",
        }}
    )
print(f"F3 inactive_approver   : {col.count_documents({'_anomaly': 'inactive_approver'})}")

# ── Finding 4: Role violations ─────────────────────────────────────────────────
high_risk_ids = [c["customer_id"] for c in db["customers"].find({"risk_level": "high"})]
analyst_ids   = [e["emp_id"] for e in db["employees"].find({"role": "analyst", "active": True})]
f4_ids = [
    d["txn_id"] for d in col.find(
        {"customer_id": {"$in": high_risk_ids}, "_anomaly": {"$exists": False}}
    ).limit(31)
]
for txn_id in f4_ids:
    col.update_one(
        {"txn_id": txn_id},
        {"$set": {
            "approved_by": random.choice(analyst_ids) if analyst_ids else "EMP0001",
            "status":      "approved",
            "_anomaly":    "role_violation",
        }}
    )
print(f"F4 role_violation      : {col.count_documents({'_anomaly': 'role_violation'})}")

# ── Finding 5: Missing audit trail ────────────────────────────────────────────
f5_ids = pool[100:129]
for txn_id in f5_ids:
    col.update_one(
        {"txn_id": txn_id},
        {"$set": {
            "approved_by": "EMP0004",
            "status":      "approved",
            "_anomaly":    "missing_audit_trail",
            # intentionally NO approval_log entry written
        }}
    )
print(f"F5 missing_audit_trail : {col.count_documents({'_anomaly': 'missing_audit_trail'})}")

# ── Write approval_log for clean transactions only ────────────────────────────
approved_no_trail = col.distinct("txn_id", {"_anomaly": "missing_audit_trail"})
clean_approved = list(col.find({
    "status":   "approved",
    "_anomaly": {"$nin": ["missing_audit_trail"]},
    "approved_by": {"$exists": True, "$ne": None},
}))

log_docs = [{
    "txn_id":    t["txn_id"],
    "emp_id":    t["approved_by"],
    "action":    "approved",
    "timestamp": t.get("approved_at", "2025-01-01T00:00:00"),
} for t in clean_approved]

if log_docs:
    db["approval_log"].insert_many(log_docs)

print(f"\napproval_log entries   : {db['approval_log'].count_documents({}):,}")
print(f"deactivated employees  : {db['employees'].count_documents({'active': False})}")
print("\n✅ All 5 findings planted. Run Genesis with Prompt 3 to find them.")
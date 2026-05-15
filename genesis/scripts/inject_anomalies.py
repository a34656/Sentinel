"""
inject_anomalies.py
───────────────────
Plants 5 categories of compliance violations into MongoDB.
Run AFTER load_data_mongo.py.

Violations injected:
  1. Transactions with approved_by = null         (missing approvals)
  2. approved_by = ghost employee IDs             (non-existent approvers)
  3. Inactive employees who approved transactions (deactivated staff)
  4. High-risk customers approved by analysts     (role violation)
  5. Transactions with no approval_log entry      (broken audit trail)

Usage:
    pip install pymongo faker python-dotenv
    python scripts/inject_anomalies.py

Expects in .env:
    MONGODB_URI=mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/
    MONGODB_DB=genesis_compliance
"""

import os
import sys
import random
from datetime import datetime, timedelta
from pymongo import MongoClient
from faker import Faker
from dotenv import load_dotenv

load_dotenv()
fake = Faker()
random.seed(99)

# ── Config ────────────────────────────────────────────────────────────────────

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB  = os.getenv("MONGODB_DB", "Cluster0")

# How many violations to plant per category
N = {
    "missing_approval":    47,   # txns where approved_by stays null
    "ghost_approvers":     23,   # txns approved by emp IDs that don't exist
    "inactive_approvers":  18,   # txns approved by deactivated employees
    "role_violations":     31,   # high-risk customers approved by analysts
    "missing_audit_trail": 29,   # txns with no approval_log entry
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_db():
    if not MONGODB_URI:
        sys.exit("❌  MONGODB_URI not set in .env")
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    print("✅  Connected to MongoDB Atlas")
    return client[MONGODB_DB]


def sample_txn_ids(col, n: int, query: dict = None) -> list:
    """Return n random txn_ids matching query."""
    pipeline = [
        {"$match": query or {}},
        {"$sample": {"size": n}},
        {"$project": {"txn_id": 1}},
    ]
    return [doc["txn_id"] for doc in col.aggregate(pipeline)]


def random_past_date(days_back=90) -> str:
    dt = datetime.utcnow() - timedelta(days=random.randint(1, days_back))
    return dt.isoformat()


# ── Violation 1: Missing approvals ───────────────────────────────────────────

def inject_missing_approvals(db):
    """
    Leave approved_by = null on a subset of transactions.
    The loader already sets everything to null, so we just make sure
    we DON'T fill these in. We tag them so we can verify later.
    """
    print("\n[1/5] Marking missing-approval transactions…")
    col = db["transactions"]

    ids = sample_txn_ids(col, N["missing_approval"])
    result = col.update_many(
        {"txn_id": {"$in": ids}},
        {"$set": {"_anomaly": "missing_approval", "status": "pending"}}
    )
    print(f"  Tagged {result.modified_count} transactions with approved_by = null")


# ── Violation 2: Ghost approvers ──────────────────────────────────────────────

def inject_ghost_approvers(db):
    """
    Set approved_by to employee IDs that don't exist in the employees collection.
    """
    print("\n[2/5] Injecting ghost approver IDs…")
    col_txn = db["transactions"]

    ghost_ids = [f"EMP{str(9000 + i).zfill(4)}" for i in range(10)]  # IDs 9000-9009

    ids = sample_txn_ids(col_txn, N["ghost_approvers"],
                         {"_anomaly": {"$exists": False}})

    for txn_id in ids:
        col_txn.update_one(
            {"txn_id": txn_id},
            {"$set": {
                "approved_by": random.choice(ghost_ids),
                "approved_at": random_past_date(),
                "status":      "approved",
                "_anomaly":    "ghost_approver",
            }}
        )
    print(f"  Injected {len(ids)} transactions with non-existent approver IDs")
    print(f"  Ghost IDs used: {ghost_ids[:3]}… (none exist in employees collection)")


# ── Violation 3: Inactive approvers ──────────────────────────────────────────

def inject_inactive_approvers(db):
    """
    Deactivate 2 employees, then assign them as approvers on real transactions.
    """
    print("\n[3/5] Deactivating employees + injecting their approvals…")
    col_emp = db["employees"]
    col_txn = db["transactions"]

    # Deactivate 2 analysts
    inactive = list(col_emp.find({"role": "analyst", "active": True}).limit(2))
    if len(inactive) < 2:
        print("  ⚠️  Not enough active analysts found — skipping")
        return

    inactive_ids = [e["emp_id"] for e in inactive]
    col_emp.update_many(
        {"emp_id": {"$in": inactive_ids}},
        {"$set": {"active": False, "deactivated_at": random_past_date(180)}}
    )
    print(f"  Deactivated: {inactive_ids}")

    ids = sample_txn_ids(col_txn, N["inactive_approvers"],
                         {"_anomaly": {"$exists": False}})
    for txn_id in ids:
        col_txn.update_one(
            {"txn_id": txn_id},
            {"$set": {
                "approved_by": random.choice(inactive_ids),
                "approved_at": random_past_date(),
                "status":      "approved",
                "_anomaly":    "inactive_approver",
            }}
        )
    print(f"  Injected {len(ids)} approvals by deactivated employees")


# ── Violation 4: Role violations (analyst approved high-risk) ─────────────────

def inject_role_violations(db):
    """
    Find high-risk customers, find their transactions,
    set approved_by to an analyst (who lacks authority).
    """
    print("\n[4/5] Injecting role violations (analyst approved high-risk customers)…")
    col_cust = db["customers"]
    col_txn  = db["transactions"]
    col_emp  = db["employees"]

    # Get high-risk customer IDs
    high_risk = [c["customer_id"] for c in col_cust.find({"risk_level": "high"})]
    if not high_risk:
        print("  ⚠️  No high-risk customers found — skipping")
        return

    # Get active analyst IDs
    analysts = [e["emp_id"] for e in col_emp.find({"role": "analyst", "active": True})]
    if not analysts:
        print("  ⚠️  No active analysts found — skipping")
        return

    # Find transactions for high-risk customers that haven't been tagged yet
    pipeline = [
        {"$match": {
            "customer_id": {"$in": high_risk},
            "_anomaly": {"$exists": False}
        }},
        {"$sample": {"size": N["role_violations"]}},
        {"$project": {"txn_id": 1}},
    ]
    ids = [doc["txn_id"] for doc in col_txn.aggregate(pipeline)]

    for txn_id in ids:
        col_txn.update_one(
            {"txn_id": txn_id},
            {"$set": {
                "approved_by": random.choice(analysts),
                "approved_at": random_past_date(),
                "status":      "approved",
                "_anomaly":    "role_violation",
            }}
        )
    print(f"  Injected {len(ids)} high-risk approvals by analysts (requires director)")


# ── Violation 5: Missing audit trail ─────────────────────────────────────────

def inject_missing_audit_trail(db):
    """
    Mark some transactions as approved but write NO approval_log entry.
    The remaining clean transactions DO get approval_log entries.
    """
    print("\n[5/5] Creating approval_log + injecting gaps…")
    col_txn = db["transactions"]
    col_log = db["approval_log"]
    col_emp = db["employees"]

    active_directors = [e["emp_id"] for e in
                        col_emp.find({"role": "director", "active": True})]
    if not active_directors:
        print("  ⚠️  No active directors found — skipping")
        return

    # Tag some clean transactions as "approved but log will be missing"
    clean_ids = sample_txn_ids(col_txn, N["missing_audit_trail"],
                               {"_anomaly": {"$exists": False}})
    for txn_id in clean_ids:
        col_txn.update_one(
            {"txn_id": txn_id},
            {"$set": {
                "approved_by": random.choice(active_directors),
                "approved_at": random_past_date(),
                "status":      "approved",
                "_anomaly":    "missing_audit_trail",
                # intentionally NO approval_log entry written below
            }}
        )

    # Write approval_log for ALL other approved transactions (the clean ones)
    approved_txns = list(col_txn.find({
        "status":   "approved",
        "_anomaly": {"$nin": ["missing_audit_trail"]},
        "approved_by": {"$exists": True, "$ne": None},
    }))

    log_docs = []
    for txn in approved_txns:
        log_docs.append({
            "txn_id":      txn["txn_id"],
            "emp_id":      txn.get("approved_by"),
            "action":      "approved",
            "timestamp":   txn.get("approved_at", random_past_date()),
            "ip_address":  fake.ipv4(),
            "notes":       "Standard approval",
        })

    if log_docs:
        col_log.insert_many(log_docs)

    print(f"  {len(clean_ids)} approved transactions have NO approval_log entry")
    print(f"  {len(log_docs)} legitimate approval_log entries written")


# ── Verification report ───────────────────────────────────────────────────────

def verify(db):
    col_txn = db["transactions"]
    col_log = db["approval_log"]
    col_emp = db["employees"]

    print("\n" + "=" * 55)
    print("  Verification — what Genesis should find")
    print("=" * 55)

    checks = [
        ("Missing approvals (approved_by null)",
         col_txn.count_documents({"approved_by": None})),

        ("Ghost approver transactions",
         col_txn.count_documents({"_anomaly": "ghost_approver"})),

        ("Inactive approver transactions",
         col_txn.count_documents({"_anomaly": "inactive_approver"})),

        ("Role violations (analyst → high-risk)",
         col_txn.count_documents({"_anomaly": "role_violation"})),

        ("Missing audit trail transactions",
         col_txn.count_documents({"_anomaly": "missing_audit_trail"})),

        ("Total transactions",
         col_txn.count_documents({})),

        ("Total approval_log entries",
         col_log.count_documents({})),

        ("Deactivated employees",
         col_emp.count_documents({"active": False})),
    ]

    for label, count in checks:
        flag = "🔴" if "violation" in label.lower() or "missing" in label.lower() \
                    or "ghost" in label.lower() or "inactive" in label.lower() \
                    or "deactivated" in label.lower() else "✅"
        print(f"  {flag}  {label:<45} {count:>6,}")

    print("=" * 55)
    print("\n  Run Genesis with Prompt 3 to find all of these.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  Genesis — Anomaly Injector")
    print("  Database:", MONGODB_DB)
    print("=" * 55)

    db = get_db()

    # Sanity check — transactions must exist
    txn_count = db["transactions"].count_documents({})
    if txn_count == 0:
        sys.exit("❌  No transactions found.\n"
                 "    Run load_data_mongo.py first.")
    print(f"\n  Found {txn_count:,} transactions — proceeding with injection")

    inject_missing_approvals(db)
    inject_ghost_approvers(db)
    inject_inactive_approvers(db)
    inject_role_violations(db)
    inject_missing_audit_trail(db)

    verify(db)


if __name__ == "__main__":
    main()
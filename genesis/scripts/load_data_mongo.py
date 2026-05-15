"""
load_data_mongo.py
──────────────────
Loads HI-Small_Trans.csv (IBM AML dataset) into MongoDB Atlas.
Collections created: transactions, employees, customers

Usage:
    pip install pymongo pandas python-dotenv
    python scripts/load_data_mongo.py

Expects in .env:
    MONGODB_URI=mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/
    MONGODB_DB=genesis_compliance
"""

import os
import sys
import pandas as pd
from datetime import datetime
from pymongo import MongoClient, InsertOne, ASCENDING
from pymongo.errors import BulkWriteError
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB  = os.getenv("MONGODB_DB", "genesis_compliance")
CSV_PATH    = os.path.join(os.path.dirname(__file__), "..", "data", "HI-Small_Trans.csv")
BATCH_SIZE  = 1000  # rows per bulk insert

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_db():
    if not MONGODB_URI:
        sys.exit("❌  MONGODB_URI not set in .env")
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    # Verify connection
    client.admin.command("ping")
    print("✅  Connected to MongoDB Atlas")
    return client[MONGODB_DB]


def bulk_insert(collection, docs: list, label: str):
    """Insert in batches, skip duplicates."""
    total = 0
    for i in range(0, len(docs), BATCH_SIZE):
        batch = docs[i : i + BATCH_SIZE]
        requests = [InsertOne(d) for d in batch]
        try:
            result = collection.bulk_write(requests, ordered=False)
            total += result.inserted_count
        except BulkWriteError as e:
            # Count only successful inserts
            total += e.details.get("nInserted", 0)
        pct = min(100, int((i + len(batch)) / len(docs) * 100))
        print(f"  {label}: {pct}% ({total} inserted)", end="\r")
    print(f"  {label}: done — {total} documents inserted          ")
    return total


# ── Step 1: Load transactions ─────────────────────────────────────────────────

def load_transactions(db):
    print("\n📂  Loading transactions from CSV…")

    if not os.path.exists(CSV_PATH):
        sys.exit(f"❌  CSV not found at {CSV_PATH}\n"
                 "    Download HI-Small_Trans.csv from Kaggle and place it at genesis/data/")

    df = pd.read_csv(CSV_PATH, nrows=50000)
    print(f"    Rows in CSV: {len(df):,}")

    # Normalise column names (IBM CSV uses spaces)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Expected IBM AML columns (adapt if yours differ slightly)
    col_map = {
        "timestamp":            "timestamp",
        "from_bank":            "from_bank",
        "from_id":              "from_account",
        "to_bank":              "to_bank",
        "to_id":                "to_account",
        "amount_received":      "amount_received",
        "receiving_currency":   "receiving_currency",
        "amount_paid":          "amount_paid",
        "payment_currency":     "payment_currency",
        "payment_format":       "payment_format",
        "is_laundering":        "is_laundering",
    }
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)

    # Add fields Genesis agents will use
    df["txn_id"]      = ["TXN" + str(i).zfill(8) for i in range(len(df))]
    df["approved_by"] = None          # intentionally null — anomaly injector fills some
    df["status"]      = "pending"
    df["customer_id"] = "CUST" + (df.index % 500).astype(str).str.zfill(5)
    df["created_at"]  = datetime.utcnow().isoformat()

    docs = df.to_dict("records")

    col = db["transactions"]
    col.drop_indexes()
    col.create_index([("txn_id", ASCENDING)], unique=True)
    col.create_index([("approved_by", ASCENDING)])
    col.create_index([("customer_id", ASCENDING)])
    col.create_index([("is_laundering", ASCENDING)])

    return bulk_insert(col, docs, "transactions")


# ── Step 2: Seed employees ────────────────────────────────────────────────────

def load_employees(db):
    print("\n👷  Seeding employees…")

    employees = []
    roles = [
        ("analyst",  False),   # cannot approve high-risk
        ("analyst",  False),
        ("analyst",  False),
        ("director", True),    # can approve anything
        ("director", True),
        ("director", True),
        ("analyst",  False),
        ("analyst",  False),
        ("director", True),
        ("analyst",  False),
    ]
    for i, (role, can_approve_high_risk) in enumerate(roles):
        employees.append({
            "emp_id":                f"EMP{str(i+1).zfill(4)}",
            "name":                  f"Employee {i+1}",
            "role":                  role,
            "active":                True,   # anomaly injector deactivates some
            "can_approve_high_risk": can_approve_high_risk,
            "department":            "compliance",
            "created_at":            datetime.utcnow().isoformat(),
        })

    col = db["employees"]
    col.drop_indexes()
    col.create_index([("emp_id", ASCENDING)], unique=True)

    return bulk_insert(col, employees, "employees")


# ── Step 3: Seed customers ────────────────────────────────────────────────────

def load_customers(db):
    print("\n🧑  Seeding customers…")

    import random
    random.seed(42)

    risk_levels = ["low", "medium", "high"]
    customers = []
    for i in range(500):
        customers.append({
            "customer_id": f"CUST{str(i).zfill(5)}",
            "name":        f"Customer {i}",
            "risk_level":  random.choices(risk_levels, weights=[60, 25, 15])[0],
            "kyc_status":  random.choice(["verified", "pending", "failed"]),
            "created_at":  datetime.utcnow().isoformat(),
        })

    col = db["customers"]
    col.drop_indexes()
    col.create_index([("customer_id", ASCENDING)], unique=True)
    col.create_index([("risk_level", ASCENDING)])

    return bulk_insert(col, customers, "customers")


# ── Step 4: Create approval_log (empty — injector fills it) ──────────────────

def create_approval_log(db):
    print("\n📋  Creating approval_log collection…")
    col = db["approval_log"]
    col.drop_indexes()
    col.create_index([("txn_id", ASCENDING)])
    col.create_index([("emp_id", ASCENDING)])
    # Insert a placeholder so collection exists
    col.insert_one({"_placeholder": True, "created_at": datetime.utcnow().isoformat()})
    col.delete_many({"_placeholder": True})
    print("  approval_log: ready (empty, anomaly injector will populate)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  Genesis — MongoDB Data Loader")
    print("  Database:", MONGODB_DB)
    print("=" * 55)

    db = get_db()

    txn_count  = load_transactions(db)
    emp_count  = load_employees(db)
    cust_count = load_customers(db)
    create_approval_log(db)

    print("\n" + "=" * 55)
    print("  ✅  Load complete")
    print(f"     transactions : {txn_count:,}")
    print(f"     employees    : {emp_count}")
    print(f"     customers    : {cust_count}")
    print("=" * 55)
    print("\n  Next step: python scripts/inject_anomalies.py")


if __name__ == "__main__":
    main()

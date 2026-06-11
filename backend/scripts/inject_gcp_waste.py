"""
inject_gcp_waste.py
-------------------
Plants 5 realistic GCP waste categories into BigQuery.
Mimics the schema of a real Cloud Billing + Cloud Monitoring export.

Run ONCE before starting the agent:
    python scripts/inject_gcp_waste.py

Waste categories injected:
    W1  idle_vm            : 12  VMs with CPU < 3% for 14+ days
    W2  oversized_vm       : 8   VMs using < 15% of provisioned RAM
    W3  overprovisioned_cr : 6   Cloud Run services with 0 requests in 7 days
    W4  orphaned_storage   : 9   GCS buckets not accessed in 90+ days
    W5  expensive_bq       : 11  BigQuery jobs scanning > 100GB repeatedly
"""

import os
import json
import random
from datetime import datetime, timedelta
from google.cloud import bigquery

PROJECT_ID = os.environ["GCP_PROJECT_ID"]
DATASET    = os.environ.get("BQ_DATASET", "genesis_cost")
client     = bigquery.Client(project=PROJECT_ID)

# ── helpers ──────────────────────────────────────────────────────────────────

def create_dataset():
    ds = bigquery.Dataset(f"{PROJECT_ID}.{DATASET}")
    ds.location = "US"
    client.create_dataset(ds, exists_ok=True)
    print(f"✅  Dataset {DATASET} ready")

def drop_and_create(table_id: str, schema: list[bigquery.SchemaField]):
    full = f"{PROJECT_ID}.{DATASET}.{table_id}"
    client.delete_table(full, not_found_ok=True)
    tbl = bigquery.Table(full, schema=schema)
    client.create_table(tbl)
    print(f"   Created {table_id}")
    return full

def insert(full_id: str, rows: list[dict]):
    errs = client.insert_rows_json(full_id, rows)
    if errs:
        raise RuntimeError(f"Insert errors: {errs}")
    print(f"   Inserted {len(rows)} rows → {full_id.split('.')[-1]}")

# ── W1  idle_vm ───────────────────────────────────────────────────────────────

def inject_idle_vms():
    schema = [
        bigquery.SchemaField("instance_id",   "STRING"),
        bigquery.SchemaField("instance_name", "STRING"),
        bigquery.SchemaField("zone",          "STRING"),
        bigquery.SchemaField("machine_type",  "STRING"),
        bigquery.SchemaField("avg_cpu_7d",    "FLOAT"),
        bigquery.SchemaField("avg_cpu_14d",   "FLOAT"),
        bigquery.SchemaField("monthly_cost",  "FLOAT"),
        bigquery.SchemaField("last_active",   "TIMESTAMP"),
        bigquery.SchemaField("status",        "STRING"),
    ]
    full = drop_and_create("vm_cpu_utilization", schema)

    zones   = ["us-central1-a", "us-east1-b", "europe-west1-c", "asia-east1-a"]
    mtypes  = ["n1-standard-4", "n1-standard-8", "n2-standard-4", "e2-standard-4"]
    costs   = {"n1-standard-4": 97.09, "n1-standard-8": 194.18,
                "n2-standard-4": 97.09, "e2-standard-4": 65.27}

    rows = []
    # 12 idle VMs (W1 anomalies)
    for i in range(1, 13):
        mt = random.choice(mtypes)
        rows.append({
            "instance_id":   f"inst-{1000 + i}",
            "instance_name": f"worker-{i:02d}",
            "zone":          random.choice(zones),
            "machine_type":  mt,
            "avg_cpu_7d":    round(random.uniform(0.5, 2.8), 2),   # < 3%
            "avg_cpu_14d":   round(random.uniform(0.3, 2.5), 2),   # < 3%
            "monthly_cost":  costs[mt],
            "last_active":   (datetime.utcnow() - timedelta(days=random.randint(14, 45))).isoformat(),
            "status":        "RUNNING",
        })
    # 8 healthy VMs (not anomalies)
    for i in range(13, 21):
        mt = random.choice(mtypes)
        rows.append({
            "instance_id":   f"inst-{1000 + i}",
            "instance_name": f"api-server-{i:02d}",
            "zone":          random.choice(zones),
            "machine_type":  mt,
            "avg_cpu_7d":    round(random.uniform(35.0, 78.0), 2),
            "avg_cpu_14d":   round(random.uniform(30.0, 72.0), 2),
            "monthly_cost":  costs[mt],
            "last_active":   datetime.utcnow().isoformat(),
            "status":        "RUNNING",
        })
    insert(full, rows)

# ── W2  oversized_vm ──────────────────────────────────────────────────────────

def inject_oversized_vms():
    schema = [
        bigquery.SchemaField("instance_id",        "STRING"),
        bigquery.SchemaField("instance_name",       "STRING"),
        bigquery.SchemaField("machine_type",        "STRING"),
        bigquery.SchemaField("provisioned_ram_gb",  "FLOAT"),
        bigquery.SchemaField("avg_ram_used_gb",     "FLOAT"),
        bigquery.SchemaField("ram_utilization_pct", "FLOAT"),
        bigquery.SchemaField("monthly_cost",        "FLOAT"),
        bigquery.SchemaField("recommended_type",    "STRING"),
        bigquery.SchemaField("potential_saving",    "FLOAT"),
    ]
    full = drop_and_create("vm_memory_utilization", schema)

    oversized = [
        ("inst-2001", "ml-pipeline-01",  "n1-standard-16", 60.0,  4.1,  "n1-standard-4",  145.64),
        ("inst-2002", "batch-processor", "n1-standard-32", 120.0, 9.2,  "n1-standard-8",  291.27),
        ("inst-2003", "data-export-svc", "n2-standard-16", 64.0,  5.8,  "n2-standard-4",  145.64),
        ("inst-2004", "legacy-etl",      "n1-standard-16", 60.0,  3.3,  "n1-standard-4",  145.64),
        ("inst-2005", "nightly-job",     "n1-standard-8",  30.0,  2.1,  "n1-standard-2",  48.55),
        ("inst-2006", "report-gen",      "n2-standard-8",  32.0,  4.0,  "n2-standard-2",  48.55),
        ("inst-2007", "kafka-consumer",  "n1-standard-16", 60.0,  6.8,  "n1-standard-4",  145.64),
        ("inst-2008", "sync-worker",     "n1-standard-8",  30.0,  1.9,  "n1-standard-2",  48.55),
    ]
    rows = []
    for iid, name, mtype, ram, used, rec, saving in oversized:
        rows.append({
            "instance_id":        iid,
            "instance_name":      name,
            "machine_type":       mtype,
            "provisioned_ram_gb": ram,
            "avg_ram_used_gb":    used,
            "ram_utilization_pct": round(used / ram * 100, 1),
            "monthly_cost":       round(ram * 3.24, 2),
            "recommended_type":   rec,
            "potential_saving":   saving,
        })
    insert(full, rows)

# ── W3  overprovisioned_cloud_run ─────────────────────────────────────────────

def inject_cloud_run():
    schema = [
        bigquery.SchemaField("service_name",      "STRING"),
        bigquery.SchemaField("region",             "STRING"),
        bigquery.SchemaField("cpu_limit",          "STRING"),
        bigquery.SchemaField("memory_limit",       "STRING"),
        bigquery.SchemaField("max_instances",      "INTEGER"),
        bigquery.SchemaField("requests_7d",        "INTEGER"),
        bigquery.SchemaField("last_request_time",  "TIMESTAMP"),
        bigquery.SchemaField("monthly_cost",       "FLOAT"),
        bigquery.SchemaField("anomaly_type",       "STRING"),
    ]
    full = drop_and_create("cloud_run_metrics", schema)

    regions = ["us-central1", "us-east1", "europe-west1"]
    rows = []

    # 6 dead services (W3 anomalies)
    dead = [
        ("auth-service-v1",    "us-central1", "2", "512Mi", 10,  0,  91, 43.20, "zero_requests_90d"),
        ("legacy-webhook",     "us-east1",    "2", "1Gi",   20,  2,  21, 86.40, "near_zero_requests"),
        ("analytics-v2",       "europe-west1","4", "2Gi",   50,  0,  67, 172.80,"zero_requests_67d"),
        ("notification-svc",   "us-central1", "1", "256Mi", 10,  1,  14, 21.60, "near_zero_requests"),
        ("export-worker",      "us-east1",    "8", "4Gi",   100, 0,  45, 345.60,"zero_requests_45d"),
        ("staging-api",        "us-central1", "2", "512Mi", 30,  3,  10, 64.80, "near_zero_requests"),
    ]
    for name, region, cpu, mem, max_inst, reqs, days_ago, cost, atype in dead:
        rows.append({
            "service_name":     name,
            "region":           region,
            "cpu_limit":        cpu,
            "memory_limit":     mem,
            "max_instances":    max_inst,
            "requests_7d":      reqs,
            "last_request_time":(datetime.utcnow() - timedelta(days=days_ago)).isoformat(),
            "monthly_cost":     cost,
            "anomaly_type":     atype,
        })

    # 5 healthy services
    for i in range(1, 6):
        rows.append({
            "service_name":     f"prod-api-{i}",
            "region":           random.choice(regions),
            "cpu_limit":        "2",
            "memory_limit":     "512Mi",
            "max_instances":    20,
            "requests_7d":      random.randint(50000, 500000),
            "last_request_time":datetime.utcnow().isoformat(),
            "monthly_cost":     round(random.uniform(80, 250), 2),
            "anomaly_type":     "healthy",
        })
    insert(full, rows)

# ── W4  orphaned_storage ──────────────────────────────────────────────────────

def inject_orphaned_storage():
    schema = [
        bigquery.SchemaField("bucket_name",        "STRING"),
        bigquery.SchemaField("location",           "STRING"),
        bigquery.SchemaField("storage_class",      "STRING"),
        bigquery.SchemaField("size_gb",            "FLOAT"),
        bigquery.SchemaField("object_count",       "INTEGER"),
        bigquery.SchemaField("last_access_days",   "INTEGER"),
        bigquery.SchemaField("monthly_cost",       "FLOAT"),
        bigquery.SchemaField("has_lifecycle_rule", "BOOL"),
        bigquery.SchemaField("anomaly_type",       "STRING"),
    ]
    full = drop_and_create("gcs_bucket_usage", schema)

    rows = []
    # 9 orphaned buckets (W4 anomalies)
    orphans = [
        ("logs-archive-2021",   "US",          "STANDARD",         890.0,  12450000, 520, True,  "ancient_logs"),
        ("ml-experiments-old",  "US-CENTRAL1", "STANDARD",         1240.0, 890000,   180, False, "stale_ml_data"),
        ("staging-backups",     "US",          "STANDARD",         340.0,  23000,    95,  False, "orphaned_backups"),
        ("temp-data-etl",       "EU",          "STANDARD",         78.0,   4500,     120, False, "forgotten_temp"),
        ("dev-snapshots-2022",  "US",          "NEARLINE",         2100.0, 560,      400, True,  "ancient_snapshots"),
        ("test-artifacts",      "US-EAST1",    "STANDARD",         45.0,   89000,    200, False, "stale_test_data"),
        ("old-terraform-state", "US-CENTRAL1", "STANDARD",         1.2,    340,      300, False, "stale_iac"),
        ("export-dumps-q1-23",  "US",          "STANDARD",         670.0,  1200,     400, False, "orphaned_export"),
        ("analytics-raw-2022",  "US",          "COLDLINE",         3400.0, 8900000,  365, True,  "ancient_analytics"),
    ]
    for name, loc, cls, sz, cnt, days, lifecycle, cost_per_gb, atype in [
        (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]) for r in orphans
    ]:
        monthly = round(sz * 0.020, 2)  # $0.02/GB standard
        rows.append({
            "bucket_name":        name,
            "location":           loc,
            "storage_class":      cls,
            "size_gb":            sz,
            "object_count":       cnt,
            "last_access_days":   days,
            "monthly_cost":       monthly,
            "has_lifecycle_rule": lifecycle,
            "anomaly_type":       atype,
        })

    # 5 active buckets
    for i in range(1, 6):
        sz = round(random.uniform(10, 500), 1)
        rows.append({
            "bucket_name":        f"prod-assets-{i}",
            "location":           "US",
            "storage_class":      "STANDARD",
            "size_gb":            sz,
            "object_count":       random.randint(1000, 100000),
            "last_access_days":   random.randint(0, 3),
            "monthly_cost":       round(sz * 0.020, 2),
            "has_lifecycle_rule": True,
            "anomaly_type":       "healthy",
        })
    insert(full, rows)

# ── W5  expensive_bq_jobs ─────────────────────────────────────────────────────

def inject_bq_jobs():
    schema = [
        bigquery.SchemaField("job_id",          "STRING"),
        bigquery.SchemaField("user_email",       "STRING"),
        bigquery.SchemaField("query_preview",    "STRING"),
        bigquery.SchemaField("bytes_processed",  "INTEGER"),
        bigquery.SchemaField("gb_processed",     "FLOAT"),
        bigquery.SchemaField("estimated_cost",   "FLOAT"),
        bigquery.SchemaField("run_count_30d",    "INTEGER"),
        bigquery.SchemaField("total_cost_30d",   "FLOAT"),
        bigquery.SchemaField("has_partition_filter", "BOOL"),
        bigquery.SchemaField("anomaly_type",     "STRING"),
    ]
    full = drop_and_create("bq_job_history", schema)

    rows = []
    # 11 expensive jobs (W5 anomalies)
    bad_jobs = [
        ("job_001", "analyst@co.com",  "SELECT * FROM events WHERE date > '2020-01-01'",
         320_000_000_000, False, "full_table_scan"),
        ("job_002", "ml@co.com",       "SELECT * FROM raw_logs",
         890_000_000_000, False, "full_table_scan"),
        ("job_003", "bi@co.com",       "SELECT user_id, COUNT(*) FROM pageviews GROUP BY 1",
         145_000_000_000, False, "missing_partition_filter"),
        ("job_004", "analyst@co.com",  "SELECT * FROM transactions JOIN users ON ...",
         230_000_000_000, False, "no_partition_no_cluster"),
        ("job_005", "etl@co.com",      "CREATE TABLE AS SELECT * FROM archive_2021",
         560_000_000_000, False, "full_archive_scan"),
        ("job_006", "reporting@co.com","SELECT * FROM billing_export",
         78_000_000_000,  False, "full_table_scan"),
        ("job_007", "analyst@co.com",  "SELECT *, UNNEST(items) FROM orders",
         190_000_000_000, False, "unnest_without_filter"),
        ("job_008", "bi@co.com",       "SELECT date, revenue FROM daily_metrics WHERE year=2022",
         110_000_000_000, False, "missing_partition_filter"),
        ("job_009", "ml@co.com",       "SELECT * FROM feature_store",
         430_000_000_000, False, "full_table_scan"),
        ("job_010", "etl@co.com",      "SELECT * FROM raw_events WHERE event_type='click'",
         670_000_000_000, False, "full_table_scan_with_filter"),
        ("job_011", "analyst@co.com",  "SELECT DISTINCT user_id FROM sessions",
         95_000_000_000,  False, "distinct_without_cluster"),
    ]
    for jid, user, query, bytes_p, part, atype in bad_jobs:
        gb   = round(bytes_p / 1e9, 1)
        cost = round(gb * 0.005, 2)          # $5/TB
        runs = random.randint(3, 25)
        rows.append({
            "job_id":              jid,
            "user_email":          user,
            "query_preview":       query,
            "bytes_processed":     bytes_p,
            "gb_processed":        gb,
            "estimated_cost":      cost,
            "run_count_30d":       runs,
            "total_cost_30d":      round(cost * runs, 2),
            "has_partition_filter":part,
            "anomaly_type":        atype,
        })

    # 5 efficient jobs
    for i in range(1, 6):
        gb = round(random.uniform(0.5, 5.0), 1)
        runs = random.randint(10, 100)
        rows.append({
            "job_id":              f"job_ok_{i:03d}",
            "user_email":          f"svc-account-{i}@co.com",
            "query_preview":       f"SELECT id, ts FROM events WHERE DATE(ts) = @run_date LIMIT 1000",
            "bytes_processed":     int(gb * 1e9),
            "gb_processed":        gb,
            "estimated_cost":      round(gb * 0.005, 2),
            "run_count_30d":       runs,
            "total_cost_30d":      round(gb * 0.005 * runs, 2),
            "has_partition_filter":True,
            "anomaly_type":        "efficient",
        })
    insert(full, rows)

# ── summary ───────────────────────────────────────────────────────────────────

def print_summary():
    print("\n" + "="*55)
    print("  GCP WASTE INJECTION COMPLETE")
    print("="*55)
    summary = {
        "W1 idle_vm            (avg_cpu < 3%, 14d+)": 12,
        "W2 oversized_vm       (RAM util < 15%)":      8,
        "W3 overprovisioned_CR (0 requests 7d+)":      6,
        "W4 orphaned_storage   (no access 90d+)":      9,
        "W5 expensive_bq_jobs  (scan > 100GB)":        11,
    }
    total_waste = 0
    for label, count in summary.items():
        print(f"  {label}: {count}")
    print("-"*55)
    print(f"  Total anomalous resources    : {sum(summary.values())}")
    print(f"  BigQuery dataset             : {PROJECT_ID}.{DATASET}")
    print("="*55)

if __name__ == "__main__":
    print(f"🚀  Injecting GCP waste data → {PROJECT_ID}.{DATASET}")
    create_dataset()
    inject_idle_vms()
    inject_oversized_vms()
    inject_cloud_run()
    inject_orphaned_storage()
    inject_bq_jobs()
    print_summary()
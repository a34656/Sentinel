import requests
import json

url = "http://127.0.0.1:8000/api/incident"
headers = {"Content-Type": "application/json"}
data = {"prompt": "Our fintech company has an external audit tomorrow. Investigate our MongoDB database — specifically the transactions, employees, customers, and approval_log collections. Find missing approvals, approvals by non-existent or inactive employees, high-risk customers approved by junior staff, and incomplete audit trails. Report every compliance violation you find with evidence."}

print("Sending request...")
with requests.post(url, headers=headers, json=data, stream=True) as r:
    for line in r.iter_lines():
        if line:
            print(line.decode('utf-8'))

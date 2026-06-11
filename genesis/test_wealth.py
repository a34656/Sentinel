import requests
import json

url = "http://127.0.0.1:8000/api/incident"
headers = {"Content-Type": "application/json"}
data = {
    "prompt": "Analyse our client portfolio data for risk concentrations, generate personalized wealth management recommendations, and flag anomalous trading patterns. Use the CSV file directly."
}

print("Sending request...")

with requests.post(url, headers=headers, json=data, stream=True) as r:
    for line in r.iter_lines():
        if line:
            decoded = line.decode("utf-8")
            if not decoded.startswith("data: "):
                continue
            try:
                evt = json.loads(decoded[6:])
            except:
                continue

            etype = evt.get("type", "")

            if etype == "graph_data":
                s = evt.get("summary", {})
                print(f"\n✅ WEALTH DATA RECEIVED")
                print(f"   Clients (nodes): {len(evt.get('nodes', []))}")
                print(f"   Flows (edges):   {len(evt.get('edges', []))}")
                print(f"   Summary: {json.dumps(s, indent=4)}")
                print(f"\n   Top suspects:")
                for i, sus in enumerate(evt.get("suspects", [])[:5], 1):
                    print(f"   {i}. {sus.get('client', sus.get('account', '?'))} | score={sus.get('wealth_score', sus.get('score', '?'))} | {sus.get('actions', sus.get('patterns', []))[:1]}")

            elif etype == "step":
                for log in evt.get("step_log", []):
                    print(log[:150])

            elif etype == "awaiting_script_approval":
                print(f"\n⏸  APPROVAL NEEDED: {evt.get('what_it_does', '')}")
                print(f"   Reasoning: {evt.get('reasoning', '')[:100]}")
                choice = input("   Approve? [y/n] (default y): ").strip().lower()
                if choice != "n":
                    incident_id = evt.get("incident_id", "")
                    approve_url = f"http://127.0.0.1:8000/api/incident/{incident_id}/approve-script"
                    requests.post(approve_url)
                    print("   ✅ Approved")
                else:
                    incident_id = evt.get("incident_id", "")
                    reject_url = f"http://127.0.0.1:8000/api/incident/{incident_id}/reject-script"
                    requests.post(reject_url)
                    print("   ❌ Rejected")

            elif etype == "complete":
                print(f"\n✅ Investigation complete")
                print(f"   Root cause: {evt.get('root_cause', 'N/A')}")

            elif etype == "error":
                print(f"\n❌ Error: {evt.get('message', '')}")
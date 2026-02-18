import requests
import json

print("Testing API...")

# Test health endpoint
health = requests.get("http://localhost:8000/api/health")
print(f"Health: {health.json()}")

# List procedures  
procs = requests.get("http://localhost:8000/api/procedures")
print(f"Existing procedures: {len(procs.json())}")

# Import simple procedure
with open(r"c:\Users\karup\AGProjects\LangOrch\demo_procedures\simple_http_test.ckp.json") as f:
    ckp = json.load(f)

existing_proc = None
for proc in procs.json():
    if proc.get("procedure_id") == ckp["procedure_id"] and proc.get("version") == ckp["version"]:
        existing_proc = proc
        break

payload = {
    "procedure_id": ckp["procedure_id"],
    "version": ckp["version"],
    "ckp_json": ckp
}

if existing_proc:
    print("\nImport result: skipped (already exists)")
    data = existing_proc
    print(f"Imported: {data['procedure_id']} v{data['version']}")
else:
    result = requests.post("http://localhost:8000/api/procedures", json=payload)
    print(f"\nImport result: {result.status_code}")
    if not result.ok:
        print(f"Error: {result.text}")
        raise SystemExit(1)
    data = result.json()
    print(f"Imported: {data['procedure_id']} v{data['version']}")

# Create a run
run_payload = {
    "procedure_id": data["procedure_id"],
    "procedure_version": data["version"],
    "input_vars": {"post_id": 42}
}
run_result = requests.post("http://localhost:8000/api/runs", json=run_payload)
if run_result.ok:
    run_data = run_result.json()
    print(f"\n✓ Run created: {run_data['run_id']}")
    print(f"View at: http://localhost:3000/runs/{run_data['run_id']}")
else:
    print(f"Run creation failed: {run_result.text}")

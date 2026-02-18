import requests
import json
import sys
from pathlib import Path

def import_procedure(ckp_file_path):
    """Import a CKP procedure via the API"""
    # Read the CKP file
    with open(ckp_file_path, 'r') as f:
        ckp_data = json.load(f)

    try:
        existing = requests.get("http://localhost:8000/api/procedures", timeout=10)
        existing.raise_for_status()
        for proc in existing.json():
            if proc.get("procedure_id") == ckp_data["procedure_id"] and proc.get("version") == ckp_data["version"]:
                print(f"ℹ Already imported: {proc['procedure_id']} v{proc['version']}")
                return proc
    except requests.exceptions.RequestException:
        pass
    
    # Prepare the API payload
    payload = {
        "procedure_id": ckp_data["procedure_id"],
        "version": ckp_data["version"],
        "ckp_json": ckp_data
    }
    
    # Call the API
    url = "http://localhost:8000/api/procedures"
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        print(f"✓ Imported: {result['procedure_id']} v{result['version']}")
        print(f"  Database ID: {result['id']}")
        return result
    except requests.exceptions.RequestException as e:
        print(f"✗ Error importing {ckp_file_path.name}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"  Response: {e.response.text}")
        sys.exit(1)

def create_run(procedure_id, version, input_vars):
    """Create a run for the imported procedure"""
    url = "http://localhost:8000/api/runs"
    payload = {
        "procedure_id": procedure_id,
        "procedure_version": version,
        "input_vars": input_vars
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        print(f"✓ Run created: {result['run_id']}")
        print(f"  Status: {result['status']}")
        print(f"  View at: http://localhost:3000/runs/{result['run_id']}")
        return result
    except requests.exceptions.RequestException as e:
        print(f"✗ Error creating run: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"  Response: {e.response.text}")
        sys.exit(1)

if __name__ == "__main__":
    base_path = Path(r"c:\Users\karup\AGProjects\LangOrch\demo_procedures")
    
    print("=" * 60)
    print("Importing Demo Procedures")
    print("=" * 60)
    
    # Import simple test
    print("\n1. Simple HTTP Test")
    simple_proc = import_procedure(base_path / "simple_http_test.ckp.json")
    
    # Import complex enrichment pipeline
    print("\n2. Product Enrichment Pipeline")
    enrichment_proc = import_procedure(base_path / "product_enrichment_pipeline.ckp.json")
    
    print("\n" + "=" * 60)
    print("Creating Test Runs")
    print("=" * 60)
    
    # Create a run for the simple test
    print("\n1. Running Simple HTTP Test (post_id=42)")
    simple_run = create_run("simple-http-test", "1.0.0", {"post_id": 42})
    
    # Create a run for the enrichment pipeline
    print("\n2. Running Product Enrichment (product_id=5, enrichment_mode=standard)")
    enrichment_run = create_run("product-enrichment-demo", "1.0.0", {
        "product_id": 5,
        "enrichment_mode": "standard"
    })
    
    print("\n" + "=" * 60)
    print("✓ All procedures imported and runs started!")
    print("=" * 60)
    print("\nOpen the frontend to watch execution:")
    print(f"  Simple test: http://localhost:3000/runs/{simple_run['run_id']}")
    print(f"  Enrichment: http://localhost:3000/runs/{enrichment_run['run_id']}")

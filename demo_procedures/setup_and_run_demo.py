"""
Complete demo setup: register agent, import procedures, create runs
"""
import requests
import json
import sys
from pathlib import Path
import time

BASE_URL = "http://localhost:8000/api"

def register_agent():
    """Register a demo agent with full capabilities"""
    agent_payload = {
        "agent_id": "demo-agent-001",
        "name": "Demo Agent",
        "url": "http://localhost:9000",
        "channel": "masteragent",
        "status": "online",
        "capabilities": [
            "web_navigation",
            "data_extraction",
            "form_filling",
            "api_calls",
            "screenshot",
            "pdf_parsing",
            "ocr",
            "file_download"
        ],
        "metadata": {
            "description": "Demo agent for testing workflows",
            "version": "1.0.0"
        }
    }
    
    try:
        # Check if agent already exists
        response = requests.get(f"{BASE_URL}/agents")
        existing_agents = response.json()
        
        # Delete if exists
        for agent in existing_agents:
            if agent.get("agent_id") == "demo-agent-001":
                print(f"  Removing existing agent: {agent['agent_id']}")
                requests.delete(f"{BASE_URL}/agents/{agent['id']}")
        
        # Register new agent
        response = requests.post(f"{BASE_URL}/agents", json=agent_payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        print(f"✓ Agent registered: {result['agent_id']}")
        print(f"  Name: {result['name']}")
        print(f"  Channel: {result['channel']}")
        print(f"  Capabilities: {len(result.get('capabilities', []))}")
        return result
    except requests.exceptions.RequestException as e:
        print(f"✗ Error registering agent: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"  Response: {e.response.text}")
        sys.exit(1)

def import_procedure(ckp_file_path):
    """Import a CKP procedure via the API"""
    with open(ckp_file_path, 'r') as f:
        ckp_data = json.load(f)

    try:
        existing = requests.get(f"{BASE_URL}/procedures", timeout=10)
        existing.raise_for_status()
        for proc in existing.json():
            if proc.get("procedure_id") == ckp_data["procedure_id"] and proc.get("version") == ckp_data["version"]:
                print(f"ℹ Already imported: {proc['procedure_id']} v{proc['version']}")
                return proc
    except requests.exceptions.RequestException:
        pass
    
    payload = {
        "procedure_id": ckp_data["procedure_id"],
        "version": ckp_data["version"],
        "ckp_json": ckp_data
    }
    
    try:
        response = requests.post(f"{BASE_URL}/procedures", json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        print(f"✓ Imported: {result['procedure_id']} v{result['version']}")
        return result
    except requests.exceptions.RequestException as e:
        print(f"✗ Error importing {ckp_file_path.name}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"  Response: {e.response.text}")
        sys.exit(1)

def create_run(procedure_id, version, input_vars):
    """Create a run for the imported procedure"""
    payload = {
        "procedure_id": procedure_id,
        "procedure_version": version,
        "input_vars": input_vars
    }
    
    try:
        response = requests.post(f"{BASE_URL}/runs", json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        print(f"✓ Run created: {result['run_id']}")
        print(f"  Status: {result['status']}")
        print(f"  View: http://localhost:3000/runs/{result['run_id']}")
        return result
    except requests.exceptions.RequestException as e:
        print(f"✗ Error creating run: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"  Response: {e.response.text}")
        sys.exit(1)

def check_server():
    """Check if backend server is running"""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=3)
        if response.json().get("status") == "ok":
            print("✓ Backend server is running\n")
            return True
    except:
        print("✗ Backend server is not running!")
        print("  Please start it with: cd backend && uvicorn app.main:app --reload")
        sys.exit(1)

if __name__ == "__main__":
    print("=" * 70)
    print("LangOrch Demo Setup")
    print("=" * 70)
    
    # Step 1: Check server
    print("\n1. Checking Backend Server")
    print("-" * 70)
    check_server()
    
    # Step 2: Register agent
    print("2. Registering Demo Agent")
    print("-" * 70)
    agent = register_agent()
    
    # Step 3: Import procedures
    print("\n3. Importing Procedures")
    print("-" * 70)
    base_path = Path(r"c:\Users\karup\AGProjects\LangOrch\demo_procedures")
    
    print("\n  a) Simple HTTP Test")
    simple_proc = import_procedure(base_path / "simple_http_test.ckp.json")
    
    print("\n  b) Product Enrichment Pipeline")
    enrichment_proc = import_procedure(base_path / "product_enrichment_pipeline.ckp.json")
    
    # Step 4: Create runs
    print("\n4. Creating Test Runs")
    print("-" * 70)
    
    print("\n  a) Simple HTTP Test (post_id=42)")
    simple_run = create_run("simple-http-test", "1.0.0", {"post_id": 42})
    
    print("\n  b) Product Enrichment (product_id=5)")
    enrichment_run = create_run("product-enrichment-demo", "1.0.0", {
        "product_id": 5,
        "enrichment_mode": "standard"
    })
    
    # Success summary
    print("\n" + "=" * 70)
    print("✓ Demo Setup Complete!")
    print("=" * 70)
    print("\nNext Steps:")
    print("-" * 70)
    print(f"1. Open frontend: http://localhost:3000/runs")
    print(f"\n2. Watch Simple Test execution:")
    print(f"   http://localhost:3000/runs/{simple_run['run_id']}")
    print(f"\n3. Watch Enrichment Pipeline execution:")
    print(f"   http://localhost:3000/runs/{enrichment_run['run_id']}")
    print(f"\n4. The enrichment workflow will pause at approval gate")
    print(f"   Go to: http://localhost:3000/approvals")
    print(f"   And approve/reject the enrichment")
    print("\n" + "=" * 70)

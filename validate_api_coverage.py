#!/usr/bin/env python3
"""
Cross-validate frontend API calls against backend OpenAPI schema.
Identifies:
1. Frontend calls to non-existent backend routes
2. Backend routes not used by frontend
3. Method mismatches (GET vs POST etc)
"""
import json
import re
from pathlib import Path
from collections import defaultdict

def extract_backend_routes(openapi_path: Path):
    """Parse OpenAPI schema and extract all routes with their methods."""
    with open(openapi_path, encoding='utf-8') as f:
        content = f.read()
        # Skip any log lines at the beginning
        if not content.strip().startswith('{'):
            # Find first {
            start = content.find('{')
            if start > 0:
                content = content[start:]
        schema = json.loads(content)
    
    routes = defaultdict(list)
    for path, methods_obj in schema.get("paths", {}).items():
        for method in methods_obj.keys():
            if method.upper() in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
                routes[path].append(method.upper())
    
    return routes

def extract_frontend_calls(api_ts_path: Path):
    """Extract all API endpoint patterns from frontend api.ts file."""
    with open(api_ts_path, encoding='utf-8') as f:
        content = f.read()
    
    # Extract all request() calls with their paths
    # Pattern: request(`/some/path...`
    # Also handle template literals with ${vars}
    pattern = r'request\([`\'"]([^`\'"]+)[`\'"]'
    
    calls = []
    for match in re.finditer(pattern, content):
        path = match.group(1)
        # Get method from context (find method: in preceding 20 chars)
        start = max(0, match.start() - 200)
        context = content[start:match.start()]
        
        method = "GET"  # default
        if 'method: "POST"' in context or "method: 'POST'" in context:
            method = "POST"
        elif 'method: "PUT"' in context or "method: 'PUT'" in context:
            method = "PUT"
        elif 'method: "PATCH"' in context or "method: 'PATCH'" in context:
            method = "PATCH"
        elif 'method: "DELETE"' in context or "method: 'DELETE'" in context:
            method = "DELETE"
        
        calls.append({"path": path, "method": method, "raw": match.group(0)})
    
    return calls

def normalize_path(path: str) -> str:
    """Convert template literals like ${id} to OpenAPI style {id}."""
    # Replace ${encodeURIComponent(var)} with {var}
    path = re.sub(r'\$\{encodeURIComponent\(([^)]+)\)\}', r'{\1}', path)
    # Replace ${var} with {var}
    path = re.sub(r'\$\{([^}]+)\}', r'{\1}', path)
    return path

def compare_routes(backend_routes, frontend_calls):
    """Compare frontend calls against backend routes."""
    findings = {
        "missing_backend": [],  # Frontend calls non-existent backend route
        "unused_backend": [],   # Backend route not called by frontend
        "method_mismatch": [],  # Route exists but method wrong
        "matched": []
    }
    
    # Normalize frontend calls
    normalized_calls = {}
    for call in frontend_calls:
        norm_path = normalize_path(call["path"])
        if not norm_path.startswith("/api/"):
            norm_path = "/api" + norm_path
        key = (norm_path, call["method"])
        normalized_calls[key] = call
    
    # Check each frontend call
    for (fe_path, fe_method), call_info in normalized_calls.items():
        if fe_path in backend_routes:
            if fe_method in backend_routes[fe_path]:
                findings["matched"].append({
                    "path": fe_path,
                    "method": fe_method
                })
            else:
                findings["method_mismatch"].append({
                    "path": fe_path,
                    "frontend_method": fe_method,
                    "backend_methods": backend_routes[fe_path],
                    "raw": call_info["raw"]
                })
        else:
            # Try fuzzy match with different param names
            matched = False
            for be_path in backend_routes.keys():
                # Replace {param_name} with generic pattern
                be_pattern = re.sub(r'\{[^}]+\}', r'{[^/]+}', be_path)
                fe_pattern = re.sub(r'\{[^}]+\}', r'{[^/]+}', fe_path)
                if be_pattern == fe_pattern:
                    if fe_method in backend_routes[be_path]:
                        findings["matched"].append({
                            "path": f"{fe_path} (matches {be_path})",
                            "method": fe_method
                        })
                        matched = True
                        break
            
            if not matched:
                findings["missing_backend"].append({
                    "path": fe_path,
                    "method": fe_method,
                    "raw": call_info["raw"]
                })
    
    # Check for unused backend routes
    used_backend = {path for path, method in normalized_calls.keys()}
    for be_path in backend_routes.keys():
        # Fuzzy match
        be_pattern = re.sub(r'\{[^}]+\}', r'{[^/]+}', be_path)
        matched = any(
            re.sub(r'\{[^}]+\}', r'{[^/]+}', fe_path) == be_pattern
            for fe_path in used_backend
        )
        if not matched:
            findings["unused_backend"].append({
                "path": be_path,
                "methods": backend_routes[be_path]
            })
    
    return findings

def main():
    workspace = Path(__file__).parent
    openapi_path = workspace / "backend" / "openapi_schema_clean.json"
    api_ts_path = workspace / "frontend" / "src" / "lib" / "api.ts"
    
    print("🔍 Validating Frontend ↔ Backend API Coverage\n")
    print(f"Backend OpenAPI: {openapi_path}")
    print(f"Frontend API Client: {api_ts_path}\n")
    
    backend_routes = extract_backend_routes(openapi_path)
    frontend_calls = extract_frontend_calls(api_ts_path)
    
    print(f"✓ Backend routes: {len(backend_routes)}")
    print(f"✓ Frontend unique calls: {len(set((normalize_path(c['path']), c['method']) for c in frontend_calls))}\n")
    
    findings = compare_routes(backend_routes, frontend_calls)
    
    print("=" * 80)
    print("📊 RESULTS")
    print("=" * 80)
    
    print(f"\n✅ Matched routes: {len(findings['matched'])}")
    
    if findings["missing_backend"]:
        print(f"\n❌ CRITICAL: Frontend calls non-existent backend routes ({len(findings['missing_backend'])})")
        for item in findings["missing_backend"][:20]:  # Show first 20
            print(f"   {item['method']:6} {item['path']}")
            print(f"          Source: {item['raw'][:80]}")
    
    if findings["method_mismatch"]:
        print(f"\n⚠️  Method mismatches ({len(findings['method_mismatch'])})")
        for item in findings["method_mismatch"][:20]:
            print(f"   {item['path']}")
            print(f"          Frontend: {item['frontend_method']}, Backend: {item['backend_methods']}")
    
    if findings["unused_backend"]:
        print(f"\n📋 Backend routes not used by frontend ({len(findings['unused_backend'])})")
        for item in findings["unused_backend"][:30]:  # Show first 30
            print(f"   {', '.join(item['methods']):20} {item['path']}")
    
    # Save detailed report
    report_path = workspace / "api_coverage_report.json"
    with open(report_path, 'w') as f:
        json.dump(findings, f, indent=2)
    
    print(f"\n💾 Detailed report: {report_path}")
    
    # Exit code
    critical_issues = len(findings["missing_backend"]) + len(findings["method_mismatch"])
    if critical_issues > 0:
        print(f"\n🚨 {critical_issues} critical integration issues found")
        return 1
    else:
        print("\n✅ All frontend API calls match backend routes")
        return 0

if __name__ == "__main__":
    exit(main())

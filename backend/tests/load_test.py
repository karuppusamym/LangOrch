"""Load and soak testing script for LangOrch.

Run this script to perform sustained load testing against a running LangOrch instance.

Usage:
    python load_test.py --duration 300 --qps 50 --url http://localhost:8000
    
Options:
    --duration: Test duration in seconds (default: 60)
    --qps: Queries per second to sustain (default: 10)
    --url: LangOrch API base URL (default: http://localhost:8000)
    --procedure: Procedure ID to test (default: creates a test procedure)
"""

from __future__ import annotations

import argparse
import asyncio
import httpx
import time
from datetime import datetime
from typing import Any


class LoadTester:
    """Orchestrates load testing against LangOrch API."""
    
    def __init__(self, base_url: str, duration_seconds: int, qps: int):
        self.base_url = base_url.rstrip("/")
        self.duration_seconds = duration_seconds
        self.qps = qps
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        
        # Metrics
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.response_times: list[float] = []
        self.errors: list[str] = []
    
    async def setup_test_procedure(self) -> str:
        """Create a simple test procedure for load testing."""
        procedure_id = f"load_test_{int(time.time())}"
        
        ckp = {
            "procedure_id": procedure_id,
            "version": "1.0.0",
            "global_config": {"max_retries": 0},
            "variables_schema": {"message": {"type": "string", "default": "load test"}},
            "workflow_graph": {
                "start_node": "log_step",
                "nodes": {
                    "log_step": {
                        "type": "sequence",
                        "steps": [
                            {"step_id": "log1", "action": "log", "message": "Load test execution"}
                        ],
                        "next_node": "end",
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        
        response = await self.client.post("/api/procedures", json=ckp)
        response.raise_for_status()
        print(f"✓ Created test procedure: {procedure_id}")
        return procedure_id
    
    async def fire_run(self, procedure_id: str) -> dict[str, Any]:
        """Fire a single workflow run."""
        start_time = time.perf_counter()
        
        try:
            response = await self.client.post(
                "/api/runs",
                json={
                    "procedure_id": procedure_id,
                    "procedure_version": "1.0.0",
                    "input_vars": {},
                },
            )
            elapsed = time.perf_counter() - start_time
            
            self.total_requests += 1
            self.response_times.append(elapsed)
            
            if response.status_code in [200, 202]:
                self.successful_requests += 1
                return {"success": True, "elapsed": elapsed}
            else:
                self.failed_requests += 1
                self.errors.append(f"HTTP {response.status_code}: {response.text[:100]}")
                return {"success": False, "elapsed": elapsed, "error": response.text}
        
        except Exception as exc:
            elapsed = time.perf_counter() - start_time
            self.total_requests += 1
            self.failed_requests += 1
            self.response_times.append(elapsed)
            self.errors.append(f"{type(exc).__name__}: {str(exc)[:100]}")
            return {"success": False, "elapsed": elapsed, "error": str(exc)}
    
    async def run_load_test(self, procedure_id: str):
        """Execute sustained load test."""
        print(f"\n🚀 Starting load test:")
        print(f"   Duration: {self.duration_seconds}s")
        print(f"   Target QPS: {self.qps}")
        print(f"   Procedure: {procedure_id}")
        print(f"   Started at: {datetime.now().isoformat()}\n")
        
        start_time = time.time()
        interval_seconds = 1.0
        
        while time.time() - start_time < self.duration_seconds:
            batch_start = time.time()
            
            # Fire batch of requests for this second
            batch_tasks = [self.fire_run(procedure_id) for _ in range(self.qps)]
            await asyncio.gather(*batch_tasks, return_exceptions=True)
            
            # Calculate how long to sleep to maintain QPS
            elapsed = time.time() - batch_start
            sleep_time = max(0, interval_seconds - elapsed)
            
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            
            # Progress update every 10 seconds
            if int(time.time() - start_time) % 10 == 0:
                self._print_interim_stats(time.time() - start_time)
    
    def _print_interim_stats(self, elapsed: float):
        """Print interim statistics during test."""
        success_rate = (self.successful_requests / self.total_requests * 100) if self.total_requests > 0 else 0
        avg_latency = sum(self.response_times) / len(self.response_times) if self.response_times else 0
        
        print(f"⏱️  {int(elapsed)}s elapsed | "
              f"Requests: {self.total_requests} | "
              f"Success: {success_rate:.1f}% | "
              f"Avg latency: {avg_latency*1000:.0f}ms")
    
    async def print_final_report(self):
        """Print final test results and statistics."""
        print("\n" + "=" * 70)
        print("LOAD TEST RESULTS")
        print("=" * 70)
        
        print(f"\n📊 Request Statistics:")
        print(f"   Total requests:       {self.total_requests}")
        print(f"   Successful:           {self.successful_requests}")
        print(f"   Failed:               {self.failed_requests}")
        
        success_rate = (self.successful_requests / self.total_requests * 100) if self.total_requests > 0 else 0
        print(f"   Success rate:         {success_rate:.2f}%")
        
        if self.response_times:
            self.response_times.sort()
            avg_latency = sum(self.response_times) / len(self.response_times)
            p50_latency = self.response_times[len(self.response_times) // 2]
            p95_latency = self.response_times[int(len(self.response_times) * 0.95)]
            p99_latency = self.response_times[int(len(self.response_times) * 0.99)]
            
            print(f"\n⚡ Latency Distribution (ms):")
            print(f"   Average:              {avg_latency * 1000:.2f}")
            print(f"   p50:                  {p50_latency * 1000:.2f}")
            print(f"   p95:                  {p95_latency * 1000:.2f}")
            print(f"   p99:                  {p99_latency * 1000:.2f}")
            print(f"   Min:                  {min(self.response_times) * 1000:.2f}")
            print(f"   Max:                  {max(self.response_times) * 1000:.2f}")
        
        if self.errors:
            print(f"\n❌ Error Summary (showing first 10):")
            for i, error in enumerate(self.errors[:10], 1):
                print(f"   {i}. {error}")
            if len(self.errors) > 10:
                print(f"   ... and {len(self.errors) - 10} more errors")
        
        # Health check after load
        print(f"\n🏥 System Health Check:")
        try:
            health_response = await self.client.get("/api/health")
            if health_response.status_code == 200:
                print(f"   ✓ System healthy after load test")
            else:
                print(f"   ⚠️  Health check returned {health_response.status_code}")
        except Exception as exc:
            print(f"   ❌ Health check failed: {exc}")
        
        print("\n" + "=" * 70)
    
    async def cleanup(self):
        """Close client connections."""
        await self.client.aclose()


async def main():
    """Main entry point for load testing."""
    parser = argparse.ArgumentParser(description="LangOrch load testing tool")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--qps", type=int, default=10, help="Target queries per second")
    parser.add_argument("--url", type=str, default="http://localhost:8000", help="LangOrch API base URL")
    parser.add_argument("--procedure", type=str, default=None, help="Existing procedure ID to test (optional)")
    
    args = parser.parse_args()
    
    tester = LoadTester(
        base_url=args.url,
        duration_seconds=args.duration,
        qps=args.qps,
    )
    
    try:
        # Setup test procedure or use existing
        if args.procedure:
            procedure_id = args.procedure
            print(f"Using existing procedure: {procedure_id}")
        else:
            procedure_id = await tester.setup_test_procedure()
        
        # Run load test
        await tester.run_load_test(procedure_id)
        
        # Print results
        await tester.print_final_report()
    
    finally:
        await tester.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

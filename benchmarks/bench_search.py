"""Benchmark semantic and full-text search queries."""
import time, urllib.request, urllib.error, json, sys

API_KEY = "lamadb_test_key_2026"
BASE = "http://localhost:8000"
QUERIES = [
    ("full-text", f"{BASE}/api/search?q=docker"),
    ("semantic", f"{BASE}/api/search/semantic?q=docker+container"),
]

def bench():
    for name, url in QUERIES:
        times = []
        print(f"\n--- {name} ({url}) ---")
        for i in range(5):
            start = time.monotonic()
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                    count = len(data.get("results", data.get("documents", [])))
            except urllib.error.HTTPError as e:
                print(f"HTTP {e.code}: {e.read().decode()}")
                sys.exit(1)
            elapsed = time.monotonic() - start
            times.append(elapsed)
            print(f"  Run {i+1}/5: {elapsed*1000:.1f}ms  ({count} results)")

        times.sort()
        print(f"  p50={times[len(times)//2]*1000:.1f}ms  p95={times[int(len(times)*0.95)]*1000:.1f}ms")

if __name__ == "__main__":
    bench()

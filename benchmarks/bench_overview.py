"""Benchmark GET /api/dashboard/overview — 10 iterations, report p50/p95."""
import time
import urllib.request
import urllib.error
import json
import sys

API_KEY = "lamadb_test_key_2026"
URL = "http://localhost:8000/api/dashboard/overview"

def bench():
    times = []
    for i in range(10):
        start = time.monotonic()
        req = urllib.request.Request(URL, headers={"Authorization": f"Bearer {API_KEY}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                data = json.loads(body)
                assert "documents" in data, f"Missing 'documents' in response: {data.keys()}"
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}: {e.read().decode()}")
            sys.exit(1)
        elapsed = time.monotonic() - start
        times.append(elapsed)
        print(f"  Run {i+1}/10: {elapsed*1000:.1f}ms")

    times.sort()
    p50 = times[len(times) // 2]
    p95 = times[int(len(times) * 0.95)]
    print(f"\nResults: p50={p50*1000:.1f}ms  p95={p95*1000:.1f}ms  min={times[0]*1000:.1f}ms  max={times[-1]*1000:.1f}ms")

if __name__ == "__main__":
    bench()

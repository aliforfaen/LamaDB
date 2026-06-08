"""Benchmark GET /api/uptime/status — measures monitor status aggregation speed."""
import time, urllib.request, urllib.error, json, sys

API_KEY = "lamadb_test_key_2026"
URL = "http://localhost:8000/api/uptime/status"

def bench():
    times = []
    for i in range(10):
        start = time.monotonic()
        req = urllib.request.Request(URL, headers={"Authorization": f"Bearer {API_KEY}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                data = json.loads(body)
                assert "monitors" in data, f"Missing 'monitors': {data.keys()}"
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}: {e.read().decode()}")
            sys.exit(1)
        elapsed = time.monotonic() - start
        times.append(elapsed)
        print(f"  Run {i+1}/10: {elapsed*1000:.1f}ms  ({len(data.get('monitors',[]))} monitors)")

    times.sort()
    print(f"\nResults: p50={times[len(times)//2]*1000:.1f}ms  p95={times[int(len(times)*0.95)]*1000:.1f}ms  min={times[0]*1000:.1f}ms  max={times[-1]*1000:.1f}ms")

if __name__ == "__main__":
    bench()

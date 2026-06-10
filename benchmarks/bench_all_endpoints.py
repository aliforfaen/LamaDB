"""Time all dashboard API endpoints, report p50/p95."""
import os, time, json, httpx, sys

BASE_URL = os.environ.get("LAMADB_TEST_URL", "http://localhost:8000")
API_KEY = os.environ.get("LAMADB_TEST_KEY", "lamadb_test_key_2026")
HEADERS = {"Authorization": f"Bearer {API_KEY}"}
ITERATIONS = int(os.environ.get("ITERATIONS", "5"))
TIMEOUT = int(os.environ.get("TIMEOUT", "60"))

ENDPOINTS = [
    "/api/dashboard/overview",
    "/api/dashboard/modules",
    "/api/dashboard/health",
    "/api/dashboard/module-health",
    "/api/dashboard/module-settings",
    "/api/dashboard/api-keys",
    "/api/dashboard/api-keys/stats",
    "/api/dashboard/cache-stats?key=" + API_KEY,
    "/api/dashboard/user-layout?page=overview",
    "/api/uptime/status",
    "/api/uptime/history/recent?limit=10",
    "/api/events?limit=10",
    "/api/documents?limit=10",
    "/api/search?q=test",
    "/api/feeds",
    "/api/freshrss/status",
    "/api/hermes/health",
    "/api/hermes/sessions/stats",
    "/api/wiki/pages",
    "/api/agent_board/tasks?limit=10",
    "/api/notifications/rules",
]

def percentile(values, p):
    k = (len(values) - 1) * p / 100
    f = int(k)
    c = k - f
    if f + 1 < len(values):
        return values[f] + c * (values[f + 1] - values[f])
    return values[f]

def main():
    client = httpx.Client(base_url=BASE_URL, timeout=TIMEOUT)
    results = []

    for ep in ENDPOINTS:
        times = []
        errors = 0
        for _ in range(ITERATIONS):
            try:
                start = time.monotonic()
                resp = client.get(ep, headers=HEADERS)
                elapsed = (time.monotonic() - start) * 1000
                if resp.status_code == 200:
                    times.append(elapsed)
                else:
                    errors += 1
            except Exception:
                errors += 1
        if times:
            times.sort()
            results.append({
                "endpoint": ep,
                "p50_ms": round(percentile(times, 50), 1),
                "p95_ms": round(percentile(times, 95), 1),
                "min_ms": round(min(times), 1),
                "max_ms": round(max(times), 1),
                "errors": errors,
            })
        else:
            results.append({"endpoint": ep, "p50_ms": None, "p95_ms": None, "errors": errors})

    # Print table
    print(f"{'Endpoint':<55} {'p50':>8} {'p95':>8} {'min':>8} {'max':>8} {'errs':>5}")
    print("-" * 95)
    slow = []
    for r in results:
        p50 = f"{r['p50_ms']:.0f}ms" if r['p50_ms'] else "FAIL"
        p95 = f"{r['p95_ms']:.0f}ms" if r['p95_ms'] else "FAIL"
        mn = f"{r['min_ms']:.0f}ms" if r['min_ms'] else "-"
        mx = f"{r['max_ms']:.0f}ms" if r['max_ms'] else "-"
        print(f"{r['endpoint']:<55} {p50:>8} {p95:>8} {mn:>8} {mx:>8} {r['errors']:>5}")
        if r['p95_ms'] and r['p95_ms'] > 1000:
            slow.append(r)

    print(f"\n--- Slow endpoints (>1s p95): {len(slow)} ---")
    for r in slow:
        print(f"  {r['endpoint']}: p95={r['p95_ms']:.0f}ms")

    client.close()

if __name__ == "__main__":
    main()

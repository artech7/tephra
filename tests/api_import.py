import os, io, json, shutil, time
VAULT = os.environ.setdefault("TEPHRA_VAULT", "/tmp/tephra-test-import")
shutil.rmtree(VAULT, ignore_errors=True)
from fastapi.testclient import TestClient
from app.main import app
from app import guide_import

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  PASS  {label} {extra}")
    else:    fail += 1; print(f"  FAIL  {label} {extra}")

def poll(c, job_id, timeout=5):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = c.get(f"/api/study/import/status/{job_id}")
        last = r
        if r.status_code == 200 and r.json()["finished"]:
            return r.json()
        time.sleep(0.02)
    raise AssertionError(f"import job {job_id} never finished: {last and last.text}")


print("── run_import's progress callback: total up front, done reaches it even with a skip ──")
seen = []
guide = json.dumps({"topics": [
    {"title": "Alpha", "category": "Cat", "answer": "First topic about alpha, in some detail."},
    {"title": "Alpha again", "category": "Cat", "answer": "First topic about alpha, in some detail."},
    {"title": "Beta", "category": "Cat", "answer": "Second topic about beta, in some detail."},
]})
summary = guide_import.run_import(guide, dry_run=True, filename="g.json",
                                  progress=lambda d, t: seen.append((d, t)))
check("first call announces the total before any topic is touched", seen[0] == (0, 3), seen)
check("done reaches total exactly once, including the skipped duplicate",
      seen[-1] == (3, 3) and len(seen) == 4, seen)
check("the near-duplicate was at least flagged (dedupe engaged, whatever the threshold call)",
      len(summary["duplicates"]) == 1 and summary["duplicates"][0]["matches"] == "Alpha", summary["duplicates"])

with TestClient(app) as c:
    print("\n── /api/study/import/upload returns a job id, not the summary directly ──")
    guide_bytes = json.dumps({"topics": [
        {"title": "ICMP", "category": "Networking", "answer": "Internet Control Message Protocol."},
    ]}).encode()
    r = c.post("/api/study/import/upload",
               files={"files": ("icmp_guide.json", io.BytesIO(guide_bytes), "application/json")})
    check("responds immediately with a job id, not the summary", r.status_code == 200 and "job_id" in r.json(), r.text)
    job_id = r.json()["job_id"]

    print("\n── polling to completion returns the same summary shape run_import always has ──")
    job = poll(c, job_id)
    check("no error", job["error"] is None, job)
    check("summary carries the usual fields",
          job["result"]["created"] == 1 and job["result"]["topics"] == 1, job["result"])
    check("progress reached the total", job["done"] == job["total"] == 1, job)
    check("reindexed after a real (non-dry) import", job["result"].get("reindexed") is not None, job["result"])

    print("\n── a finished job is one-shot -- gone on the next poll ──")
    r2 = c.get(f"/api/study/import/status/{job_id}")
    check("404 once already collected", r2.status_code == 404, r2.status_code)

    print("\n── an unknown job id 404s ──")
    r3 = c.get("/api/study/import/status/does-not-exist")
    check("404", r3.status_code == 404, r3.status_code)

    print("\n── a parse error surfaces through the job, not as an immediate 400 ──")
    r4 = c.post("/api/study/import/upload",
               files={"files": ("bad.json", io.BytesIO(b"not json"), "application/json")})
    check("still returns a job id -- parsing itself runs in the background",
          r4.status_code == 200 and "job_id" in r4.json(), r4.text)
    job2 = poll(c, r4.json()["job_id"])
    check("job reports the parse error", bool(job2["error"]) and "not valid JSON" in job2["error"], job2)

    print("\n── validation that IS cheap still fails immediately, no job created ──")
    r5 = c.post("/api/study/import/upload",
               files={"files": ("readme.txt", io.BytesIO(b"nothing importable here"), "text/plain")})
    check("400 with no job id -- no recognised guide file among the uploads",
          r5.status_code == 400 and "job_id" not in r5.json(), r5.text)

print(f"\n  {ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)

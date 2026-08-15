import os, io, json, shutil, time
VAULT = os.environ.setdefault("TEPHRA_VAULT", "/tmp/tephra-test-import")
shutil.rmtree(VAULT, ignore_errors=True)
from fastapi.testclient import TestClient
from app.main import app
from app import guide_import, study

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

print("\n── two guides sharing a category: the index page accumulates both ──")
guide_a = json.dumps({"topics": [
    {"title": "Shared Topic A", "category": "Shared Cat",
     "answer": "Some real prose about topic A, long enough to be its own thing."},
]})
guide_b = json.dumps({"topics": [
    {"title": "Shared Topic B", "category": "Shared Cat",
     "answer": "Some real prose about topic B, unrelated to A but same category."},
]})
guide_import.run_import(guide_a, filename="Guide A.json")
guide_import.run_import(guide_b, filename="Guide B.json")
from app import vault as _vault
cat_note = next(n for n in _vault.all_notes() if n.title == "Shared Cat")
check("both guides' topics are listed",
      "[[Shared Topic A]]" in cat_note.body and "[[Shared Topic B]]" in cat_note.body, cat_note.body)
check("both guides are named in the Part of line",
      "[[Guide A]]" in cat_note.body and "[[Guide B]]" in cat_note.body, cat_note.body)

print("\n── deleting one guide's topic and root note by hand leaves a stale stub ──")
topic_b = next(n for n in _vault.all_notes() if n.title == "Shared Topic B")
root_b = next(n for n in _vault.all_notes() if n.title == "Guide B")
_vault.delete(topic_b.slug)
_vault.delete(root_b.slug)
stale = next(n for n in _vault.all_notes() if n.slug == cat_note.slug)
check("the category page still links the now-deleted topic and guide (nothing prunes on delete)",
      "[[Shared Topic B]]" in stale.body and "[[Guide B]]" in stale.body, stale.body)

print("\n── /api/study/import/reconcile drops the dead references ──")
with TestClient(app) as c:
    preview = c.post("/api/study/import/reconcile", params={"dry_run": "true"}).json()
    changed_entry = next((e for e in preview["changed"] if e["title"] == cat_note.title), None)
    check("dry run reports the category as changed, writes nothing", changed_entry is not None, preview)
    # dead only covers the bullet-list topic links -- a dead "Part of
    # [[Guide]]" reference is dropped via import_roots filtering separately
    # and isn't reflected here.
    check("...and lists the specific dead topic link, not just a bare count",
          changed_entry and changed_entry["dead"] == ["Shared Topic B"], changed_entry)
    check("...tagged with the page's own slug, for the frontend to link to it",
          changed_entry and changed_entry["slug"] == cat_note.slug, changed_entry)
    stillstale = next(n for n in _vault.all_notes() if n.slug == cat_note.slug)
    check("dry run did not touch the file", "[[Shared Topic B]]" in stillstale.body)

    r = c.post("/api/study/import/reconcile").json()
    check("real run reports it changed", any(e["title"] == cat_note.title for e in r["changed"]), r)
    fixed = next(n for n in _vault.all_notes() if n.slug == cat_note.slug)
    check("the dead topic link is gone", "[[Shared Topic B]]" not in fixed.body, fixed.body)
    check("the dead guide is gone from Part of", "[[Guide B]]" not in fixed.body, fixed.body)
    check("the surviving topic and guide are untouched",
          "[[Shared Topic A]]" in fixed.body and "[[Guide A]]" in fixed.body, fixed.body)

    print("\n── running it again is a no-op ──")
    r2 = c.post("/api/study/import/reconcile").json()
    check("nothing left to change", r2["changed"] == [] and r2["removed"] == [], r2)

print("\n── a category with every topic deleted loses its index page entirely ──")
last_topic = next(n for n in _vault.all_notes() if n.title == "Shared Topic A")
_vault.delete(last_topic.slug)
with TestClient(app) as c:
    r3 = c.post("/api/study/import/reconcile").json()
    removed_entry = next((e for e in r3["removed"] if e["title"] == cat_note.title), None)
    check("the now-empty category page is removed, not left as a hollow shell",
          removed_entry is not None, r3)
    check("...and reports which title left it empty",
          removed_entry and removed_entry["dead"] == ["Shared Topic A"], removed_entry)
check("it's actually gone from disk",
      not any(n.slug == cat_note.slug for n in _vault.all_notes()))

print("\n── re-importing self-heals a stale category without reconcile ──")
guide_c = json.dumps({"topics": [
    {"title": "Heal Topic A", "category": "Heal Cat",
     "answer": "Prose for the topic that will stay, distinct enough to skip dedupe."},
]})
guide_d = json.dumps({"topics": [
    {"title": "Heal Topic B", "category": "Heal Cat",
     "answer": "Prose for the topic that will be deleted before the next import."},
]})
guide_import.run_import(guide_c, filename="Heal Guide C.json")
guide_import.run_import(guide_d, filename="Heal Guide D.json")
heal_cat = next(n for n in _vault.all_notes()
                if n.meta.get("study_index") == "true" and "import_roots" in n.meta
                and "Heal Topic A" in n.body)
_vault.delete(next(n for n in _vault.all_notes() if n.title == "Heal Topic B").slug)
_vault.delete(next(n for n in _vault.all_notes() if n.title == "Heal Guide D").slug)
# Re-import guide C (the survivor) -- its own regeneration pass should drop
# the now-dead Heal Topic B / Heal Guide D references on its own.
guide_import.run_import(guide_c, filename="Heal Guide C.json")
healed = next(n for n in _vault.all_notes() if n.slug == heal_cat.slug)
check("re-importing dropped the dead topic reference on its own",
      "[[Heal Topic B]]" not in healed.body, healed.body)
check("re-importing dropped the dead guide from Part of",
      "[[Heal Guide D]]" not in healed.body, healed.body)
check("the surviving topic and guide are still there",
      "[[Heal Topic A]]" in healed.body and "[[Heal Guide C]]" in healed.body, healed.body)

print("\n── deleting a category's index note un-studies its topics, not just the page ──")
guide_e = json.dumps({"topics": [
    {"title": "Orphan Topic A", "category": "Orphan Cat",
     "answer": "Prose for a topic whose category index will be deleted by hand.",
     "quiz": [{"question": "Orphaned but still a real question?", "options": ["Yes", "No"], "answers": [0]}]},
    {"title": "Orphan Topic B", "category": "Orphan Cat",
     "answer": "A second topic in the same soon-to-be-indexless category."},
]})
guide_import.run_import(guide_e, filename="Orphan Guide.json")
orphan_cat = next(n for n in _vault.all_notes()
                  if n.meta.get("study_index") == "true" and "Orphan Topic A" in n.body)
_vault.delete(orphan_cat.slug)

# A hand-categorized note sharing no index at all -- must never be touched,
# even though it also has no matching study_index note.
manual_note = next(n for n in _vault.all_notes() if n.title == "Orphan Topic B")
manual_note.meta["category_source"] = "manual"
_vault.write(manual_note)

with TestClient(app) as c:
    preview = c.post("/api/study/import/reconcile", params={"dry_run": "true"}).json()
    orphaned_titles = {e["title"] for e in preview["orphaned"]}
    check("the import-sourced topic under the deleted index is flagged",
          "Orphan Topic A" in orphaned_titles, preview["orphaned"])
    check("the now hand-categorized sibling is left alone",
          "Orphan Topic B" not in orphaned_titles, preview["orphaned"])
    check("dry run touched nothing on disk",
          study.is_study(next(n for n in _vault.all_notes() if n.title == "Orphan Topic A")),
          "still study:true before the real run")

    r = c.post("/api/study/import/reconcile").json()
    check("real run reports the same topic un-studied",
          any(e["title"] == "Orphan Topic A" for e in r["orphaned"]), r["orphaned"])
    a = next(n for n in _vault.all_notes() if n.title == "Orphan Topic A")
    b = next(n for n in _vault.all_notes() if n.title == "Orphan Topic B")
    check("Orphan Topic A is un-studied", not study.is_study(a), a.meta)
    check("...but keeps its category and quiz content untouched",
          a.meta.get("category") == "Orphan Cat" and "## Quiz" in a.body, a.body)
    check("Orphan Topic B (manual category, never indexed) is still studyable", study.is_study(b), b.meta)

    print("\n── running it again is a no-op (already un-studied is excluded from the scan) ──")
    r2 = c.post("/api/study/import/reconcile").json()
    check("nothing left to orphan", r2["orphaned"] == [], r2["orphaned"])

print(f"\n  {ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)

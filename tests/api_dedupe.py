"""
dedupe.scan_notes: the sorted-by-length + early-break inner loop must find
exactly the same pairs the original full O(n^2) brute force did -- it's
only allowed to change which candidates get *visited*, never which pairs
get *reported*. This checks that equivalence directly, with a reference
brute-force implementation kept deliberately separate from app.dedupe so a
bug in the real one can't also be baked into what it's compared against.
"""
import random

from app.vault import Note
from app import dedupe

ok = fail = 0
def ck(l, c, x=""):
    global ok, fail
    if c: ok += 1; print(f"  PASS  {l} {x}")
    else: fail += 1; print(f"  FAIL  {l} {x}")


def brute_force(notes):
    """The pre-optimization algorithm, kept here as a fixed reference: every
    pair, no length-based skipping of the outer walk."""
    texts = [(n.slug, n.title, n.updated,
              dedupe.content_text(n.title, n.meta.get("question"), n.body))
             for n in notes]
    out = []
    for i in range(len(texts)):
        slug_a, title_a, updated_a, text_a = texts[i]
        for slug_b, title_b, updated_b, text_b in texts[i + 1:]:
            r = dedupe.similarity(text_a, text_b)
            if r >= dedupe.REPORT_THRESHOLD:
                out.append({"a_slug": slug_a, "a_title": title_a, "a_updated": updated_a,
                           "b_slug": slug_b, "b_title": title_b, "b_updated": updated_b,
                           "similarity": round(r, 3)})
    out.sort(key=lambda d: -d["similarity"])
    return out


def as_pairs(result):
    """Order-independent view: which (slug, slug) pairs were found, each
    with its score -- a_slug/b_slug can legitimately land on either side
    once the real implementation sorts notes by length first."""
    return {frozenset((d["a_slug"], d["b_slug"])): d["similarity"] for d in result}


def note(slug, body, question=None, updated="2026-01-01T00:00:00Z"):
    return Note(slug=slug, title=slug, body=body, updated=updated,
                meta={"question": question} if question else {})


def check_equivalent(label, notes):
    got = dedupe.scan_notes(notes)
    want = brute_force(notes)
    ck(f"{label}: same pairs found", as_pairs(got) == as_pairs(want),
       (as_pairs(got), as_pairs(want)))
    ck(f"{label}: sorted highest-similarity first",
       all(got[i]["similarity"] >= got[i + 1]["similarity"] for i in range(len(got) - 1)),
       got)


print("── edge cases ──")
check_equivalent("empty vault", [])
check_equivalent("single note", [note("a", "some text here")])
check_equivalent("two unrelated notes",
    [note("a", "completely different content about routers"),
     note("b", "an entirely unrelated note about spreadsheets")])
check_equivalent("two near-identical notes",
    [note("a", "The quick brown fox jumps over the lazy dog in the yard."),
     note("b", "The quick brown fox jumps over the lazy dog in the park.")])
check_equivalent("zero-length bodies", [note("a", ""), note("b", "")])
check_equivalent("one zero-length, one not", [note("a", ""), note("b", "some content")])
check_equivalent("exact-length ties, unrelated content",
    [note("a", "xxxxxxxxxx"), note("b", "yyyyyyyyyy"), note("c", "zzzzzzzzzz")])

print("\n── a within-batch duplicate at each end of a mixed-length set ──")
subnet = ("Subnetting divides a network into smaller pieces using a subnet mask. "
          "Each subnet has its own range of usable host addresses.")
check_equivalent("duplicate pair surrounded by unrelated notes of very different lengths", [
    note("short", "hi"),
    note("dup-a", subnet),
    note("filler1", "Routing protocols exchange reachability information between routers."),
    note("dup-b", subnet.replace("divides", "splits")),
    note("long", "Lorem ipsum dolor sit amet, " * 200),
])

print("\n── randomized equivalence sweep ──")
random.seed(1234)
WORDS = ("network subnet router switch firewall packet frame protocol address "
         "gateway server client cable port vlan route dns dhcp host domain").split()

def random_notes(n, rng):
    notes = []
    for i in range(n):
        length = rng.choice([5, 20, 80, 80, 200, 200, 200, 600])
        body = " ".join(rng.choice(WORDS) for _ in range(length))
        notes.append(note(f"n{i}", body))
    # Force a handful of genuine near-duplicates into the mix so some trials
    # actually have pairs to find, not just confirm "nothing found" every time.
    if n >= 2 and rng.random() < 0.6:
        base = notes[0].body
        notes[1] = note(notes[1].slug, base + " extra")
    return notes

for trial in range(8):
    n = random.randint(0, 40)
    check_equivalent(f"random trial {trial} (n={n})", random_notes(n, random))

print("\n── the parallel path (>= PARALLEL_MIN_NOTES notes) is exercised, not just the sequential fallback ──")
ck("this vault size actually crosses the real default threshold",
   60 >= dedupe.PARALLEL_MIN_NOTES, dedupe.PARALLEL_MIN_NOTES)
big_notes = random_notes(60, random.Random(99))
check_equivalent("60 notes at the real default threshold (forces the worker-pool path for real)", big_notes)

print("\n── same equivalence check, forced through the worker-pool path at small scale ──")
# Lowering the threshold instead of generating hundreds of notes keeps this
# fast while still exercising _init_worker/_scan_row_worker and the
# pool.imap_unordered merge -- the part of scan_notes that never runs
# unless a vault is large enough, otherwise.
original_threshold = dedupe.PARALLEL_MIN_NOTES
dedupe.PARALLEL_MIN_NOTES = 2
try:
    check_equivalent("forced-parallel: two unrelated notes", random_notes(6, random.Random(1)))
    check_equivalent("forced-parallel: with a real duplicate pair", random_notes(10, random.Random(2)))
    check_equivalent("forced-parallel: mixed-length set from earlier", [
        note("short", "hi"),
        note("dup-a", subnet),
        note("filler1", "Routing protocols exchange reachability information between routers."),
        note("dup-b", subnet.replace("divides", "splits")),
        note("long", "Lorem ipsum dolor sit amet, " * 200),
    ])
finally:
    dedupe.PARALLEL_MIN_NOTES = original_threshold

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)

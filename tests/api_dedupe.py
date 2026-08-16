"""
dedupe.scan_notes: the sorted-by-length + early-break inner loop, and the
shingle-sketch pre-filter on top of it, must find exactly the same pairs
the original full O(n^2) brute force did -- they're only allowed to change
which candidates get *visited*, never which pairs get *reported*. This
checks that equivalence directly, with a reference brute-force
implementation kept deliberately separate from app.dedupe so a bug in the
real one can't also be baked into what it's compared against.

The sketch filter is the one piece of this that isn't exact by
construction (see _plausible's docstring): it's a hash-based approximation,
deliberately biased to over-include rather than risk a false negative, but
"deliberately biased" is a design intent, not a proof. The boundary-edit
sweep near the end of this file is the section actually load-bearing for
that: it generates near-duplicates right around REPORT_THRESHOLD with edits
scattered through the text (the case where a real near-duplicate has the
least surviving unbroken text for a hash sketch to catch), across enough
random seeds to build real confidence the filter never quietly drops a
duplicate the brute-force reference still finds.
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

print("\n── sketch filter boundary sweep: scattered edits around REPORT_THRESHOLD ──")
# The regime that actually stresses _plausible: a near-duplicate with edits
# spread evenly through the text, not clustered at one end (an append or a
# single word swap, like the cases above, leaves long unbroken runs a
# sketch catches easily -- scattered edits break up 8-grams throughout).
#
# Non-repetitive on purpose: an early version of this built the base text
# by repeating the same 10 sentences 6 times, and SequenceMatcher's
# similarity() came back nowhere near smooth in edit_rate -- clustered at a
# handful of distinct values regardless of rate. A highly self-repetitive
# base gives ratio() many near-equally-good ways to align matching blocks,
# so a tiny scattered edit can flip which alignment wins rather than
# smoothly costing a few percent -- a real note is not six copies of the
# same paragraph, so this generates ~90 genuinely distinct sentences
# instead (subject/verb/object/qualifier combinations, practically none of
# which repeat), the shape scattered edits actually take in a real vault.
SUBJECTS = ("A subnet mask", "The default gateway", "A static route", "The DNS resolver",
            "A DHCP lease", "The firewall ruleset", "A VLAN trunk", "The routing table",
            "An ACL entry", "The NAT overload pool")
VERBS = ("determines", "forwards", "filters", "resolves", "leases", "partitions",
         "advertises", "prioritizes", "rewrites", "validates")
OBJECTS = ("the broadcast domain", "outbound traffic", "the next hop", "a hostname",
           "an address range", "inbound connections", "the default zone",
           "a trunked interface", "the longest prefix", "translated ports")
QUALIFIERS = ("for this segment", "without manual intervention", "once configured",
              "across the topology", "during normal operation", "per the policy",
              "when the lease expires", "under load", "by design", "at layer three")

def build_prose(n_sentences):
    sentences = []
    for i in range(n_sentences):
        s, v, o, q = (SUBJECTS[i % len(SUBJECTS)], VERBS[(i * 3) % len(VERBS)],
                      OBJECTS[(i * 7) % len(OBJECTS)], QUALIFIERS[(i * 11) % len(QUALIFIERS)])
        sentences.append(f"{s} {v} {o} {q}.")
    return " ".join(sentences)

def scattered_edit(base_words, rng, k):
    """Replace exactly k words, at k random scattered positions -- damage
    spread through the whole text instead of concentrated at one end,
    unlike the append/single-swap cases above. An exact count rather than
    a per-word probability: at the low rates that matter here (a handful
    of words out of ~800), binomial variance between seeds swings the
    *actual* edit count enough that a target rate doesn't reliably land
    near any particular similarity -- picking the count directly does."""
    pool = "alpha bravo charlie delta echo foxtrot golf hotel india juliet".split()
    positions = rng.sample(range(len(base_words)), k)
    edited = list(base_words)
    for p in positions:
        edited[p] = rng.choice(pool)
    return " ".join(edited)

base_text = build_prose(90)  # ~90 distinct sentences, ~3-4KB, real-note-sized, no repetition
base_words = base_text.split()
normalized_base = dedupe.normalize(base_text)

def similarity_at(k, rng):
    edited = scattered_edit(base_words, rng, k)
    return edited, dedupe.similarity(normalized_base, dedupe.normalize(edited))

boundary_hits = {"near_threshold": 0, "total": 0}
for seed in range(8):
    rng = random.Random(f"boundary-{seed}")
    # Binary search on the *count* of scattered edits for the largest k
    # whose similarity is still >= REPORT_THRESHOLD -- brackets the exact
    # boundary this seed's edit pattern produces, rather than hoping a
    # fixed rate happens to land near it.
    lo, hi = 0, len(base_words) // 4
    while lo < hi:
        mid = (lo + hi + 1) // 2
        _, r = similarity_at(mid, random.Random(f"boundary-{seed}-probe-{mid}"))
        if r >= dedupe.REPORT_THRESHOLD:
            lo = mid
        else:
            hi = mid - 1
    # lo is the largest edit count that still met the threshold (or 0);
    # lo+1 is the smallest that fell just short -- test both, the pair
    # that actually straddles REPORT_THRESHOLD for this seed's pattern.
    # Turns out this content doesn't have a gentle slope through
    # REPORT_THRESHOLD -- one more scattered word substitution is often the
    # difference between ~0.998 and ~0.665, no stable middle ground, likely
    # because scattered edits fragment SequenceMatcher's matching blocks
    # much faster than their raw character count would suggest. So instead
    # of expecting either point to land numerically close to the threshold,
    # what actually matters is confirmed directly below: lo really is on
    # one side and lo+1 really is on the other, i.e. the binary search
    # found this seed's real crossing point rather than two points that
    # both happen to be far from it.
    results = {}
    for k in (lo, lo + 1):
        edited, actual = similarity_at(k, random.Random(f"boundary-{seed}-probe-{k}"))
        results[k] = actual
        boundary_hits["total"] += 1
        notes = [
            note("filler-a", "Completely unrelated content about spreadsheets and payroll."),
            note("base", base_text),
            note("filler-b", "Also unrelated: coffee brewing temperatures and grind size."),
            note("edited", edited),
        ]
        check_equivalent(f"scattered seed={seed} k={k} words changed (actual similarity={actual:.3f})", notes)
    if results[lo] >= dedupe.REPORT_THRESHOLD > results[lo + 1]:
        boundary_hits["near_threshold"] += 1
    ck(f"seed={seed}: the two tested points actually straddle REPORT_THRESHOLD",
       results[lo] >= dedupe.REPORT_THRESHOLD > results[lo + 1], results)

ck("every seed's binary search found a real straddle point, not two points on the same side",
   boundary_hits["near_threshold"] == 8, boundary_hits)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)

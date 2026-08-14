"""
Index: a derived cache, never a source of truth.

Everything here can be thrown away and rebuilt from the markdown files in
under a second for a normal vault. That is the whole point — it means a
schema change, a corrupt database, or a version upgrade is never a data
loss event. Delete .index/index.db and restart.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections import Counter, defaultdict
from pathlib import Path

from . import vault

def db_path():
    """A function, not a constant. vault.INDEX_DIR moves when the vault is
    switched, and a module-level capture meant two vaults quietly shared one
    index database — B's notes indexed into A's .index/ directory."""
    return vault.INDEX_DIR / "index.db"

# ![[embed.png]] must be tried before [[wikilink]] or the leading ! is orphaned.
EMBED_RE = re.compile(r"!\[\[\s*([^\]|]+?)\s*(?:\|([^\]]*))?\]\]")
WIKI_RE = re.compile(r"(?<!!)\[\[\s*([^\]|]+?)\s*(?:\|([^\]]*))?\]\]")
TAG_RE = re.compile(r"(?:^|\s)#([\w-]{2,40})")
# A citation marker referencing the Nth entry (1-indexed) of the note's own
# `## Sources` list. `[^N]` rather than bare `[N]` because bare brackets
# collide with ordinary prose; this doesn't collide with anything else here.
CITE_RE = re.compile(r"\[\^(\d+)\]")
CODE_RE = re.compile(r"`[^`]*`|```.*?```", re.S)

# Spans the auto-linker must never write inside. Existing links are the
# important one: rewriting inside `[[Answer Ping|answer ping]]` produced
# `[[Answer [[Ping]]|answer ping]]` — a nested link that renders as raw markup.
#
# `[text](url)` and bare URLs belong here too. Without them, a term matching
# plain text inside a URL path (e.g. "documentation" in
# `.../commonly-referenced-documentation`) got wikilink-wrapped mid-URL,
# breaking the link, and a term inside a markdown link's own anchor text got
# nested-linked the same way `[[...]]` nesting did. The anchor-text branch
# allows exactly one nested `[[wikilink]]` -- e.g. a link whose visible text
# already names another note, `[...for [[Flashblade|FlashBlade]]...](url)` --
# since that is the one shape real link text takes here.
PROTECTED_RE = re.compile(
    r"```.*?```"
    r"|`[^`\n]*`"
    r"|!?\[\[[^\[\]]*\]\]"
    r"|!?\[(?:[^\[\]]|\[\[[^\[\]]*\]\])*\]\([^()\s]*\)"
    r"|https?://\S+",
    re.S,
)

# The quiz block is data, not prose. Links injected there show up as literal
# brackets in questions and options, because the quiz UI renders plain text.
QUIZ_SPLIT_RE = re.compile(r"^##\s+Quiz\s*$", re.M | re.I)

EMPTY_LINK_RE = re.compile(r"!?\[\[\s*\|?\s*\]\]")


def flatten_nested_links(text: str) -> tuple[str, int]:
    """Remove link brackets that occur *inside* another link, keeping the text.

        [[Answer [[Ping]]|answer ping]]  ->  [[Answer Ping|answer ping]]
        [[Deep [[A]] [[B]]|d]]           ->  [[Deep A B|d]]

    A depth-tracking scan rather than a regex: the regex version could only see
    one nested link per outer link, so it silently left the two-nested case
    both unrepaired and undetected by the audit that shared it.
    """
    out, depth, removed, i, n = [], 0, 0, 0, len(text)
    while i < n:
        if text.startswith("[[", i):
            if depth == 0:
                out.append("[[")
            else:
                removed += 1                 # inner opener: drop it
            depth += 1
            i += 2
            continue
        if text.startswith("]]", i) and depth > 0:
            depth -= 1
            if depth == 0:
                out.append("]]")
            else:
                removed += 1                 # inner closer: drop it
            i += 2
            continue
        out.append(text[i])
        i += 1
    result = "".join(out)
    # collapse the double spaces unwrapping can leave behind
    result = re.sub(r"\[\[([^\[\]]*)\]\]",
                    lambda m: "[[" + re.sub(r"\s{2,}", " ", m.group(1)).strip() + "]]",
                    result)
    return result, removed


def count_nested_links(text: str) -> int:
    return flatten_nested_links(text)[1]


def split_quiz_block(body: str) -> tuple[str, str]:
    m = QUIZ_SPLIT_RE.search(body)
    return (body, "") if not m else (body[:m.start()], body[m.start():])


# A `## Sources` section, like the quiz block, is data for its own panel, not
# prose to be rendered inline where it sits. Unlike the quiz block -- which
# always owns the rest of the file -- this one stops at the *next* `##`
# heading (or end of body), so a `## Sources` list can sit anywhere and still
# leave a `## Quiz` section after it alone. That does mean a note with both
# needs `## Sources` written first: Quiz still claims everything after itself.
SOURCES_SPLIT_RE = re.compile(r"^##\s+Sources\s*$", re.M | re.I)
_NEXT_HEADING_RE = re.compile(r"^##\s+\S", re.M)
SOURCE_LINE_RE = re.compile(r"^[-*+]\s*(.+?)\s*$")
SOURCE_LINK_RE = re.compile(r"^\[(?P<text>[^\]]*)\]\((?P<url>[^()\s]+)\)$")
# A bullet that is nothing but a pasted link -- the fastest way to jot down a
# source -- has no brackets to make it a SOURCE_LINK_RE match, but it should
# still be clickable, the same way a bare URL on its own line becomes a
# bookmark card in ordinary prose (see render.py's URL_LINE_RE).
SOURCE_BARE_URL_RE = re.compile(r"https?://\S+")


def split_sources_block(body: str) -> tuple[str, str]:
    """Return (rest, sources_section), sources_section including its own
    heading line."""
    m = SOURCES_SPLIT_RE.search(body)
    if not m:
        return body, ""
    nxt = _NEXT_HEADING_RE.search(body, m.end())
    end = nxt.start() if nxt else len(body)
    return body[:m.start()] + body[end:], body[m.start():end].strip()


def parse_sources(section: str) -> list[dict]:
    """Parse `## Sources` bullet lines into {text, url}. A `- [Title](url)`
    line becomes a clickable source with its own label; a bullet that's just
    a bare URL (or has one embedded, e.g. `- Baker et al. -- https://...`) is
    still clickable, with the whole bullet text as the visible label. Only a
    bullet with no URL at all falls back to plain, unclickable text -- so
    pasting bare citations works with no markdown to learn. The heading line
    itself never matches the bullet pattern, so it's skipped for free."""
    out: list[dict] = []
    for line in section.splitlines():
        m = SOURCE_LINE_RE.match(line.strip())
        if not m:
            continue
        item = m.group(1).strip()
        if not item:
            continue
        lm = SOURCE_LINK_RE.match(item)
        if lm:
            out.append({"text": lm.group("text").strip() or lm.group("url"),
                       "url": lm.group("url")})
            continue
        um = SOURCE_BARE_URL_RE.search(item)
        if um:
            out.append({"text": item, "url": um.group(0).rstrip(").,;:!?")})
            continue
        out.append({"text": item, "url": None})
    return out


def load_sources(body: str) -> list[dict]:
    return parse_sources(split_sources_block(body)[1])


def rewrite_outside_protected(text: str, pattern: re.Pattern, repl) -> str:
    """Apply a substitution only in the gaps between protected spans."""
    parts, last = [], 0
    for m in PROTECTED_RE.finditer(text):
        parts.append(pattern.sub(repl, text[last:m.start()]))
        parts.append(m.group(0))
        last = m.end()
    parts.append(pattern.sub(repl, text[last:]))
    return "".join(parts)


def unlink(text: str) -> str:
    """[[Target|shown]] -> shown, [[Target]] -> Target. Embeds are left alone."""
    return re.sub(r"(?<!!)\[\[\s*([^\[\]|]+?)\s*(?:\|\s*([^\[\]]*?)\s*)?\]\]",
                  lambda m: (m.group(2) or m.group(1)), text)

STOP = set(
    """the a an and or but if then than that this these those of in on at to for from by with
    without into onto over under is are was were be been being it its as not no so such can could
    should would will may might must do does did done have has had you your we our they them their
    he she his her i me my one two three new old more most less least also very just only about
    after before while when where which who whom what why how all any both each few other some own
    same too much many every there here up down out off again further once during until against
    among between through above below set get got make made use used using
    """.split()
)

# Without a POS tagger, a word list is the only thing separating "voltage drop"
# from "run needs". Verbs and generic modifiers are where naive phrase
# extraction goes wrong: they sit on grammatical boundaries that a sliding
# n-gram window strides straight across.
BOUNDARY = set(
    """run runs ran running need needs needed require requires required matter matters
    check checks checked keep keeps kept put puts add adds added give gives gave show shows
    showed work works worked take takes took mean means meant come comes came go goes went
    look looks looked find finds found know knows knew think thinks thought want wants wanted
    say says said see sees seen let lets leave leaves left start starts started stop stops
    answer answers answered reply replies replied respond responds responded return returns
    send sends sent receive receives received happen happens happened cause causes caused
    turn turns turned move moves moved call calls called try tries tried ask asks asked
    mention mentions mentioned
    correct wrong good bad better best worse great nice fine same different several various
    certain particular actual real proper simple easy hard quick slow long short high low
    first last next previous following current recent early late able likely
    possible important necessary useful helpful available common general specific
    """.split()
)


class Conn:
    """Thin serialising wrapper around one SQLite connection.

    FastAPI runs sync endpoints in a threadpool, so the connection is
    shared across threads. check_same_thread=False permits that; the
    lock makes multi-statement work atomic rather than merely legal.
    One connection is the right shape here — this is a single-user
    self-hosted app, not a service with contention.
    """

    def __init__(self, raw: sqlite3.Connection):
        self._c = raw
        self._lock = threading.RLock()
        # Bumped by every write that changes notes/links (reindex_note,
        # drop_note, rebuild). suggestions() caches its expensive corpus-wide
        # mining pass against this, so browsing notes between edits doesn't
        # re-mine the whole vault on every click.
        self.version = 0
        self._sugg_cache: tuple[int, tuple[dict, list]] | None = None

    def touch(self) -> None:
        self.version += 1

    def execute(self, sql, params=()):
        with self._lock:
            cur = self._c.execute(sql, params)
            cur.arraysize = 512
            return cur

    def executescript(self, sql):
        with self._lock:
            return self._c.executescript(sql)

    def commit(self):
        with self._lock:
            return self._c.commit()

    def close(self):
        with self._lock:
            return self._c.close()

    def transaction(self):
        return self._lock


def connect() -> "Conn":
    vault.ensure_dirs()
    raw = sqlite3.connect(db_path(), check_same_thread=False, timeout=15)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA synchronous=NORMAL")
    raw.execute("PRAGMA busy_timeout=15000")
    return Conn(raw)


def init(con: "Conn") -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS notes(
            slug TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '',
            updated TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS links(
            src TEXT NOT NULL,
            target TEXT NOT NULL,
            dst TEXT,
            UNIQUE(src, target)
        );
        CREATE INDEX IF NOT EXISTS links_dst ON links(dst);
        CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
            slug UNINDEXED, title, body, tokenize='porter unicode61'
        );
        """
    )
    con.commit()


def strip_code(text: str) -> str:
    return CODE_RE.sub(" ", text)


def outgoing(body: str) -> list[str]:
    return [m.group(1).strip() for m in WIKI_RE.finditer(strip_code(body))]


def embeds(body: str) -> list[str]:
    return [m.group(1).strip() for m in EMBED_RE.finditer(body)]


def _title_map(con) -> dict[str, str]:
    return {
        r["title"].strip().lower(): r["slug"]
        for r in con.execute("SELECT slug,title FROM notes")
    }


def reindex_note(con: "Conn", note: vault.Note) -> None:
    con.execute(
        """INSERT INTO notes(slug,title,body,tags,updated,created)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(slug) DO UPDATE SET
             title=excluded.title, body=excluded.body, tags=excluded.tags,
             updated=excluded.updated, created=excluded.created""",
        (note.slug, note.title, note.body, ",".join(note.tags),
         note.updated, note.created),
    )
    con.execute("DELETE FROM fts WHERE slug=?", (note.slug,))
    con.execute("INSERT INTO fts(slug,title,body) VALUES(?,?,?)",
                (note.slug, note.title, note.body))

    tmap = _title_map(con)
    con.execute("DELETE FROM links WHERE src=?", (note.slug,))
    seen = set()
    for target in outgoing(note.body):
        key = target.lower()
        if key in seen:
            continue
        seen.add(key)
        con.execute(
            "INSERT OR IGNORE INTO links(src,target,dst) VALUES(?,?,?)",
            (note.slug, target, tmap.get(key)),
        )
    # a new note can resolve links other notes were already making to it
    con.execute("UPDATE links SET dst=? WHERE dst IS NULL AND lower(target)=?",
                (note.slug, note.title.strip().lower()))
    con.commit()
    con.touch()


def drop_note(con: "Conn", slug: str) -> None:
    con.execute("DELETE FROM notes WHERE slug=?", (slug,))
    con.execute("DELETE FROM fts WHERE slug=?", (slug,))
    con.execute("DELETE FROM links WHERE src=?", (slug,))
    con.execute("UPDATE links SET dst=NULL WHERE dst=?", (slug,))
    con.commit()
    con.touch()


def rebuild(con: "Conn") -> int:
    """Full rescan. Also the recovery path for edits made outside the app —
    if you write markdown into the vault by hand, this picks it up."""
    con.executescript("DELETE FROM notes; DELETE FROM links; DELETE FROM fts;")
    notes = vault.all_notes()
    for n in notes:
        con.execute(
            """INSERT INTO notes(slug,title,body,tags,updated,created)
               VALUES(?,?,?,?,?,?)""",
            (n.slug, n.title, n.body, ",".join(n.tags), n.updated, n.created),
        )
        con.execute("INSERT INTO fts(slug,title,body) VALUES(?,?,?)",
                    (n.slug, n.title, n.body))
    tmap = _title_map(con)
    for n in notes:
        seen = set()
        for target in outgoing(n.body):
            key = target.lower()
            if key in seen:
                continue
            seen.add(key)
            con.execute("INSERT OR IGNORE INTO links(src,target,dst) VALUES(?,?,?)",
                        (n.slug, target, tmap.get(key)))
    con.commit()
    con.touch()
    return len(notes)


# ── queries ────────────────────────────────────────────────────────────────

def backlinks(con, slug: str) -> list[dict]:
    row = con.execute("SELECT title FROM notes WHERE slug=?", (slug,)).fetchone()
    if not row:
        return []
    title = row["title"]
    out = []
    for r in con.execute(
        """SELECT n.slug, n.title, n.body FROM links l
           JOIN notes n ON n.slug = l.src
           WHERE l.dst = ? ORDER BY n.title""", (slug,)
    ):
        out.append({"slug": r["slug"], "title": r["title"],
                    "excerpt": _excerpt(r["body"], title)})
    return out


def _excerpt(body: str, term: str, width: int = 190) -> str:
    m = re.search(re.escape(term), body, re.I)
    if not m:
        return re.sub(r"\s+", " ", body)[:width].strip()
    start = max(0, m.start() - width // 2)
    frag = re.sub(r"\s+", " ", body[start:start + width]).strip()
    return ("…" if start else "") + frag + "…"


def search(con, q: str, limit: int = 20) -> list[dict]:
    q = q.strip()
    if not q:
        return []
    try:
        rows = con.execute(
            """SELECT f.slug, n.title, snippet(fts,2,'','',' … ',12) AS snip
               FROM fts f JOIN notes n ON n.slug=f.slug
               WHERE fts MATCH ? ORDER BY rank LIMIT ?""",
            (f'"{q}"*' if " " in q else f"{q}*", limit),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = con.execute(
            """SELECT slug, title, substr(body,1,140) AS snip FROM notes
               WHERE title LIKE ? OR body LIKE ? LIMIT ?""",
            (f"%{q}%", f"%{q}%", limit),
        ).fetchall()
    return [{"slug": r["slug"], "title": r["title"], "snippet": r["snip"]} for r in rows]


def graph(con) -> dict:
    notes = con.execute("SELECT slug,title,tags FROM notes ORDER BY title").fetchall()
    idx = {r["slug"]: i for i, r in enumerate(notes)}
    deg = Counter()
    edges = []
    for r in con.execute("SELECT src,dst,target FROM links"):
        if r["dst"] and r["dst"] in idx and r["src"] in idx and r["dst"] != r["src"]:
            edges.append([idx[r["src"]], idx[r["dst"]]])
            deg[r["src"]] += 1
            deg[r["dst"]] += 1
    stubs = {
        r["target"].lower()
        for r in con.execute("SELECT target FROM links WHERE dst IS NULL")
    }
    # Category comes along so the graph can cluster by it — with 100+ notes a
    # flat force layout is a hairball, and grouping is what makes it readable.
    cats = {}
    from . import vault as _v
    for n in _v.all_notes():
        c = (n.meta.get("category") or "").strip()
        if c:
            cats[n.slug] = c
    nodes = [
        {
            "slug": r["slug"],
            "label": r["title"],
            "kind": "stub" if r["title"].lower() in stubs else "note",
            "deg": deg.get(r["slug"], 0),
            "category": cats.get(r["slug"], ""),
            "index": "index" in (r["tags"] or ""),
        }
        for r in notes
    ]
    # unresolved targets ride along as stub nodes so gaps are visible
    seen = {n["label"].lower() for n in nodes}
    for r in con.execute("SELECT DISTINCT src,target FROM links WHERE dst IS NULL"):
        t = r["target"]
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        nodes.append({"slug": None, "label": t, "kind": "stub", "deg": 1,
                      "category": "", "index": False})
        if r["src"] in idx:
            edges.append([idx[r["src"]], len(nodes) - 1])
    return {"nodes": nodes, "links": edges}


# ── the auto-wiki: what should be linked but isn't ─────────────────────────

MIN_DOCS = 3   # a phrase must recur across this many notes to earn a page
DISMISSED_FILE = "link-suggestions.json"


def dismissed_path():
    return vault.VAULT / DISMISSED_FILE


def load_dismissed() -> dict:
    """Terms the user has said no to.

    Kept in the vault rather than in memory: dismissing used to only remove the
    row from the DOM, so the same suggestions came back the moment you
    navigated away and returned.
    """
    p = dismissed_path()
    if p.is_file():
        try:
            data = json.loads(p.read_text())
            if isinstance(data.get("dismissed"), dict):
                return data
        except Exception:
            pass
    return {"dismissed": {}}


def save_dismissed(data: dict) -> None:
    vault.ensure_dirs()
    dismissed_path().write_text(json.dumps(data, indent=2))


def dismiss_term(term: str, note: str = "") -> dict:
    data = load_dismissed()
    data["dismissed"][term.strip().lower()] = {
        "term": term.strip(), "at": vault.now(), "note": note}
    save_dismissed(data)
    return data


def restore_term(term: str) -> dict:
    data = load_dismissed()
    data["dismissed"].pop(term.strip().lower(), None)
    save_dismissed(data)
    return data


def _mine_suggestions(con) -> tuple[dict, list]:
    """The expensive corpus-wide pass behind suggestions(): every existing
    title checked for plain-text mentions across every note, plus the full
    n-gram scan for recurring unlinked phrases. Neither depends on which
    note is being viewed or how many results are wanted, so this used to
    re-run in full on every note open and every suggestions poll -- for a
    vault of any size that's an O(notes x total text) pass paid on every
    click. It's cached in suggestions() against Conn.version instead, and
    only redone when a note is actually written, dropped, or reindexed.

    Returns (unlinked_by_slug, emerging) where unlinked_by_slug maps a
    target note's slug to its title and full per-note hit list (unfiltered
    by viewing note), and emerging is the already-ranked, already-deduped
    list of 'kind': 'emerging' suggestion dicts.
    """
    rows = con.execute("SELECT slug,title,body FROM notes").fetchall()
    if not rows:
        return {}, []
    # Mined and matched with code, existing links (wiki or markdown), and
    # bare URLs blanked out -- a phrase found only inside one of those would
    # get suggested, and accepting it would corrupt exactly what it's inside
    # of (see PROTECTED_RE).
    bodies = {r["slug"]: PROTECTED_RE.sub(" ", r["body"]) for r in rows}
    titles = {r["slug"]: r["title"] for r in rows}
    linked = defaultdict(set)
    for r in con.execute("SELECT src,target FROM links"):
        linked[r["src"]].add(r["target"].strip().lower())

    # 1. existing titles mentioned as plain text
    #
    # The floor here is 3, not the emerging-phrase miner's 4 below -- this
    # loop only ever matches a title someone already deliberately gave a
    # real note (RPO, RTO, ...), never a guessed n-gram, so a 3-letter
    # acronym is exactly the case worth catching: high confidence, a
    # concrete existing target to link to, not a guess. The word-boundary
    # regex below is what keeps this safe at that length -- "RPO" can only
    # match whole-word, never as a fragment of a longer word. 1-2 character
    # titles stay excluded; those would just be common English words/letters
    # by themselves and flood the list with noise no boundary check saves.
    unlinked_by_slug: dict[str, dict] = {}
    for tslug, title in titles.items():
        if len(title) < 3:
            continue
        pat = re.compile(r"(?<![\w\[])" + re.escape(title) + r"(?![\w\]])", re.I)
        hits = []
        for s, body in bodies.items():
            if s == tslug or title.lower() in linked[s]:
                continue
            n = len(pat.findall(body))
            if n:
                hits.append({"slug": s, "title": titles[s], "count": n})
        if hits:
            unlinked_by_slug[tslug] = {"title": title, "hits": hits}

    emerging = list(_mine_emerging(bodies, titles))
    return unlinked_by_slug, emerging


def _mine_emerging(bodies: dict[str, str], titles: dict[str, str]):
    # 2. recurring phrases with no page
    known = {t.lower() for t in titles.values()}
    df: Counter = Counter()
    caps: Counter = Counter()          # times this phrase appeared Title Cased
    where: dict[str, list] = defaultdict(list)
    for s, body in bodies.items():
        text = re.sub(r"[^\w\s-]", " ", body)
        words = text.split()
        seen_here = set()
        for n in (3, 2, 1):
            for i in range(len(words) - n + 1):
                gram = words[i:i + n]
                low = [w.lower() for w in gram]
                if any(w in STOP or w in BOUNDARY for w in low):
                    continue
                if any(len(w) < 3 or w.isdigit() for w in gram):
                    continue
                phrase = " ".join(gram)
                key = phrase.lower()
                if key in known or key in seen_here:
                    continue
                seen_here.add(key)
                df[key] += 1
                if all(w[:1].isupper() for w in gram):
                    caps[key] += 1
                where[key].append({"slug": s, "title": titles[s]})

    # A phrase earns a page if it reads like a proper noun, or if it recurs
    # widely enough that casing stops mattering. Then drop anything that is
    # only a fragment of a longer phrase already surfaced, so "voltage drop
    # calculation" suppresses "voltage drop" rather than competing with it.
    #
    # "Suppresses" has to mean the longer phrase is genuinely a more specific
    # version of the shorter one -- not just any string containing it. Two
    # things a raw substring test (`k in o`) got wrong:
    #
    # 1. It matches "cat" inside "category" -- no word-boundary check at all.
    #
    # 2. Worse, it matches an n-gram window that only landed on the shorter
    #    phrase by coincidence, bridged by some connecting verb: "mentions
    #    Test Bed" contains "test bed" but is not a more specific phrase than
    #    it, and suppressing "test bed" behind it meant the real, useful
    #    phrase never got suggested at all -- the actual bug report this
    #    fixes. A curated verb list (BOUNDARY, below) can catch known cases
    #    of this, but can never be exhaustive, so it is not the deciding
    #    check here.
    #
    # The document-count match is: if `shorter` ever recurs *without* the
    # extra words, they cannot be a fixed part of the phrase, no matter what
    # they are -- which needs no word list and generalizes past any verb
    # BOUNDARY happens to be missing.
    def extends(shorter: str, longer: str) -> bool:
        if df[longer] != df[shorter]:
            return False
        lw, sw = longer.split(), shorter.split()
        for i in range(len(lw) - len(sw) + 1):
            if lw[i:i + len(sw)] == sw:
                return bool(lw[:i] + lw[i + len(sw):])   # True iff there is an extra word
        return False

    # A single word carries far less evidence of intentionality than a
    # recurring multi-word phrase does -- "system" or "process" would clear
    # MIN_DOCS in any vault about anything. This is exactly the "reads like a
    # proper noun" half of the comment above, which caps[] was already being
    # computed for but nothing was actually checking: a lone word only
    # qualifies if it was capitalized *every* time, the same load-bearing
    # signal that separates "Actuation" (a term) from "the" (not one).
    cands = [
        k for k, n in df.items()
        if n >= MIN_DOCS and (" " in k or (caps[k] == n and len(k) >= 4))
    ]
    cands.sort(key=lambda k: (-df[k], -len(k)))
    kept: list[str] = []
    for k in cands:
        if any(k != o and extends(k, o) for o in kept):
            continue
        kept.append(k)

    for key in kept[:6]:
        yield {
            "kind": "emerging",
            "term": key,
            "target": None,
            "notes": df[key],
            "mentions": df[key],
            "where": where[key][:6],
        }


def suggestions(con, slug: str | None = None, limit: int = 12) -> list[dict]:
    """Two kinds, ranked together.

    'unlinked'  an existing note's title appears as plain prose elsewhere.
                High confidence — the page already exists, we just aren't
                pointing at it.
    'emerging'  a phrase recurs across several notes and has no page yet.
                This is the part that grows a wiki on its own.

    The corpus-wide mining (_mine_suggestions) doesn't vary by slug or
    limit, so it's cached on the connection and reused across calls until
    the index actually changes -- opening notes one after another shouldn't
    re-scan the whole vault each time.
    """
    cached = con._sugg_cache
    if cached is None or cached[0] != con.version:
        cached = (con.version, _mine_suggestions(con))
        con._sugg_cache = cached
    unlinked_by_slug, emerging = cached[1]

    out: list[dict] = []
    for tslug, info in unlinked_by_slug.items():
        hits = info["hits"] if slug is None else [h for h in info["hits"] if h["slug"] == slug]
        if not hits:
            continue
        out.append({
            "kind": "unlinked",
            "term": info["title"],
            "target": tslug,
            "notes": len(hits),
            "mentions": sum(h["count"] for h in hits),
            "where": hits[:6],
        })
    out.extend(emerging)

    hidden = load_dismissed()["dismissed"]
    out = [d for d in out if d["term"].strip().lower() not in hidden]
    out.sort(key=lambda d: (d["kind"] != "unlinked", -d["notes"], -d["mentions"]))
    return out[:limit]


def repair_links(con, dry_run: bool = False) -> dict:
    """Fix link damage across the vault, idempotently.

    Three things get repaired, all of them caused by the auto-linker writing
    where it should not have: links nested inside other links, links injected
    into quiz blocks, and empty `[[]]` husks. Runs on the markdown itself, so
    the fix is visible in the files rather than papered over at render time.
    """
    report = {"scanned": 0, "changed": 0, "notes": [], "created": [],
              "dry_run": dry_run}
    invented: set[str] = set()
    for note in vault.all_notes():
        report["scanned"] += 1
        original = note.body
        body = original
        detail = {"slug": note.slug, "title": note.title,
                  "nested": 0, "quiz_links": 0, "empty": 0, "frontmatter": 0}

        # The `question:` header is prose shown on flashcards, never a link, and
        # repair used to skip it entirely because it only looked at the body.
        meta_changed = False

        # Titles and categories are labels, never links. The old linker could
        # write into either, and a bracketed title is what broke parsing.
        for field, target in (("title", None), ("category", "meta")):
            cur = note.title if field == "title" else (note.meta.get("category") or "")
            if not isinstance(cur, str) or "[[" not in cur:
                continue
            flat, _ = flatten_nested_links(cur)
            fixed = unlink(flat).strip()
            if fixed and fixed != cur:
                if field == "title":
                    note.title = fixed
                else:
                    note.meta["category"] = fixed
                detail["frontmatter"] = detail.get("frontmatter", 0) + 1
                meta_changed = True

        q = (note.meta.get("question") or "")
        if isinstance(q, str) and "[[" in q:
            flat, _ = flatten_nested_links(q)
            cleaned_q = unlink(flat)
            if cleaned_q != q:
                note.meta["question"] = cleaned_q
                detail["frontmatter"] = 1
                meta_changed = True

        # Flattening [[A [[B]]|shown]] yields a link to "A B", which usually
        # names no note. Record the targets it invented so they can be created
        # rather than left as dead amber links.
        before_targets = {m.group(1).strip() for m in WIKI_RE.finditer(body)}
        body, removed = flatten_nested_links(body)
        detail["nested"] = removed
        if removed:
            after_targets = {m.group(1).strip() for m in WIKI_RE.finditer(body)}
            invented |= {t for t in after_targets - before_targets if t}

        prose, quiz = split_quiz_block(body)
        if quiz:
            cleaned = unlink(quiz)
            if cleaned != quiz:
                detail["quiz_links"] = len(WIKI_RE.findall(quiz))
                quiz = cleaned
        body = prose + quiz

        stripped = EMPTY_LINK_RE.sub("", body)
        if stripped != body:
            detail["empty"] = len(EMPTY_LINK_RE.findall(body))
            body = stripped

        if body != original or meta_changed:
            # A dry run that writes is worse than no dry run: it looks like a
            # preview and silently commits, so the real run then reports
            # nothing to do and the user believes it was a no-op.
            if not dry_run:
                note.body = body
                vault.write(note)
                reindex_note(con, note)
            report["changed"] += 1
            detail["preview"] = _first_diff(original, body) or (
                {"before": q[:160], "after": note.meta.get("question", "")[:160]}
                if meta_changed else {})
            report["notes"].append(detail)

    # Create a page for every title flattening produced that does not exist.
    # Doing it after the sweep means titles created here are already visible to
    # the resolver when the index is rebuilt.
    if invented:
        have = {r["title"].strip().lower()
                for r in con.execute("SELECT title FROM notes")}
        for title in sorted(invented):
            if title.lower() in have or "[[" in title:
                continue
            report["created"].append(title)
            if dry_run:
                continue
            note = vault.Note(slug=vault.unique_slug(title), title=title,
                              body="", tags=["repaired"])
            vault.write(note)
            reindex_note(con, note)
            have.add(title.lower())
    return report


def _first_diff(before: str, after: str) -> dict:
    """One concrete before/after line, so a preview shows what will change."""
    a = before.splitlines()
    b = after.splitlines()
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else ""
        y = b[i] if i < len(b) else ""
        if x != y:
            return {"before": x.strip()[:160], "after": y.strip()[:160]}
    return {}


def audit_links(con) -> dict:
    """Read-only version of the same checks, for reporting without writing."""
    issues = []
    for note in vault.all_notes():
        prose, quiz = split_quiz_block(note.body)
        nested_count = count_nested_links(note.body)
        quiz_links = WIKI_RE.findall(quiz) if quiz else []
        empty = EMPTY_LINK_RE.findall(note.body)
        if nested_count or quiz_links or empty:
            sample = ""
            if nested_count:
                m = re.search(r"!?\[\[[^\[\]]*\[\[.{0,60}", note.body, re.S)
                sample = (m.group(0).split("\n")[0] if m else "")
            elif quiz_links:
                sample = f"[[{quiz_links[0][0]}]]"
            issues.append({"slug": note.slug, "title": note.title,
                           "nested": nested_count, "quiz_links": len(quiz_links),
                           "empty": len(empty), "sample": sample})
    return {"issues": issues, "clean": not issues}


def apply_suggestion(con, term: str, target_slug: str | None) -> dict:
    """Link every plain-text mention of `term`. Creates the page first when
    it doesn't exist yet, so accepting a suggestion is one action.

    Rebuilds the index from disk first. This is the one place staleness is
    not an acceptable tradeoff: everything else the index backs (search,
    the graph, backlinks) is allowed to lag a save cycle behind disk, but
    "link every mention" is a promise, and the index -- built incrementally,
    one reindex_note() per save -- is the derived, disposable copy; the
    vault's files are the actual source of truth. A full rescan is not free,
    but this runs once per deliberate accept-click, not per keystroke.
    """
    rebuild(con)
    if not target_slug:
        existing = con.execute(
            "SELECT slug FROM notes WHERE lower(title)=?", (term.lower(),)
        ).fetchone()
        if existing:
            target_slug = existing["slug"]
        else:
            title = term if term[:1].isupper() else term.title()
            note = vault.Note(slug=vault.unique_slug(title), title=title, body="")
            vault.write(note)
            reindex_note(con, note)
            target_slug = note.slug

    title = con.execute("SELECT title FROM notes WHERE slug=?",
                        (target_slug,)).fetchone()["title"]
    pat = re.compile(r"(?<![\w])(" + re.escape(term) + r")(?![\w])", re.I)

    def repl(m):
        return f"[[{title}]]" if m.group(1) == title else f"[[{title}|{m.group(1)}]]"

    touched = 0
    for r in con.execute("SELECT slug FROM notes WHERE slug != ?", (target_slug,)):
        note = vault.read(r["slug"])
        if not note:
            continue
        # Only the prose is linkable; the quiz block is left byte for byte.
        prose, quiz = split_quiz_block(note.body)
        new_prose = rewrite_outside_protected(prose, pat, repl)
        if new_prose != prose:
            note.body = new_prose + quiz
            vault.write(note)
            reindex_note(con, note)
            touched += 1
    return {"slug": target_slug, "title": title, "notes_updated": touched}

"""ENGINEERING.md 2a (drillgroup, 2026-10-21): decisions go into tables,
not long chains. Six or more branches on one variable is a finding.

Taken from GLYPHDRILL's tests/test_branching.py (t-0021-blobs-ccl, a2a6eeb).
The rule and its planted cases are unchanged. Two things are added, because
this repository is a fork of lucasastorian/llmwiki and already has offenders:

  * a finding is keyed by `file:function`, not by line number, so the
    baseline survives edits above the site;
  * `tests/branching_baseline.txt` lists what exists today. The test fails
    on a site that is not in the list, on a site whose count grew, on a
    count that shrank without the list being lowered, and on a stale entry.
    The list only shrinks, and it follows every fix.

The baseline carries a fourth column, the kind of site (elif / sibling-ifs /
match), because one function can branch on the same variable in two shapes.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).resolve().parent / "branching_baseline.txt"
LIMIT = 6
PACKAGES = ("api", "converter", "mcp")
SKIP = {"__pycache__", ".venv", "venv", "node_modules", "migrations", "scripts"}


def _subject(test) -> str | None:
    """The variable an `if` compares: `x == ..`, `x in ..`, `x is ..`."""
    if isinstance(test, ast.Compare):
        return ast.unparse(test.left)
    if isinstance(test, ast.BoolOp):
        subs = {_subject(v) for v in test.values}
        return subs.pop() if len(subs) == 1 else None
    return None


def _scopes(tree) -> dict[int, str]:
    """node id -> the qualified name of the def or class it sits in."""
    out: dict[int, str] = {}

    def visit(node, path):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                here = [*path, child.name]
                out[id(child)] = ".".join(here)
                visit(child, here)
            else:
                out[id(child)] = ".".join(path) or "<module>"
                visit(child, path)

    visit(tree, [])
    return out


def chains(source: str, name: str) -> list[tuple[str, str, str, int]]:
    """Findings as (site, kind, variable, count), sorted."""
    tree = ast.parse(source)
    scope = _scopes(tree)
    found = []

    def site(node) -> str:
        return f"{name}:{scope.get(id(node), '<module>')}"

    inner = set()                      # elif nodes, counted with their head
    for node in ast.walk(tree):
        if isinstance(node, ast.Match) and len(node.cases) >= LIMIT:
            found.append((site(node), "match", ast.unparse(node.subject), len(node.cases)))
        if not isinstance(node, ast.If) or id(node) in inner:
            continue
        subjects, cur = [], node
        while True:
            subjects.append(_subject(cur.test))
            if len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
                cur = cur.orelse[0]
                inner.add(id(cur))
            else:
                break
        for s in set(subjects) - {None}:
            n = subjects.count(s)
            if n >= LIMIT:
                found.append((site(node), "elif", s, n))

    for node in ast.walk(tree):            # flat runs: `if ..: return` x n
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        run = []
        for stmt in [*body, None]:
            if isinstance(stmt, ast.If) and not stmt.orelse:
                run.append(stmt)
                continue
            subjects = [_subject(s.test) for s in run]
            for s in set(subjects) - {None}:
                n = subjects.count(s)
                if n >= LIMIT:
                    first = next(r for r in run if _subject(r.test) == s)
                    found.append((site(first), "sibling-ifs", s, n))
            run = []
    return sorted(found)


def sources() -> list[Path]:
    """Every non-test Python file of the package, in a stable order."""
    out = []
    for pkg in PACKAGES:
        for p in sorted((ROOT / pkg).rglob("*.py")):
            if not SKIP & set(p.relative_to(ROOT).parts):
                out.append(p)
    return out


def scan() -> dict[tuple[str, str, str], int]:
    """{(site, kind, variable): count} over the whole package."""
    found = {}
    for p in sources():
        rel = p.relative_to(ROOT).as_posix()
        for site, kind, var, n in chains(p.read_text(), rel):
            found[site, kind, var] = max(n, found.get((site, kind, var), 0))
    return found


def _format(key, count) -> str:
    site, kind, var = key
    return f"{site} | {kind} | {var} | {count}"


def read_baseline() -> dict[tuple[str, str, str], int]:
    if not BASELINE.exists():
        return {}
    out = {}
    for raw in BASELINE.read_text().splitlines():
        line = raw.split("#")[0].strip()
        if not line:
            continue
        site, kind, var, count = (f.strip() for f in line.split("|"))
        out[site, kind, var] = int(count)
    return out


def compare(found: dict, baseline: dict) -> dict[str, list[str]]:
    """The four ways the gate fails."""
    def drifted(direction):
        return sorted(
            f"{_format(k, n)} (baseline {baseline[k]})"
            for k, n in found.items()
            if k in baseline and direction(n, baseline[k])
        )

    return {
        "new": sorted(_format(k, n) for k, n in found.items() if k not in baseline),
        "grown": drifted(lambda n, b: n > b),
        "shrunk": drifted(lambda n, b: n < b),
        "stale": sorted(_format(k, n) for k, n in baseline.items() if k not in found),
    }


def test_no_new_or_grown_branching_in_the_package():
    bad = compare(scan(), read_baseline())
    assert bad["new"] == [], (
        "six or more branches on one variable — put the decision in a table "
        "(ENGINEERING.md 2a):\n  " + "\n  ".join(bad["new"])
    )
    assert bad["grown"] == [], "a baselined site grew:\n  " + "\n  ".join(bad["grown"])
    assert bad["shrunk"] == [], (
        "these sites got better — lower them in tests/branching_baseline.txt, "
        "the list follows every fix:\n  " + "\n  ".join(bad["shrunk"])
    )
    assert bad["stale"] == [], (
        "these sites are gone — remove them from tests/branching_baseline.txt, "
        "the list only shrinks:\n  " + "\n  ".join(bad["stale"])
    )


def test_the_check_sees_a_planted_chain():
    planted = "def f(op):\n" + "".join(
        f"    {'if' if k == 0 else 'elif'} op == {k}:\n        return {k}\n"
        for k in range(6))
    assert chains(planted, "planted.py") == [("planted.py:f", "elif", "op", 6)]
    five = "\n".join(planted.splitlines()[:-2]) + "\n"
    assert chains(five, "five.py") == []


def test_the_check_sees_a_planted_match():
    src = "def f(op):\n    match op:\n" + "".join(
        f"        case {k}:\n            return {k}\n" for k in range(6))
    assert chains(src, "m.py") == [("m.py:f", "match", "op", 6)]


def test_the_check_sees_flat_sibling_ifs():
    src = "def f(a):\n" + "".join(
        f"    if a.x == {k}:\n        return {k}\n" for k in range(6))
    assert chains(src, "s.py") == [("s.py:f", "sibling-ifs", "a.x", 6)]


def test_the_check_names_the_enclosing_method():
    src = "class C:\n    def m(self, op):\n" + "".join(
        f"        {'if' if k == 0 else 'elif'} op == {k}:\n            return {k}\n"
        for k in range(6))
    assert chains(src, "c.py") == [("c.py:C.m", "elif", "op", 6)]


def test_the_baseline_catches_growth_shrink_and_stale_entries():
    key = ("api/x.py:f", "elif", "op")
    base = {key: 7}
    assert compare({key: 7}, base) == {"new": [], "grown": [], "shrunk": [], "stale": []}

    grown = compare({key: 8}, base)
    assert grown["grown"] == ["api/x.py:f | elif | op | 8 (baseline 7)"]
    assert grown["new"] == [] and grown["shrunk"] == [] and grown["stale"] == []

    shrunk = compare({key: 6}, base)      # still a finding, but the list must follow
    assert shrunk["shrunk"] == ["api/x.py:f | elif | op | 6 (baseline 7)"]
    assert shrunk["grown"] == [] and shrunk["stale"] == []

    assert compare({}, base)["stale"] == ["api/x.py:f | elif | op | 7"]
    assert compare({("api/y.py:g", "match", "kind"): 8}, base)["new"] == [
        "api/y.py:g | match | kind | 8"
    ]


def test_the_baseline_file_is_readable_and_every_entry_is_a_finding():
    base = read_baseline()
    assert base, "the baseline exists; a repository without offenders deletes it"
    assert all(n >= LIMIT for n in base.values()), "a baseline entry below the limit"

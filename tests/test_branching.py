"""ENGINEERING.md 2a (drillgroup, 2026-10-21): decisions go into tables,
not long chains. Six or more branches on one variable is a finding.

The rule is GLYPHDRILL's tests/test_branching.py (t-0021-blobs-ccl, ddcd2b9),
copied unchanged with its planted cases: it counts elif chains, flat sibling
ifs and match statements, and a branch names a variable through a comparison,
a method receiver, a call's last positional argument and `not`. `isinstance`,
plain truthiness and modules name nothing.

Two things are added, because this repository is a fork of
lucasastorian/llmwiki and already has offenders:

  * a finding is keyed by `file:function`, not by line number, so the
    baseline survives edits above the site;
  * `tests/branching_baseline.txt` lists what exists today. The test fails
    on a site that is not in the list, on a site whose count grew, on a
    count that shrank without the list being lowered, and on a stale entry.
    The list only shrinks, and it follows every fix.

The baseline carries a fourth column, the kind of site (elif / sibling-ifs /
match), as the settled T-0057 contract requires: one function can branch on
the same variable in two shapes, and without the column the two collide on
one key and the smaller count reads as a shrink against the larger.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).resolve().parent / "branching_baseline.txt"
LIMIT = 6
PACKAGES = ("api", "converter", "mcp")
SKIP = {"__pycache__", ".venv", "venv", "node_modules", "migrations", "scripts"}

#: calls that are not decisions on a variable (type tests)
UNCOUNTED_CALLS = {"isinstance", "issubclass"}


def _named(node) -> bool:
    return isinstance(node, ast.Name | ast.Attribute)


def _imported(tree) -> set[str]:
    """Names an import binds in the module: `import os` (os), `import
    os.path` (os), `import re as rx` (rx), `from x import y as z` (z)."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.asname or a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            out |= {a.asname or a.name for a in node.names}
    return out


def _root(node) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _subjects(test, modules: frozenset = frozenset()) -> set[str]:
    """The variables an `if` decides on (T-0057 rule, 2026-10-21):
    the left side of a comparison (`x == ..`, `x in ..`, `x < ..`,
    `x is ..`); the receiver of a method call (`s.startswith(..)` -> s);
    the last positional argument of a call (`re.match(p, s)` -> s);
    through `not`; a BoolOp names what all its parts name. `isinstance`
    and plain truthiness name nothing, and neither does a module: a name
    an import binds, or an attribute chain starting with one
    (`os.path.exists(a)` names only a)."""
    def named(node) -> bool:
        return _named(node) and _root(node) not in modules
    if isinstance(test, ast.Compare):
        if isinstance(test.left, ast.Constant) and test.comparators:
            return {ast.unparse(test.comparators[0])}     # "a" == op -> op
        return {ast.unparse(test.left)}
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _subjects(test.operand, modules)
    if isinstance(test, ast.BoolOp):
        subs = [_subjects(v, modules) for v in test.values]
        return set.intersection(*subs) if subs else set()
    if isinstance(test, ast.Call):
        if isinstance(test.func, ast.Name) and test.func.id in UNCOUNTED_CALLS:
            return set()
        out = set()
        if isinstance(test.func, ast.Attribute) and named(test.func.value):
            out.add(ast.unparse(test.func.value))
        if test.args and named(test.args[-1]):
            out.add(ast.unparse(test.args[-1]))
        return out
    return set()


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


def _tests(node, modules) -> list[set[str]]:
    """The subjects of every test along an if/elif chain."""
    out, cur = [], node
    while True:
        out.append(_subjects(cur.test, modules))
        if len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
            cur = cur.orelse[0]
        else:
            return out


def _elifs(node) -> list:
    out, cur = [], node
    while len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
        cur = cur.orelse[0]
        out.append(cur)
    return out


def chains(source: str, name: str) -> list[tuple[str, str, str, int]]:
    """Six or more branches on one variable: in one if/elif chain, or in a
    run of sibling `if` statements counted together with the chains among
    them (`if a: .. if b: .. if c: .. elif d: ..`). A chain inside a run
    that is reported is not reported again. Match statements by cases.

    Findings as (site, kind, variable, count), sorted. `site` is
    file:function, where GLYPHDRILL's reference reports file:lineno.
    """
    tree = ast.parse(source)
    modules = frozenset(_imported(tree))
    scope = _scopes(tree)
    found, covered = [], set()

    def site(node) -> str:
        return f"{name}:{scope.get(id(node), '<module>')}"

    for node in ast.walk(tree):            # runs of sibling if statements
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if not isinstance(body, list):
                continue
            run = []
            for stmt in [*body, None]:
                if isinstance(stmt, ast.If):
                    run.append(stmt)
                    continue
                if len(run) >= 2:
                    tests = [(s, sub) for s in run for sub in _tests(s, modules)]
                    for subj in sorted(set().union(*(sub for _, sub in tests))):
                        n = sum(subj in sub for _, sub in tests)
                        if n >= LIMIT:
                            first = next(s for s, sub in tests if subj in sub)
                            found.append((site(first), "sibling-ifs", subj, n))
                            covered |= {(id(s), subj) for s in run}
                run = []

    inner = set()                      # elif nodes, counted with their head
    for node in ast.walk(tree):
        if isinstance(node, ast.Match) and len(node.cases) >= LIMIT:
            found.append((site(node), "match", ast.unparse(node.subject), len(node.cases)))
        if not isinstance(node, ast.If) or id(node) in inner:
            continue
        inner |= {id(e) for e in _elifs(node)}
        subjects = _tests(node, modules)
        for s in sorted(set().union(*subjects)):
            n = sum(s in sub for sub in subjects)
            if n >= LIMIT and (id(node), s) not in covered:
                found.append((site(node), "elif", s, n))
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


def _chain(tests: list[str], head: str = "", args: str = "s, x") -> str:
    return head + f"def f({args}):\n" + "".join(
        f"    {'if' if k == 0 else 'elif'} {t}:\n        return {k}\n"
        for k, t in enumerate(tests))


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


def test_the_check_sees_method_calls_on_one_receiver():
    src = _chain([f"s.startswith('{c}')" for c in "abcde"] + ["s.isdigit()"])
    assert chains(src, "a.py") == [("a.py:f", "elif", "s", 6)]


def test_the_check_sees_one_variable_as_the_last_argument():
    src = _chain(["s.startswith('a')", "s.startswith('b')",
                  "re.fullmatch('x+', s)", "re.match('y', s)",
                  "not re.search('z', s)", "s.endswith('q')"])
    assert chains(src, "b.py") == [("b.py:f", "elif", "s", 6)]


def test_isinstance_and_truthiness_stay_uncounted():
    src = _chain([f"isinstance(x, T{k})" for k in range(6)])
    assert chains(src, "c.py") == []
    src = _chain(["x"] * 6)
    assert chains(src, "d.py") == []


def test_a_module_is_not_a_subject():
    head = "import os\nimport re as rx\nfrom os import path as p\n"
    different = _chain([f"os.path.exists(a{k})" for k in range(6)], head)
    assert chains(different, "e.py") == []
    aliased = _chain([f"p.isdir(b{k})" for k in range(6)], head)
    assert chains(aliased, "g.py") == []
    one_path = _chain(
        [f"os.path.{fn}(q)" for fn in ("exists", "isdir", "isfile", "islink",
                                       "ismount", "isabs")],
        "import os\n", args="q")
    assert chains(one_path, "h.py") == [("h.py:f", "elif", "q", 6)]
    same = _chain(["os.path.exists(s)", "os.path.isdir(s)",
                   "p.isfile(s)", "rx.match('x', s)",
                   "not rx.search('y', s)", "s.endswith('z')"], head)
    assert chains(same, "f.py") == [("f.py:f", "elif", "s", 6)]


def test_a_constant_on_the_left_names_the_variable():
    src = _chain([f"'{c}' == op" for c in "abcdef"])
    assert chains(src, "k.py") == [("k.py:f", "elif", "op", 6)]


def test_sibling_ifs_and_a_following_chain_count_together():
    src = ("def f(name, args):\n"
           + "".join(f"    if name in T{k}:\n        return {k}\n"
                     for k in range(4))
           + "    if name == 'sqrt':\n        return 4\n"
           + "    elif name in DROP:\n        return 5\n"
           + "    elif name in SYM:\n        return 6\n")
    assert chains(src, "l.py") == [("l.py:f", "sibling-ifs", "name", 7)]
    five = ("def f(name):\n"
            + "".join(f"    if name in T{k}:\n        return {k}\n"
                      for k in range(3))
            + "    if name == 'a':\n        return 3\n"
            + "    elif x:\n        return 4\n")
    assert chains(five, "m.py") == []


def test_a_chain_inside_a_reported_run_is_not_reported_twice():
    """The merge's point: one site, not two. Six in the chain alone, and
    four siblings before it, would be an elif finding and a sibling finding
    on `tag` in the old rule."""
    src = ("def f(tag):\n"
           + "".join(f"    if tag == 'x{k}':\n        return {k}\n"
                     for k in range(4))
           + "".join(f"    {'if' if k == 0 else 'elif'} tag == 'y{k}':\n"
                     f"        return {k}\n" for k in range(6)))
    assert chains(src, "n.py") == [("n.py:f", "sibling-ifs", "tag", 10)]


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

# 319 — defect: `_WIKI_LINK_RE` reads LaTeX as internal links

Measured on a 2,222-page mathematics wiki holding 46,808 maths expressions.

---

## The defect

```python
_WIKI_LINK_RE = re.compile(r"(?<!!)\[(?:[^\]]*)\]\(([^)]+)\)")
```

Defined identically in two places:

- `mcp/tools/references.py:11`
- `api/services/references.py:13`

It treats **any** bracket group followed by a parenthesis group as a link. That
is the markdown shape, but it is also an extremely common LaTeX shape:

```latex
\left[\begin{array}{c} i \\ k l \end{array}\right](\mu \nu)
```

The parser extracts `\mu \nu` as an href and resolves it to
`bh2/equations/\mu \nu`.

Real examples from this corpus:

| page | href extracted |
|---|---|
| `wiki/bh2/equations/bh2_EQ0083.md` | `\mu \nu` |
| `wiki/bh2/equations/bh2_EQ0115.md` | `\kappa \lambda` |
| `wiki/BH1org_OCR/equations/BH1org_OCR_EQ0145.md` | `\kappa` |
| (two pages) | `+` |

**A second group is a link target only if it looks like a path.** These do not.

## Scale, and why it matters more than 0.7 % suggests

Of 4,460 internal links parsed across the wiki:

| | |
|---|---|
| resolve to a real page | 4,427 (99.3 %) |
| **dangling** | **33 (0.7 %)** |
| of those, genuinely broken links | **0** |
| of those, LaTeX misread as a link | **33 (100 %)** |

The direct harm is small: because no page is named `\mu \nu`, the false links
resolve to nothing and no wrong edge is written. Nothing in the graph is
corrupted.

The real cost is the **dangling-link signal**. Anyone auditing this wiki for
broken links gets 33 reports, and **every one is false**. The one report that
would surface a genuine broken link is exactly the report this defect makes
unusable — and it degrades with the amount of matrix and index notation in the
corpus, so it is worst precisely where the wiki is most mathematical.

## Can the regex be tightened without breaking real links?

Yes. Five candidates, each measured against all 4,460 hrefs (after llmwiki's own
`http`/`#`/`mailto:`/image pre-filters):

| rule | real kept | **real lost** | false killed | false left |
|---|---|---|---|---|
| A — reject href containing `\` | 4,427 | **0** | 29 | 4 |
| B — reject href containing whitespace | 4,427 | **0** | 28 | 5 |
| C — A and B | 4,427 | **0** | 31 | 2 |
| D — require a file extension | 4,427 | **0** | **33** | 0 |
| **F — path-safe characters only** | **4,427** | **0** | **33** | **0** |

C leaves the two bare `+` hrefs. D and F both clear the set.

**Do not use D.** Requiring an extension would reject extensionless targets, and
`_parse_wiki_links` deliberately supports them — the `elif "/" not in href`
branch resolves a bare name against the current directory. llmwiki's own tracked
markdown contains such links (`LICENSE`, `source`). D would break them.

**Recommended: F** — constrain the href to characters a path can contain:

```python
_WIKI_LINK_RE = re.compile(r"(?<!!)\[(?:[^\]]*)\]\(([A-Za-z0-9._~\-/%#]+)\)")
```

Verified against the corpus:

- keeps **4,427 of 4,427** real links — none lost
- rejects **33 of 33** LaTeX false positives
- still accepts extensionless same-directory targets (`SomePage`)
- still accepts anchors (`notes.md#top`)
- still accepts percent-encoded spaces (`a%20b.md`)

It excludes backslash, whitespace, `+`, `$`, `{`, `}` and the rest of the
characters that appear in mathematics but not in a path.

## Fraction of the 4,460 that would change

**33 — 0.74 %.** All of them currently dangle; none becomes an edge either way.
So the change alters **no graph edge at all**: it only stops the parser
manufacturing targets that never existed.

For real links the change is **0 %**. That is the point of choosing F over D.

## Caveats on the fix

- A link whose target genuinely contains a space (`[x](my file.md)`) would now
  be skipped. Markdown requires such targets to be percent-encoded or
  angle-bracketed, and F accepts `%20`; but if llmwiki wants to keep tolerating
  raw spaces, add `<...>` handling rather than widening the class back out.
- **Fix both copies.** The pattern is duplicated verbatim in
  `mcp/tools/references.py` and `api/services/references.py`, so patching one
  leaves the other misreading maths.
- A stricter fix would make the parser math-aware — skip spans between `$…$`
  and `$$…$$` before looking for links. That is more correct and more
  invasive; F gets the same result here for one line, and the two compose if
  the stricter fix is ever wanted.

## Reproducing

The measurement is a scan of the wiki's stored content using llmwiki's own
parser, not a reimplementation: load `_parse_wiki_links` from
`mcp/tools/references.py`, run it over every `source_kind='wiki'` row, and
partition the extracted hrefs on whether they resolve to a `relative_path` in
`documents`. The 33 that do not are listed above in full.

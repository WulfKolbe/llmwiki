# 313 — what llmwiki's wiki page store accepts, and whether it can hold the Heim material

Short answer to the question posed: **it can, and it already does.** The premise
that the page store is plain markdown with no maths convention is false, and the
finding is a measurement rather than a mapping.

---

## 1. The store

Wiki pages are rows in `documents` (`shared/sqlite_schema.sql:17`) with
`source_kind = 'wiki'`:

| column | what it holds |
|---|---|
| `content` | **the markdown, verbatim** — no transformation on the way in |
| `relative_path` | `wiki/…/page.md`, `UNIQUE` — the page's identity |
| `title`, `filename`, `path` | display and location |
| `tags`, `date`, `metadata` | from frontmatter |
| `content_hash`, `mtime_ns`, `version`, `status`, `stale_since` | change tracking |
| `highlights` | reader highlights, JSONB |
| `file_type`, `file_size`, `page_count`, `parser` | provenance |

`content TEXT` is the whole contract. **The store does not parse, validate or
normalise markdown** — whatever the file says is what the row says. There is no
schema of element types here at all, which is precisely why it can hold things
`converter/main.py` cannot (see 312).

Alongside each page:

| table | rows here | what it is |
|---|---|---|
| `document_chunks` | 4,277 | FTS units, with `source_content` and `annotations_text` |
| `document_references` | **0** | the link graph — see §4 |
| `document_pages` | 0 | per-page elements; used for PDF sources, not wiki pages |
| `knowledge_base_events` | 325,674 | append-only event log |

## 2. The markdown dialect

Set by `web/src/components/wiki/WikiContent.tsx:24`:

```
remark:  remarkGfm · remarkMath · remarkFixOverescapedMath · remarkTaskStatus
rehype:  rehypeKatex
```

So: GitHub-flavoured markdown (tables, strikethrough, autolinks), task lists,
**maths**, plus dynamically-loaded `mermaid` and quiz blocks. Links are ordinary
markdown links to wiki paths (`mcp/tools/guide.py:157`); there is no wikilink
plugin, so `[[…]]` renders as literal text.

## 3. Maths — supported, and actively repaired

`remark-math` + `rehype-katex` with **KaTeX 0.16.45**:

- inline `$…$`, display `$$…$$`
- `\( … \)` and `\[ … \]` are **forbidden**, explicitly, because markdown eats
  the backslashes (`mcp/tools/guide.py:138`)

llmwiki goes further than accepting maths — it *repairs* it.
`remarkFixOverescapedMath` (`WikiContent.tsx:218`) walks `inlineMath` and `math`
nodes and undoes the two failure modes that survive a round trip through
markdown:

```js
node.value = node.value
  .replace(/\\\\(?=[a-zA-Z])/g, '\\')     // \\alpha -> \alpha
  .replace(/\\%|%/g, m => m === '%' ? '\\%' : m)   // bare % -> \%
```

A store with no maths convention does not ship a pass whose only job is fixing
over-escaped LaTeX.

## 4. Measured: the Heim material is in there

Counted directly from the live index of `~/HeimWiki`:

| | |
|---|---|
| wiki pages stored | **2,222** |
| inline `$…$` expressions stored | **45,831** |
| display `$$…$$` blocks stored | **977** |
| **total maths expressions in the page store** | **46,808** |
| LaTeX altered on the way in | **none** — `r \leqq 6`, `V_{r}` stored byte-for-byte |
| chunks that cut a formula in half | 12 of 4,277 (**0.3 %**) |

All four volumes are present: 950 document pages carrying the prose, 1,054
element pages, 27 references, 192 concept pages. Every expression compiles under
the same KaTeX the renderer uses.

So the question "can llmwiki hold this material" has an empirical answer that
does not need a design decision: it is holding it now.

## 5. The real gap is not maths — it is the link graph

`document_references` has **0 rows**, though the 2,222 pages contain thousands
of internal links. The table exists and is exactly the right shape
(`source_document_id`, `target_document_id`, `reference_type`, `page`), and
`api/services/references.py` is written to fill it — it parses citations *and*
`[text](path.md)` internal links, which is the format these pages use.

It has simply never been run here: it is driven from `api/routes/graph.py`, a
separate build step, not by indexing. Until it runs, backlinks and the graph
view are empty while the links themselves render fine. **That is a build-step
gap, not a schema gap** — nothing needs to change for it to work.

Second observation, minor: `knowledge_base_events` holds 325,674 rows against
2,222 pages, almost all of it churn from repeated re-indexing while the build
tree sat inside the workspace (see 312's sibling finding). It is an append-only
log and harmless, but it is not a useful record of anything.

## 6. Conclusion

- **The page store accepts arbitrary markdown, verbatim.** It has no element
  schema, so nothing about a document's structure can be rejected by it.
- **It has a maths convention**: `$…$` / `$$…$$`, KaTeX, plus a repair pass.
- **The four Heim volumes are representable and represented** — 46,808
  expressions stored unaltered.
- The constraint that does exist is upstream: `converter/main.py` (312) can put
  none of this in, because its six-type schema has no equation, table or
  citation. Material of this kind has to arrive from a drilled docmodel, and it
  does.

No importer written, per the task.

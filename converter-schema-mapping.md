# 312 — converter/main.py: the schema it accepts, and what pdfdrill has no home for

Read before writing an importer, as instructed. Counts on the pdfdrill side are
measured over 60 drilled documents in `~/pdfdrill-library`.

---

## 1. Where this code actually sits

`converter/main.py` is **not** the path a wiki page travels. It is the isolated
service that turns an uploaded **source document** into text: `api/services/ocr.py`
calls `_call_converter_extract(presigned_url, "pdf")`, and the converter returns
per-page markdown for that source.

So it defines what llmwiki can get out of a PDF **on its own** — the alternative
to drilling one. A projector that writes `wiki/**.md` bypasses it entirely.

That makes the comparison below the useful one: it is the difference between
what llmwiki's own extractor can represent and what pdfdrill's docmodel holds.

## 2. What it accepts

Input is **opendataloader JSON**, not a schema llmwiki defines:

```json
{ "number of pages": 42,
  "kids": [ { "type": "paragraph", "page number": 3, "content": "…" }, … ] }
```

A flat list of page-tagged elements. `_extract_pages` walks `kids`, drops
anything whose `page number` is not an integer in `1..number of pages`, renders
each element, and joins per page:

```json
[ { "page": 1, "content": "<markdown>" }, … ]
```

## 3. The element types it renders — all six

`_element_to_markdown` (line 202) handles exactly:

| `type` | fields read | markdown produced |
|---|---|---|
| `heading` | `content`, `heading level` (clamped 1–6) | `#…# content` |
| `paragraph` | `content` | the text |
| `list` | `list items[]` → `content`, `kids[]` → `content` | `- item` / `  - child` |
| `image` | `source` | `![image](source)` |
| `caption` | `content` | `*content*` |
| `header`, `footer` | — | **skipped** (line 313) |

Every other type falls through to `return ""` at line 269 and is **dropped
silently** — no warning, no counter, no record that anything was there.

Two structural limits worth naming: lists nest **exactly two levels**, and
`caption` is a top-level element rather than an attachment, so a rendered
caption has no link to the thing it captions.

## 4. Mapping — pdfdrill object → converter element

| pdfdrill object | count | destination | note |
|---|---|---|---|
| `Section` | 491 | **`heading`** | clean; `level` maps to `heading level`, clamped at 6 |
| `Paragraph` | 13,399 | **`paragraph`** | clean |
| `ListItem` | 1,608 | **`list`** | lossy: pdfdrill emits flat `ListItem`s, the converter wants one `list` element owning its items, and only two levels survive |
| `Picture` | 107 | **`image`** | needs a resolvable `source`; pdfdrill carries `cdn_url` |
| `Abstract` | 32 | `paragraph` | representable, but loses that it is an abstract |
| `Diagram` | 521 | `image` *partially* | only if a raster source exists; a Diagram carrying `latex_code` has nowhere to put it |
| `Equation` | 6,784 | **none** | |
| `Formula` | 22,857 | **none** | |
| `Table` / `TableRow` / `TableCell` | 142 / 719 / 3,600 | **none** | the converter has no table type at all |
| `Citation` | 2,635 | **none** | |
| `Reference` | 1,080 | **none** | no BibTeX destination |
| `Footnote` | 188 | **none** | |
| `Sidenote` | 446 | **none** | |
| `Theorem` | 69 | **none** | |
| `Proof` | 8 | **none** | |
| `Toc` | 6 | **none** | and `header`/`footer` are explicitly discarded |
| `LtxCommand` | 123 | **none** | |
| `MathTail` | 1 | **none** | |
| `CodeListing` | **0** | **none** | `docmodel/modules/code_listing.py` exists; no instance in any of the 60 documents. The converter has no `code` type either, so both sides are empty — a gap on paper, not in practice |
| `Page` | 2,651 | — | becomes the `page number` field, not an element |
| `Document` | 60 | — | becomes `number of pages` |

**Four types map cleanly. One maps partially. Fourteen have no destination.**

## 5. The gap that matters

**Mathematics has no representation in this schema.** `Formula` (22,857) plus
`Equation` (6,784) is **29,641 objects with nowhere to go** — 63% of everything
pdfdrill extracts from these documents. There is no `equation` type, no `math`
type, and no convention for inline maths inside `paragraph` content: whatever
opendataloader put there arrives as prose and is stored as prose.

For a mathematics corpus that is the whole document. The four Heim volumes carry
13,454 Formula and Equation objects between them; through this path all of them
would be either flattened into paragraph text or lost.

Second: **tables are absent entirely** — 142 tables, 719 rows and 3,600 cells
have no type to become.

Third: **nothing that carries provenance survives** — no citation, reference,
footnote or sidenote type. A claim extracted this way cannot cite anything,
because the citation was dropped on the way in.

## 6. What this implies (no importer written, per the task)

- The converter is a **reader of last resort**: it is what you get when a
  document has not been drilled. It answers "what does this PDF say", not "what
  is in this document".
- Its silence is the risk. An unhandled type returns `""` and vanishes, so a
  document whose substance is equations arrives looking complete and short. The
  count of what was dropped is never recorded.
- Anything that needs mathematics, tables, or citations has to reach the wiki by
  another route, and the drilled docmodel is that route — it already holds all
  22 types with their relationships intact.
- If this schema is ever to carry drilled content, the smallest useful additions
  are an `equation` type (block, with `latex` and an optional number), a
  convention for inline maths inside `paragraph` content, and a `table` type.
  Those three cover 29,641 + 4,461 of the objects that currently have no home.

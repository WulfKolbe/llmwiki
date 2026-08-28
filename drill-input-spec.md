# 266 — LLMWiki CLI: input specification for a drilled folder

What a projector needs from a `pdfdrill` drill folder to build wiki pages, stated
before anything changes on either side.

Everything below was read from three real documents on 2026-08-27/28:
`crane2020` (42 pp.), the four Heim volumes (`BH1org_OCR`, `bh2`, `BH3FR`,
`WDorg4`; 1,042 pp.), and `cardona2013` (378 pp.). Counts are measured, not
estimated.

---

## 1. What is read today

### 1.1 Files in the drill folder

| path | why | required |
|---|---|---|
| `model.docmodel.json` | the whole structural read | **yes** |
| `okf/<bibkey>/<type>/*.md` | per-unit ids, stable across runs | yes, for citing |
| `report-crops/*.jpg` | the scan behind each equation | yes, for evidence pages |
| `<bibkey>.tiddlers.json` | **only** for `translated_lang` (§2.6) | workaround |
| `<name>.drill.json` | read indirectly via `pdfdrill status` | no |

Not read: `report.tex`, `report.pdf`, `inspect/`, `texzip/`, `*.lines.json`,
`model.docpack.json`, `*.coverage.tsv`, `*.ink.json`.

### 1.2 Model objects and the fields consumed

Field presence measured on `cardona2013`:

| object | fields read | presence |
|---|---|---|
| `Toc` | `entries` | 1/1 — a flat list of 70 strings |
| `Abstract` | `text`, `page` | 11/11 both |
| `Section` | `caption`, `level`, `page` | 24/24 all three |
| `Equation` | `latex`, `page`, `refnum`, `cdn_url`, `confidence` | 1012/1012 present; `refnum` **non-empty on 494** |
| `Formula` | `latex` | 3755 |
| `Paragraph` | `text`, `page`, `flow_index`, `text_source` | `text` 1792/1792; `region` 1499/1792 |
| `Reference` | `citekey`, `raw_text`, `year`, `author`, `entry_type`, `bibtex` | 8/8 except `bibtex` (0 until `bibfetch`) |
| `Page` | counted only | 378 |

Read on the Heim volumes in addition: `Paragraph.text_source` (the untranslated
original; 1,555 of 1,582 units), `ListItem.text`.

**Not read but present, and it cost me:** `model.meta` (`bibkey`, `source_path`,
`source`, and a `pages[]` array with `page_height`/`page_width`/`image_id` per
page) and `model.streams`. I recomputed the page count by counting `Page`
objects when `meta.pages` already had it, and re-derived the bibkey from the
folder name when `meta.bibkey` is authoritative. That is my defect, not the
model's — but see §5.1 on why it kept happening.

---

## 2. Parsed out of strings; wanted as fields

Each item below is information the extractor **had** and flattened into prose,
forcing every consumer to write the same fragile regex.

### 2.1 Table of contents → structured rows

`Toc.entries` is a flat `list[str]` mixing three shapes:

```
"Gravitation Theory and Chern-Simons Forms  ..... 137"
"Gravitation Theory and Chern-Simons Forms"
"..... 137"
"J. Zanelli"
```

I parse title, printed page and author out of that with two regexes. **Wanted:**

```json
"entries": [
  {"title": "Gravitation Theory and Chern-Simons Forms",
   "printed_page": "137", "level": 1, "authors": ["J. Zanelli"]}
]
```

The dot leader is already recognised — that is how the split lines are produced.
Emitting the parts instead of the parts *and* the joined string would remove the
regex entirely.

### 2.2 Printed page ↔ PDF page

There is no mapping. I **search** for it: try each offset 0–60 and keep the one
aligning the most TOC rows with an `Abstract` page. On `cardona2013` that yields
`+11`, confirmed by 11 abstracts. It is a guess that happened to be checkable.

**Wanted:** `meta.page_offset`, or `printed_page` on each `Page`. Front matter
means the offset is not always constant, which is exactly why the consumer
should not be inferring it.

### 2.3 Chapter membership

No object says which chapter anything belongs to. I reconstruct chapters as
"TOC row that an `Abstract` confirms", then take page ranges from consecutive
abstract pages.

**Wanted:** a `Chapter`/`Part` object (`title`, `authors`, `page_start`,
`page_end`, `level`), or `chapter_id` on every object. `parent_section` already
exists on `Paragraph` and `Abstract` — a `parent_chapter` would follow the same
shape.

### 2.4 Unit ↔ crop

`report-crops/` filenames are built from the bibkey **at `cdncrops` time**:

```
Geometric__Algebraic_..._Z-Library__EQ0003.jpg     # crop, old bibkey
cardona2013_EQ0003                                  # unit, after --bibkey
```

I join them on the `EQ####` ordinal parsed out of the filename.

**Wanted:** `crop_path` (relative to the drill folder) on the unit, alongside
`cdn_url`. Then a rename cannot desynchronise anything.

### 2.5 Math delimiters

`latex` fields and prose use `\( … \)` and `\[ … \]`. llmwiki forbids both
(`mcp/tools/guide.py:138` — markdown eats the backslashes). Every consumer
rewrites them to `$ … $`.

**Wanted:** either `$`-delimited output, or `meta.math_delimiters: "latex-paren"`
so the conversion is declared rather than guessed.

### 2.6 Translation language

`Paragraph.text` holds the translation and `Paragraph.text_source` the original
— but **`translated_lang` exists only in `<bibkey>.tiddlers.json`**, never in the
model. A projector can see two texts and cannot say which language either is, so
it must open a second file to find out.

**Wanted:** `translated_lang` and `lang_source` on the object, or in `meta`.

### 2.7 In-text citations to sibling volumes

Heim's register writes `\((2,21)\)` for "volume 2, page 21". I regex it into a
link. **Wanted:** structured cross-references `{volume, pages}` on the object.

### 2.8 Definition-list structure

`BH3FR` pages 80–99 are a glossary: `Term: definition`, with `→` cross-references
and volume citations. It arrives as 23 `Paragraph` blobs; I split 192 entries out
of them, and the German needed a Needleman–Wunsch alignment against the English
because German capitalises every noun and a Title-case scan steals the previous
definition's tail.

**Wanted:** a `DefinitionList`/`GlossaryEntry` object (`term`, `definition`,
`xrefs[]`). This is the highest-value item on the list: it is the only content in
1,042 pages that is *already* wiki-shaped.

---

## 3. What is built from it

| page kind | built from |
|---|---|
| source page | `meta` + object census + `Toc` |
| chapter page | `Toc` row + `Abstract.text` + page range |
| evidence page | `Equation.latex` + `refnum` + `page` + crop |
| concept page | `GlossaryEntry`-shaped text parsed from `Paragraph` (§2.8) |
| register page | `Equation` grouped by `page` |

Invariants the projector holds itself to, and which the input should make
possible to satisfy:

1. **No prose is written by hand.** Every sentence is the document's own.
2. **Every formula ships with its scan.** OCR is a reading, not a fact.
3. **Every expression compiles** under the same KaTeX the renderer uses, or is
   shipped verbatim in a code block with the scan as authority.
4. **Every link and image resolves** before publishing.

---

## 4. Where the model and the wiki do not line up

| # | mismatch | effect |
|---|---|---|
| 1 | model is object-centric; a wiki is document-centric | chapters must be reconstructed (§2.3) |
| 2 | `okf/<bibkey>/equations/` holds **both** `Equation` (1012) and `Formula` (3755) — 4,772 files | the folder name does not discriminate; `page` presence is the de-facto test |
| 3 | OKF frontmatter optionality is undeclared | `page` is on 1012 of 4772 units (21%); I assumed it universal and silently dropped correct matches until a `TypeError` on `int(None)` exposed it |
| 4 | `resource:` is a CDN URL | an OKF bundle is not self-contained; must be paired with `report-crops/` by filename convention |
| 5 | `refnum` key present ≠ populated | present on 1012 `Equation`s, non-empty on 494. OKF emits the 494 — correct, but only discoverable by measuring |
| 6 | no output contract | `commands.yaml` describes the input surface only; `grep -cE '^\s*(outputs\|writes\|schema\|emits):'` → **0** |

---

## 5. Attribution

### 5.1 Mine — projection defects, not input defects

- **A dot leader parsed as a chapter title.** My regex accepted `".."` as a
  title, producing 22 chapters from 11 abstracts and silently overwriting pages
  through slug collisions. I wrote the regex; the bug is mine. §2.1 would have
  made it unwritable, which is a different claim from it being pdfdrill's fault.
- **I read `Section.text` and `Section.title` and concluded "Section is too
  noisy to use".** The populated field is `caption` (24/24, with `level`);
  `title` is empty on 12 of 24. My conclusion was right by accident — 24 sections
  across a 378-page volume is sparse and duplicated, so `Abstract` is still the
  better chapter signal — but my stated reason was wrong, and I had not read the
  field before judging it.
- **I ignored `model.meta`** and recomputed what it already carried.
- **I hand-rolled formula matching with `difflib`** when `crossref --query`
  exists and scores 1.00 where my similarity scored 0.94.
- **Choosing `Abstract` as the chapter signal, capping evidence at 3 per
  chapter, excluding Marcolli's chapter** — projection choices. Marcolli's
  chapter has no `Abstract` object; declining to guess a boundary and saying so
  on the source page is the projector behaving correctly, not an input defect.
- **Rendering choices** (`![` at line start being a TiddlyWiki heading; LaTeX in
  a widget attribute failing on `<`, `>`, `&`) are mine and downstream of this
  interface entirely.

### 5.2 pdfdrill's — the input contract

- **§2.1** `Toc.entries` discards structure that existed at parse time.
- **§2.2** no printed↔PDF page mapping, though front matter is what makes one
  necessary.
- **§2.4** crop filenames bind to the bibkey at fetch time with no field linking
  unit → crop.
- **§2.6** `translated_lang` reaches the tiddler bundle but not the model.
- **A `model` rebuild destroys translations.** Measured on `2409.18839`: 105
  translated units in the tiddler bundle, **0** in a model rebuilt six days
  later. `plan` already refuses to clobber a held `LATEX_INGESTED`; translation
  deserves the same guard.
- **§4.6** no declared output contract, so every consumer discovers the shape by
  reading files and, eventually, by crashing on it.

### 5.3 Neither

- `Section` being sparse, and Marcolli's chapter having no abstract, are
  properties of the document and its OCR. The contract cannot fix them; it can
  only let a projector detect and report them, which it does.

---

## 6. Normative summary

A projector can be built against a drill folder that provides:

**Must have** — `model.docmodel.json` with `meta.bibkey`; objects carrying
`type`, stable `id`, and `page` where a page exists; `Equation.latex` +
`cdn_url`; `Paragraph.text`.

**Should have, currently parsed out of strings** — structured `Toc.entries`
(§2.1); `page_offset` or per-`Page` `printed_page` (§2.2); chapter membership
(§2.3); `crop_path` per unit (§2.4); declared math delimiters (§2.5);
`translated_lang` + `lang_source` on the object (§2.6).

**Should declare** — per-projection `outputs:` in `commands.yaml`: root path,
layout, and each frontmatter key with its type and **whether it is always
present**, plus a note on why it is absent when it is not (§4.3, §4.5).

**Must not** — silently drop an enrichment on rebuild (§5.2).

Nothing here requires a new projection. §2.1–§2.4 and §2.6 are fields the
extractor already knows at the moment it flattens them into a string.

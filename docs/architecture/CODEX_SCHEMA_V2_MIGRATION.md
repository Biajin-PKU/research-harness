# Codex Task: Schema v2 Migration

## Context

`packages/paperindex/paperindex/cards/schema_v2.py` contains the new `PaperCard` frozen dataclass (34 typed fields, 3 nested types: `MathFormulation`, `StructuredResult`, `EvidenceEntry`). It was designed by Opus and adversarial-reviewed by Codex in the previous session. It is ready for production use.

The current production code uses `schema.py` (plain dict with 33 string/list fields, `build_empty_paper_card() -> dict`). The migration replaces the dict-based schema with the typed dataclass.

## Scope: 3 Tasks

### Task 1: Replace schema.py with schema_v2.py

**Goal:** Make `PaperCard` dataclass the single source of truth.

**Steps:**

1. **Delete** `packages/paperindex/paperindex/cards/schema.py` (the old dict-based schema)
2. **Rename** `schema_v2.py` → `schema.py` (move the file, keep all content)
3. **Update imports** everywhere that references the old schema:
   - `assembler.py` line 7: `from .schema import build_empty_paper_card` → `from .schema import PaperCard, build_empty_paper_card_v2 as build_empty_paper_card` (or better: just use `PaperCard()` directly)
   - `extraction.py` line 6: return type annotation should become `PaperCard` (not `dict`)
   - Any other `from .schema import ...` or `from ..cards.schema import ...`
4. **Rename** `build_empty_paper_card_v2` → `build_empty_paper_card` in the new schema.py
5. **Rename** `PAPER_CARD_FIELDS_V2` → `PAPER_CARD_FIELDS` in the new schema.py
6. **Delete** `schema_v2_draft.py` if it still exists (obsolete draft)

### Task 2: Update assembler.py to produce PaperCard dataclass

**Goal:** `build_card_snapshot()` returns `PaperCard` instead of `dict`.

**Current code** (`assembler.py`):
```python
def build_card_snapshot(structure: StructureResult, sections: list[SectionResult]) -> dict:
    card = build_empty_paper_card()  # returns dict
    card["paper_id"] = hashlib.sha1(...).hexdigest()[:16]
    card["title"] = title
    # ... mutates dict fields
    return card
```

**Target:** Build a `PaperCard` dataclass instead. Since `PaperCard` is frozen, collect all fields into a kwargs dict first, then construct once:

```python
from .schema import PaperCard, EvidenceEntry

def build_card_snapshot(structure: StructureResult, sections: list[SectionResult]) -> PaperCard:
    title = structure.raw.get("title") or Path(structure.doc_name).stem
    section_map = {item.section: item for item in sections}

    # Build evidence list
    evidence = [
        EvidenceEntry(
            section=item.section,
            confidence=item.confidence,
            snippet=item.content[:300],
        )
        for item in sections if item.content
    ]

    # Extract key_results from experiments
    experiments_content = section_map.get("experiments", SectionResult("experiments", "")).content
    key_results = [line.strip() for line in experiments_content.splitlines() if line.strip()][:5] if experiments_content else []

    # Extract limitations
    limitations_content = section_map.get("limitations", SectionResult("limitations", "")).content
    limitations = [line.strip() for line in limitations_content.splitlines() if line.strip()][:5] if limitations_content else []

    return PaperCard(
        paper_id=hashlib.sha1(structure.pdf_hash.encode("utf-8")).hexdigest()[:16],
        title=title,
        pdf_path=structure.doc_name,
        core_idea=section_map.get("summary", SectionResult("summary", "")).content[:1200],
        method_summary=section_map.get("methodology", SectionResult("methodology", "")).content[:2000],
        key_results=key_results,
        limitations=limitations,
        evidence=evidence,
    )
```

**Also update:**
- `extraction.py`: return type `dict` → `PaperCard`
- `indexer.py` line 54-59: `build_card()` return type `dict` → `PaperCard`

### Task 3: Add new extraction prompts and expand section coverage

**Goal:** Use all 6 prompts defined in `extraction/prompts.py` (currently only 4 are used).

**Current** (`extraction.py` line 9):
```python
sections = [indexer.extract_section(structure, name)
            for name in ("summary", "methodology", "experiments", "limitations")]
```

**Target:** Extract all 6 sections:
```python
sections = [indexer.extract_section(structure, name)
            for name in ("summary", "methodology", "experiments", "equations", "limitations", "reproduction_notes")]
```

**Then wire new sections into assembler** — map the new section data to PaperCard fields:
- `"equations"` → `algorithmic_view` field (store the equation-heavy content as text)
- `"reproduction_notes"` → `reproduction_notes` field

Update `build_card_snapshot()` accordingly.

## Files to Modify

| File | Action |
|------|--------|
| `packages/paperindex/paperindex/cards/schema.py` | DELETE (old) |
| `packages/paperindex/paperindex/cards/schema_v2.py` | RENAME → `schema.py`, rename `_v2` suffixes |
| `packages/paperindex/paperindex/cards/schema_v2_draft.py` | DELETE if exists |
| `packages/paperindex/paperindex/cards/assembler.py` | Rewrite to produce `PaperCard` dataclass |
| `packages/paperindex/paperindex/cards/extraction.py` | Add 2 sections, update return type |
| `packages/paperindex/paperindex/cards/__init__.py` | Update exports if needed |
| `packages/paperindex/paperindex/indexer.py` | Update return type of `build_card()` |
| `packages/paperindex/paperindex/cli.py` | Update any `card["field"]` → `card.field` access |
| `packages/paperindex/tests/test_cards.py` | Update assertions: `card["title"]` → `card.title`, `card["key_results"]` → `card.key_results` |

## Constraints

- **154 tests must still pass** after migration. Run `python -m pytest packages/ -q --tb=short`.
- Do NOT touch `packages/research_harness/` in this task — the `_get_paper_text()` wiring (reading card fields per `CARD_FIELD_CONSUMERS`) is a separate future task.
- Keep `PaperCard.to_dict()` and `PaperCard.from_dict()` working — downstream code (library store, MCP server) may serialize cards as dicts.
- If `cli.py` prints card as dict (e.g. `json.dumps(card)`), change to `json.dumps(card.to_dict())`.

## Verification

```bash
python -m pytest packages/paperindex/ -q --tb=short
python -c "from paperindex.cards.schema import PaperCard, PAPER_CARD_FIELDS; print(len(PAPER_CARD_FIELDS), 'fields'); c = PaperCard(title='test'); print(c.to_dict()['title'])"
```

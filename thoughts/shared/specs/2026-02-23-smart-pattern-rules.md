# Smart Pattern Rules v1.0 — Specification

## Executive Summary

Redesign dirdigest's `-i` (include) and `-x` (exclude) pattern interpretation to be intuitive through smart anchoring, strict file/folder type discrimination, standard glob semantics, and specificity-based conflict resolution. The CLI flags stay the same; pattern semantics become significantly smarter.

## Problem Statement

The current pattern matching requires users to remember and type verbose glob syntax for common operations. Constructing commands for simple combinations (e.g., "all Python files except tests") is tedious and error-prone. Patterns don't behave intuitively — users must understand fnmatch internals to predict results.

## Success Criteria

- Common pattern tasks expressible in fewer characters than today
- Users can predict behavior without reading docs (after learning 3 rules)
- `--dry-run` flag makes pattern resolution fully transparent
- No silent surprising behavior — errors and warnings guide the user

## User Persona

Developers using dirdigest to create LLM context digests. Technical enough to use CLI tools, familiar with glob patterns from shells and .gitignore. Want fast, predictable results without memorizing custom syntax.

---

## Pattern Interpretation Rules

### Rule 1: Anchoring (Path Specificity)

The presence or absence of `./` prefix determines match scope:

| Prefix | Behavior | Example |
|--------|----------|---------|
| `./` | **Exact** path from project root | `./src/` = only root-level `src/` folder |
| (none) | **Suffix** match — pattern can match at any depth | `src/` = any folder whose path ends in `/src/` |
| `**/` | **Escape hatch** — explicit gitignore-style, bypasses smart anchoring | `**/utils/` = same as `utils/` but explicit |

#### Examples (given tree: `myproject/src/utils/`, `myproject/lib/vendor/src/utils/`)

| Pattern | Matches |
|---------|---------|
| `./src/` | `src/utils/helpers.py`, `src/main.py` (root src/ only) |
| `src/` | All of the above PLUS `lib/vendor/src/utils/legacy.py` |
| `./lib/vendor/src/` | `lib/vendor/src/utils/legacy.py` only |
| `vendor/src/` | `lib/vendor/src/utils/legacy.py` (suffix match) |

#### Multi-segment paths

Path segments are literal and positional: `src/utils/` means a folder named `utils` that is a **direct child** of a folder named `src`. It does NOT recursively search for `utils` inside `src`.

| Pattern | Interpretation |
|---------|----------------|
| `src/utils/` | Folder `utils/` at exactly one level under any `src/` folder |
| `./src/utils/` | Folder `utils/` at exactly `./src/utils/` |

---

### Rule 2: Type Discriminator (Trailing Slash)

Trailing slash determines whether a pattern targets files or folders:

| Suffix | Behavior | Example |
|--------|----------|---------|
| `/` | Matches **folders** only (and their contents recursively) | `tests/` = folder named `tests` + everything inside |
| (none) | Matches **files** only | `config.py` = file named `config.py` |

#### Strict enforcement with helpful errors

If a pattern asks for a file but only a folder exists (or vice versa), dirdigest produces an error with a suggestion:

```
Error: No file 'utils' found. Did you mean 'utils/'?
Error: No folder 'config.py/' found. Did you mean 'config.py'?
```

This applies when the pattern contains no wildcards (literal names only). Wildcard patterns never error on type mismatch — they simply match nothing silently.

---

### Rule 3: Wildcards (Standard Glob Semantics)

Glob patterns follow POSIX/standard semantics:

| Wildcard | Meaning |
|----------|---------|
| `*` | Matches any characters **except** path separator — one directory level only |
| `**` | Matches across directory boundaries — recursive |
| `?` | Matches exactly one character |

#### Examples

| Pattern | Meaning | Matches |
|---------|---------|---------|
| `*.py` | Python files at **root only** | `config.py` |
| `**/*.py` | Python files at **any depth** | All `.py` files in tree |
| `src/*.py` | Direct children of suffix-matched `src/` | `src/main.py` but NOT `src/sub/deep.py` |
| `src/**/*.py` | All Python recursively under suffix-matched `src/` | `src/main.py`, `src/sub/deep.py` |
| `./src/**/*.py` | All Python recursively under root `src/` only | Anchored recursive |
| `test_*.py` | Files starting with `test_` at root only | Root-level test files |
| `**/test_*.py` | Files starting with `test_` at any depth | All test files everywhere |

---

### Rule 4: Multiple Includes = OR (Additive)

Each `-i` pattern adds to the result set:

| Command | Meaning |
|---------|---------|
| `-i '**/*.py' -i '**/*.ts'` | Python OR TypeScript (any depth) |
| `-i 'src/' -i 'tests/'` | Everything in `src/` OR `tests/` |

**Path composition for AND**: To express intersection, compose patterns:
- `-i 'tests/**/*.py'` = Python files **inside** any tests/ folder

---

### Rule 5: Exclusion Symmetry

`-x` patterns follow **identical** interpretation rules as `-i` patterns (anchoring, trailing slash, wildcards).

---

### Rule 6: Targeting Distance + Specificity Precedence

When an `-i` and `-x` pattern both match the same path, the **most targeted** pattern wins.

Resolution uses a two-tier system:

#### Primary Axis: Targeting Distance (per-path, not per-pattern)

For each matching pattern, compute how many directory levels separate the pattern's
match point from the actual item:

| Distance | Meaning | Example |
|----------|---------|---------|
| 0 | Pattern directly names this item | `**/*.py` → `tests/test_main.py` (file pattern targets file) |
| 0 | Folder pattern matches exact folder | `**/utils/` → `dirdigest/utils` |
| 1 | Folder contains the item (1 level) | `tests/` → `tests/test_main.py` |
| 2 | Folder is 2 levels above | `./dirdigest/` → `dirdigest/utils/patterns.py` |
| N | Folder is N levels above | General case |

**Key insight:** File patterns always have distance 0 for files they match, because they
directly target the file. Folder patterns have distance ≥ 1 for files inside them.

#### Secondary Axis: 8-Rank System (breaks ties at same distance)

| Rank | Pattern Type | Example |
|------|-------------|---------|
| 1 | Anchored + exact filename | `./src/test_main.py` |
| 2 | Anchored + folder | `./src/tests/` |
| 3 | Anchored + glob | `./tests/**/*.py` |
| 4 | Path + filename | `tests/test_main.py` |
| 5 | Path + glob | `tests/**/*.py` |
| 6 | Single name (file) | `config.py` |
| 7 | Single name (folder) | `tests/` |
| 8 | Glob only | `**/*.py` |

#### Tertiary: Exclude Wins Ties

When two patterns have equal (distance, rank), `-x` (exclusion) wins.

#### Resolution Order

1. **Closest distance wins** — the pattern that most directly targets the path
2. **Lower rank wins** — at the same distance, more specific pattern type wins
3. **Exclude wins** — at same distance and same rank

#### Examples

```bash
# Broad scope + file cherry-pick
dirdigest -i '**/*.py' -x 'tests/' -i 'tests/test_main.py'
```

Resolution for `tests/test_main.py`:
- `-i '**/*.py'` → distance 0, rank 8 (file pattern directly targets file)
- `-x 'tests/'` → distance 1, rank 7 (folder pattern, file is 1 level inside)
- `-i 'tests/test_main.py'` → distance 0, rank 4 (exact path targets file)

Winner: `-i 'tests/test_main.py'` — distance 0 beats distance 1.
Note: `-i '**/*.py'` also beats `-x 'tests/'` by distance (0 < 1).

Result: **All Python files included everywhere**, plus the exact file cherry-pick.
To exclude Python in tests/: use `-x 'tests/**/*.py'` (file-level exclude, distance 0).

```bash
# Broad scope + narrow exclusion + cherry-pick
dirdigest -i './dirdigest/' -x '**/utils/' -i '**/patterns*'
```

Resolution for `dirdigest/utils/patterns.py`:
- `-i './dirdigest/'` → distance 2 (folder, 2 levels above file)
- `-x '**/utils/'` → distance 1 (folder, 1 level above file)
- `-i '**/patterns*'` → distance 0 (file pattern directly targets file)

Winner: `-i '**/patterns*'` — cherry-pick at distance 0 beats all.

---

### Rule 7: Default Ignore Behavior

Default ignore patterns (`.git`, `node_modules`, `__pycache__`, binary files, etc.) **always apply** unless `--no-default-ignore` is used.

`-i` does NOT override default ignores. However, if an `-i` pattern matches something that would be excluded by default ignores, a **warning** is emitted:

```
Warning: Pattern 'node_modules/' matches a default-ignored path.
         Use --no-default-ignore to include it.
```

---

## New Feature: --dry-run / --explain

A new flag that shows how patterns resolved without producing a digest:

```bash
dirdigest --dry-run -i '**/*.py' -x 'tests/' -i 'tests/test_main.py'
```

Output:

```
Pattern Resolution:
  -i '**/*.py'              [rank 8, glob]
  -x 'tests/'               [rank 7, single folder]
  -i 'tests/test_main.py'   [rank 4, path + filename]

Results:
  INCLUDED  src/main.py              (matched: -i '**/*.py')
  INCLUDED  src/utils/helpers.py     (matched: -i '**/*.py')
  INCLUDED  tests/test_utils.py      (matched: -i '**/*.py', distance 0 beats -x 'tests/' distance 1)
  INCLUDED  tests/test_main.py       (matched: -i 'tests/test_main.py', distance 0)
  EXCLUDED  .git/                    (default ignore)

Summary: 4 included, 1 excluded
```

This flag makes the entire specificity system transparent and debuggable.

---

## Quick Reference

| Goal | Command |
|------|---------|
| All Python files | `-i '**/*.py'` |
| Only root-level Python | `-i '*.py'` |
| Everything in src/ | `-i 'src/'` |
| Everything in root src/ only | `-i './src/'` |
| Python in tests/ | `-i 'tests/**/*.py'` |
| Python + TypeScript | `-i '**/*.py' -i '**/*.ts'` |
| All Python except in tests/ | `-i '**/*.py' -x 'tests/**/*.py'` |
| Exclude tests/ but keep one file | `-i '**/*.py' -x 'tests/**/*.py' -i 'tests/test_main.py'` |
| Any utils/ folder anywhere | `-i 'utils/'` |
| A specific file | `-i './src/main.py'` |
| Broad scope + narrow exclusion | `-i './dirdigest/' -x '**/utils/'` |
| Scope + narrow + cherry-pick | `-i './dirdigest/' -x '**/utils/' -i '**/patterns*'` |
| Multiple scopes with narrowing | `-i './src/' -i './tests/' -x '**/fixtures/' -x '**/__pycache__/'` |

**Note on folder vs file excludes:** `-x 'tests/'` excludes the tests *directory* but
file-level includes (`**/*.py`) still match files inside at distance 0. To exclude
files by type inside a folder, use a file-level exclude: `-x 'tests/**/*.py'`.

---

## Implementation Notes

### Changes Required

1. **`dirdigest/utils/patterns.py`** — Complete rewrite of `matches_pattern()`:
   - Parse anchoring prefix (`./` vs bare vs `**/`)
   - Parse trailing slash (file vs folder)
   - Standard POSIX glob matching (not recursive-by-default)
   - Suffix matching for unanchored patterns

2. **`dirdigest/core.py`** — Add specificity-based conflict resolution:
   - Compute specificity rank for each pattern
   - When file matches both `-i` and `-x`, compare ranks
   - Warning emission for default-ignore conflicts

3. **`dirdigest/cli.py`** — Add `--dry-run` flag:
   - New Click option
   - Pattern resolution display logic
   - Skip digest generation when active

4. **Error handling** — Strict type checking for literal patterns:
   - Check filesystem for type mismatch
   - Emit "Did you mean X?" suggestions
   - Only for non-wildcard patterns

### Backward Compatibility

This is a v0.1.0 tool with few users. The changes are a breaking improvement. Key differences from current behavior:

| Behavior | Current | New |
|----------|---------|-----|
| `*.py` | Matches root-level (fnmatch) | Same (standard glob) |
| `utils/` | Depends on `**/` prefix | Suffix match by default |
| `-i` vs `-x` conflict | `-x` always wins | Most specific wins |
| `./` prefix | Not supported | Anchors to root |
| `--dry-run` | Not available | New feature |
| Default ignore + `-i` conflict | Silent | Warning emitted |

### Risk Mitigations (from Pre-Mortem)

1. **Glob semantics**: Standard POSIX globs chosen over custom recursive-by-default. Familiar to all CLI users.
2. **Type strictness**: Helpful error messages ("Did you mean X?") reduce frustration.
3. **Specificity opacity**: `--dry-run` flag makes resolution fully transparent.
4. **Default ignore conflicts**: Warning message guides users to `--no-default-ignore`.

---

## Out of Scope

- Interactive wizard mode
- Brace expansion (`*.{py,ts}`)
- Regex support
- Inline negation (`!pattern`)
- `--ext` shorthand flag
- Config file profile switching
- Direct-children-only matching (recursive is always fine)

## Open Questions for Implementation

1. Should `--dry-run` be a separate flag or a verbosity level (`-vvv`)?
2. Should the "Did you mean?" error be auto-correctable with `--auto-fix-patterns`?
3. Performance: specificity computation for large directory trees — should we cache pattern ranks?

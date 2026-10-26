# Cross-corpus warm mmap dictionary experiment

Historical pre-release experiment: the opt-in/publication statements below
refer to that run. The subsequent 0.2.5862 release work makes the bounded
accelerator default; see [release notes](../../docs/releases/0.2.5862.md).

## Outcome

The opt-in Zig bbtree dictionary won the median paired comparison on all
three selected local corpora. No sibling repository was modified. No PR,
comment, commit or other publication was created. Production defaults remain
unchanged.

| Corpus | Source files | Dictionary words | Exact median, binary → bbtree | Exact paired improvement | Prefix median, binary → bbtree | Prefix paired improvement |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| codedb | 63 | 12,913 | 118.75 → 86.45 ns | 27.56% | 402 → 340 ns | 15.21% |
| codegraff | 2,119 | 42,100 | 175.89 → 107.90 ns | 36.88% | 467 → 381 ns | 20.17% |
| zigrepper | 1,548 | 36,994 | 155.44 → 101.93 ns | 33.98% | 470 → 391 ns | 14.66% |

Improvement is `1 - median(candidate_round / baseline_round)` over seven
paired rounds; it is not computed from the independent latency medians.
Individual rounds are noisy: codegraff prefix search was slower in two rounds,
although its paired median improved. These numbers are microbenchmark latency,
not CLI/MCP or hosted hybrid end-to-end latency.

| Corpus | Added node payload | Tree construction |
| --- | ---: | ---: |
| codedb | 435,712 bytes | 0.149 ms |
| codegraff | 1,436,672 bytes | 0.427 ms |
| zigrepper | 1,262,592 bytes | 0.361 ms |

Node payload excludes allocator overhead and the original offset directory.
Both binary and candidate paths retain zero-copy mmap postings. Timed queries
run only after parity walks have warmed both mappings and tree nodes.

## Corpus selection and correctness

The codedb control keeps the original tracked `src/*.zig` selection. The other
corpora use tracked source files across supported/common source extensions,
excluding hidden/generated/vendor/build directories, symlinked paths, missing
files, and files over 64 MiB. Ten zigrepper source candidates were skipped by
these safety checks. Sources come from current working trees, not immutable
commit snapshots; codedb and codegraff were dirty, zigrepper was clean. Existing
changes were retained. No untracked sibling source files were included.

This builds fresh temporary `WordIndex` fixtures from the selected sources;
it does not modify or benchmark a running installed daemon or reuse its private
index. All fixture data stays in codedb's `.zig-cache` and is removed after each
successful run. Result files contain aggregate metrics, not source text or
absolute corpus paths. No embeddings, network retrieval, or local models run.

- codedb: **38,739** exact queries and lower bounds checked.
- codegraff: **126,300** exact queries and lower bounds checked.
- zigrepper: **110,982** exact queries and lower bounds checked.
- Every corpus: **1,000 full prefix results**, byte-for-byte identical.
- Every corpus: **all original posting lists** identical after mutation promotes
  the candidate back to the existing mutable heap index.

The actual `WordIndex.search` and `searchPrefix` methods are timed with the
production C allocator. Prefix timing includes result allocation and hit
processing. Seven AB/BA rounds run per corpus, with five full exact-query passes
per round and the same deterministic shuffled query mix as the first experiment.

## Existing PRs inspected

- [codedb #525](https://github.com/justrach/codedb/pull/525), **merged**:
  introduced the zero-copy mmap word index and warm CLI daemon. This is the
  direct architectural predecessor: the experiment optimizes dictionary lookup
  inside that path, preserving postings and promote-on-write behavior.
- [codedb #551](https://github.com/justrach/codedb/pull/551), **merged**:
  loads the word index for CLI search. The new tree could accelerate its word
  lookup once enabled; it does not replace that recall/correctness fix.
- [codedb #607](https://github.com/justrach/codedb/pull/607), **merged**:
  fixes document-ID reuse and persistence attribution. Preserve it; bbtree does
  not change document IDs or substitute for its mutation logic.
- [codedb #750](https://github.com/justrach/codedb/pull/750), **open**:
  semantic fallback and watcher work; touches related tests but not
  `src/index.zig`. It is not a competing dictionary implementation to migrate.
- The current open codedb PR file lists contain no `src/index.zig` change.
- [zigrepper #155](https://github.com/justrach/zigrepper/pull/155), **open**:
  codedbpro lookup routing and compact MCP catalog. It changes dispatch/tool
  overhead, not the native mmap dictionary. The benchmark does not establish
  that its own lookup implementation should be replaced by bbtree.
- Its linked [codegraff #603](https://github.com/justrach/codegraff/pull/603)
  is **closed**; it concerns one-shot routing and the compact catalog, not
  dictionary storage. It is not treated as merged.

No inspected PR proposes migrating an ordered map to bbtree. The evidence
supports further adoption evaluation in native codedb's mmap word dictionary,
not asking these unrelated PRs to switch algorithms.

## Reproduction and next decision

Run from this checkout, with explicit read-only corpus roots:

```sh
ZIG_COMMAND='zigup run 0.17.0-dev.1398+cb5635714' \
  python3 experiments/bbtree/run.py \
  --corpus codedb "$PWD" \
  --corpus codegraff /absolute/path/to/codegraff \
  --corpus zigrepper /absolute/path/to/zigrepper
```

The compatible compiler and native Apple Silicon/macOS environment match the
first experiment. Raw paired rounds are in `*-warm-results.txt`; the runner's
computed medians and corpus metadata are in `cross-corpus-summary.json`.
The old `warm-results.txt` retains the original single-corpus run.

This broadens the dictionary evidence from one to three repositories. Before
making it default, measure end-to-end native retrieval and resident memory/cold
loading: the absolute lookup savings are tens of nanoseconds and the additional
tree uses roughly 0.4–1.4 MiB on these corpora. Ranking, candidate breadth, hosted
fallback, and retrieval accuracy must remain unchanged.

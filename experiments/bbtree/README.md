# Warm mmap word dictionary: bbtree Zig experiment

Historical experiment below. Release 0.2.5862 enables this read path by default
with a single slab and an 8 MiB cap; see
[release notes](../../docs/releases/0.2.5862.md) for RSS and verification results.

## Result

On this repository's tracked `src/*.zig` files (12,913 dictionary words),
the source-aligned bbtree read path improved warm exact lookup and prefix
search. It remains **opt-in**, not the production default: this is one local
corpus and a dictionary microbenchmark, not an end-to-end hybrid retrieval
measurement or a general performance claim.

| Measurement | Binary-search median | bbtree median | Median paired latency change |
| --- | ---: | ---: | ---: |
| Exact `WordIndex.search` | 139.37 ns | 95.37 ns | -30.92% |
| Prefix `WordIndex.searchPrefix` (cap 100) | 430 ns | 370 ns | -14.42% |

The paired percentage is the median of seven per-round candidate/baseline
ratios, not the ratio of the two independent medians. Added node payload:
435,712 bytes (~425.5 KiB), beyond the existing 51,652-byte offset directory.
Allocator overhead is not included. One-time tree construction: 0.188 ms.
Both mappings and the tree are warm before timing; cold paging/startup RSS
are not measured.

## What was ported

Pinned upstream: `XiangpengHao/bbtree` commit
`f0a5d361ecb4df176b3e07d4e33bb399dc3d22bf`.
The upstream license is retained in `LICENSE-upstream` (MIT option).

`src/bbtree_dictionary.zig` specializes the **unsynchronized string read
algorithm**, not a generic B-tree substitute:

- 1 KiB aligned leaves, 512-byte aligned internal pages;
- 8-byte leaf and 4-byte internal big-endian inline windows;
- full-capacity below/equal counts, expressed as Zig vector reductions;
- max-value padding, with live-length cuts;
- fence-derived prefix stripping and a root shared prefix capped at 64 bytes;
- separators held in right-child leaf heads, not copied full keys internally;
- early-exit binary search only within inline-window ties;
- saturated string-length tags and upstream's zero/one/two/many candidate cases;
- tied strings compared in 8-byte big-endian words, skipping proven-equal bytes.

Source correspondence: upstream `tree/search.rs`, `tree/prefix.rs`,
`tree/shared_prefix.rs`, `tree/node/{inline_key_search,inline_keys,leaf,internal,
node_plan,slots,layout}.rs`, and `proof/search_bytes.rs`.

This is a faithful **read-path specialization**, not a complete 1:1 library
translation. Deliberate integration adaptations: keys borrow validated mmap
records; values are dictionary ordinals; bulk construction balances the
already sorted dictionary directly instead of porting upstream's mutable
insertion/streaming builder. Zig generates the target's SIMD instructions
rather than copying Rust intrinsics. Concurrent latches, mutable tree updates,
file storage and the generic Rust API are not part of this experiment.

## Integration and correctness

Call `WordIndex.enableBBDictionary()` on a successfully mmap-loaded index to
opt in. Normal calls remain on the original binary-search path. Exact hits
still return the original zero-copy mmap postings. Prefix lookup changes only
the lower-bound search; forward scanning, strict-prefix exclusion, deduplication,
result caps and ordering are unchanged. First mutation frees the tree before
unmapping and promotes to the existing heap hash index.

No disk-format, ranking, candidate-pool, embedding, hosted-fallback or query
normalization changes. No local embedding model is used.

The benchmark checks all 38,739 exact queries and lower bounds against the
baseline, 1,000 full prefix results byte-for-byte, and every original posting
list after promotion. Queries comprise each real key, a missing extension,
and a half-length prefix, shuffled with a fixed seed. Timing alternates AB/BA
across seven rounds, five exact passes per round, with production `c_allocator`.
Source paths identify documents independently; the corpus is not collapsed
into a single synthetic document. Prefix timing includes allocations and hit
processing, not just tree descent.

Standalone tests cover empty/singleton dictionaries, leaf and multilevel page
boundaries through 55,000 keys, long shared prefixes, prefix keys, inline ties,
and saturated length tags. Debug checks: 453 passed, 2 skipped across
`test-bbtree`, `test-index`, and `test-search`. The CLI ReleaseFast build also
passes.

## Reproduce

```sh
zig build test-bbtree test-index test-search --summary all
python3 experiments/bbtree/run.py
zig build -Doptimize=ReleaseFast --summary all
```

Measured on native Apple Silicon/macOS. The default installed Zig 0.17.0 is
incompatible with this checkout's build API. The pinned
`0.17.0-dev.813+2153f8143` archive returned HTTP 404; these runs used the
installed compatible `0.17.0-dev.1398+cb5635714`, without changing the global
compiler selection or migrating project code. To reproduce with that compiler:

```sh
zigup run 0.17.0-dev.1398+cb5635714 build test-bbtree test-index test-search --summary all
ZIG_COMMAND='zigup run 0.17.0-dev.1398+cb5635714' python3 experiments/bbtree/run.py
zigup run 0.17.0-dev.1398+cb5635714 build -Doptimize=ReleaseFast --summary all
```

Original successful measurements are in `warm-results.txt`. Follow-up
three-repository measurements and existing-PR analysis are in
[cross-corpus-report.md](cross-corpus-report.md), with machine-readable results
in `cross-corpus-summary.json`. End-to-end retrieval and cold-load/RSS
measurements are still needed before enabling by default.

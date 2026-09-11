# macOS watcher CPU: issue #748

Reproduced locally from release commit `4eaca89` (0.2.5854), using
[`repro_watcher_748.py`](../scripts/repro_watcher_748.py). See
[the original report](https://github.com/justrach/codedb/issues/748).

## Reproduction

On macOS, build separate, stable ReleaseFast binaries for the baseline and
candidate. Keep them outside `zig-out`: the unit suite rebuilds that path.

```sh
zig build -Doptimize=ReleaseFast --prefix /absolute/path/to/build
python3 scripts/repro_watcher_748.py \
  --binary /absolute/path/to/build/bin/codedb \
  --out /absolute/path/to/results.json
```

The runner makes a disposable Git repository under `~/tmp` with 1,200 directories
and 4,800 Python files, beyond the default 1,024-vnode budget. It initializes an
explicit-root MCP server, waits for `scan: ready`, then measures two ten-second
windows: quiet, followed by creating/deleting a root-level `.lock` file about
every 20ms. It makes no retrieval calls during either window. CPU is the process
CPU-time delta from macOS `ps`, divided by elapsed wall time; 100% is one core.
It asserts that the reported file count and sequence stay unchanged.

A first non-Git scratch run also showed high CPU, but its sequence changed;
that run is excluded from the comparison. The recorded fixture uses Git and
ignores generated snapshot/archive files so those do not muddy the result.

## Diagnosis and patch

The baseline inserts all watch-overflow paths into the actual dirty set on every
event or timeout. That bypasses exact metadata checks and reads/hashes unchanged
files. A kqueue timeout is only a maximum wait: unrelated directory events can
repeat this work continuously.

The patch keeps the descriptor ceiling and changes reconciliation:

- Overflow verification runs on a monotonic two-second cadence. It still
  reads/hashes overflow files, including same-metadata rewrites on coarse or
  remote filesystems. Those invalidations never enter native-event rearming.
- Event bursts are coalesced over 100ms. This is bounded waiting, so continuous
  churn cannot indefinitely postpone a real change.
- The event pass returns immediately for an empty set. A validated, unchanged
  directory outside event ancestry can preserve its descendants without opening
  them when no inherited ignore rules or symlink aliases require the broader walk.
- Empty cached directories participate in the parent index, allowing the first
  file created inside them to become visible.
- Failed directory-watch admissions are retried separately from file dirtiness.
  Root policy metadata is checked even without OS events, including
  `.git/info/exclude`, which lives outside the watched tree.

This is a conservative CPU fix, not the end of watcher optimization. The regular
directory audit remains approximately every two seconds to preserve discovery
of nested ignore-policy changes and aliases. Overflow still requires periodic content
verification; ignore-bearing trees retain conservative traversal. Event passes still
build a parent index in memory, and root directory events must inspect entries.
Each MCP process still owns a watcher. A shared watcher or persistent directory
index is separate follow-up work; increasing the descriptor cap is not the fix.

## Validation

The new issue-748 regression checks zero filesystem work for an empty event pass,
bounded directory opens under skipped-file churn, no unchanged content rereads
in metadata polling, edits/additions/deletions without OS events, first-file
discovery in an empty directory, and observation of excluded policy changes.
Existing atomic-replacement and sensitive-file tests exercise the event entry
point. The same-metadata rewrite regression from PR #747 covers both file and
parent-directory fallback. The normal suite also covers descriptor bounds and
watch rearming.

Run `zig build test` and the existing MCP end-to-end suite before integration:

```sh
python3 scripts/e2e_mcp_test.py \
  --binary /absolute/path/to/stable/codedb \
  --project /absolute/path/to/codedb
```

Measurements and final validation are recorded below. These are short synthetic
observations on an Apple M4 Pro / macOS 26.6.2, not a general CPU guarantee.


The earlier candidate measured 3.3% quiet / 22.7% churn CPU but omitted periodic
hash verification. That candidate is withdrawn: matching metadata can hide a
rewrite on coarse or remote filesystems. Release measurements below must be
regenerated after restoring the two-second content verification.

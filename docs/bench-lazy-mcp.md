# Experimental lazy MCP startup benchmark

`CODEDB_LAZY_MCP=1` avoids the default project's indexing and watcher startup
until a code request arrives. This experiment measures unused sessions, not
indexing throughput or steady-state CPU after every session has been queried.

Two cold runs per binary, ordered baseline/candidate/candidate/baseline, used
four real Git worktrees with 1,024 Python files in 64 directories each. Each
session has an isolated HOME cache. Two sessions use explicit roots and two use
client roots; explicit-root sessions receive a conflicting client root to verify
precedence. Both builds disable telemetry and auto-update.

After all four handshakes, wait five seconds and sum cumulative process CPU and
RSS from `ps`. Processes are launched sequentially, so this includes startup
and the observation window, not exactly five seconds per process. RSS is summed
resident memory, not unique physical memory. CPU has 0.01-second resolution per
process; a precise percentage reduction near the timer floor is not meaningful.

| Run | Startup CPU, seconds | Combined RSS, MiB | First query, seconds |
| --- | ---: | ---: | ---: |
| Baseline 1 | 0.71 | 183.34 | 0.020–0.025 |
| Candidate 1 | 0.01 | 46.11 | 0.069–0.073 |
| Candidate 2 | 0.01 | 46.13 | 0.070–0.112 |
| Baseline 2 | 0.68 | 182.73 | 0.020–0.025 |

The fixture shows about 75% less combined RSS and little startup CPU before
first use. The first query pays deferred work. These small synthetic projects
do not establish first-query latency for large repositories. Active sessions
still run their normal watchers; this is not worktree index sharing.

Each run adds a file before the first query and requires it to be returned.
Afterward it edits and deletes that file, verifying changes through the same
live MCP process. Baseline fails `--require-lazy` because it eagerly indexes.
Separate lifecycle tests cover metadata-only sessions beyond the old fallback
deadlines, root changes, cwd fallback, missing roots, explicit root precedence,
and stale snapshots. No ranking or retrieval-breadth changes are involved.

Raw samples and binary identification are in [bench-lazy-mcp.json](bench-lazy-mcp.json).
The baseline is the previous safe watcher optimization at `cf86ae8`, so these
results are separate from the [watcher rearming benchmark](bench-watcher-rearm.json).

## Reproduce

Preserve ReleaseFast binaries outside `zig-out`, which unit tests can overwrite
with a Debug build. Run on macOS or a compatible POSIX host with Git and `ps`:

```sh
zig build -Doptimize=ReleaseFast --prefix /tmp/codedb-lazy-candidate
python3 scripts/bench_lazy_mcp.py --binary /tmp/codedb-baseline/bin/codedb
python3 scripts/bench_lazy_mcp.py --binary /tmp/codedb-lazy-candidate/bin/codedb --require-lazy
# Repeat in reverse order. Each invocation creates fresh worktrees and caches.
python3 scripts/e2e_lazy_mcp_test.py --binary /tmp/codedb-lazy-candidate/bin/codedb
```

The timing benchmark is observational: CI should not assert these CPU numbers.
The lifecycle regression runs in the macOS process-test job.

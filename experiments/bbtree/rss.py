#!/usr/bin/env python3
"""Compare frozen native CLI RSS using disposable copies, never original indexes."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('bb_runner', Path(__file__).with_name('run.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--corpus', nargs=2, action='append', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    binaries = {'binary': args.baseline.resolve(), 'bbtree': args.candidate.resolve()}
    results = {}
    cache = ROOT / '.zig-cache/release-verify'
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rss-', dir=cache) as tmp:
        work = Path(tmp)
        config = work / 'empty.codedbrc'
        config.write_text('')
        for name, original in args.corpus:
            source = Path(original).resolve()
            paths, skipped = runner.corpus_paths(source, default=name == 'codedb' and source == ROOT)
            corpus = work / name
            corpus.mkdir()
            for path in paths:
                destination = corpus / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
            subprocess.run(['git', 'init', '-q', str(corpus)], check=True)
            rows = []
            def measure(side):
                home = work / ('home-' + name + '-' + side)
                home.mkdir(exist_ok=True)
                env = {'PATH': os.environ['PATH'], 'HOME': str(home), 'TMPDIR': str(work),
                       'CODEDB_NO_TELEMETRY': '1', 'CODEDB_NO_AUTO_UPDATE': '1',
                       'CODEDB_NO_CLI_DAEMON': '1', 'CODEDB_NO_WARMUP': '1',
                       'CODEDB_ALLOW_TEMP': '1'}
                # Deny network access, even if a future command accidentally
                # starts a semantic provider. No credentials enter this process.
                command = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)',
                           '/usr/bin/time', '-l', str(binaries[side]), str(corpus),
                           'bench-engine', 'word', 'function', '10000',
                           '--config-file=' + str(config)]
                result = subprocess.run(command, env=env, cwd=corpus, text=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
                if result.returncode:
                    raise RuntimeError('Native RSS command failed: ' + result.stderr[-2000:])
                metrics = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
                timing = metrics[-1]
                match = re.search(r'(\d+)\s+maximum resident set size', result.stderr)
                if not match:
                    raise RuntimeError('Missing macOS time peak RSS')
                return {'implementation': side, 'peak_rss_bytes': int(match.group(1)),
                        'hits': timing['hits'], 'p50_ns': timing['p50_ns'], 'p99_ns': timing['p99_ns']}
            # Prepare each HOME/index separately, then only compare warm loads.
            for side in binaries:
                measure(side)
            for pair in range(6):
                order = ['binary', 'bbtree'] if pair % 2 == 0 else ['bbtree', 'binary']
                pair_rows = []
                for side in order:
                    row = measure(side)
                    row['pair'] = pair
                    rows.append(row)
                    pair_rows.append(row)
                if pair_rows[0]['hits'] != pair_rows[1]['hits'] or pair_rows[0]['hits'] == 0:
                    raise RuntimeError('Native CLI word-result parity failed or query has no hits')
            medians = {side: statistics.median(r['peak_rss_bytes'] for r in rows
                                               if r['implementation'] == side) for side in binaries}
            delta = medians['bbtree'] - medians['binary']
            results[name] = {'source_files': len(paths), 'skipped_source_files': skipped,
                             'binary_median_peak_rss_bytes': medians['binary'],
                             'bbtree_median_peak_rss_bytes': medians['bbtree'],
                             'median_peak_rss_delta_bytes': delta,
                             'median_peak_rss_delta_pct': 100 * delta / medians['binary'],
                             'samples': rows}
            print(json.dumps({name: {k: v for k, v in results[name].items() if k != 'samples'}}), flush=True)
    args.out.write_text(json.dumps(results, indent=2) + '\n')
    # Fixed absolute ceiling and relative guard prevent an unnoticed RSS blowup.
    if any(r['median_peak_rss_delta_bytes'] > 10 * 1024 * 1024 or
           r['median_peak_rss_delta_pct'] > 5 for r in results.values()):
        raise SystemExit('RSS regression exceeds 10 MiB absolute or 5% relative guard')


if __name__ == '__main__':
    main()

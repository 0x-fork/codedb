#!/usr/bin/env python3
"""Paired warm mmap benchmarks; external corpora are read-only and explicit."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import statistics
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE_SUFFIXES = {'.zig', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs',
                   '.rs', '.py', '.go', '.c', '.h', '.cc', '.cpp', '.hpp',
                   '.swift', '.rb', '.php', '.java', '.kt', '.cs', '.dart'}
SKIP_DIRS = {'node_modules', 'vendor', 'third_party', 'zig-out', 'zig-cache',
             'target', 'dist', 'build', '__pycache__', 'generated'}


def corpus_paths(directory, default=False):
    command = ['git', '-C', str(directory), 'ls-files', '-z']
    if default:
        command += ['--', 'src']
    paths = []
    skipped = 0
    for raw in subprocess.check_output(command).split(b'\0'):
        if not raw:
            continue
        relative = Path(os.fsdecode(raw))
        if relative.suffix not in ({'.zig'} if default else SOURCE_SUFFIXES):
            continue
        if any(part in SKIP_DIRS or part.startswith('.') for part in relative.parts[:-1]):
            continue
        path = directory / relative
        # Never follow symlinks out of the selected corpus, including parents.
        resolved = path.resolve()
        try:
            resolved.relative_to(directory)
        except ValueError:
            skipped += 1
            continue
        if resolved != path or not path.is_file():
            skipped += 1
            continue
        if path.stat().st_size > 64 * 1024 * 1024:
            skipped += 1
            continue
        paths.append(path)
    if not paths:
        raise ValueError('No eligible tracked source files')
    return paths, skipped


def summarize(text):
    rows = re.findall(r'round=(\d+) implementation=(binary|bbtree) exact_ns=([\d.]+) prefix_ns=([\d.]+)', text)
    if len(rows) != 14:
        raise ValueError('Expected seven complete paired rounds')
    summary = {}
    for column, label in [(2, 'exact'), (3, 'prefix')]:
        medians = {name: statistics.median(float(row[column]) for row in rows
                                         if row[1] == name)
                   for name in ['binary', 'bbtree']}
        ratios = []
        for round_id in sorted(set(row[0] for row in rows)):
            pair = {row[1]: float(row[column]) for row in rows if row[0] == round_id}
            ratios.append(pair['bbtree'] / pair['binary'])
        summary[label] = {'binary_median_ns': medians['binary'],
                          'bbtree_median_ns': medians['bbtree'],
                          'paired_latency_change_pct': (statistics.median(ratios) - 1) * 100}
    fields = dict(re.findall(r'(files|source_bytes|words|queries|prefix_parity|extra_bytes|build_ms)=([\d.]+)', text))
    summary['corpus'] = {key: float(value) if key == 'build_ms' else int(value)
                         for key, value in fields.items()}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', nargs=2, action='append', metavar=('NAME', 'ROOT'))
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'experiments/bbtree')
    args = parser.parse_args()
    os.chdir(ROOT)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    corpora = args.corpus or [('codedb', str(ROOT))]
    zig = shlex.split(os.environ.get('ZIG_COMMAND', 'zig'))
    results = {}
    for name, directory in corpora:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or name in results:
            parser.error('Corpus labels must be unique simple names')
        directory = Path(directory).resolve()
        # Record dirty status only as a boolean, never source paths or git output.
        dirty = bool(subprocess.check_output(['git', '-C', str(directory), 'status', '--porcelain']))
        paths, skipped = corpus_paths(directory, default=name == 'codedb' and directory == ROOT)
        cache = ROOT / '.zig-cache'
        cache.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache) as manifest:
            manifest.write(b'\0'.join(os.fsencode(path) for path in paths) + b'\0')
            manifest.flush()
            command = zig + ['build', 'bench-bbtree', '-Doptimize=ReleaseFast', '--', '--manifest', manifest.name]
            print('Benchmarking {}: {} source files, skipped={}'.format(name, len(paths), skipped), flush=True)
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        sys.stdout.write(result.stdout)
        if result.returncode:
            sys.exit(result.returncode)
        summary = summarize(result.stdout)
        summary.update({'working_tree_dirty': dirty, 'skipped_source_files': skipped})
        results[name] = summary
        # Successful aggregate measurements only: no absolute paths or source text.
        filename = 'warm-results.txt' if not args.corpus else name + '-warm-results.txt'
        (output / filename).write_text(result.stdout)
        for operation in ['exact', 'prefix']:
            row = summary[operation]
            print('{} {}: {:.2f} -> {:.2f} ns; paired latency change {:+.2f}%'.format(
                name, operation, row['binary_median_ns'], row['bbtree_median_ns'], row['paired_latency_change_pct']))
    if args.corpus:
        (output / 'cross-corpus-summary.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()

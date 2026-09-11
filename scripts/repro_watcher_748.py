#!/usr/bin/env python3
"""macOS issue #748: compare ready MCP CPU with quiet and excluded-file churn.
Uses a disposable synthetic repository; makes no retrieval or embedding calls.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from e2e_mcp_test import MCPProcess, do_initialize


def cpu_seconds(pid):
    value = subprocess.check_output(['ps', '-p', str(pid), '-o', 'time='], text=True).strip()
    parts = value.split(':')
    return sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts)))


def status(p):
    response = p.call_tool('codedb_status', {})
    if not response or response.get('error'):
        raise RuntimeError(response)
    return '\n'.join(c.get('text', '') for c in response['result'].get('content', []))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--binary', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--seconds', type=float, default=10)
    ap.add_argument('--directories', type=int, default=1200)
    ap.add_argument('--files-per-dir', type=int, default=4)
    args = ap.parse_args()
    binary = str(Path(args.binary).resolve())
    base = Path.home() / 'tmp'
    base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='codedb-748-corpus-', dir=base) as scratch:
        root = Path(scratch)
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        (root / '.gitignore').write_text('codedb.snapshot\n.zigrep_archive\n.codedb*\n')
        payload = 'def value():\n    return 1\n' + '# unchanged source padding\n' * 600
        for d in range(args.directories):
            directory = root / f'd{d:04d}'
            directory.mkdir()
            for f in range(args.files_per_dir):
                (directory / f'f{f}.py').write_text(payload)
        p = MCPProcess(binary, [], str(root), command=[binary, str(root), 'mcp'])
        try:
            assert do_initialize(p, with_roots=False)
            deadline = time.monotonic() + 120
            while True:
                before = status(p)
                if 'scan: ready' in before.lower():
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError('not ready: ' + before)
                time.sleep(.2)
            time.sleep(3)
            before = status(p)
            phases = []
            for churn in (False, True):
                start_cpu = cpu_seconds(p.proc.pid)
                start = time.monotonic()
                events = 0
                while time.monotonic() - start < args.seconds:
                    if churn:
                        lock = root / 'ignored.lock'
                        lock.write_text('churn')
                        lock.unlink()
                        events += 1
                    time.sleep(.02)
                wall = time.monotonic() - start
                cpu = cpu_seconds(p.proc.pid) - start_cpu
                phases.append(dict(phase='churn' if churn else 'quiet', cpu_seconds=cpu,
                                   wall_seconds=wall, cpu_percent=100 * cpu / wall, churn_pairs=events))
            after = status(p)
            stable = lambda s: re.findall(r'(?:files|seq)\s*[:=]\s*\d+', s.lower())
            result = dict(binary=binary, directories=args.directories, files=args.directories * args.files_per_dir,
                          phases=phases, status_before=before, status_after=after,
                          index_unchanged=bool(stable(before)) and stable(before) == stable(after))
            Path(args.out).write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2))
            assert result['index_unchanged'], 'indexed files/sequence changed during churn'
        finally:
            p.close()

if __name__ == '__main__':
    main()

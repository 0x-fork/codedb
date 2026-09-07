#!/usr/bin/env python3
"""Opt-in MCP startup trial. Owns and cleans up only its fixture processes.

Run once with --require-lazy against a baseline to demonstrate the regression,
then compare baseline/candidate runs. CPU is cumulative process CPU, not %CPU.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from e2e_mcp_test import MCPProcess, do_initialize, reply_roots, tool_text


def usage(p):
    row = subprocess.check_output(['ps', '-p', str(p.proc.pid), '-o', 'time=', '-o', 'rss='], text=True).split()
    parts = row[0].split(':')
    cpu = sum(float(v) * 60 ** i for i, v in enumerate(reversed(parts)))
    return cpu, int(row[1])


def symbol(p, token):
    reply = p.call_tool('codedb_symbol', {'name': token}, timeout=40)
    assert reply and 'result' in reply and not reply['result'].get('isError'), reply
    return tool_text(reply)


def run(args):
    with tempfile.TemporaryDirectory(prefix='codedb-lazy-') as tmp:
        base = Path(tmp)
        repo = base / 'repo'
        repo.mkdir()
        for i in range(args.files):
            path = repo / f'd{i % 64}' / f'f{i}.py'
            path.parent.mkdir(exist_ok=True)
            path.write_text(f'def fixture_{i}():\n    return {i}\n')
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Trial', '-c', 'user.email=trial@example.invalid', 'commit', '-qm', 'fixture'], check=True)
        sessions = []
        try:
            for i in range(args.sessions):
                root = base / f'worktree{i}'
                subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '--detach', '-q', str(root)], check=True)
                home = base / f'home{i}'
                home.mkdir()
                env = dict(os.environ, HOME=str(home), CODEDB_LAZY_MCP='1', CODEDB_NO_AUTO_UPDATE='1', CODEDB_NO_TELEMETRY='1', CODEDB_NO_CLI_DAEMON='1')
                # Alternate explicit root and roots-handshake sessions.
                command = [args.binary, str(root), 'mcp'] if i % 2 == 0 else [args.binary, 'mcp']
                p = MCPProcess(args.binary, [], cwd='/', command=command, env=env)
                sessions.append((p, root))
                assert do_initialize(p, with_roots=True)
                # A conflicting client root must not override explicit root.
                assert reply_roots(p, str(repo if i % 2 == 0 else root))
            time.sleep(args.seconds)
            samples = [usage(p) for p, _ in sessions]
            statuses = [tool_text(p.call_tool('codedb_status', {})) for p, _ in sessions]
            result = dict(binary=args.binary, sessions=args.sessions, files_per_tree=args.files,
                          cpu_seconds=sum(x[0] for x in samples), rss_mib=sum(x[1] for x in samples)/1024,
                          idle=all('scan: idle' in s for s in statuses))
            print(json.dumps(result), flush=True)
            if args.require_lazy:
                assert result['idle'], statuses[0]
            latencies=[]
            for i, (p, root) in enumerate(sessions):
                path=root/'before.py'
                token=f'before_first_query_{i}'
                path.write_text(f'def {token}():\n    return 1\n')
                t=time.monotonic()
                first=symbol(p,token)
                assert token in first, first
                latencies.append(time.monotonic()-t)
                after=f'after_first_query_{i}'
                path.write_text(f'def {after}():\n    return 2\n')
                deadline=time.monotonic()+20
                while after not in symbol(p,after):
                    assert time.monotonic()<deadline, 'watcher missed edit'
                    time.sleep(.25)
                path.unlink()
                deadline=time.monotonic()+20
                while 'before.py' in symbol(p,after):
                    assert time.monotonic()<deadline, 'watcher missed deletion'
                    time.sleep(.25)
            print(json.dumps(dict(first_query_seconds=latencies, freshness='passed')), flush=True)
        finally:
            for p,_ in sessions:
                p.close()


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--binary',required=True)
    ap.add_argument('--sessions',type=int,default=4)
    ap.add_argument('--files',type=int,default=1024)
    ap.add_argument('--seconds',type=float,default=5)
    ap.add_argument('--require-lazy',action='store_true')
    run(ap.parse_args())

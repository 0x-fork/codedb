#!/usr/bin/env python3
"""Correctness cases for opt-in lazy initialization, independent of timings."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import time

from e2e_mcp_test import MCPProcess, do_initialize, reply_roots, tool_text


def query(p, name, args):
    reply = p.call_tool(name, args, timeout=40)
    assert reply and 'result' in reply and not reply['result'].get('isError'), reply
    return tool_text(reply)


def main(binary):
    modes = ['cwd', 'roots_changed', 'no_root', 'metadata', 'cached_snapshot', 'explicit_root']
    for mode in modes:
        with tempfile.TemporaryDirectory(prefix='codedb-lazy-edge-') as tmp:
            base = Path(tmp).resolve()
            first, second = base / 'first', base / 'second'
            for root, token in [(first, 'first_root_token'), (second, 'second_root_token')]:
                root.mkdir()
                (root / 'package.json').write_text('{}')
                (root / 'probe.py').write_text(f'def {token}():\n    return 1\n')
            env = dict(os.environ, HOME=tmp, CODEDB_LAZY_MCP='1',
                       CODEDB_NO_AUTO_UPDATE='1', CODEDB_NO_TELEMETRY='1')
            env.pop('CODEDB_ROOT', None)
            if mode == 'explicit_root':
                env.pop('CODEDB_ALLOW_TEMP', None)  # exercise admitted project capability
            else:
                env['CODEDB_ALLOW_TEMP'] = '1'
            if mode == 'cached_snapshot':
                subprocess.run([binary, str(first), 'index'], env=env, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            cwd = str(first) if mode in ['cwd', 'cached_snapshot'] else '/'
            command = [binary, str(first), 'mcp'] if mode == 'explicit_root' else None
            p = MCPProcess(binary, [], cwd=cwd, env=env, command=command)
            try:
                with_roots = mode in ['roots_changed', 'metadata', 'explicit_root']
                assert do_initialize(p, with_roots=with_roots)
                if with_roots:
                    assert reply_roots(p, str(second if mode == 'explicit_root' else first))
                if mode == 'roots_changed':
                    p.send({'jsonrpc': '2.0', 'method': 'notifications/roots/list_changed'})
                    assert reply_roots(p, str(second))
                p.send({'jsonrpc': '2.0', 'id': 90, 'method': 'tools/list'})
                listing = p.recv()
                assert listing and listing.get('id') == 90 and 'result' in listing, listing
                assert 'scan: idle' in query(p, 'codedb_status', {})
                if mode == 'metadata':
                    query(p, 'codedb_projects', {})
                    invalid = p.call_tool('not_a_tool', {})
                    assert invalid and 'error' in invalid, invalid
                    time.sleep(14)  # beyond both automatic fallback deadlines
                    assert 'scan: idle' in query(p, 'codedb_status', {})
                if mode == 'no_root':
                    reply = p.call_tool('codedb_symbol', {'name': 'anything'})
                    assert reply and 'No indexable root' in reply['error']['message'], reply
                else:
                    root = second if mode == 'roots_changed' else first
                    # Delete/add before the first query, including a stale snapshot.
                    (root / 'probe.py').unlink()
                    (root / 'new.py').write_text('def newly_added_token():\n    return 2\n')
                    assert 'new.py' in query(p, 'codedb_symbol', {'name': 'newly_added_token'})
                    for token in ['first_root_token', 'second_root_token']:
                        assert 'probe.py' not in query(p, 'codedb_symbol', {'name': token})
                print(mode, 'PASS', flush=True)
            finally:
                p.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    main(str(Path(parser.parse_args().binary).resolve()))

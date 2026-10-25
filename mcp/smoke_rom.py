#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Test the compiled emulator on a user-provided ROM using isolated runtime files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from client import Debugger


def wait(client, process, predicate=lambda s: True):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Emulator exited with code '+str(process.returncode))
        try:
            result = client.call('status')
            if predicate(result):
                return result
        except FileNotFoundError:
            pass
        time.sleep(.02)
    raise TimeoutError('Emulator did not reach the requested state')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--binary', type=Path, default=Path(__file__).resolve().parents[1]/'build-wswan/src/mednafen')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='mednafen-mcp-smoke-') as tmp:
        folder = Path(tmp)
        home = folder/'home'; home.mkdir()
        if args.state:
            (home/'mcs').mkdir()
            md5 = hashlib.md5(args.rom.read_bytes()).hexdigest()
            shutil.copy2(args.state,home/'mcs'/(args.rom.stem+'.'+md5+'.mca'))
        env = dict(os.environ, MEDNAFEN_HOME=str(home), MEDNAFEN_MCP_DIR=str(folder/'bridge'), SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
        with (folder/'emulator.log').open('w+') as log:
            command = [str(args.binary),'-video.driver','softfb','-sound','0','-autosave',str(int(bool(args.state))),str(args.rom.resolve())]
            process = subprocess.Popen(command,env=env,stdout=log,stderr=log)
            try:
                client = Debugger(folder/'bridge')
                initial = wait(client,process,lambda s:s['paused'])
                registers = client.call('registers')
                memory = client.call('read_memory 1048560 16')
                disassembly = client.call('disassemble %d 4' % registers['IP'])
                client.call('step 3')
                stepped = wait(client,process,lambda s:s['paused'])
                assert stepped['ticks'] == initial['ticks']+3, (initial,stepped)
                client.call('breakpoint write 0 65535')
                client.call('resume 1000000')
                hit = wait(client,process,lambda s:s['paused'])
                assert hit['reason'] == 'breakpoint' and hit['hit']['kind'] == 'write', hit
                result = {'initial':initial,'registers':registers,'header':memory,'disassembly':disassembly,'step':stepped,'write_breakpoint':hit}
                print(json.dumps(result,indent=2))
            except Exception:
                log.flush();log.seek(0);print(log.read(),file=__import__('sys').stderr)
                raise
            finally:
                process.terminate()
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait()

if __name__ == '__main__': main()

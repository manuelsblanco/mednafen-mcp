#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Client for Mednafen's local debugger bridge. No sockets or extra packages."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import stat
import time
import uuid


class Debugger:
    def __init__(self, directory=None, timeout=5):
        self.directory = Path(directory or os.environ.get('MEDNAFEN_MCP_DIR', '/tmp/mednafen-mcp-' + str(os.getuid())))
        self.timeout = timeout

    def call(self, command):
        st = self.directory.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise RuntimeError('Bridge directory must be owned by you with mode 0700')
        with (self.directory / 'emulator.lock').open('rb') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise RuntimeError('No emulator is connected to this directory')
        name = uuid.uuid4().hex
        tmp = self.directory / (name + '.tmp')
        request = self.directory / (name + '.req')
        response = self.directory / (name + '.res')
        try:
            with tmp.open('x') as stream:
                os.chmod(tmp, 0o600)
                stream.write(command + '\n')
            tmp.rename(request)
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                if response.exists():
                    result = json.loads(response.read_text())
                    if 'error' in result:
                        raise RuntimeError(result['error'])
                    return result['result']
                time.sleep(0.01)
            raise TimeoutError('Emulator did not respond; command outcome is unknown. Inspect status before retrying.')
        finally:
            tmp.unlink(missing_ok=True)
            request.unlink(missing_ok=True)
            response.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory')
    parser.add_argument('command', nargs='+', help='Wire command; all numeric arguments are decimal')
    args = parser.parse_args()
    print(json.dumps(Debugger(args.directory).call(' '.join(args.command)), indent=2))


if __name__ == '__main__':
    main()

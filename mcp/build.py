#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the WonderSwan-only developer executable without installing it globally."""
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
subprocess.run(['autoreconf', '-fi'], cwd=root, check=True)
build = root / 'build-wswan'
build.mkdir(exist_ok=True)
systems = 'apple2 gb gba lynx md nes ngp pce pce-fast pcfx psx sasplay sms snes snes-faust ss ssfplay vb'.split()
subprocess.run([str(root/'configure'), '--enable-debugger', '--disable-alsa', '--disable-jack'] + ['--disable-'+s for s in systems], cwd=build, check=True)
subprocess.run(['make', '-j'+str(min(os.cpu_count() or 2, 4))], cwd=build, check=True)
print('Built:', build/'src/mednafen')

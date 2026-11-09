#!/usr/bin/env python3
"""Copy the managed assemblies the simulation needs into one folder (used by sim/setup.sh).

Versions come from the repo's .bonsai/Bonsai.config (the same file Bonsai's own Setup.cmd restores from). Each assembly
is taken from the local NuGet cache (~/.nuget/packages) at that version, and if the cache does not have that version
(e.g. it has Bonsai.Core 2.9.0 where Bonsai.config says 2.9.1) from the closest cached version, which is reported.
The repo's own UclOpen.* packages are unzipped from local_packages/*.nupkg.

Packages whose native or Windows-only dependencies cannot load on macOS (Bonsai.Dsp, Bonsai.Audio, OpenCV.Net) are NOT
copied: setup.sh builds managed stand-ins with the same assembly names from sim/fakes instead.

Usage: gather_libs.py REPO OUT_DIR [--nuget DIR]
"""
import argparse
import os
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

# Assemblies loaded by the parts of main.bonsai the harness keeps, plus their managed dependencies.
NEEDED = [
    'Bonsai.Core', 'Bonsai.System', 'Bonsai.Scripting.Expressions', 'System.Linq.Dynamic.Core', 'Newtonsoft.Json',
    'System.Reactive.Core', 'System.Reactive.Interfaces', 'System.Reactive.Linq', 'System.Reactive.PlatformServices',
    'Bonsai.Harp', 'Harp.Behavior', 'Harp.StepperDriver', 'Harp.TimestampGeneratorGen3',
    'AllenNeuralDynamics.LicketySplit',
    'Bonsai.Numerics', 'MathNet.Numerics',
    'BonVision',          # only for its embedded Primitives.ParameterRange.bonsai (no GL is used)
    'OpenTK',             # enum types only (Bonsai.Audio's ALSourceState); no OpenAL/GL calls are made
    'LibGit2Sharp',       # referenced by UclOpen.Core (managed part only)
]
# Assemblies faked in sim/fakes (never copied from the cache)
FAKED = {'Bonsai.Dsp', 'Bonsai.Audio', 'OpenCV.Net'}
LOCAL_PACKAGES = ['UclOpen.Core', 'UclOpen.Devices', 'UclOpen.Logging']


def vkey(v):
    """Sort key for NuGet versions like 2.9.0, 0.10.0, 42.42.42-dev0."""
    main, _, pre = v.partition('-')
    nums = [int(x) if x.isdigit() else 0 for x in main.split('.')]
    return nums + [0] * (4 - len(nums)), pre == '', pre


def read_config(repo):
    cfg = Path(repo) / '.bonsai' / 'Bonsai.config'
    root = ET.parse(cfg).getroot()
    packages = {p.get('id'): p.get('version') for p in root.iter('Package')}
    locations = {}
    for loc in root.iter('AssemblyLocation'):
        if loc.get('processorArchitecture') not in ('MSIL', None):
            continue
        locations[loc.get('assemblyName')] = loc.get('location')
    return packages, locations


def find_in_cache(nuget, location, packages):
    """location like Packages/Bonsai.Core.2.9.1/lib/net472/Bonsai.Core.dll -> (path, package id, wanted, used)."""
    parts = location.replace('\\', '/').split('/')
    pkg_dir, tail = parts[1], parts[2:]
    # package folder is '<Id>.<Version>'; match the longest known package id
    pid = max((p for p in packages if pkg_dir.lower().startswith(p.lower() + '.')), key=len, default=None)
    if pid is None:
        return None
    wanted = pkg_dir[len(pid) + 1:]
    base = Path(nuget) / pid.lower()
    if not base.is_dir():
        return None
    versions = sorted((d.name for d in base.iterdir() if d.is_dir()), key=vkey, reverse=True)
    # exact version first, then the closest cached version (highest that is <= wanted, else highest)
    order = [v for v in versions if v == wanted]
    order += [v for v in versions if v != wanted and vkey(v) <= vkey(wanted)]
    order += [v for v in versions if v not in order]
    for v in order:
        cand = base / v / Path(*tail)
        if cand.is_file():
            return cand, pid, wanted, v
        # same file name under another lib/<tfm> folder
        libdir = base / v / 'lib'
        if libdir.is_dir():
            hits = sorted(libdir.glob('net4*/' + tail[-1])) + sorted(libdir.glob('net3*/' + tail[-1]))
            if hits:
                return hits[-1], pid, wanted, v
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('repo')
    ap.add_argument('out')
    ap.add_argument('--nuget', default=os.path.expanduser('~/.nuget/packages'))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    packages, locations = read_config(a.repo)
    missing = []
    print(f"{'assembly':38} {'Bonsai.config':14} {'used':14} source")
    for name in NEEDED:
        assert name not in FAKED
        loc = locations.get(name)
        hit = find_in_cache(a.nuget, loc, packages) if loc else None
        if hit is None:
            missing.append(name)
            print(f"{name:38} {'?':14} {'MISSING':14}")
            continue
        src, pid, wanted, used = hit
        shutil.copy2(src, out / src.name)
        cfg = src.with_name(src.name + '.config')       # e.g. OpenTK.dll.config (dllmaps)
        if cfg.is_file():
            shutil.copy2(cfg, out / cfg.name)
        flag = '' if used == wanted else '  (closest cached version)'
        print(f"{name:38} {wanted:14} {used:14} {src}{flag}")
    for pkg in LOCAL_PACKAGES:
        nupkgs = sorted((Path(a.repo) / 'local_packages').glob(pkg + '.*.nupkg'))
        nupkgs = [p for p in nupkgs if re.match(re.escape(pkg) + r'\.\d', p.name)]
        if not nupkgs:
            missing.append(pkg)
            print(f"{pkg:38} {'?':14} {'MISSING':14}")
            continue
        with zipfile.ZipFile(nupkgs[-1]) as z:
            dlls = [n for n in z.namelist() if n.lower().endswith(pkg.lower() + '.dll') and '/net4' in n]
            if not dlls:
                missing.append(pkg)
                continue
            data = z.read(sorted(dlls)[-1])
            (out / (pkg + '.dll')).write_bytes(data)
        print(f"{pkg:38} {'local':14} {nupkgs[-1].name[len(pkg) + 1:-6]:14} {nupkgs[-1]}")
    if missing:
        print('\nERROR: not found in the NuGet cache: ' + ', '.join(missing), file=sys.stderr)
        print('Restore the packages once on any machine with network access (e.g. Bonsai Setup, or `nuget install`).',
              file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

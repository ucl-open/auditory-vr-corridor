#!/usr/bin/env python3
"""Run the auditory-vr-corridor task workflow headless on this Mac with simulated hardware and a simulated mouse.

  python3 sim/run.py --stage 5 --trials 20            # one command: build if needed, session, harness, run, summary
  python3 sim/run.py --stage 1 --seconds 60 --speed 15
  python3 sim/run.py --repo ../avc --stage 5 --trials 10 --opto   # another checkout; optogenetics with the mock Zapit

Steps: (1) sim/setup.sh if the kit is not built or the repo's src/Extensions/*.cs changed; (2) a run folder (a new temp
folder unless --run-dir) laid out like the repo: session-schemas/current-session/<session>.json from sim/make_session.py
(TEST animal, logs into RUN/Logs), src/waveforms, src/main.bonsai from sim/make_harness.py; (3) the mock Zapit server
(--opto); (4) mono BonsaiRun.exe on the harness until N trials completed (--trials), T seconds (--seconds) or Ctrl+C;
(5) a summary of the logs (sim/summarize.py). The repo's own src/ and session-schemas/ are never written.
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

SIM = Path(__file__).resolve().parent
sys.path.insert(0, str(SIM))
import make_harness   # noqa: E402
import make_session   # noqa: E402
import summarize      # noqa: E402


def log(msg):
    print(f'[sim/run] {msg}', flush=True)


def extensions_hash(repo):
    import hashlib
    h = hashlib.sha1()
    for f in sorted((repo / 'src' / 'Extensions').glob('*.cs')):
        h.update(f.read_bytes())
    return h.hexdigest()


def ensure_built(repo, force=False):
    lib = SIM / 'build' / 'lib'
    stamp = lib / 'Extensions.stamp'
    needed = force or not (SIM / 'build' / 'bin' / 'BonsaiRun.exe').is_file() or not stamp.is_file()
    if not needed:
        values = dict(line.split('=', 1) for line in stamp.read_text().splitlines() if '=' in line)
        newer = any(f.stat().st_mtime > stamp.stat().st_mtime for d in ('simext', 'fakes', 'runner')
                    for f in (SIM / d).rglob('*.cs'))
        same_repo = os.path.realpath(values.get('repo', '')) == os.path.realpath(repo)
        needed = not same_repo or values.get('sha') != extensions_hash(repo) or newer
    if needed:
        log(f'building the simulation kit for {repo} (sim/setup.sh)')
        subprocess.run(['bash', str(SIM / 'setup.sh'), '--repo', str(repo)], check=True)


def free_port_pair():
    # An even base port with both it and the next one free: pairs from runs started at the same time cannot overlap
    for _ in range(50):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1] & ~1
        try:
            with socket.socket() as s1, socket.socket() as s2:
                s1.bind(('127.0.0.1', port))
                s2.bind(('127.0.0.1', port + 1))
            return port
        except OSError:
            continue
    raise SystemExit('no free port pair for the mock Zapit server')


def wait_for_port(port, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


class TrialTail(threading.Thread):
    """Prints each TrialLog row as the workflow writes it."""

    def __init__(self, run_dir):
        super().__init__(daemon=True)
        self.run_dir = run_dir
        self.stop_event = threading.Event()
        self.seen = 0

    def run(self):
        header = None
        while not self.stop_event.wait(0.5):
            session = summarize.latest_session_dir(self.run_dir)
            log_file = summarize.find_log(session, 'TrialLog') if session else None
            if not log_file:
                continue
            lines = log_file.read_text().splitlines()
            if not lines:
                continue
            header = lines[0].split(',')
            for line in lines[1 + self.seen:]:
                values = dict(zip(header, line.split(',')))
                if len(values) < len(header):
                    break
                self.seen += 1
                try:
                    run_s = float(values['OutcomeHarp']) - float(values['TrialStartHarp'])
                except ValueError:
                    run_s = float('nan')
                print(f'[trial {values["Trial"]:>3}] {values["EndReason"]:<14} rewarded={values["WasRewarded"]:<5} '
                      f'punished={values["WasPunished"]:<5} licks={values["LickCount"]:<3} '
                      f'track={float(values["TrackLength"]):.0f} cm  start->outcome {run_s:.2f} s', flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split('\n', 2)[2])
    ap.add_argument('--repo', default=str(SIM.parent), help='checkout to simulate (default: this repo)')
    ap.add_argument('--workflow', help='workflow to simulate (default REPO/src/main.bonsai)')
    ap.add_argument('--run-dir', help='run folder (default: a new temporary folder)')
    ap.add_argument('--stage', type=int, default=5, help='shaping stage (1-6)')
    ap.add_argument('--modality', default='A', choices=['A', 'V', 'AV'])
    ap.add_argument('--animal', default='TEST')
    ap.add_argument('--session-id', default='SIM1')
    stop = ap.add_mutually_exclusive_group()
    stop.add_argument('--trials', type=int, help='stop after N completed trials (default 20)')
    stop.add_argument('--seconds', type=float, help='stop after T seconds')
    ap.add_argument('--max-seconds', type=float, help='safety timeout with --trials (default 60 + 30 s per trial)')
    ap.add_argument('--threads', choices=['serial', 'rig'], default='serial',
                    help='serial (default): Rx timer callbacks and the simulated devices take turns, so lock-order '
                         'races inside the workflow cannot deadlock it; rig: threads run freely as in Bonsai on the '
                         'rig (exposes races such as the TrialDistFloor deadlock, see README)')
    ap.add_argument('--check', action='store_true', help='fail (exit 1) if the summary consistency checks fail')
    ap.add_argument('--rebuild', action='store_true', help='run sim/setup.sh first even if up to date')
    ap.add_argument('--verbose', action='store_true', help='echo the workflow\'s own console output')
    g = ap.add_argument_group('rig (SimRigConfigs)')
    g.add_argument('--valve-ms', type=float, default=80.0)
    g = ap.add_argument_group('optogenetics (branches with Zapit support)')
    g.add_argument('--opto', action='store_true', help='optogenetics session against the mock Zapit server')
    g.add_argument('--zapit-sw', action='store_true', help='software-triggered Zapit (default: hardware TTL on DO3)')
    g.add_argument('--daq', choices=['real', 'simulated'], default='real', help='mock Zapit DAQ behaviour')
    g.add_argument('--zapit-conditions', type=int, default=4)
    g.add_argument('--zapit-config', help='Zapit stimulus config YAML (default: a generated one)')
    g.add_argument('--zapit-port', type=int, help='mock Zapit port (default: a free one; trigger port = port + 1)')
    g.add_argument('--stim-probability', type=float)
    g.add_argument('--warmup-trials', type=int)
    g.add_argument('--stim-duration', type=float)
    g.add_argument('--lead-time', type=float)
    g = ap.add_argument_group('simulated mouse')
    g.add_argument('--speed', type=float, default=25.0, help='running speed, cm/s (default 25)')
    g.add_argument('--speed-jitter', type=float, default=0.15)
    g.add_argument('--licks', type=int, default=4, help='licks per reward-zone bout')
    g.add_argument('--p-wrong', type=float, default=0.1, help='per-trial probability of a wrong-lick bout before the zone')
    g.add_argument('--wrong-licks', type=int, default=8, help='licks in a wrong-lick bout')
    g.add_argument('--p-miss', type=float, default=0.1, help='per-trial probability of not licking in the zone')
    g.add_argument('--p-nolick', type=float, default=0.05, help='per-trial probability of no licks at all')
    g.add_argument('--seed', type=int, default=-1, help='mouse random seed (-1 = random)')
    a = ap.parse_args(argv)
    if a.trials is None and a.seconds is None:
        a.trials = 20

    repo = Path(a.repo).resolve()
    for tool in ('mono', 'csc'):
        if not shutil.which(tool):
            raise SystemExit(f'{tool} not found: install Mono (https://www.mono-project.com/download/stable/)')
    ensure_built(repo, a.rebuild)

    run = Path(a.run_dir).resolve() if a.run_dir else Path(tempfile.mkdtemp(prefix='avc-sim-'))
    src = run / 'src'
    session_json = run / 'session-schemas' / 'current-session' / 'UclOpenAuditoryVrCorridorTaskLogic.json'
    for d in ('Logs', 'sim-logs'):
        (run / d).mkdir(parents=True, exist_ok=True)
    log(f'run folder: {run}')

    session_args = ['--repo', str(repo), '--out', str(session_json), '--logs', str(run / 'Logs'),
                    '--stage', str(a.stage), '--modality', a.modality, '--animal', a.animal,
                    '--session-id', a.session_id, '--waveforms', str(src / 'waveforms')]
    mock = None
    zapit_port = a.zapit_port or 1488
    if a.opto:
        zapit_port = a.zapit_port or free_port_pair()
        session_args += ['--opto', '--zapit-conditions', str(a.zapit_conditions)]
        for name in ('zapit_config', 'stim_probability', 'warmup_trials', 'stim_duration', 'lead_time'):
            value = getattr(a, name)
            if value is not None:
                session_args += ['--' + name.replace('_', '-'), str(value)]
    make_session.main(session_args)

    harness_args = ['--repo', str(repo), '--out', str(src), '--sim-log-dir', str(run / 'sim-logs'),
                    '--trials', str(a.trials or 0), '--valve-ms', str(a.valve_ms), '--zapit-port', str(zapit_port),
                    '--speed', str(a.speed), '--speed-jitter', str(a.speed_jitter), '--licks', str(a.licks),
                    '--p-wrong', str(a.p_wrong), '--wrong-licks', str(a.wrong_licks), '--p-miss', str(a.p_miss),
                    '--p-nolick', str(a.p_nolick), '--seed', str(a.seed)]
    if a.workflow:
        harness_args += ['--workflow', str(Path(a.workflow).resolve())]
    if a.opto:
        harness_args += ['--trigger-port', str(zapit_port + 1)]
        if a.zapit_sw:
            harness_args += ['--zapit-sw']
    make_harness.main(harness_args)

    if a.opto:
        mock_log = open(run / 'mock_zapit.log', 'w')
        mock = subprocess.Popen([sys.executable, '-u', str(SIM / 'mock_zapit_server.py'), '--port', str(zapit_port),
                                 '--daq', a.daq, '--conditions', str(a.zapit_conditions)],
                                stdout=mock_log, stderr=subprocess.STDOUT)
        if not wait_for_port(zapit_port):
            mock.kill()
            raise SystemExit('mock Zapit server did not start')
        log(f'mock Zapit server on 127.0.0.1:{zapit_port} (trigger port {zapit_port + 1}, DAQ {a.daq}), '
            f'log {run / "mock_zapit.log"}')

    timeout = a.seconds if a.seconds else (a.max_seconds or 60 + 30 * a.trials)
    cmd = ['mono', str(SIM / 'build' / 'bin' / 'BonsaiRun.exe'), str(src / 'main.bonsai'),
           '--lib', str(SIM / 'build' / 'lib'), '--timeout', str(timeout)]
    if a.threads == 'serial':
        cmd.append('--serialize')
    env = dict(os.environ, COMPUTERNAME='SIM-' + socket.gethostname().split('.')[0].upper())
    log(('running until %d trials have completed' % a.trials if a.trials else 'running for %g s' % a.seconds)
        + f' (Bonsai console: {run / "bonsai_console.log"})')
    tail = TrialTail(run)
    tail.start()
    started = time.time()
    (run / 'bonsai_console.log').write_text('')
    with open(run / 'bonsai_console.log', 'a') as console:
        proc = subprocess.Popen(cmd, stdout=console if not a.verbose else None, stderr=subprocess.PIPE, text=True,
                                env=env)
        try:
            for line in proc.stderr:
                console.write(line)
                console.flush()
                if line.startswith('[run') or line.startswith('[sim') or a.verbose or 'rror' in line:
                    print(line.rstrip(), flush=True)
            proc.wait()
        except KeyboardInterrupt:
            proc.send_signal(2)
            proc.wait()
    time.sleep(0.6)
    tail.stop_event.set()
    tail.join()
    if mock:
        mock.terminate()
        mock.wait()
    log(f'BonsaiRun exited with code {proc.returncode} after {time.time() - started:.0f} s')
    print()
    failures = summarize.summarize(run, check=a.check, expect_trials=a.trials)
    print(f'\nrun folder: {run}')
    if proc.returncode == 5:
        log('DEADLOCK: two workflow threads blocked each other (see the [run]/[sim] lines above); every thread\'s '
            f'stack is in {run / "bonsai_console.log"} after "Full thread dump". The logs above are complete up to '
            'the deadlock.')
        return 5
    if proc.returncode != 0:
        log(f'FAILED: the workflow did not run cleanly (exit {proc.returncode}); see {run / "bonsai_console.log"}')
        return 2
    if a.check and failures:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

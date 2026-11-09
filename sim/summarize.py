#!/usr/bin/env python3
"""Summarise a simulated session from its logs: trials, outcomes, rewards and per-trial timing, cross-checked against
what the simulated mouse and Behavior board did.

Usage: summarize.py RUN_DIR [--check] [--expect-trials N]
  RUN_DIR is a sim run folder (Logs/, sim-logs/, session-schemas/ inside), as made by sim/run.py.
  --check exits 1 if a consistency check fails (used as a test).
"""
import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


def read_csv(path):
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def fnum(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def latest_session_dir(run):
    sessions = sorted((Path(run) / 'Logs').glob('sub-*/ses-*'), key=lambda p: p.stat().st_mtime)
    return sessions[-1] if sessions else None


def find_log(session, name):
    hits = sorted(session.glob(f'{name}_*/{name}_*.csv'))
    return hits[-1] if hits else None


def load_session_json(run):
    files = list((Path(run) / 'session-schemas' / 'current-session').glob('*.json'))
    return json.loads(files[0].read_text()) if files else {}


def expected_outcome(stage, plan, wrong_licks, limit):
    """What the task should do for a mouse plan (None = no firm expectation)."""
    kind, wrong = plan
    if stage <= 2:
        return {'FreqReached'}
    if stage >= 4 and wrong and wrong_licks >= limit:
        return {'WrongLickLimit'}
    if kind == 'Hit':
        return {'CorrectLick'}
    if kind in ('Miss', 'NoLick'):
        return {'EndOfTrack', 'Timeout'}
    return None


def summarize(run, check=False, expect_trials=None, out=sys.stdout):
    run = Path(run)
    problems = []
    session = latest_session_dir(run)
    if session is None:
        print(f'no session logs under {run / "Logs"}', file=out)
        return ['no session logs']
    params = load_session_json(run).get('taskParameters', {})
    stage = params.get('shapingStage')
    trial_log = find_log(session, 'TrialLog')
    trials = read_csv(trial_log) if trial_log else []
    mouse = read_csv(run / 'sim-logs' / 'SimMouse.csv') if (run / 'sim-logs' / 'SimMouse.csv').is_file() else []
    board = read_csv(run / 'sim-logs' / 'SimBehaviorBoard.csv') if (run / 'sim-logs' / 'SimBehaviorBoard.csv').is_file() else []
    zapit = find_log(session, 'Zapit')

    plans, wrong_bouts, licks = {}, defaultdict(int), []
    for row in mouse:
        t = int(row['Trial'])
        if row['Event'] == 'Plan':
            plans[t] = (row['Detail'].split('+')[0], '+WrongLicks' in row['Detail'])
        elif row['Event'] == 'WrongLickBout':
            wrong_bouts[t] = int(row['Detail'].split()[0])
        elif row['Event'] == 'Lick':
            licks.append(fnum(row['HarpTime']))
    valves = [fnum(r['HarpTime']) for r in board if r['Event'] == 'Valve']
    ttls = [fnum(r['HarpTime']) for r in board if r['Event'] == 'ZapitTTL']

    limit = None
    punishment = params.get('punishment', {})
    if stage is not None:
        limit = punishment.get('stage4PunishedLick') if stage == 4 else punishment.get('stage5PunishedLick') if stage >= 5 else 1000

    print(f'session logs: {session}', file=out)
    print(f'stage {stage}, modality {params.get("modality")}, animal {params.get("logConfig", {}).get("animalId")}, '
          f'{len(trials)} trials in {trial_log.name if trial_log else "(no TrialLog)"}', file=out)
    header = (f'{"trial":>5} {"mouse plan":<16} {"EndReason":<15} {"rew":>3} {"pun":>3} {"licks":>5} {"track":>5} '
              f'{"ITI s":>6} {"cue ms":>6} {"run s":>6} {"end s":>5}')
    print(header, file=out)
    reasons, rewarded, punished = Counter(), 0, 0
    mismatches = []
    for row in trials:
        t = int(row['Trial'])
        iti = fnum(row['TrialStartHarp']) - fnum(row['ITIStartHarp'])
        cue = (fnum(row['CueOnsetHarp']) - fnum(row['TrialStartHarp'])) * 1000
        run_s = fnum(row['OutcomeHarp']) - fnum(row['TrialStartHarp'])
        post = fnum(row['TrialEndHarp']) - fnum(row['OutcomeHarp'])
        was_rewarded = row['WasRewarded'] == 'True'
        was_punished = row['WasPunished'] == 'True'
        reasons[row['EndReason']] += 1
        rewarded += was_rewarded
        punished += was_punished
        plan = plans.get(t)
        plan_text = (plan[0] + ('+wrong' if plan[1] else '')) if plan else '?'
        print(f'{t:>5} {plan_text:<16} {row["EndReason"]:<15} {"yes" if was_rewarded else "-":>3} '
              f'{"yes" if was_punished else "-":>3} {row["LickCount"]:>5} {fnum(row["TrackLength"]):>5.0f} '
              f'{iti:>6.2f} {cue:>6.0f} {run_s:>6.2f} {post:>5.2f}', file=out)
        if plan and stage is not None:
            expected = expected_outcome(stage, plan, wrong_bouts.get(t, 0), limit)
            if expected and row['EndReason'] not in expected:
                mismatches.append(f'trial {t}: mouse plan {plan_text} -> {row["EndReason"]} (expected {"/".join(sorted(expected))})')
        # licks the mouse made during this trial (trial start to trial end) vs the task's LickCount
        start, end = fnum(row['TrialStartHarp']), fnum(row['TrialEndHarp'])
        made = sum(1 for x in licks if start <= x <= end)
        if mouse and abs(made - int(row['LickCount'])) > 1:
            problems.append(f'trial {t}: task counted {row["LickCount"]} licks, the mouse made {made}')
        for col in ('ITIStartHarp', 'TrialStartHarp', 'OutcomeHarp', 'TrialEndHarp'):
            if math.isnan(fnum(row[col])):
                problems.append(f'trial {t}: {col} is NaN')
        if not (fnum(row['ITIStartHarp']) <= fnum(row['TrialStartHarp']) <= fnum(row['OutcomeHarp']) <= fnum(row['TrialEndHarp'])):
            problems.append(f'trial {t}: Harp event times out of order')

    n = len(trials)
    if n:
        print(f'\noutcomes: ' + ', '.join(f'{k} {v}' for k, v in reasons.most_common())
              + f'; rewarded {rewarded}/{n} ({100.0 * rewarded / n:.0f}%), punished {punished}/{n}', file=out)
        durations = [fnum(r['TrialEndHarp']) - fnum(r['ITIStartHarp']) for r in trials]
        print(f'trial cycle (ITI start to trial end): mean {sum(durations) / n:.2f} s, '
              f'min {min(durations):.2f}, max {max(durations):.2f}', file=out)
        truncated = Counter(r['TruncationPoint'] for r in trials if fnum(r.get('TruncationPoint')) < 1)
        if truncated or stage == 6:
            print(f'truncated trials (cue off part way): {sum(truncated.values())}/{n}'
                  + (' at ' + ', '.join(f'{k} x{v}' for k, v in sorted(truncated.items())) if truncated else ''), file=out)
    print(f'simulated board: {len(valves)} valve openings, {len(ttls)} Zapit TTLs; mouse: {len(licks)} licks', file=out)
    if trials:
        # only count valve openings up to the end of the last logged trial (the run may stop mid-trial)
        last_end = fnum(trials[-1]['TrialEndHarp'])
        logged_valves = sum(1 for v in valves if v <= last_end)
        if logged_valves != rewarded:
            problems.append(f'{logged_valves} valve openings during the logged trials but {rewarded} rewarded trials')
    if zapit:
        rows = read_csv(zapit)
        cmds = Counter(r.get('Command') for r in rows)
        print(f'Zapit.csv: {len(rows)} replies ' + ', '.join(f'command {k}: {v}' for k, v in sorted(cmds.items())), file=out)
        # Optogenetics consistency: one StartStimulus then one StopStimulus per trial, what Zapit was sent matches the TrialLog,
        # hardware onsets are the DO3 TTLs, no error replies, and the StimulusLeftOn? safety stop never needed
        order = [r.get('Command') for r in rows if r.get('Command') in ('0', '1')]
        if any(a == b for a, b in zip(order, order[1:])) or (order and order[0] != '1'):
            problems.append('Zapit StartStimulus/StopStimulus do not alternate: ' + ''.join(order))
        if any(str(r.get('IsError', '')).lower() == 'true' for r in rows):
            problems.append('Zapit.csv has error replies')
        starts = [r for r in rows if r.get('Command') == '1']
        for i, t in enumerate(trials):
            if i >= len(starts):
                problems.append(f'trial {i + 1}: no StartStimulus in Zapit.csv')
                break
            laser = str(starts[i].get('LaserOn')).lower() in ('1', 'true')
            if starts[i].get('Value') != t.get('OptogeneticCondition') or laser != (str(t.get('OptogeneticEnabled')).lower() == 'true'):
                problems.append(f'trial {i + 1}: TrialLog condition {t.get("OptogeneticCondition")}/{t.get("OptogeneticEnabled")} '
                                f'but Zapit was sent {starts[i].get("Value")}/laser {starts[i].get("LaserOn")}')
            onset = fnum(t.get('OptoOnsetHarp'))
            # 20 ms: the TTL and the OptoOnsetHarp stamp are written by parallel branches; under Mono the first trial or two
            # can be ~10 ms apart (first-run JIT), later trials ~1 ms
            if ttls and onset == onset and min(abs(x - onset) for x in ttls) > 0.02:
                problems.append(f'trial {i + 1}: OptoOnsetHarp {onset:.3f} is more than 20 ms from any DO3 TTL')
        console = os.path.join(run, 'bonsai_console.log')
        if os.path.exists(console) and 'previous trial ended without a StopStimulus' in open(console, errors='replace').read():
            problems.append('the StimulusLeftOn? safety stop fired: a trial ended without its StopStimulus')
    if mismatches:
        print('\nmouse plan vs outcome mismatches (timing or task-logic differences worth a look):', file=out)
        for m in mismatches:
            print('  ' + m, file=out)
    if expect_trials is not None and n < expect_trials:
        problems.append(f'{n} trials logged, expected at least {expect_trials}')
    if problems:
        print('\nCHECK FAILURES:' if check else '\nproblems:', file=out)
        for p in problems:
            print('  ' + p, file=out)
    elif check:
        print('\nchecks passed: Harp event order, lick counts, valve openings = rewarded trials'
              + (f', >= {expect_trials} trials' if expect_trials else ''), file=out)
    return problems + (mismatches if check else [])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('run_dir')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--expect-trials', type=int)
    a = ap.parse_args(argv)
    failures = summarize(a.run_dir, a.check, a.expect_trials)
    sys.exit(1 if (a.check and failures) else 0)


if __name__ == '__main__':
    main()

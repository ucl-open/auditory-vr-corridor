'''Synthetic TrialLogs, laid out on disk as Bonsai writes them, for testing how gen_session reads past sessions.'''
from pathlib import Path

import pandas as pd


def make_trials(n_trials, stage, modality="A", rewarded=None, licked=None, laser_on=None, condition=None):
    '''
    A TrialLog with the columns gen_session reads. rewarded, licked and laser_on are per-trial lists of bools (default: every trial rewarded and licked).
    laser_on and condition add the optogenetics columns; leave both None for a log from before optogenetics, which has none of them.
    '''
    rewarded = [True] * n_trials if rewarded is None else list(rewarded)
    licked = [True] * n_trials if licked is None else list(licked)
    trials = pd.DataFrame({
        "Modality": [modality] * n_trials,
        "Trial": range(1, n_trials + 1),
        "ShapingStage": [stage] * n_trials,
        "LickCount": [3 if lick else 0 for lick in licked],
        "WasRewarded": rewarded,
    })
    if laser_on is not None or condition is not None:
        trials["OptogeneticEnabled"] = [False] * n_trials if laser_on is None else list(laser_on)
        trials["OptogeneticCondition"] = [0] * n_trials if condition is None else list(condition)
        trials["OptoOnsetHarp"] = float("nan")
        trials["OptoOffsetHarp"] = float("nan")
    return trials


def fraction(n_trials, n_true):
    '''n_trials bools, the first n_true of them True.'''
    return [i < n_true for i in range(n_trials)]


def spread(n_trials, every):
    '''n_trials bools, True on every `every`-th trial, so the True trials are spread through the session rather than bunched at the start.'''
    return [i % every == 0 for i in range(n_trials)]


def write_trial_log(logging_root, animal_id, session_id, date, trials):
    '''Writes a TrialLog where Bonsai puts it: {root}/sub-{animal}/ses-{session}_date-{date}/TrialLog_{session}_{animal}/TrialLog_....csv'''
    log_dir = Path(logging_root) / f"sub-{animal_id}" / f"ses-{session_id}_date-{date}" / f"TrialLog_{session_id}_{animal_id}"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"TrialLog_{session_id}_{animal_id}_{date}.csv"
    trials.to_csv(path, index=False) # Booleans are written as True/False, as Bonsai's CsvWriter does
    return path

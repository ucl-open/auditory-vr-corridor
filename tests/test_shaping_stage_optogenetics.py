'''
determine_shaping_stage with optogenetics: an optogenetics session keeps its stage and reports laser-on and control trials separately, laser-on trials
never count toward a stage decision, and logs from before optogenetics (no optogenetics columns) are decided exactly as before.
'''
import pandas as pd
import pytest

from helpers import determine_shaping_stage, is_optogenetics_session, laser_on_trials
from trial_logs import fraction, make_trials, spread, write_trial_log

ANIMAL = "TC999"
DATES = ["2026-11-01T10-00-00", "2026-11-02T10-00-00", "2026-11-03T10-00-00"] # Oldest first


def run(root, sessions, modality="A"):
    '''Writes the given sessions (oldest first) as A1, A2, ... and returns the stage worked out for the next one.'''
    for number, (trials, date) in enumerate(zip(sessions, DATES), start=1):
        write_trial_log(root, ANIMAL, f"{modality}{number}", date, trials)
    return determine_shaping_stage(animal_id=ANIMAL, session_id=f"{modality}{len(sessions) + 1}", logging_root_paths=[str(root)], modality=modality)


def opto_session(n_trials, stage, warmup=20, laser_on_rewarded=None, control_rewarded=None, **kwargs):
    '''
    An optogenetics session as Bonsai logs it: every trial has a Zapit condition (1-4), the first `warmup` trials are sham, and after them every other
    trial is laser-on. laser_on_rewarded / control_rewarded give how many trials of each kind were rewarded (default all).
    '''
    laser_on = [i >= warmup and (i - warmup) % 2 == 0 for i in range(n_trials)]
    laser_on_left = sum(laser_on) if laser_on_rewarded is None else laser_on_rewarded
    control_left = n_trials - sum(laser_on) if control_rewarded is None else control_rewarded
    rewarded = []
    for on in laser_on: # Reward the first laser_on_rewarded laser-on trials and the first control_rewarded control trials
        if on:
            rewarded.append(laser_on_left > 0)
            laser_on_left -= 1
        else:
            rewarded.append(control_left > 0)
            control_left -= 1
    condition = [i % 4 + 1 for i in range(n_trials)]
    return make_trials(n_trials, stage, rewarded=rewarded, laser_on=laser_on, condition=condition, **kwargs)


# --- Logs from before optogenetics decide exactly as before ---------------------------------------------------------------------------------------------

LEGACY_CASES = {
    # name: (sessions oldest first, expected stage, text the decision prints)
    "stage 3 advances on first 100 trials": ([make_trials(100, 3, rewarded=spread(100, 1))], 4, "Success rate >= 70% in first 100 trials at stage 3"),
    "stage 3 stays below 70%": ([make_trials(100, 3, rewarded=spread(100, 2))], 3, "Success rate less than 70%. Staying in current shaping stage."),
    "stage 1 advances on whole session": ([make_trials(60, 1, rewarded=fraction(60, 50))], 2, "Success rate >= 70%. Advancing to next shaping stage."),
    "stage 4 advances on a short session": ([make_trials(60, 4, rewarded=fraction(60, 50))], 5, "Success rate >= 70% in first 60 trials at stage 4"),
    "stage 5 is not advanced past": ([make_trials(100, 5)], 5, "stage 5 is not advanced past automatically"),
    "under 50 trials keeps stage": ([make_trials(40, 4)], 4, "Less than 50 trials in previous session"),
    "stage 2 advances after two sessions of 50": ([make_trials(60, 2), make_trials(60, 2)], 3, ">= 50 correct trials for 2 consecutive sessions"),
    "stage 2 waits for a second session": ([make_trials(60, 2, rewarded=fraction(60, 40)), make_trials(60, 2)], 2, "(this session: 60, previous: 40)"),
    "stage 2 regresses below 50%": ([make_trials(60, 2, rewarded=fraction(60, 20))], 1, "Success rate < 50%. Regressing"),
}


@pytest.mark.parametrize("sessions, expected, message", LEGACY_CASES.values(), ids=LEGACY_CASES.keys())
def test_legacy_logs(tmp_path, capsys, sessions, expected, message):
    assert "OptogeneticCondition" not in sessions[-1].columns
    assert run(tmp_path, sessions) == expected
    out = capsys.readouterr().out
    assert message in out
    assert "Optogenetics" not in out and "Laser-on" not in out


def test_no_previous_sessions_starts_at_stage_1(tmp_path):
    assert determine_shaping_stage(animal_id=ANIMAL, session_id="A1", logging_root_paths=[str(tmp_path)], modality="A") == 1


@pytest.mark.parametrize("sessions, expected, message", LEGACY_CASES.values(), ids=LEGACY_CASES.keys())
def test_sessions_without_optogenetics_decide_as_legacy_logs(tmp_path, capsys, sessions, expected, message):
    '''Since optogenetics, every TrialLog has the optogenetics columns, set to off when it is not used. Those sessions must decide and print the same.'''
    run(tmp_path / "legacy", sessions)
    legacy_out = capsys.readouterr().out
    with_columns = [make_trials(len(trials), int(trials["ShapingStage"].iloc[0]), rewarded=trials["WasRewarded"], licked=trials["LickCount"] > 0,
                                laser_on=[False] * len(trials), condition=[0] * len(trials)) for trials in sessions]
    assert run(tmp_path / "new", with_columns) == expected
    assert capsys.readouterr().out == legacy_out


# --- An optogenetics session keeps its stage ------------------------------------------------------------------------------------------------------------

def test_optogenetics_session_keeps_stage_and_reports_trials_separately(tmp_path, capsys):
    # 100 trials: 20 warmup + 80 alternating, so 40 laser-on and 60 control trials
    trials = opto_session(100, 5, laser_on_rewarded=12, control_rewarded=54)
    assert run(tmp_path, [trials]) == 5
    out = capsys.readouterr().out
    assert "Laser-on trials: 40, Rewarded trials: 12, Success rate: 30.00%" in out
    assert "Engaged trials: 40, Success rate while engaged: 30.00%" in out
    assert "Control (laser-off) trials: 60, Rewarded trials: 54, Success rate: 90.00%" in out
    assert "Engaged trials: 60, Success rate while engaged: 90.00%" in out
    assert "Optogenetics sessions never change the shaping stage, maintaining same shaping stage (5)" in out
    assert "Next shaping stage" not in out


@pytest.mark.parametrize("stage, rewarded, would_be", [
    (3, None, 4), # All rewarded: a session without optogenetics would advance
    (4, None, 5),
    (2, 0, 1), # None rewarded: a stage 2 session without optogenetics would regress
])
def test_optogenetics_session_never_changes_stage(tmp_path, capsys, stage, rewarded, would_be):
    '''TEST animals can run optogenetics at any stage, where a session without it would advance or regress.'''
    trials = opto_session(120, stage, laser_on_rewarded=rewarded, control_rewarded=rewarded)
    without_optogenetics = make_trials(120, stage, rewarded=trials["WasRewarded"])
    assert run(tmp_path / "without", [without_optogenetics]) == would_be
    assert run(tmp_path / "with", [trials]) == stage


def test_short_optogenetics_session_still_reports_both_kinds(tmp_path, capsys):
    assert run(tmp_path, [opto_session(30, 6, warmup=10)]) == 6
    out = capsys.readouterr().out
    assert "Laser-on trials: 10, Rewarded trials: 10, Success rate: 100.00%" in out
    assert "Control (laser-off) trials: 20, Rewarded trials: 20, Success rate: 100.00%" in out


def test_session_that_never_left_warmup_is_still_an_optogenetics_session(tmp_path, capsys):
    '''Warmup trials are sham trials: they have a condition but no laser. A session that ended in its warmup has no laser-on trials at all.'''
    trials = opto_session(15, 4, warmup=20)
    assert not laser_on_trials(trials).any()
    assert run(tmp_path, [trials]) == 4
    assert "Laser-on trials: 0, Rewarded trials: 0, Success rate: n/a" in capsys.readouterr().out


def test_laser_on_trial_without_a_condition_still_keeps_the_stage(tmp_path):
    '''Bonsai never logs this, but if it did the laser-on trials must still not reach a stage decision.'''
    trials = make_trials(100, 3, laser_on=fraction(100, 50), condition=[0] * 100)
    assert is_optogenetics_session(trials)
    assert run(tmp_path, [trials]) == 3


def test_missing_laser_values_count_as_laser_off(tmp_path, capsys):
    trials = opto_session(100, 5, laser_on_rewarded=0)
    trials["OptogeneticEnabled"] = trials["OptogeneticEnabled"].astype(object)
    trials.loc[0:9, "OptogeneticEnabled"] = None # Written as empty cells, read back as NaN
    path = write_trial_log(tmp_path, ANIMAL, "A1", DATES[0], trials)
    assert pd.read_csv(path)["OptogeneticEnabled"].isna().sum() == 10
    assert determine_shaping_stage(animal_id=ANIMAL, session_id="A2", logging_root_paths=[str(tmp_path)], modality="A") == 5
    assert "Laser-on trials: 40, Rewarded trials: 0" in capsys.readouterr().out


# --- Laser-on trials never count toward a stage decision ------------------------------------------------------------------------------------------------

def test_previous_optogenetics_session_counts_only_its_control_trials_for_stage_2(tmp_path, capsys):
    '''
    Stage 2 advances once the last two sessions each have 50 rewarded trials. The previous session here is an optogenetics one with 60 rewarded laser-on
    trials but only 30 rewarded control trials, so it does not count as a 50-trial session.
    '''
    previous = opto_session(140, 2, warmup=20, laser_on_rewarded=60, control_rewarded=30)
    assert int(previous["WasRewarded"].sum()) == 90
    latest = make_trials(60, 2, laser_on=[False] * 60, condition=[0] * 60) # A session without optogenetics, as Bonsai now logs one
    assert run(tmp_path, [previous, latest]) == 2
    assert "(this session: 60, previous: 30)" in capsys.readouterr().out


def test_previous_optogenetics_session_with_enough_control_trials_lets_stage_2_advance(tmp_path):
    previous = opto_session(140, 2, warmup=20, laser_on_rewarded=0, control_rewarded=55)
    assert run(tmp_path, [previous, make_trials(60, 2)]) == 3


def test_laser_on_trials_read_from_csv(tmp_path):
    trials = opto_session(100, 5)
    path = write_trial_log(tmp_path, ANIMAL, "A1", DATES[0], trials)
    read_back = pd.read_csv(path)
    assert laser_on_trials(read_back).tolist() == trials["OptogeneticEnabled"].tolist()
    assert is_optogenetics_session(read_back)

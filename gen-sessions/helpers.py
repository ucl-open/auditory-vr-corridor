import pandas as pd
from pathlib import Path


def determine_shaping_stage(animal_id: str, session_id: str, logging_root_path: str):
    '''
    Grabs last trial log for a specific animal and calculates shaping stage based on success rate:
    - >70% success: advance to next stage
    - 50-70% success: stay in current stage
    - <50% success: regress to previous stage
    '''
    print(f"Determining shaping stage for animal '{animal_id}' (new session: {session_id})...")

    # Folder structure: {logging_root_path}/sub-{animal_id}/ses-{session_id}_date-{date}/TrialLog_{session_id}_{animal_id}/TrialLog_{session_id}_{animal_id}_{date}.csv
    animal_dir = Path(logging_root_path) / f"sub-{animal_id}"
    if not animal_dir.exists():
        print(f"\nNo log directory found for animal '{animal_id}' at {animal_dir}, defaulting to shaping stage 1.\n")
        return 1

    # Find all session folders for this animal, excluding the current session
    session_dirs = [dir for dir in animal_dir.iterdir() if dir.is_dir() and dir.name.startswith("ses-") and f"ses-{session_id}_" not in dir.name]
    if not session_dirs:
        print(f"\nNo previous session folders found for animal '{animal_id}', defaulting to shaping stage 1.\n")
        return 1

    # Take the most recently created session folder
    latest_session_dir = max(session_dirs, key=lambda d: d.stat().st_ctime)
    print(f"\nMost recent previous session folder: {latest_session_dir.name}")

    # Find the trial log CSV inside it
    trial_logs = list(latest_session_dir.glob("**/TrialLog_*.csv"))
    if not trial_logs:
        print(f"\nNo trial log CSV found in {latest_session_dir}, defaulting to shaping stage 1.\n")
        return 1

    latest_log = max(trial_logs, key=lambda p: p.stat().st_ctime)
    df = pd.read_csv(latest_log)
    print(f"Trial log: {latest_log.name}")

    # If empty log, raise error
    total_trials = len(df)
    if total_trials == 0:
        raise ValueError('No trials found in latest log. Please delete empty TrialLog files then run again.\n')

    # Check stage was consistent throughout previous session
    start_stage = df['ShapingStage'].iloc[0]
    end_stage = df['ShapingStage'].iloc[-1]
    if start_stage != end_stage:
        print(f"\nNB: Shaping stage changed during session (start: {start_stage}, end: {end_stage}). Using last recorded stage.")
    df = df[df['ShapingStage'] == end_stage] # Filter df to trials from last shaping stage only

    # If less than 50 trials, keep to same shaping stage
    if total_trials < 50:
        print(f'\nNB: Less than 50 trials in previous session, maintaining same shaping stage ({end_stage}).\n')
        return end_stage

    # If at least 50 trials, calculate success rate and determine shaping stage for next session
    else:
        rewarded_trials = df['WasRewarded'].sum()
        success_rate = rewarded_trials / total_trials if total_trials > 0 else 0

        print(f"\nTotal trials: {total_trials}, Rewarded trials: {rewarded_trials}, Success rate: {success_rate:.2%}")

        if success_rate >= 0.7:
            print("\nSuccess rate >= 70%. Advancing to next shaping stage.")
            next_stage = min(6, end_stage + 1) # NB: hard coding in 6 shaping stages here - if more stages added in future, update this
        elif success_rate < 0.7 and success_rate >= 0.5:
            print("\nSuccess rate between 50% and 70%. Staying in current shaping stage.")
            next_stage = end_stage 
        else:
            next_stage = max(1, end_stage - 1) 
            print("\nSuccess rate < 50%. Regressing to previous shaping stage.")

        print(f"Next shaping stage: {next_stage}\n")

        return next_stage
import pandas as pd
from pathlib import Path


def determine_shaping_stage():
    '''
    Grabs last trial log and calculates shaping stage based on success rate:
    - >70% success: advance to next stage
    - 50-70% success: stay in current stage
    - <50% success: regress to previous stage
    '''
    # Grab most recent trial log 
    trial_logs_dir = Path('src\Logs\TrialLogs')
    trial_logs = list(trial_logs_dir.glob("*.csv"))
    latest_log = max(trial_logs, key=lambda path: path.stat().st_ctime) # Get creation timestamp of each log and take most recent (NB - only works for Windows...Linux/Mac etc it's last modiied timestamp)
    df = pd.read_csv(latest_log)
    print(f"\nLatest trial log: {latest_log.name}")

    # If empty log, raise error
    total_trials = len(df)
    if total_trials == 0:
        raise ValueError('No trials found in latest log. Please delete empty TrialLog files then run again.\n')

    # Check stage was consistent throughout previous session
    start_stage = df['ShapingStage'].iloc[0]
    end_stage = df['ShapingStage'].iloc[-1]
    if start_stage != end_stage:
        print(f"NB: Shaping stage changed during session (start: {start_stage}, end: {end_stage}). Using last recorded stage.")
    df = df[df['ShapingStage'] == end_stage] # Filter df to trials from last shaping stage only

    # If less than 50 trials, keep to same shaping stage
    if total_trials < 50:
        print(f'NB: Lesss than 50 trials in previous session, maintaining same shaping stage ({end_stage}).\n')
        return end_stage

    # If at least 50 trials, calculate success rate and determine shaping stage for next session
    else:
        rewarded_trials = df['WasRewarded'].sum()
        success_rate = rewarded_trials / total_trials if total_trials > 0 else 0

        print(f"Total trials: {total_trials}, Rewarded trials: {rewarded_trials}, Success rate: {success_rate:.2%}")

        if success_rate >= 0.7:
            print("Success rate >= 70%. Advancing to next shaping stage.")
            next_stage = end_stage + 1
        elif success_rate < 0.7 and success_rate >= 0.5:
            print("Success rate between 50% and 70%. Staying in current shaping stage.")
            next_stage = end_stage 
        else:
            next_stage = max(1, end_stage - 1) 
            print("Success rate < 50%. Regressing to previous shaping stage.")

        print(f"Next shaping stage: {next_stage}\n")

        return next_stage
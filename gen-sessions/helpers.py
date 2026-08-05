import pandas as pd
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt


def collect_session_dirs(
        logging_root_paths: list,
        animal_id: str
    ):
    '''
    Returns every session folder for this animal across all log roots, most recent first.
    Logs are written locally and pushed to the server daily (after which the local copy is deleted), so the server holds the full history.
    The local folder is checked too, to catch a session that has been run but not yet synced.
    Folders are de-duplicated by name, keeping the copy from the first root given.
    Ordering uses the date in the folder name rather than file timestamps, since copying to the server rewrites those.
    '''
    session_dirs = {}
    for logging_root_path in logging_root_paths:
        animal_dir = Path(logging_root_path) / f"sub-{animal_id}"
        if not animal_dir.exists():
            continue
        for dir in animal_dir.iterdir():
            if dir.is_dir() and dir.name.startswith("ses-"):
                session_dirs.setdefault(dir.name, dir)
    return sorted(session_dirs.values(), key=lambda dir: dir.name.split("_date-")[-1], reverse=True)


def session_exists(
        animal_id: str,
        session_id: str,
        logging_root_paths: list
    ):
    '''
    Returns True if a session folder for this session_id already exists for this animal, in any of the log roots.
    '''
    return any(dir.name.startswith(f"ses-{session_id}_") for dir in collect_session_dirs(logging_root_paths, animal_id))


def determine_shaping_stage(
        animal_id: str,
        session_id: str,
        logging_root_paths: list,
        modality: str,
        continue_session: bool = False
    ):
    '''
    Grabs the most recent trial log of the SAME modality for a specific animal and calculates shaping stage based on success rate:
    - >70% success: advance to next stage
    - 10-70% success: stay in current stage
    - <10% success: regress to previous stage
    Sessions of a different modality are ignored, so e.g. a first-ever 'A' session starts at stage 1 even if 'V' is on a later stage.
    Since stage 2 is auto-rewarded, it only advances to stage 3 once the 2 most recent consecutive sessions each have at least 50 trials.
    Stages 3-5 also advance on the first 100 or first 150 trials alone, since mice often stop licking late in a session and drag the full-session average down.
    '''
    print(f"Determining shaping stage for animal '{animal_id}' (new session: {session_id}, modality: {modality})...")

    # Folder structure: {logging_root_path}/sub-{animal_id}/ses-{session_id}_date-{date}/TrialLog_{session_id}_{animal_id}/TrialLog_{session_id}_{animal_id}_{date}.csv
    # Find all session folders for this animal, across every log root. When continuing an existing session, include it; otherwise exclude any folder for this session_id
    session_dirs = collect_session_dirs(logging_root_paths, animal_id) # Already ordered most to least recent
    if not continue_session:
        session_dirs = [dir for dir in session_dirs if not dir.name.startswith(f"ses-{session_id}_")]
    if not session_dirs:
        print(f"\nNo previous session folders found for animal '{animal_id}' in {logging_root_paths}, defaulting to shaping stage 1.\n")
        return 1

    # Search session folders from most to least recent for the two most recent non-empty logs matching this modality.
    # Empty logs (sessions that were opened but ran no trials) and other modalities are skipped, not errored on.
    df = None
    prev_df = None # Second most recent matching session, used for the stage 2 advancement rule below
    for session_dir in session_dirs:
        trial_logs = list(session_dir.glob("**/TrialLog_*.csv"))
        if not trial_logs:
            continue

        latest_log = max(trial_logs, key=lambda p: p.stat().st_ctime)
        try:
            candidate = pd.read_csv(latest_log)
        except pd.errors.EmptyDataError:
            print(f"\nNB: Skipping empty trial log (no trials): {latest_log.name}")
            continue
        if len(candidate) == 0:
            print(f"\nNB: Skipping empty trial log (no trials): {latest_log.name}")
            continue

        if 'Modality' not in candidate.columns or str(candidate['Modality'].iloc[-1]) != modality:
            continue # Different modality (or legacy log with no Modality column), keep looking further back

        if df is None:
            df = candidate
            print(f"\nMost recent previous '{modality}' session with trials: {session_dir.name}")
            print(f"Trial log: {latest_log.name}")
        else:
            prev_df = candidate # Second most recent matching session
            break # Have the two most recent matching sessions - stop searching

    if df is None:
        print(f"\nNo previous '{modality}' session with trials found for animal '{animal_id}', defaulting to shaping stage 1.\n")
        return 1

    total_trials = len(df)

    # Check stage was consistent throughout previous session
    start_stage = df['ShapingStage'].iloc[0]
    end_stage = df['ShapingStage'].iloc[-1]
    if start_stage != end_stage:
        print(f"\nNB: Shaping stage changed during session (start: {start_stage}, end: {end_stage}). Using last recorded stage.")
    df = df[df['ShapingStage'] == end_stage] # Filter df to trials from last shaping stage only

    # If continuing the same session, keep the same shaping stage as the last session
    if continue_session:
        print(f'\nContinuing session, maintaining same shaping stage as last session ({end_stage}).\n')
        return end_stage

    # If less than 50 trials, keep to same shaping stage
    if total_trials < 50:
        print(f'\nNB: Less than 50 trials in previous session, maintaining same shaping stage ({end_stage}).\n')
        return end_stage

    # If at least 50 trials, calculate success rate and determine shaping stage for next session
    else:
        rewarded_trials = df['WasRewarded'].sum()
        success_rate = rewarded_trials / total_trials if total_trials > 0 else 0

        # Report the success rate over the first n trials as well as the whole session, since mice often stop licking late on and drag the full-session average down
        print()
        for n_trials in (50, 100, 150):
            first_n_trials = df.head(n_trials)
            if len(first_n_trials) < n_trials:
                continue # Session did not run this many trials, so skip
            first_n_rewarded_trials = first_n_trials['WasRewarded'].sum()
            print(f"First {n_trials} trials: Rewarded trials: {first_n_rewarded_trials}, Success rate: {first_n_rewarded_trials / n_trials:.2%}")
        print(f"Total trials: {total_trials}, Rewarded trials: {rewarded_trials}, Success rate: {success_rate:.2%}")

        # Stage 2 only advances to stage 3 once the 2 most recent consecutive sessions each have at least 50 correct (rewarded) trials
        if end_stage == 2:
            prev_stage2 = prev_df[prev_df['ShapingStage'] == 2] if prev_df is not None else None
            prev_rewarded_trials = prev_stage2['WasRewarded'].sum() if prev_stage2 is not None else 0

            if rewarded_trials >= 50 and prev_rewarded_trials >= 50:
                next_stage = end_stage + 1
                print("\n>= 50 correct trials for 2 consecutive sessions at stage 2. Advancing to next shaping stage.")
            elif success_rate < 0.5:
                next_stage = max(1, end_stage - 1)
                print("\nSuccess rate < 50%. Regressing to previous shaping stage.")
            else:
                next_stage = end_stage
                print(f"\nStage 2 needs 2 consecutive sessions with >= 50 correct trials to advance (this session: {rewarded_trials}, previous: {prev_rewarded_trials}). Staying in current shaping stage.")

            print(f"Next shaping stage: {next_stage}\n")
            return next_stage

        # Mice often 'zone out' late in a session and run the track without licking, which drags the full-session success rate below 70% even when they do understand the task.
        # So stages 3-5 also advance if either the first 100 or the first 150 trials alone were >= 70% successful. Otherwise they fall through to the normal full-session rules below.
        if end_stage in (3, 4, 5):
            for n_trials in (100, 150):
                early_trials = df.head(n_trials)
                early_success_rate = early_trials['WasRewarded'].sum() / len(early_trials) if len(early_trials) > 0 else 0

                if early_success_rate >= 0.7:
                    next_stage = end_stage + 1
                    print(f"\nSuccess rate >= 70% in first {len(early_trials)} trials at stage {end_stage}. Advancing to next shaping stage.")
                    print(f"Next shaping stage: {next_stage}\n")
                    return next_stage

        if success_rate >= 0.7:
            print("\nSuccess rate >= 70%. Advancing to next shaping stage.")
            next_stage = min(6, end_stage + 1) # NB: hard coding in 6 shaping stages here - if more stages added in future, update this
        elif success_rate < 0.7 and success_rate >= 0.1:
            print("\nSuccess rate between 10% and 70%. Staying in current shaping stage.")
            next_stage = end_stage 
        else:
            next_stage = max(1, end_stage - 1) 
            print("\nSuccess rate < 10%. Regressing to previous shaping stage.")

        print(f"Next shaping stage: {next_stage}\n")

        return next_stage


def generate_waveforms(
        start_freq: int,
        end_freq: int,
        n_freq_bins: int,
        sample_rate: int = 50000,
        duration_ms: int = 50,
        amplitude: float = 0.5,
        out_dir: Path | str = "./src/waveforms",
    ):
    '''
    Generates pure tone waveforms for each frequency bin between start_freq and end_freq, as well as an error tone consisting of band-limited white noise between start_freq and end_freq. 
    Saves waveforms as 16-bit stereo wav files in out_dir, and also saves a text file listing the frequencies of each tone.

    TESTING: also saves a combined matrix .bin of all waveforms and individual .bin for each freq.
    '''
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate logarithmically spaced frequencies between start_freq and end_freq with n_freq_bins total frequencies
    duration = duration_ms / 1000.0
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    envelope = np.sin(np.pi * t / duration)
    frequencies = np.round(np.logspace(np.log10(start_freq), np.log10(end_freq), n_freq_bins)).astype(int)

    all_waveforms = []
    for freq in frequencies:
        tone = np.sin(2 * np.pi * freq * t)
        signal_f32 = (tone * envelope * amplitude).astype(np.float32)
        signal_i16 = np.clip(signal_f32 * 32767, -32768, 32767).astype(np.int16)

        stereo = np.column_stack([signal_i16, signal_i16])
        wavfile.write(out_dir / f"{int(freq)}Hz.wav", sample_rate, stereo)

        # Per-frequency F32 raw binary (mono, no header) for Bonsai MatrixReader - TESTING
        signal_f32.tofile(out_dir / f"{int(freq)}Hz.bin")

        all_waveforms.append(signal_f32)

    # Save combined F32 matrix for Bonsai MatrixReader (one file, random-access by byte offset) - TESTING 
    matrix_f32 = np.stack(all_waveforms)  # shape (n_freq_bins, samples_per_waveform), dtype float32
    assert matrix_f32.dtype == np.float32
    matrix_f32.tofile(out_dir / "all_waveforms.bin")

    with open(out_dir / "frequencies.txt", "w", encoding="utf-8") as f:
        for freq in frequencies:
            f.write(f"{freq}\n")

    # Error tone - band-limited white noise between [start_freq, end_freq]
    low = float(frequencies[0])
    high = float(min(frequencies[-1], sample_rate / 2 - 1))
    sos = butter(4, [low, high], btype="band", fs=float(sample_rate), output="sos")
    noise = np.random.randn(int(sample_rate * 1.0)).astype(np.float64)
    filtered = sosfilt(sos, noise).astype(np.float32)
    filtered /= (np.max(np.abs(filtered)) + 1e-12)
    filtered *= amplitude
    filtered_i16 = np.clip(filtered * 32767, -32768, 32767).astype(np.int16)
    wavfile.write(out_dir / "error_tone.wav", sample_rate, filtered_i16)  # mono

    # Return summary
    return {
        "n_freqs": int(len(frequencies)),
        "sample_rate": int(sample_rate),
        "duration_ms": int(duration_ms),
        "samples_per_waveform": int(matrix_f32.shape[1]),
        "out_dir": str(out_dir),
    }
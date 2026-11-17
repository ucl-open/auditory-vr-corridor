from helpers import MAX_SHAPING_STAGE, determine_shaping_stage, generate_waveforms, next_session_id
from pathlib import Path


from ucl_open_auditory_vr_corridor.task import (
    UclOpenAuditoryVrCorridorTaskLogic,
    UclOpenAuditoryVrCorridorTaskParameters,
    LogConfig
)

TEST_ANIMAL_PREFIX = "TEST" # Animal IDs starting with this are test sessions, e.g. 'TEST' or 'TEST2'


def prompt_shaping_stage(auto_stage: int):
    '''Asks which shaping stage to run, defaulting to the one worked out from previous sessions. Overriding is useful for testing a stage without an animal.'''
    while True:
        answer = input(f"Enter shaping stage (1-{MAX_SHAPING_STAGE}) [default={auto_stage}]: ").strip()
        if not answer:
            return auto_stage
        if answer.isdigit() and 1 <= int(answer) <= MAX_SHAPING_STAGE:
            return int(answer)
        print(f"Shaping stage must be a whole number from 1 to {MAX_SHAPING_STAGE}.")


def main():
    animal_id = input("\nEnter animal ID: ").strip().upper() or "unknown_animal" # Upper-cased so 'tc001' and 'TC001' are the same animal and end up in the same log folder
    modality = (input("Enter modality (A/V/AV) [default=A]: ").strip().upper() or "A")
    project_root = Path(__file__).parent.parent # Absolute path to the repo root, so every path below is absolute and does not depend on where this script is run from
    # Past sessions on the lab server, through the rigs share (K:, mapped on every rig). Two places, because neither holds everything:
    # - Live-Data holds the full history up to its last sync, but not the most recent sessions.
    # - staging\<rig> holds each rig's sessions copied to the server and not yet in Live-Data. Every rig's folder is read, since an animal can be run on any rig.
    live_data_path = r"K:\legacy-sessions\Live-Data\AV_VR_Corridor"
    staging_path = r"K:\staging"

    # Test sessions are written to their own folder, which is not part of the daily push to the server, and their history is read only from there.
    # That keeps test runs out of the real data both ways round: they are never uploaded, and a real animal's sessions never affect a test one.
    is_test_session = animal_id.startswith(TEST_ANIMAL_PREFIX)
    if is_test_session:
        logging_root_path = str(project_root / "TestLogs")
        read_root_paths = [logging_root_path]
        print(f"\nTEST SESSION - logging to {logging_root_path}, nothing here is pushed to the server")
    else:
        logging_root_path = str(project_root / "Logs") # This session is written locally, to a "Logs" folder at project root. Writing live to the server risks stalling acquisition mid-session
        # Past sessions are read from local, Live-Data and every rig's staging folder, and the most recent one across all of them is used: local catches anything not yet copied to the server.
        # A server folder that cannot be reached would otherwise just look like an animal with no history, silently restarting it at session 1 and shaping stage 1.
        unreachable = [path for path in (live_data_path, staging_path) if not Path(path).is_dir()]
        if unreachable:
            raise SystemExit(f"\nCannot reach the lab server folder(s): {', '.join(unreachable)}\n"
                             "Without them this animal's past sessions cannot be read, so the session id and shaping stage would be wrong.\n"
                             "Check K: (the rigs share) is connected, then run this again.\n")
        staging_rig_paths = sorted(str(path) for path in Path(staging_path).iterdir() if path.is_dir())
        read_root_paths = [logging_root_path, live_data_path, *staging_rig_paths]

    # Session id is set automatically by incrementing the most recent session of this modality for this animal, e.g. 'A7' if the last 'A' session was 'A6'
    session_id = next_session_id(animal_id=animal_id, modality=modality, logging_root_paths=read_root_paths)
    print(f"\nSession ID: {session_id}")

    # Shaping stage is worked out from previous session logs of the same modality for this animal, then offered as the default so it can be overridden
    auto_stage = determine_shaping_stage(animal_id=animal_id, session_id=session_id, logging_root_paths=read_root_paths, modality=modality)
    shaping_stage = prompt_shaping_stage(auto_stage)
    if shaping_stage != auto_stage:
        print(f"\n***!!! OVERRIDING shaping stage {auto_stage} with {shaping_stage} !!!***\n")

    task_logic = UclOpenAuditoryVrCorridorTaskLogic(
        task_parameters=UclOpenAuditoryVrCorridorTaskParameters(
            log_config=LogConfig(
                session_id=session_id,
                animal_id=animal_id,
                logging_root_path=logging_root_path
            ),
            shaping_stage=shaping_stage,
            modality=modality,
        ),
    )

    # Save generated task logic to json that will be read by Bonsai at the start of the session
    filename = task_logic.__class__.__name__
    bonsai_path = project_root / "session-schemas" / "current-session" / f"{filename}.json"
    bonsai_path.parent.mkdir(parents=True, exist_ok=True)
    with open(bonsai_path, "w", encoding="utf-8") as f:
        f.write(task_logic.model_dump_json(indent=2, by_alias=True))
    
    # Generate waveforms for the session based on task parameters
    params = task_logic.task_parameters
    
    log = generate_waveforms(
        start_freq=params.start_freq,
        end_freq=params.end_freq,
        n_freq_bins=params.n_freq_bins,
        amplitude=params.amplitude,
        out_dir=project_root / "src" / "waveforms"
    )

    print(log, '\n')


if __name__ == "__main__":
    main()
from helpers import determine_shaping_stage, generate_waveforms, next_session_id
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
        answer = input(f"Enter shaping stage (1-6) [default={auto_stage}]: ").strip()
        if not answer:
            return auto_stage
        if answer.isdigit() and 1 <= int(answer) <= 6:
            return int(answer)
        print("Shaping stage must be a whole number from 1 to 6.")


def main():
    animal_id = input("\nEnter animal ID: ").strip().upper() or "unknown_animal" # Upper-cased so 'tc001' and 'TC001' are the same animal and end up in the same log folder
    modality = (input("Enter modality (A/V/AV) [default=A]: ").strip().upper() or "A")
    project_root = Path(__file__).parent.parent # Absolute path to the repo root, so every path below is absolute and does not depend on where this script is run from
    server_root_path = r"\\rdp.arc.ucl.ac.uk\ritd-ag-project-rd01n9-pcoen00\AV_VR_Corridor" # Local logs are pushed here daily, so the server holds the full history for each animal

    # Test sessions are written to their own folder, which is not part of the daily push to the server, and their history is read only from there.
    # That keeps test runs out of the real data both ways round: they are never uploaded, and a real animal's sessions never affect a test one.
    is_test_session = animal_id.startswith(TEST_ANIMAL_PREFIX)
    if is_test_session:
        logging_root_path = str(project_root / "TestLogs")
        read_root_paths = [logging_root_path]
        print(f"\nTEST SESSION - logging to {logging_root_path}, nothing here is pushed to the server")
    else:
        logging_root_path = str(project_root / "Logs") # This session is written locally, to a "Logs" folder at project root. Writing live to the server risks stalling acquisition mid-session
        read_root_paths = [logging_root_path, server_root_path] # Past sessions are read from both: the server has everything up to the last sync, and local catches anything not yet synced

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
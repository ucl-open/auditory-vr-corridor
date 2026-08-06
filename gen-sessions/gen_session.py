from helpers import determine_shaping_stage, generate_waveforms, next_session_id
from pathlib import Path


from ucl_open_auditory_vr_corridor.task import (
    UclOpenAuditoryVrCorridorTaskLogic,
    UclOpenAuditoryVrCorridorTaskParameters,
    LogConfig
)

def main():
    animal_id = input("\nEnter animal ID: ").strip() or "unknown_animal"
    modality = (input("Enter modality (A/V/AV) [default=A]: ").strip().upper() or "A")
    project_root = Path(__file__).parent.parent # Absolute path to the repo root, so every path below is absolute and does not depend on where this script is run from
    logging_root_path = str(project_root / "Logs") # This session is written locally, to a "Logs" folder at project root. Writing live to the server risks stalling acquisition mid-session
    server_root_path = r"\\rdp.arc.ucl.ac.uk\ritd-ag-project-rd01n9-pcoen00\AV_VR_Corridor" # Local logs are pushed here daily, so the server holds the full history for each animal
    read_root_paths = [logging_root_path, server_root_path] # Past sessions are read from both: the server has everything up to the last sync, and local catches anything not yet synced

    # Session id is set automatically by incrementing the most recent session of this modality for this animal, e.g. 'A7' if the last 'A' session was 'A6'
    session_id = next_session_id(animal_id=animal_id, modality=modality, logging_root_paths=read_root_paths)
    print(f"\nSession ID: {session_id}")

    task_logic = UclOpenAuditoryVrCorridorTaskLogic(
        task_parameters=UclOpenAuditoryVrCorridorTaskParameters(
            log_config=LogConfig(
                session_id=session_id,
                animal_id=animal_id,
                logging_root_path=logging_root_path
            ),
            shaping_stage=determine_shaping_stage(animal_id=animal_id, session_id=session_id, logging_root_paths=read_root_paths, modality=modality), # Determine shaping stage based on previous session logs of the same modality for this animal
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
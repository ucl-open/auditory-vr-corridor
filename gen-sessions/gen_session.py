import os
from datetime import datetime
from helpers import determine_shaping_stage, generate_waveforms
from pathlib import Path


from ucl_open_auditory_vr_corridor.task import (
    UclOpenAuditoryVrCorridorTaskLogic,
    UclOpenAuditoryVrCorridorTaskParameters,
    LogConfig
)

def main():
    animal_id = input("\nEnter animal ID: ").strip() or "unknown_animal"
    session_id = input("Enter session ID: ").strip()
    logging_root_path = str(Path(__file__).parent.parent / "Logs") # Logs will be saved in a "Logs" folder at project root

    task_logic = UclOpenAuditoryVrCorridorTaskLogic(
        task_parameters=UclOpenAuditoryVrCorridorTaskParameters(
            log_config=LogConfig(
                session_id=session_id,
                animal_id=animal_id,
                logging_root_path=logging_root_path
            ),
            shaping_stage=determine_shaping_stage(animal_id=animal_id, session_id=session_id, logging_root_path=logging_root_path), # Determine shaping stage based on previous session logs for this animal
        ),
    )

    # Save generated task logic to json that will be read by Bonsai at the start of the session
    filename = task_logic.__class__.__name__
    bonsai_path = f"./session-schemas/current-session/{filename}.json"
    os.makedirs(os.path.dirname(bonsai_path), exist_ok=True)
    with open(bonsai_path, "w", encoding="utf-8") as f:
        f.write(task_logic.model_dump_json(indent=2, by_alias=True))
    
    # Generate waveforms for the session based on task parameters
    params = task_logic.task_parameters
    
    log = generate_waveforms(
        start_freq=params.start_freq,
        end_freq=params.end_freq,
        n_freq_bins=params.n_freq_bins,
        amplitude=params.amplitude,
        out_dir=Path("./src/waveforms"),
    )

    print(log, '\n')


if __name__ == "__main__":
    main()
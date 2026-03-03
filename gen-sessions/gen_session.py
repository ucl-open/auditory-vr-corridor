import os
from datetime import datetime
from helpers import determine_shaping_stage


from ucl_open_auditory_vr_corridor.task import (
    UclOpenAuditoryVrCorridorTaskLogic,
    UclOpenAuditoryVrCorridorTaskParameters,
)

task_logic = UclOpenAuditoryVrCorridorTaskLogic(
    task_parameters=UclOpenAuditoryVrCorridorTaskParameters(
        shaping_stage=determine_shaping_stage(), 
    ),
)

def main():
    # Save generated task logic to json that will be read by Bonsai at the start of the session
    filename = task_logic.__class__.__name__
    bonsai_path = f"./session-schemas/current-session/{filename}.json"
    os.makedirs(os.path.dirname(bonsai_path), exist_ok=True)
    with open(bonsai_path, "w", encoding="utf-8") as f:
        f.write(task_logic.model_dump_json(indent=2, by_alias=True))
    
    # Also save a copy of the generated task logic with a timestamp in a separate folder for records
    timestamp = datetime.now().strftime("%Y-%m-%dT%H_%M_%S")
    log_path = f'./session-schemas/prev-sessions/{filename}_{timestamp}.json'
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(task_logic.model_dump_json(indent=2, by_alias=True))

if __name__ == "__main__":
    main()
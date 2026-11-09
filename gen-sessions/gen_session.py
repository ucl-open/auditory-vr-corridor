from helpers import MAX_SHAPING_STAGE, determine_shaping_stage, generate_waveforms, next_session_id
from pathlib import Path
import json
import re


from ucl_open_auditory_vr_corridor.task import (
    UclOpenAuditoryVrCorridorTaskLogic,
    UclOpenAuditoryVrCorridorTaskParameters,
    LogConfig,
    OptogeneticsConfig
)

TEST_ANIMAL_PREFIX = "TEST" # Animal IDs starting with this are test sessions, e.g. 'TEST' or 'TEST2'

# Optogenetics is a switch for a single session, not a shaping stage, and it is only offered once an animal knows the task, so stimulation is measured
# against settled behaviour. TEST animals are offered it at every stage, so the rig can be tested without a trained animal.
OPTOGENETICS_STAGES = (5, 6)

# Top-level stimLocationsNN keys of a Zapit stimulus config. Zapit checks its configs with this same pattern, and Bonsai's ZapitStimConfig.cs reads
# the conditions with it, so gen_session, Bonsai and Zapit all agree on what a file holds.
ZAPIT_CONDITION_KEY = re.compile(r"^stimLocations(\d+)\s*:", flags=re.MULTILINE)


def prompt_shaping_stage(auto_stage: int):
    '''Asks which shaping stage to run, defaulting to the one worked out from previous sessions. Overriding is useful for testing a stage without an animal.'''
    while True:
        answer = input(f"Enter shaping stage (1-{MAX_SHAPING_STAGE}) [default={auto_stage}]: ").strip()
        if not answer:
            return auto_stage
        if answer.isdigit() and 1 <= int(answer) <= MAX_SHAPING_STAGE:
            return int(answer)
        print(f"Shaping stage must be a whole number from 1 to {MAX_SHAPING_STAGE}.")


ZAPIT_TOP_LEVEL_KEY = re.compile(r"^([A-Za-z_]\w*)\s*:", flags=re.MULTILINE)
ZAPIT_RAMP_DOWN = re.compile(r"offRampDownDuration_ms\s*:\s*([0-9.eE+-]+)")
ZAPIT_MODULATION_FREQUENCY = re.compile(r"stimModulationFreqHz\s*:\s*([0-9.eE+-]+)")


def zapit_ramp_down_problems(text: str):
    '''
    Conditions whose offRampDownDuration_ms is not longer than one stimulus cycle (1000 / stimModulationFreqHz ms). Zapit's stopOptoStim ramps the laser
    down in whole cycles, and a ramp of one cycle or less takes a shortcut that writes zeros without stopping the DAQ task. On a hardware-triggered rig the
    next trial's stimulus would then start as soon as it is sent instead of at the TTL. Bonsai's CheckZapitConditionCount applies the same rule at startup.
    '''
    keys = list(ZAPIT_TOP_LEVEL_KEY.finditer(text))
    blocks = {key.group(1): text[key.start():(following.start() if following else len(text))] for key, following in zip(keys, keys[1:] + [None])}
    frequency = ZAPIT_MODULATION_FREQUENCY.search(blocks.get("stimModulationFreqHz", "")) or ZAPIT_MODULATION_FREQUENCY.search(blocks.get("stimLocations01", ""))
    if frequency is None:
        return [] # Zapit itself refuses a config without a modulation frequency
    cycle_ms = 1000.0 / float(frequency.group(1))
    problems = []
    for name, block in blocks.items():
        if not ZAPIT_CONDITION_KEY.match(name + ":"):
            continue
        ramp = ZAPIT_RAMP_DOWN.search(block)
        if ramp is None:
            problems.append(f"{name} has no offRampDownDuration_ms")
        elif float(ramp.group(1)) <= cycle_ms:
            problems.append(f"{name} ramps down over {float(ramp.group(1)):g} ms, which is not longer than one {float(frequency.group(1)):g} Hz cycle ({cycle_ms:g} ms)")
    return problems


def count_zapit_conditions(config_path: str):
    '''
    Number of stimulation conditions in a Zapit stimulus config: its top-level stimLocations01, stimLocations02, ... entries, which Bonsai reads too.
    Raises ValueError unless they are numbered exactly 1 to N. Zapit reads stimLocations01, 02, ... in order and stops at the first gap, and a repeated
    key keeps only one of its entries, while Bonsai sends conditions by number - so with a gap or a repeat they would not mean the same sites.
    '''
    text = Path(config_path).read_text(encoding="utf-8-sig") # utf-8-sig drops a byte order mark, which would hide a stimLocations key on the first line
    numbers = sorted(int(number) for number in ZAPIT_CONDITION_KEY.findall(text))
    if not numbers:
        raise ValueError(f"No stimLocations entries in '{config_path}' - is this a Zapit stimulus config?")
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(f"The stimLocations entries in '{config_path}' must be numbered 1 to {len(numbers)}, with no gaps or repeats, but are {numbers}")
    problems = zapit_ramp_down_problems(text)
    if problems:
        raise ValueError(f"'{config_path}': " + "; ".join(problems) + ". Zapit would then leave its DAQ running after each stop, so a hardware-triggered "
                         "trial would start before its TTL. Use a ramp-down longer than one cycle (250 ms is Zapit's usual)")
    return len(numbers)


def previous_zapit_config_path(bonsai_path: Path):
    '''Zapit stimulus config used by the last session generated on this PC, offered as the default so it does not have to be typed every session.'''
    try:
        config_path = json.loads(bonsai_path.read_text(encoding="utf-8"))["taskParameters"]["optogenetics"]["zapitConfigPath"]
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    return config_path if isinstance(config_path, str) else ""


def prompt_optogenetics(shaping_stage: int, is_test_session: bool, previous_config_path: str):
    '''
    Asks whether this session stimulates with Zapit and, if so, which stimulus config. Only asked at OPTOGENETICS_STAGES, or at any stage for TEST animals;
    otherwise optogenetics is off. The config is checked here, so a session never starts with a missing file or one whose conditions Zapit would number differently.
    '''
    if shaping_stage not in OPTOGENETICS_STAGES and not is_test_session:
        return OptogeneticsConfig()
    if input("Optogenetics (Zapit)? (y/N): ").strip().lower() not in ("y", "yes"):
        return OptogeneticsConfig()
    while True:
        default = f" [default={previous_config_path}]" if previous_config_path else ""
        config_path = input(f"Zapit stimulus config file{default}, or n for no optogenetics: ").strip().strip('"') or previous_config_path # Quotes stripped, as Windows' 'Copy as path' adds them
        if config_path.lower() in ("n", "no"): # A way back after answering y by mistake
            print("Optogenetics off for this session")
            return OptogeneticsConfig()
        if not config_path or not Path(config_path).is_file():
            print(f"File not found: '{config_path}'")
            continue
        try:
            n_conditions = count_zapit_conditions(config_path)
        except (OSError, ValueError) as error: # Unreadable or not a Zapit config: ask again rather than end gen_session
            print(error)
            continue
        optogenetics = OptogeneticsConfig(enabled=True, zapit_config_path=str(Path(config_path).resolve()))
        print(f"\n***!!! OPTOGENETICS ON: {n_conditions} Zapit conditions. After {optogenetics.warmup_trials} sham warmup trials, {optogenetics.stim_probability:.0%} of trials "
              f"are laser-on ({optogenetics.stim_probability / n_conditions:.1%} per condition, so a laser-on control site counts as one condition) and the rest sham (laser off). The stimulus starts {optogenetics.lead_time * 1000:.0f} ms before the cue and stops at the outcome "
              f"(at most {optogenetics.stim_duration:g} s). This session will not change the shaping stage. Load the same file in Zapit before starting Bonsai. "
              f"Real (non-TEST) animals need a hardware-triggered rig (RigConfigs ZapitHardwareTriggered = true), or Bonsai will refuse to start !!!***\n")
        return optogenetics


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

    # Session JSON that Bonsai reads at startup. It still holds the last session's settings at this point, which supplies the default Zapit config
    bonsai_path = project_root / "session-schemas" / "current-session" / f"{UclOpenAuditoryVrCorridorTaskLogic.__name__}.json"
    optogenetics = prompt_optogenetics(shaping_stage=shaping_stage, is_test_session=is_test_session, previous_config_path=previous_zapit_config_path(bonsai_path))

    task_logic = UclOpenAuditoryVrCorridorTaskLogic(
        task_parameters=UclOpenAuditoryVrCorridorTaskParameters(
            log_config=LogConfig(
                session_id=session_id,
                animal_id=animal_id,
                logging_root_path=logging_root_path
            ),
            shaping_stage=shaping_stage,
            modality=modality,
            optogenetics=optogenetics,
        ),
    )

    # Save generated task logic to json that will be read by Bonsai at the start of the session
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
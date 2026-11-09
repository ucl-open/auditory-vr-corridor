'''
gen_session.py's optogenetics prompt: reading the conditions from a Zapit stimulus config, the default config from the last session JSON, when the
question is asked at all, and the session JSON main() writes. input() is scripted, so no test waits on a real prompt.
'''
import json
from pathlib import Path

import pytest

import gen_session
from gen_session import count_zapit_conditions, previous_zapit_config_path, prompt_optogenetics
from ucl_open_auditory_vr_corridor.task import OptogeneticsConfig, UclOpenAuditoryVrCorridorTaskLogic

# Compared through model_dump(): swc.aeon's BaseSchema keeps a private link to the model containing it, which == would compare too
OFF = OptogeneticsConfig().model_dump()


def stim_block(number, ml=-2.0, indent=""):
    '''One condition of a Zapit stimulus config, as Zapit writes them.'''
    return (f"{indent}stimLocations{number}:\n"
            f"{indent}  ML: {ml}\n"
            f"{indent}  AP: -1.0\n"
            f"{indent}  Class: stimulate\n"
            f"{indent}  Type: unilateral_point\n"
            f"{indent}  Attributes: {{laserPowerInMW: 5.0, offRampDownDuration_ms: 250.0}}\n")


def write_config(path, keys, extra="", newline="\n", encoding="utf-8"):
    text = "".join(stim_block(key) for key in keys) + extra + "stimModulationFreqHz: 40.0\n"
    Path(path).write_text(text.replace("\n", newline), encoding=encoding, newline="")
    return str(path)


# --- ramp-down rule (Zapit's stop shortcut leaves its DAQ running when a ramp-down is not longer than one stimulus cycle) ------------------------------

def config_with_ramps(path, ramps_ms, frequency_hz=40.0, flow_style=True, frequency_in_condition=False):
    text = ""
    for number, ramp in enumerate(ramps_ms, start=1):
        attributes = f"laserPowerInMW: 5.0, offRampDownDuration_ms: {ramp}" + (f", stimModulationFreqHz: {frequency_hz}" if frequency_in_condition else "")
        text += f"stimLocations{number:02d}:\n  ML: -2.0\n  AP: -1.0\n  Class: stimulate\n  Type: unilateral_point\n"
        if flow_style:
            text += f"  Attributes: {{{attributes}}}\n"
        else:
            text += "  Attributes:\n" + "".join(f"    {item.strip()}\n" for item in attributes.split(","))
    if not frequency_in_condition:
        text += f"stimModulationFreqHz: {frequency_hz}\n"
    Path(path).write_text(text, encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("flow_style", [True, False])
@pytest.mark.parametrize("ramps, frequency", [([250.0, 250.0], 40.0), ([26, 300], 40.0), ([11, 11], 100.0), ([51], 20.0)])
def test_ramp_downs_longer_than_one_cycle_are_accepted(tmp_path, ramps, frequency, flow_style):
    assert count_zapit_conditions(config_with_ramps(tmp_path / "c.yml", ramps, frequency, flow_style)) == len(ramps)


@pytest.mark.parametrize("flow_style", [True, False])
@pytest.mark.parametrize("ramps, frequency, bad", [([250.0, 25.0], 40.0, "stimLocations02"), ([0, 250], 40.0, "stimLocations01"),
                                                   ([10], 100.0, "stimLocations01"), ([50], 20.0, "stimLocations01")])
def test_ramp_downs_of_one_cycle_or_less_are_rejected(tmp_path, ramps, frequency, bad, flow_style):
    with pytest.raises(ValueError, match=bad + r" ramps down over .* not longer than one"):
        count_zapit_conditions(config_with_ramps(tmp_path / "c.yml", ramps, frequency, flow_style))


def test_frequency_given_per_condition_is_used(tmp_path):
    # Older configs store stimModulationFreqHz in each condition; Zapit then uses the first condition's value
    with pytest.raises(ValueError, match="not longer than one 40 Hz cycle"):
        count_zapit_conditions(config_with_ramps(tmp_path / "c.yml", [20.0], 40.0, frequency_in_condition=True))


def test_missing_ramp_down_is_rejected(tmp_path):
    path = tmp_path / "c.yml"
    path.write_text("stimLocations01:\n  ML: -2.0\n  AP: -1.0\n  Attributes: {laserPowerInMW: 5.0}\nstimModulationFreqHz: 40.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="has no offRampDownDuration_ms"):
        count_zapit_conditions(str(path))


# --- count_zapit_conditions ---------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("keys, expected", [
    (["01"], 1),
    (["01", "02", "03"], 3),
    (["03", "01", "02"], 3), # Order in the file does not matter, only the numbers
    ([f"{n:02d}" for n in range(1, 13)], 12),
    (["1", "2"], 2), # Zero padding is not required by the rule
])
def test_counts_conditions_numbered_1_to_n(tmp_path, keys, expected):
    assert count_zapit_conditions(write_config(tmp_path / "config.yml", keys)) == expected


def test_windows_line_endings_and_byte_order_mark(tmp_path):
    path = write_config(tmp_path / "config.yml", ["01", "02"], newline="\r\n", encoding="utf-8-sig")
    assert Path(path).read_bytes().startswith(b"\xef\xbb\xbfstimLocations01")
    assert count_zapit_conditions(path) == 2


def test_space_before_colon_is_a_key(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("stimLocations01 :\n  ML: 1.0\nstimLocations02:\n  ML: 2.0\n", encoding="utf-8")
    assert count_zapit_conditions(str(path)) == 2


def test_only_top_level_keys_count(tmp_path):
    '''Indented, commented and quoted keys are not conditions: Zapit only reads top-level stimLocationsNN keys.'''
    extra = stim_block("03", indent="  ") + "# stimLocations04:\n" + '"stimLocations05": {}\n' + "notstimLocations06:\n"
    assert count_zapit_conditions(write_config(tmp_path / "config.yml", ["01", "02"], extra=extra)) == 2


@pytest.mark.parametrize("keys", [
    ["01", "02", "04"], # Gap: Zapit stops reading at 03 and never loads 04
    ["02", "03"], # Does not start at 1
    ["01", "02", "02"], # Repeat: only one of the two entries survives in Zapit
    ["00", "01"],
])
def test_rejects_conditions_not_numbered_1_to_n(tmp_path, keys):
    with pytest.raises(ValueError, match="must be numbered 1 to"):
        count_zapit_conditions(write_config(tmp_path / "config.yml", keys))


def test_rejects_a_file_with_no_conditions(tmp_path):
    path = tmp_path / "settings.yml"
    path.write_text("laserPowerInMW: 5\nstimModulationFreqHz: 40.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="No stimLocations entries"):
        count_zapit_conditions(str(path))


# --- previous_zapit_config_path ------------------------------------------------------------------------------------------------------------------------

def test_previous_config_path_from_last_session_json(tmp_path):
    session_json = tmp_path / "UclOpenAuditoryVrCorridorTaskLogic.json"
    task_logic = UclOpenAuditoryVrCorridorTaskLogic()
    task_logic.task_parameters.optogenetics = OptogeneticsConfig(enabled=True, zapit_config_path=r"C:\zapit\config.yml")
    session_json.write_text(task_logic.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    assert previous_zapit_config_path(session_json) == r"C:\zapit\config.yml"


@pytest.mark.parametrize("content", [
    None, # No session generated on this PC yet
    "{not json",
    json.dumps({"taskParameters": {"shapingStage": 3}}), # Session JSON from before optogenetics
    json.dumps({"taskParameters": []}),
    json.dumps([1, 2]),
    json.dumps({"taskParameters": {"optogenetics": {"zapitConfigPath": None}}}),
])
def test_previous_config_path_is_empty_when_unavailable(tmp_path, content):
    session_json = tmp_path / "UclOpenAuditoryVrCorridorTaskLogic.json"
    if content is not None:
        session_json.write_text(content, encoding="utf-8")
    assert previous_zapit_config_path(session_json) == ""


# --- prompt_optogenetics: when it is asked --------------------------------------------------------------------------------------------------------------

def no_input_allowed(monkeypatch):
    def fail(prompt=""):
        raise AssertionError(f"input() should not be called, was asked {prompt!r}")
    monkeypatch.setattr("builtins.input", fail)


@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_not_asked_below_stage_5(monkeypatch, stage):
    no_input_allowed(monkeypatch)
    assert prompt_optogenetics(shaping_stage=stage, is_test_session=False, previous_config_path="").model_dump() == OFF


@pytest.mark.parametrize("stage", [5, 6])
def test_asked_at_stages_5_and_6(scripted_input, stage):
    prompts = scripted_input("n")
    assert prompt_optogenetics(shaping_stage=stage, is_test_session=False, previous_config_path="").model_dump() == OFF
    assert prompts == ["Optogenetics (Zapit)? (y/N): "]


@pytest.mark.parametrize("stage", [1, 2, 3, 4, 5, 6])
def test_asked_at_every_stage_for_test_animals(scripted_input, stage):
    prompts = scripted_input("")
    assert prompt_optogenetics(shaping_stage=stage, is_test_session=True, previous_config_path="").model_dump() == OFF
    assert prompts == ["Optogenetics (Zapit)? (y/N): "]


# --- prompt_optogenetics: the answers -------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("answer", ["", "n", "N", "no", "maybe"])
def test_anything_but_yes_leaves_optogenetics_off(scripted_input, answer):
    scripted_input(answer)
    assert prompt_optogenetics(shaping_stage=5, is_test_session=False, previous_config_path="").enabled is False


@pytest.mark.parametrize("answer", ["y", "Y", "yes", " YES "])
def test_yes_with_a_valid_config_turns_optogenetics_on(tmp_path, scripted_input, capsys, answer):
    config = write_config(tmp_path / "config.yml", ["01", "02", "03"])
    scripted_input(answer, config)
    optogenetics = prompt_optogenetics(shaping_stage=6, is_test_session=False, previous_config_path="")
    assert optogenetics.model_dump() == OptogeneticsConfig(enabled=True, zapit_config_path=str(Path(config).resolve())).model_dump()
    out = capsys.readouterr().out
    assert "OPTOGENETICS ON: 3 Zapit conditions" in out
    assert "After 20 sham warmup trials, 40% of trials are laser-on" in out
    assert "will not change the shaping stage" in out


def test_quoted_path_is_accepted(tmp_path, scripted_input):
    '''Windows' Copy as path wraps the path in quotes.'''
    config = write_config(tmp_path / "config.yml", ["01"])
    scripted_input("y", f'"{config}"')
    assert prompt_optogenetics(shaping_stage=5, is_test_session=False, previous_config_path="").zapit_config_path == str(Path(config).resolve())


def test_empty_answer_uses_the_previous_config(tmp_path, scripted_input):
    config = write_config(tmp_path / "config.yml", ["01", "02"])
    prompts = scripted_input("y", "")
    optogenetics = prompt_optogenetics(shaping_stage=5, is_test_session=False, previous_config_path=config)
    assert optogenetics.zapit_config_path == str(Path(config).resolve())
    assert prompts[1] == f"Zapit stimulus config file [default={config}], or n for no optogenetics: "


@pytest.mark.parametrize("cancel", ["n", "N", "no"])
@pytest.mark.parametrize("previous", ["", "previous.yml"])
def test_n_at_the_config_prompt_turns_optogenetics_off(tmp_path, scripted_input, capsys, cancel, previous):
    '''After a y by mistake there is a way back, with or without a previous config to fall back on.'''
    previous_path = write_config(tmp_path / previous, ["01"]) if previous else ""
    scripted_input("y", cancel)
    assert prompt_optogenetics(shaping_stage=5, is_test_session=False, previous_config_path=previous_path).model_dump() == OptogeneticsConfig().model_dump()
    assert "Optogenetics off for this session" in capsys.readouterr().out


@pytest.mark.parametrize("bad_answer, message", [
    ("missing.yml", "File not found"),
    ("", "File not found"), # No previous config to fall back on
    (".", "File not found"), # A folder
    ("gap.yml", "must be numbered 1 to"),
    ("empty.yml", "No stimLocations entries"),
])
def test_bad_config_is_asked_again(tmp_path, scripted_input, capsys, monkeypatch, bad_answer, message):
    monkeypatch.chdir(tmp_path)
    write_config(tmp_path / "gap.yml", ["01", "03"])
    (tmp_path / "empty.yml").write_text("stimModulationFreqHz: 40.0\n", encoding="utf-8")
    good = write_config(tmp_path / "good.yml", ["01", "02"])
    prompts = scripted_input("y", bad_answer, good)
    optogenetics = prompt_optogenetics(shaping_stage=5, is_test_session=False, previous_config_path="")
    assert optogenetics.enabled and optogenetics.zapit_config_path == str(Path(good).resolve())
    assert len(prompts) == 3
    assert message in capsys.readouterr().out


# --- main(): the session JSON ---------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path, monkeypatch):
    '''A throwaway project root for main(): it finds the repo from its own file path, and making waveforms is not part of these tests.'''
    monkeypatch.setattr(gen_session, "__file__", str(tmp_path / "gen-sessions" / "gen_session.py"))
    monkeypatch.setattr(gen_session, "generate_waveforms", lambda **kwargs: {"waveforms": "not generated in tests"})
    return tmp_path


def session_json(project):
    path = project / "session-schemas" / "current-session" / "UclOpenAuditoryVrCorridorTaskLogic.json"
    UclOpenAuditoryVrCorridorTaskLogic.model_validate_json(path.read_text(encoding="utf-8")) # What Bonsai reads must still be a valid session
    return json.loads(path.read_text(encoding="utf-8"))["taskParameters"]


def test_main_test_animal_with_optogenetics(project, scripted_input):
    config = write_config(project / "config.yml", ["01", "02"])
    # Animal, modality, shaping stage (default 1, as a new TEST animal has no history), optogenetics, config
    prompts = scripted_input("test1", "A", "", "y", config)
    gen_session.main()
    parameters = session_json(project)
    assert parameters["shapingStage"] == 1
    assert parameters["optogenetics"]["enabled"] is True
    assert parameters["optogenetics"]["zapitConfigPath"] == str(Path(config).resolve())
    assert len(prompts) == 5

    # The next session offers the same config as its default
    prompts = scripted_input("test1", "A", "", "y", "")
    gen_session.main()
    assert prompts[-1] == f"Zapit stimulus config file [default={Path(config).resolve()}], or n for no optogenetics: "
    assert session_json(project)["optogenetics"]["zapitConfigPath"] == str(Path(config).resolve())


@pytest.mark.parametrize("stage, asked", [(4, False), (5, True), (6, True)])
def test_main_real_animal_is_only_asked_at_stages_5_and_6(project, scripted_input, monkeypatch, stage, asked):
    # A real animal's history is also read from the lab server, so the session id and stage are fixed here rather than looked up
    monkeypatch.setattr(gen_session, "next_session_id", lambda **kwargs: "A1")
    monkeypatch.setattr(gen_session, "determine_shaping_stage", lambda **kwargs: stage)
    prompts = scripted_input("tc999", "A", "", *(["n"] if asked else []))
    gen_session.main()
    assert any(prompt.startswith("Optogenetics") for prompt in prompts) == asked
    parameters = session_json(project)
    assert parameters["shapingStage"] == stage
    assert parameters["optogenetics"] == OptogeneticsConfig().model_dump(by_alias=True)

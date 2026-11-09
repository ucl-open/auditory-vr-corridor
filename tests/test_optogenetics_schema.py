'''
The optogenetics block of the session schema: its defaults and validators, and that the three places it is written down agree - task.py (the source),
the JSON schema in src/DataSchemas and the C# class Bonsai uses in UclOpenAuditoryVrCorridor.Generated.cs. The C# class is kept in sync by hand,
since regenerating it needs the dotnet SDK, so these tests are what catches it drifting.
'''
import inspect
import json
import re
from pathlib import Path
from typing import Union

import pydantic
import pytest

from ucl_open_auditory_vr_corridor.task import (
    OptogeneticsConfig,
    UclOpenAuditoryVrCorridorTaskLogic,
    UclOpenAuditoryVrCorridorTaskParameters,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_JSON = REPO_ROOT / "src" / "DataSchemas" / "ucl_open_auditory_vr_corridor.json"
GENERATED_CS = REPO_ROOT / "src" / "Extensions" / "UclOpenAuditoryVrCorridor.Generated.cs"

# Field names (JSON keys) are fixed: av-dome and the C# class use the same ones
EXPECTED_DEFAULTS = {
    "enabled": False,
    "zapitConfigPath": "",
    "stimProbability": 0.4,
    "stimDuration": 12.5,
    "leadTime": 0.1,
    "pseudorandomSelection": True,
    "warmupTrials": 20,
}


def test_defaults():
    assert OptogeneticsConfig().model_dump(by_alias=True) == EXPECTED_DEFAULTS


# Models are compared through model_dump(): swc.aeon's BaseSchema keeps a private link to the model containing it, which == would compare too
def test_task_parameters_have_optogenetics_off_by_default():
    assert UclOpenAuditoryVrCorridorTaskParameters().optogenetics.model_dump() == OptogeneticsConfig().model_dump()
    assert UclOpenAuditoryVrCorridorTaskParameters().optogenetics.enabled is False


@pytest.mark.parametrize("lead_time", [0.05, 0.1, 0.15, 0.3, 0.35, 0.5, 1.0])
def test_lead_time_accepts_whole_beeps_from_0_05_to_1(lead_time):
    # stim_duration given so the cap rule (at least 12 s + lead_time + 0.25 s) is met for every lead_time here
    assert OptogeneticsConfig(lead_time=lead_time, stim_duration=13.5).lead_time == lead_time


@pytest.mark.parametrize("lead_time", [0.0, -0.05, 0.07, 0.125, 1.05, 2.0])
def test_lead_time_rejects_other_values(lead_time):
    with pytest.raises(pydantic.ValidationError, match="lead_time"):
        OptogeneticsConfig(lead_time=lead_time)


@pytest.mark.parametrize("lead_time, stim_duration", [(0.1, 12.35), (0.1, 12.5), (0.25, 12.5), (0.5, 12.75), (1.0, 13.25), (1.0, 20.0)])
def test_stim_duration_at_least_the_longest_trial_is_accepted(lead_time, stim_duration):
    assert OptogeneticsConfig(lead_time=lead_time, stim_duration=stim_duration).stim_duration == stim_duration


@pytest.mark.parametrize("lead_time, stim_duration", [(0.1, 12.0), (0.1, 12.3), (0.3, 12.5), (0.5, 12.7), (1.0, 13.0), (0.1, 5.0)])
def test_stim_duration_shorter_than_the_longest_trial_is_rejected(lead_time, stim_duration):
    '''The 12 s timeout counts from the first tone pip, lead_time after laser onset: a shorter cap would end the laser before a timeout trial ends.'''
    with pytest.raises(pydantic.ValidationError, match="stim_duration"):
        OptogeneticsConfig(lead_time=lead_time, stim_duration=stim_duration)


@pytest.mark.parametrize("path", ["", "   "])
def test_enabled_needs_a_zapit_config_path(path):
    with pytest.raises(pydantic.ValidationError, match="zapit_config_path is empty"):
        OptogeneticsConfig(enabled=True, zapit_config_path=path)


def test_enabled_with_a_zapit_config_path_is_valid():
    optogenetics = OptogeneticsConfig(enabled=True, zapit_config_path=r"C:\zapit\config.yml")
    assert optogenetics.enabled and optogenetics.zapit_config_path == r"C:\zapit\config.yml"


@pytest.mark.parametrize("field, value", [
    ("stim_probability", -0.1),
    ("stim_probability", 1.1),
    ("stim_duration", 0),
    ("stim_duration", -1.0),
    ("warmup_trials", -1),
])
def test_out_of_range_values_are_rejected(field, value):
    with pytest.raises(pydantic.ValidationError):
        OptogeneticsConfig(**{field: value})


@pytest.mark.parametrize("field, value", [("stim_probability", 0.0), ("stim_probability", 1.0), ("warmup_trials", 0)])
def test_boundary_values_are_accepted(field, value):
    assert getattr(OptogeneticsConfig(**{field: value}), field) == value


def test_session_json_round_trip():
    '''gen_session writes the session JSON with by_alias=True and Bonsai reads it back, so an enabled block must survive the trip unchanged.'''
    task_logic = UclOpenAuditoryVrCorridorTaskLogic(task_parameters=UclOpenAuditoryVrCorridorTaskParameters(
        shaping_stage=5,
        optogenetics=OptogeneticsConfig(enabled=True, zapit_config_path=r"C:\zapit\config.yml", warmup_trials=5),
    ))
    text = task_logic.model_dump_json(indent=2, by_alias=True)
    assert json.loads(text)["taskParameters"]["optogenetics"] == {**EXPECTED_DEFAULTS, "enabled": True, "zapitConfigPath": r"C:\zapit\config.yml", "warmupTrials": 5}
    assert UclOpenAuditoryVrCorridorTaskLogic.model_validate_json(text).model_dump() == task_logic.model_dump()


def _without_session_id_timestamps(text):
    '''The schema's default session id is the time it was generated, so it differs on every regeneration and is left out of the comparison.'''
    return re.sub(r'("sessionId": )"\d{4}-\d{2}-\d{2}T\d{2}_\d{2}_\d{2}"', r'\1"<generated>"', text)


def test_schema_json_matches_the_models():
    '''The committed JSON schema is what regenerate.py writes from the models, so a model change without a regeneration fails here.'''
    utils = pytest.importorskip("aind_behavior_services.utils")
    import ucl_open_auditory_vr_corridor.rig
    import ucl_open_auditory_vr_corridor.task
    models = [ucl_open_auditory_vr_corridor.task.UclOpenAuditoryVrCorridorTaskLogic, ucl_open_auditory_vr_corridor.rig.UclOpenAuditoryVrCorridorRig]
    expected = json.loads(_without_session_id_timestamps(utils.export_schema(pydantic.RootModel[Union[tuple(models)]])))
    committed = json.loads(_without_session_id_timestamps(SCHEMA_JSON.read_text(encoding="utf-8")))
    assert committed == expected


def test_schema_json_optogenetics_defaults():
    schema = json.loads(SCHEMA_JSON.read_text(encoding="utf-8"))
    properties = schema["$defs"]["OptogeneticsConfig"]["properties"]
    assert {name: spec["default"] for name, spec in properties.items()} == EXPECTED_DEFAULTS


# C# string literals as Bonsai.Sgen writes them: a verbatim @"..." string, or "..." chunks joined with + across lines
CS_STRING = r'(@"(?:[^"]|"")*"|"(?:[^"\\]|\\.)*"(?:\s*\+\s*"(?:[^"\\]|\\.)*")*)'
CS_ESCAPES = {"\\\\": "\\", '\\"': '"', "\\'": "'", "\\n": "\n", "\\r": "\r", "\\t": "\t", "\\0": "\0"}


def _cs_string_value(literal):
    if literal.startswith('@"'):
        return literal[2:-1].replace('""', '"')
    chunks = re.findall(r'"((?:[^"\\]|\\.)*)"', literal)
    return "".join(re.sub(r"\\.", lambda escape: CS_ESCAPES[escape.group(0)], chunk) for chunk in chunks)


def _cs_value(literal):
    if literal in ("true", "false"):
        return literal == "true"
    if literal.startswith('"'):
        return _cs_string_value(literal)
    if literal.endswith("D"):
        return float(literal[:-1])
    return int(literal)


@pytest.fixture(scope="module")
def optogenetics_cs():
    '''The OptogeneticsConfig class in the generated C#, from its doc comment to its closing brace.'''
    text = GENERATED_CS.read_text(encoding="utf-8")
    class_start = text.index("public partial class OptogeneticsConfig")
    return text[text.rindex("/// <summary>", 0, class_start):text.index("\n    }\n", class_start)]


def test_generated_cs_defaults_match_task_py(optogenetics_cs):
    constructor = re.search(r"public OptogeneticsConfig\(\)\s*\{(.*?)\}", optogenetics_cs, flags=re.DOTALL).group(1)
    cs_defaults = {name: _cs_value(value.strip()) for name, value in re.findall(r"_(\w+) = ([^;]+);", constructor)}
    assert cs_defaults == OptogeneticsConfig().model_dump(by_alias=True)


def test_generated_cs_descriptions_match_task_py(optogenetics_cs):
    cs_descriptions = {
        name: _cs_string_value(literal)
        for name, literal in re.findall(r'JsonPropertyAttribute\("(\w+)"\)\]\s*\[System\.ComponentModel\.DescriptionAttribute\(' + CS_STRING + r"\)\]", optogenetics_cs)
    }
    model_descriptions = {field.alias: field.description for field in OptogeneticsConfig.model_fields.values()}
    assert cs_descriptions == model_descriptions


def test_generated_cs_class_description_matches_task_py(optogenetics_cs):
    # Sgen indents the continuation lines of a multi-line description, so lines are compared without their leading whitespace
    literal = re.search(r"\[System\.ComponentModel\.DescriptionAttribute\(" + CS_STRING + r"\)\]\s*\[Bonsai\.WorkflowElementCategoryAttribute", optogenetics_cs).group(1)
    cs_lines = [line.strip() for line in _cs_string_value(literal).splitlines()]
    assert cs_lines == inspect.cleandoc(OptogeneticsConfig.__doc__).splitlines()


def test_generated_cs_task_parameters_include_optogenetics():
    text = GENERATED_CS.read_text(encoding="utf-8")
    assert "_optogenetics = new OptogeneticsConfig();" in text
    assert '[Newtonsoft.Json.JsonPropertyAttribute("optogenetics")]' in text
    assert UclOpenAuditoryVrCorridorTaskParameters.model_fields["optogenetics"].alias == "optogenetics"

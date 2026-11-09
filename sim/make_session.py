#!/usr/bin/env python3
"""Write a test session JSON (and the session's waveforms) for a simulated run, like gen-sessions/gen_session.py does
for a real one - but into a sim run folder, never over the repo's session-schemas/current-session file.

The JSON is built with the repo's own pydantic models (src/ucl_open_auditory_vr_corridor/task.py), so defaults,
validators and derived reward windows are exactly what gen_session.py would write. If the swc-aeon package those models
import is not installed (the usual case outside the project's uv environment), a minimal stand-in for
swc.aeon.schema.BaseSchema with the same pydantic settings (camelCase aliases) is used. If the models cannot be
imported at all, a template is used and the output says so.

Usage: make_session.py --repo REPO --out FILE.json --logs DIR [--stage N] [--modality A|V|AV] [--animal TEST] ...
       [--opto --zapit-config FILE.yaml | --zapit-conditions N] [--waveforms DIR]
"""
import argparse
import importlib
import json
import re
import sys
import types
from pathlib import Path


def install_base_schema_shim():
    """swc.aeon.schema.BaseSchema without the rest of swc-aeon (which needs harp, opencv, dotmap...)."""
    from pydantic import BaseModel, ConfigDict
    from pydantic.alias_generators import to_camel, to_pascal

    class BaseSchema(BaseModel):
        model_config = ConfigDict(alias_generator=to_camel, arbitrary_types_allowed=True,
                                  field_title_generator=lambda n, _: to_pascal(n), populate_by_name=True,
                                  from_attributes=True)

    for name in ('swc', 'swc.aeon'):
        sys.modules.setdefault(name, types.ModuleType(name))
    module = types.ModuleType('swc.aeon.schema')
    module.BaseSchema = BaseSchema
    sys.modules['swc.aeon.schema'] = module


def project_version(repo):
    text = (Path(repo) / 'pyproject.toml').read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else None


def import_task_models(repo):
    sys.path.insert(0, str(Path(repo) / 'src'))
    try:
        return importlib.import_module('ucl_open_auditory_vr_corridor.task'), 'repo models'
    except ModuleNotFoundError as e:
        if not (e.name or '').startswith('swc'):
            raise
    install_base_schema_shim()
    for name in list(sys.modules):
        if name.startswith('ucl_open_auditory_vr_corridor'):
            del sys.modules[name]
    return importlib.import_module('ucl_open_auditory_vr_corridor.task'), 'repo models (swc-aeon BaseSchema stand-in)'


TEMPLATE = {
    "version": "0.0.0-rc1",
    "name": "UclOpenAuditoryVrCorridor",
    "taskParameters": {
        "modality": "A", "shapingStage": 1, "startFreq": 2000, "endFreq": 25000, "nFreqBins": 100,
        "centerFreq": 18000, "rewardWindowSize": 6000,
        "thresholdFrequencies": {s: {"floor": f, "ceiling": c} for s, f, c in [
            ("stage1", 18000, 25000), ("stage2", 18000, 25000), ("stage3", 15248, 25000),
            ("stage4", 15248, 21248), ("stage5", 15248, 21248)]},
        "punishment": {"timeoutSec": 2, "stage4PunishedLick": 8, "stage5PunishedLick": 5},
        "truncation": {"fraction": 0.16, "points": [0.4, 0.6]},
        "engagement": {"rollWindow": 25, "rollThreshold": 0.5, "minEpoch": 10},
        "logConfig": {"loggingRootPath": "", "sessionId": "", "animalId": ""},
        "amplitude": 0.05, "backgroundNoiseLevel": 0.5, "quantizeBinSize": 1,
    },
}


def write_zapit_config(path, n):
    """A Zapit stimulus config with n conditions (stimLocations01..n), the shape Zapit and the task read."""
    lines = []
    for i in range(1, n + 1):
        lines += [f'stimLocations{i:02d}:', '  ML: [-2.5, 2.5]', '  AP: [-2.0, -2.0]', '  Class: sim',
                  '  Type: bilateral_on_coords']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n')


def build(args):
    repo = Path(args.repo).resolve()
    source = 'template'
    opto_fields = None
    try:
        task, source = import_task_models(repo)
    except Exception as e:      # noqa: BLE001 - fall back to the template, and say why
        print(f'make_session: could not import the repo task models ({type(e).__name__}: {e}); using a template',
              file=sys.stderr)
        task = None

    if task is not None:
        params_kwargs = dict(
            log_config=task.LogConfig(session_id=args.session_id, animal_id=args.animal,
                                      logging_root_path=str(Path(args.logs).resolve())),
            shaping_stage=args.stage, modality=args.modality)
        for name, value in (('n_freq_bins', args.n_freq_bins), ('amplitude', args.amplitude)):
            if value is not None:
                params_kwargs[name] = value
        fields = task.UclOpenAuditoryVrCorridorTaskParameters.model_fields
        if args.opto:
            if 'optogenetics' not in fields or not hasattr(task, 'OptogeneticsConfig'):
                raise SystemExit('make_session: --opto requested but this branch\'s task.py has no OptogeneticsConfig')
            opto = dict(enabled=True, zapit_config_path=str(Path(args.zapit_config).resolve()))
            for name, value in (('stim_probability', args.stim_probability), ('stim_duration', args.stim_duration),
                                ('lead_time', args.lead_time), ('warmup_trials', args.warmup_trials),
                                ('pseudorandom_selection', args.pseudorandom)):
                if value is not None:
                    opto[name] = value
            opto_fields = opto
            params_kwargs['optogenetics'] = task.OptogeneticsConfig(**opto)
        logic = task.UclOpenAuditoryVrCorridorTaskLogic(
            task_parameters=task.UclOpenAuditoryVrCorridorTaskParameters(**params_kwargs))
        data = json.loads(logic.model_dump_json(by_alias=True))
        version = project_version(repo)
        if version and data.get('version') in ('0.0.0', None):
            # gen_session runs with the package installed, so its version is pyproject's (e.g. 0.0.0-rc1)
            data['version'] = re.sub(r'(?<=\d)(a|b|rc)(\d+)', r'-\1\2', version)
    else:
        if args.opto:
            raise SystemExit('make_session: --opto needs the repo task models')
        data = json.loads(json.dumps(TEMPLATE))
        version = project_version(repo)
        if version:
            data['version'] = version
        p = data['taskParameters']
        p.update(modality=args.modality, shapingStage=args.stage)
        p['logConfig'] = {'loggingRootPath': str(Path(args.logs).resolve()), 'sessionId': args.session_id,
                          'animalId': args.animal}
        if args.n_freq_bins is not None:
            p['nFreqBins'] = args.n_freq_bins
        if args.amplitude is not None:
            p['amplitude'] = args.amplitude
    return data, source, opto_fields


def write_waveforms(repo, params, out_dir):
    """Session waveforms (all_waveforms.bin, error_tone.wav, ...) as gen_session.py writes them into src/waveforms."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(repo) / 'gen-sessions'))
    try:
        helpers = importlib.import_module('helpers')
        helpers.generate_waveforms(start_freq=params['startFreq'], end_freq=params['endFreq'],
                                   n_freq_bins=params['nFreqBins'], amplitude=params['amplitude'], out_dir=out_dir)
        return 'gen-sessions/helpers.generate_waveforms'
    except Exception as e:      # noqa: BLE001
        print(f'make_session: gen-sessions/helpers.generate_waveforms failed ({type(e).__name__}: {e}); '
              'writing silent waveforms of the right size', file=sys.stderr)
    import struct
    import wave
    samples = 2400          # 50 ms at 48 kHz, as generate_waveforms
    (out_dir / 'all_waveforms.bin').write_bytes(b'\0' * (4 * samples * params['nFreqBins']))
    with wave.open(str(out_dir / 'error_tone.wav'), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(struct.pack('<h', 0) * 48000)
    return 'silent placeholder waveforms'


def main(argv=None):
    ap = argparse.ArgumentParser(description='Write a test session JSON for a simulated run.')
    ap.add_argument('--repo', required=True)
    ap.add_argument('--out', required=True, help='session JSON to write (in the sim run folder)')
    ap.add_argument('--logs', required=True, help='LoggingRootPath for the session (a temporary folder)')
    ap.add_argument('--stage', type=int, default=5)
    ap.add_argument('--modality', default='A', choices=['A', 'V', 'AV'])
    ap.add_argument('--animal', default='TEST')
    ap.add_argument('--session-id', default='SIM1')
    ap.add_argument('--n-freq-bins', type=int)
    ap.add_argument('--amplitude', type=float)
    ap.add_argument('--waveforms', help='also write the session waveforms into this folder (src/waveforms)')
    g = ap.add_argument_group('optogenetics (branches with OptogeneticsConfig only)')
    g.add_argument('--opto', action='store_true')
    g.add_argument('--zapit-config', help='Zapit stimulus config YAML (default: write one with --zapit-conditions)')
    g.add_argument('--zapit-conditions', type=int, default=4)
    g.add_argument('--stim-probability', type=float)
    g.add_argument('--stim-duration', type=float)
    g.add_argument('--lead-time', type=float)
    g.add_argument('--warmup-trials', type=int)
    g.add_argument('--pseudorandom', type=lambda s: s.lower() in ('1', 'true', 'yes'), default=None)
    args = ap.parse_args(argv)

    if args.opto and not args.zapit_config:
        args.zapit_config = str(Path(args.out).resolve().parent / 'zapit_stim_config_sim.yaml')
        write_zapit_config(Path(args.zapit_config), args.zapit_conditions)

    data, source, opto = build(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2))
    params = data['taskParameters']
    print(f'session: {out} ({source}): animal {params["logConfig"]["animalId"]}, session {params["logConfig"]["sessionId"]}, '
          f'stage {params["shapingStage"]}, modality {params["modality"]}'
          + (f', optogenetics {opto}' if opto else ''))
    if args.waveforms:
        how = write_waveforms(args.repo, params, args.waveforms)
        print(f'waveforms: {args.waveforms} ({how})')
    return data


if __name__ == '__main__':
    main()

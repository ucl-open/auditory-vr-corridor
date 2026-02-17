from typing import Literal
from pydantic import Field

from swc.aeon.schema import BaseSchema

from ucl_open_auditory_vr_corridor import __semver__


class Stage(BaseSchema):
    '''Frequency boundaries for a single shaping stage.'''
    floor: int = Field(description='Lower frequency threshold (Hz)')
    ceiling: int = Field(description='Upper frequency ceiling (Hz)')


class ThresholdFrequencies(BaseSchema):
    '''Floor and ceiling frequencies of the reward zone for each shaping stage.'''
    stage1: Stage = Stage(floor=18000, ceiling=25000)
    stage2: Stage = Stage(floor=18000, ceiling=25000)
    stage3: Stage = Stage(floor=14000, ceiling=25000)
    stage4: Stage = Stage(floor=14000, ceiling=25000)
    stage5: Stage = Stage(floor=14000, ceiling=22000)
    stage6: Stage = Stage(floor=16000, ceiling=20000)


class PunishmentConfig(BaseSchema):
    '''Punishment params.'''
    timeout_sec: int = Field(default=5, description='Timeout duration in seconds')
    stage4_punished_lick: int = Field(default=5, description='Punished lick in stage 4')
    stage5_punished_lick: int = Field(default=4, description='Punished lick in stage 5')
    stage6_punished_lick: int = Field(default=3, description='Punished lick in stage 6')


class UclOpenAuditoryVrCorridorTaskParameters(BaseSchema):
    '''Task params.'''
    shaping_stage: int = Field(default=1, description='Shaping stage (1-6)')
    start_freq: int = Field(default=2000, description='Start frequency of the sweep (Hz)')
    end_freq: int = Field(default=25000, description='End frequency of the sweep (Hz)')
    threshold_frequencies: ThresholdFrequencies = ThresholdFrequencies()
    punishment: PunishmentConfig = PunishmentConfig()
    amplitude: float = Field(default=0.5, description='Audio amplitude (0.0 to 1.0)')
    quantize_bin_size: int = Field(default=1, description='Bin size for frequency quantization (Hz)')


class UclOpenAuditoryVrCorridorTaskLogic(BaseSchema):
    '''Top-level task logic schema.'''
    version: Literal[__semver__] = __semver__
    name: Literal['UclOpenAuditoryVrCorridor'] = Field(
        default='UclOpenAuditoryVrCorridor',
        description='Name of the task',
    )
    task_parameters: UclOpenAuditoryVrCorridorTaskParameters = UclOpenAuditoryVrCorridorTaskParameters()
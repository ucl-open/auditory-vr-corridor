from typing import Literal
from pydantic import Field, model_validator

from swc.aeon.schema import BaseSchema
from helpers import calc_log_window, calc_floor

from ucl_open_auditory_vr_corridor import __semver__

center_freq = 18000
end_freq = 25000

# Given the center_freq and end_freq, calculate the lower_freq that ensures the center_freq is in the center of floor_freq and ceil_freq in logarithmic space
floor_freq = calc_floor(center_freq, end_freq)

# Log window function: ensures center_freq is in the center of the window in logarithmic space, so that the window is 'perceptually balanced' around the center_freq)
stage5_floor, stage5_ceiling = calc_log_window(center_freq=center_freq, window_size=8000)
stage6_floor, stage6_ceiling = calc_log_window(center_freq=center_freq, window_size=4000)


class Stage(BaseSchema):
    '''Frequency boundaries for a single shaping stage.'''
    floor: int = Field(description='Lower frequency threshold (Hz)', ge=1, le=25000)
    ceiling: int = Field(description='Upper frequency ceiling (Hz)', ge=1, le=25000)

    @model_validator(mode="after")
    def validate_floor_less_than_ceiling(self):
        if self.floor >= self.ceiling:
            raise ValueError('Reward freq floor must be less than ceiling')
        return self


class ThresholdFrequencies(BaseSchema):
    '''Floor and ceiling frequencies of the reward zone for each shaping stage.'''
    stage1: Stage = Stage(floor=center_freq, ceiling=end_freq)
    stage2: Stage = Stage(floor=center_freq, ceiling=end_freq)
    stage3: Stage = Stage(floor=floor_freq, ceiling=end_freq)
    stage4: Stage = Stage(floor=floor_freq, ceiling=end_freq)
    stage5: Stage = Stage(floor=stage5_floor, ceiling=stage5_ceiling)
    stage6: Stage = Stage(floor=stage6_floor, ceiling=stage6_ceiling)


class PunishmentConfig(BaseSchema):
    '''Punishment params.'''
    timeout_sec: int = Field(default=5, description='Timeout duration in seconds')
    stage4_punished_lick: int = Field(default=5, description='Punished lick in stage 4', ge=1)
    stage5_punished_lick: int = Field(default=4, description='Punished lick in stage 5', ge=1)
    stage6_punished_lick: int = Field(default=3, description='Punished lick in stage 6', ge=1)


class UclOpenAuditoryVrCorridorTaskParameters(BaseSchema):
    '''Task params.'''
    shaping_stage: int = Field(default=1, description='Shaping stage (1-6)', ge=1, le=6)
    start_freq: int = Field(default=2000, description='Start frequency of the sweep (Hz)', ge=1, le=25000)
    end_freq: int = Field(default=end_freq, description='End frequency of the sweep (Hz)', ge=1, le=25000)
    threshold_frequencies: ThresholdFrequencies = ThresholdFrequencies()
    punishment: PunishmentConfig = PunishmentConfig()
    amplitude: float = Field(default=0.5, description='Audio amplitude (0.0 to 1.0)', ge=0.0, le=1.0)
    quantize_bin_size: int = Field(default=1, description='Bin size for frequency quantization (Hz)', ge=1)

    @model_validator(mode="after")
    def validate_start_less_than_end_freq(self):
        if self.start_freq >= self.end_freq:
            raise ValueError('start_freq must be less than end_freq')
        return self


class UclOpenAuditoryVrCorridorTaskLogic(BaseSchema):
    '''Top-level task logic schema.'''
    version: Literal[__semver__] = __semver__
    name: Literal['UclOpenAuditoryVrCorridor'] = Field(
        default='UclOpenAuditoryVrCorridor',
        description='Name of the task',
    )
    task_parameters: UclOpenAuditoryVrCorridorTaskParameters = UclOpenAuditoryVrCorridorTaskParameters()
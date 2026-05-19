from typing import Literal, Optional
from pydantic import Field, model_validator
from datetime import datetime

from swc.aeon.schema import BaseSchema
from ucl_open_auditory_vr_corridor.helpers import calc_log_window, calc_floor

from ucl_open_auditory_vr_corridor import __semver__


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
    stage1: Stage 
    stage2: Stage 
    stage3: Stage
    stage4: Stage 
    stage5: Stage 
    stage6: Stage 


class PunishmentConfig(BaseSchema):
    '''Punishment params.'''
    timeout_sec: int = Field(default=5, description='Timeout duration in seconds')
    stage4_punished_lick: int = Field(default=5, description='Punished lick in stage 4', ge=1)
    stage5_punished_lick: int = Field(default=4, description='Punished lick in stage 5', ge=1)
    stage6_punished_lick: int = Field(default=3, description='Punished lick in stage 6', ge=1)


class LogConfig(BaseSchema):
    '''Logging params.'''
    logging_root_path: str = Field(default=r"..\Logs", description="Root path for logs")
    session_id: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%dT%H_%M_%S"), description="Unique session identifier, defaults to timestamp")
    animal_id: str = Field(default="unknown_animal", description="Animal identifier for the session")


class UclOpenAuditoryVrCorridorTaskParameters(BaseSchema):
    '''Task params.'''
    modality: Literal["A", "V", "AV"] = Field(default="AV", description="Stimulus modality: auditory (A), visual (V), or audiovisual (AV)")

    shaping_stage: int = Field(default=1, description='Shaping stage (1-6)', ge=1, le=6)
    start_freq: int = Field(default=2000, description='Start frequency of the sweep (Hz)', ge=1, le=25000)
    end_freq: int = Field(default=25000, description='End frequency of the sweep (Hz)', ge=1, le=25000)

    n_freq_bins: int = Field(default=100, description='Number of frequency bins for quantization', ge=10)

    center_freq: int = Field(default=18000, description="Center frequency of all reward windows (Hz)", ge=1, le=25000)
    stage5_window_size: int = Field(default=8000, ge=1, le=25000, description="Window size around center_freq for stage 5 (Hz)")
    stage6_window_size: int = Field(default=4000, ge=1, le=25000, description="Window size around center_freq for stage 6 (Hz)")

    threshold_frequencies: Optional[ThresholdFrequencies] = None

    punishment: PunishmentConfig = PunishmentConfig()
    log_config: LogConfig = LogConfig()
    amplitude: float = Field(default=0.05, description='Audio amplitude (0.0 to 1.0)', ge=0.0, le=1.0)
    quantize_bin_size: int = Field(default=1, description='Bin size for frequency quantization (Hz)', ge=1)

    @model_validator(mode="after")
    def validate_start_less_than_end_freq(self):
        if self.start_freq >= self.end_freq:
            raise ValueError('start_freq must be less than end_freq')
        
        min_floor = calc_floor(center_freq=self.center_freq, ceil_freq=self.end_freq) # Picks a floor freq that gives the maximum reward window size while ensuring center_freq is centered in logarithmic space and end_freq is the window ceiling
        stage5_floor, stage5_ceiling = calc_log_window(center_freq=self.center_freq, window_size=self.stage5_window_size) # Slightly smaller reward window with center_freq in the middle of the window in log space
        stage6_floor, stage6_ceiling = calc_log_window(center_freq=self.center_freq, window_size=self.stage6_window_size) # Even smaller reward window

        # Check calculated frequencies are within valid range
        if stage5_ceiling > self.end_freq:
            raise ValueError(
                f"stage5_ceiling ({stage5_ceiling}) exceeds end_freq ({self.end_freq}) - reduce stage5_window_size or increase end_freq."
            )

        if stage6_ceiling > self.end_freq:
            raise ValueError(
                f"stage6_ceiling ({stage6_ceiling}) exceeds end_freq ({self.end_freq}) - reduce stage6_window_size or increase end_freq."
            )

        if stage5_floor < min_floor:
            raise ValueError(
                f"stage5_floor ({stage5_floor}) is below min_floor ({min_floor}) - reduce stage5_window_size or reduce center_freq."
            )

        if stage6_floor < min_floor:
            raise ValueError(
                f"stage6_floor ({stage6_floor}) is below min_floor ({min_floor}) - reduce stage5_window_size or reduce center_freq."
            )

        if self.threshold_frequencies is None: # If threshold frequencies not provided, calculate default vals based on center_freq and end_freq to ensure reward windows are 'perceptually balanced' around center_freq in log space
            self.threshold_frequencies = ThresholdFrequencies(
                stage1=Stage(floor=self.center_freq, ceiling=self.end_freq), # For stage 1 and 2, mouse is rewarded as soon as it enters reward zone, without having to lick - hence reward floor is set to center_freq  
                stage2=Stage(floor=self.center_freq, ceiling=self.end_freq),
                stage3=Stage(floor=min_floor, ceiling=self.end_freq), # Stage 3 has maximum reward window size
                stage4=Stage(floor=min_floor, ceiling=self.end_freq), # Stage 3 also has maximum rewward window size, but punishments for wrong licks now introduced
                stage5=Stage(floor=stage5_floor, ceiling=stage5_ceiling), 
                stage6=Stage(floor=stage6_floor, ceiling=stage6_ceiling)
            )
        return self


class UclOpenAuditoryVrCorridorTaskLogic(BaseSchema):
    '''Top-level task logic schema.'''
    version: Literal[__semver__] = __semver__
    name: Literal['UclOpenAuditoryVrCorridor'] = Field(
        default='UclOpenAuditoryVrCorridor',
        description='Name of the task',
    )
    task_parameters: UclOpenAuditoryVrCorridorTaskParameters = UclOpenAuditoryVrCorridorTaskParameters()
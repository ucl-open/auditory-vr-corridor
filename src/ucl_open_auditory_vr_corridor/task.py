from typing import Literal, Optional
from pydantic import Field, model_validator
from datetime import datetime

from swc.aeon.schema import BaseSchema
from ucl_open_auditory_vr_corridor.helpers import calc_log_window

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


class PunishmentConfig(BaseSchema):
    '''Punishment params.'''
    timeout_sec: int = Field(default=2, description='Timeout duration in seconds')
    stage4_punished_lick: int = Field(default=8, description='Punished lick in stage 4', ge=1)
    stage5_punished_lick: int = Field(default=5, description='Punished lick in stage 5', ge=1)


class ProbeConfig(BaseSchema):
    '''Probe trials, used in stage 6 only.

    A probe trial runs the same frequency sweep over a longer track, so the reward frequency arrives further along the corridor than the animal is used to.
    An animal following the sound still gets rewarded; one that has learnt to lick at a fixed distance does not.
    '''
    fraction: float = Field(default=0.15, description='Fraction of stage 6 trials that are probe trials. The rest are split evenly between the normal track lengths', ge=0.0, le=1.0)
    track_length: float = Field(default=120, description='Track length of a probe trial (cm)', gt=0)


class EngagementConfig(BaseSchema):
    '''Params for labelling whether the animal is still attempting the task.

    A mouse partway through a session often keeps running but stops licking. Those trials are not failures - it is not attempting the task - so they are
    labelled separately rather than scored as misses. Engagement is read from whether each trial contained a lick, smoothed over a window of trials, so
    that contiguous periods are judged rather than individual trials. Defaults match the offline analysis; changing them here changes both.
    '''
    roll_window: int = Field(default=25, description='Trials averaged around each trial when deciding engagement. Prefer an odd value: an even window is centred one trial further back than forward', ge=1)
    roll_threshold: float = Field(default=0.5, description='Lick fraction at or below which the animal counts as disengaged', ge=0.0, le=1.0)
    min_epoch: int = Field(default=10, description='Shortest run of trials that can be called engaged or disengaged - shorter runs are absorbed into their neighbours. Above 20 this starts swallowing real working periods', ge=1, le=20)


class LogConfig(BaseSchema):
    '''Logging params.'''
    logging_root_path: str = Field(default=r"..\Logs", description="Root path for logs")
    session_id: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%dT%H_%M_%S"), description="Unique session identifier, defaults to timestamp")
    animal_id: str = Field(default="unknown_animal", description="Animal identifier for the session")


class UclOpenAuditoryVrCorridorTaskParameters(BaseSchema):
    '''Task params.'''
    modality: Literal["A", "V", "AV"] = Field(default="AV", description="Stimulus modality: auditory (A), visual (V), or audiovisual (AV)")

    shaping_stage: int = Field(default=1, description='Shaping stage (1-6). Stage 6 is stage 5 with probe trials and is only ever selected by hand', ge=1, le=6)
    start_freq: int = Field(default=2000, description='Start frequency of the sweep (Hz)', ge=1, le=25000)
    end_freq: int = Field(default=25000, description='End frequency of the sweep (Hz)', ge=1, le=25000)

    n_freq_bins: int = Field(default=100, description='Number of frequency bins for quantization', ge=10)

    center_freq: int = Field(default=18000, description="Center frequency of all reward windows (Hz)", ge=1, le=25000)
    reward_window_size: int = Field(default=6000, ge=1, le=25000, description="Window size around center_freq, setting the reward floor for stages 3-5 and the ceiling for stages 4-5 (Hz)")

    threshold_frequencies: Optional[ThresholdFrequencies] = None

    punishment: PunishmentConfig = PunishmentConfig()
    probe: ProbeConfig = ProbeConfig()
    engagement: EngagementConfig = EngagementConfig()
    log_config: LogConfig = LogConfig()
    amplitude: float = Field(default=0.05, description='Audio amplitude (0.0 to 1.0)', ge=0.0, le=1.0)
    quantize_bin_size: int = Field(default=1, description='Bin size for frequency quantization (Hz)', ge=1)

    @model_validator(mode="after")
    def validate_start_less_than_end_freq(self):
        if self.start_freq >= self.end_freq:
            raise ValueError('start_freq must be less than end_freq')
        
        reward_floor, reward_ceiling = calc_log_window(center_freq=self.center_freq, window_size=self.reward_window_size) # Reward window with center_freq in the middle of the window in log space

        # Check calculated frequencies are within valid range
        if reward_ceiling > self.end_freq:
            raise ValueError(
                f"reward_ceiling ({reward_ceiling}) exceeds end_freq ({self.end_freq}) - reduce reward_window_size or increase end_freq."
            )

        if reward_floor <= self.start_freq:
            raise ValueError(
                f"reward_floor ({reward_floor}) is not above start_freq ({self.start_freq}) - reduce reward_window_size or increase center_freq."
            )

        if self.threshold_frequencies is None: # If threshold frequencies not provided, calculate default vals based on center_freq and end_freq to ensure reward windows are 'perceptually balanced' around center_freq in log space
            # The reward floor is the same from stage 3 onwards, and only the ceiling comes down. Mice lick in anticipation of the reward frequency, so moving
            # the floor between stages invalidates the timing they have already learnt and they fail the new stage on licks that would have been correct before.
            self.threshold_frequencies = ThresholdFrequencies(
                stage1=Stage(floor=self.center_freq, ceiling=self.end_freq), # For stage 1 and 2, mouse is rewarded as soon as it enters reward zone, without having to lick - hence reward floor is set to center_freq
                stage2=Stage(floor=self.center_freq, ceiling=self.end_freq),
                stage3=Stage(floor=reward_floor, ceiling=self.end_freq), # Must now lick to be rewarded, but anywhere above the floor counts and wrong licks are not punished
                stage4=Stage(floor=reward_floor, ceiling=reward_ceiling), # Ceiling comes in, so licking too late is now wrong, and wrong licks are punished
                stage5=Stage(floor=reward_floor, ceiling=reward_ceiling) # Same window as stage 4, but fewer wrong licks are tolerated
            ) # Stage 6 has no entry of its own: it is stage 5 with probe trials, so it uses the stage 5 window and punishment
        return self


class UclOpenAuditoryVrCorridorTaskLogic(BaseSchema):
    '''Top-level task logic schema.'''
    version: Literal[__semver__] = __semver__
    name: Literal['UclOpenAuditoryVrCorridor'] = Field(
        default='UclOpenAuditoryVrCorridor',
        description='Name of the task',
    )
    task_parameters: UclOpenAuditoryVrCorridorTaskParameters = UclOpenAuditoryVrCorridorTaskParameters()
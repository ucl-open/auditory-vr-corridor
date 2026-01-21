# Import core types
from typing import Literal
from pydantic import Field

from swc.aeon.io import reader
from swc.aeon.schema import BaseSchema, data_reader

from ucl_open_auditory_vr_corridor import __semver__

# TODO - should inherit from some TaskParameters base class rather than BaseSchema
class UclOpenAuditoryVrCorridorTaskParameters(BaseSchema):
    ...


class UclOpenAuditoryVrCorridorTaskLogic(BaseSchema):
    version: Literal[__semver__] = __semver__
    name: Literal["UclOpenAuditoryVrCorridor"] = Field(default="UclOpenAuditoryVrCorridor", description="Name of the task logic", frozen=True)
    task_parameters: UclOpenAuditoryVrCorridorTaskParameters = Field(description="Parameters of the task logic")
    ...
from pathlib import Path
from typing import Union

import pydantic
from ucl_open.rigs.experiment import Experiment
from aind_behavior_services.utils import BonsaiSgenSerializers, convert_pydantic_to_bonsai

import ucl_open_auditory_vr_corridor.rig
import ucl_open_auditory_vr_corridor.task

SCHEMA_ROOT = Path("./src/DataSchemas/")
EXTENSIONS_ROOT = Path("./src/Extensions/")
NAMESPACE_PREFIX = "UclOpenAuditoryVrCorridorDataSchema"


def main():
    models = [
        ucl_open_auditory_vr_corridor.task.UclOpenAuditoryVrCorridorTaskLogic,
        ucl_open_auditory_vr_corridor.rig.UclOpenAuditoryVrCorridorRig,
    ]
    model = pydantic.RootModel[Union[tuple(models)]]

    convert_pydantic_to_bonsai(
        model, # type: ignore
        model_name="ucl_open_auditory_vr_corridor",
        root_element="Root",
        cs_namespace=NAMESPACE_PREFIX,
        json_schema_output_dir=SCHEMA_ROOT,
        cs_output_dir=EXTENSIONS_ROOT,
        cs_serializer=[BonsaiSgenSerializers.JSON],
    )


if __name__ == "__main__":
    main()
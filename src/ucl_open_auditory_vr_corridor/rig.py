from typing import Literal, Dict
from pydantic import Field

from ucl_open.rigs.base import BaseSchema
import ucl_open.rigs.device as Device
import ucl_open.rigs.controllers as Controllers
from ucl_open.rigs.video import SpinnakerCamera

from ucl_open_auditory_vr_corridor import __semver__

class UclOpenAuditoryVrCorridorRig(BaseSchema):
    version: Literal[__semver__] = __semver__
    behaviorboard: Device.BehaviorBoard
    runningwheel: Controllers.RunningWheelModule
    lickety_splits:  Device.LicketySplit
    cameras: SpinnakerCamera
    led_driver: Device.ArduinoDevice
    #stepper_motors: StepperMotor
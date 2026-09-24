using Bonsai;
using System;
using System.ComponentModel;
using System.Reactive.Linq;

// Hardware and calibrations for each rig, picked by the PC's name so every rig runs the same
// main.bonsai. To add a rig, add a case below and a method for it.
[Combinator]
[Description("")]
[WorkflowElementCategory(ElementCategory.Transform)]
public class RigConfigs
{
    public IObservable<RigSpecificConfigs> Process(IObservable<String> source)
    {
        return source.Select(value =>
        {
            String machineName = Environment.MachineName.ToUpperInvariant();  // Rig PC names must be unique
            Console.WriteLine("Rig config: " + machineName);
            switch (machineName)
            {
                case "BLUE-OPTO-1":
                    return BlueOpto1Configs();
                case "BLUE-OPTO-2":
                    return BlueOpto2Configs();
                case "GREEN-DOME-2":
                    return GreenDome2Configs();
                default:
                    throw new ArgumentException("No rig settings for " + machineName + " - add a case in RigConfigs.cs");
            }
        });
    }

    private RigSpecificConfigs BlueOpto1Configs()
    {
        RigSpecificConfigs configs = new RigSpecificConfigs();

        // COM ports
        configs.COMPortTimestampGenerator = "COM5";
        configs.COMPortBehaviourBoard = "COM6";
        configs.COMPortStepperDriver1 = "COM3";  // Motors 1,2,3
        configs.COMPortStepperDriver2 = "COM4";  // Motors 4,5
        configs.COMPortLicketySplit = "COM7";

        // Cameras
        configs.SerialNumberCamera1 = "23199186";  // Body
        configs.SerialNumberCamera2 = "26120781";  // Pupil
        configs.SerialNumberCamera3 = "23201535";  // Face

        // Audio and visual
        configs.AudioDeviceName = "Speakers (7- XMOS xCORE-200 MC (UAC2.0))";  // TODO: check on this rig
        configs.MeshMapFilePath = @"C:\RigConfigs\MeshMap.csv";

        // Valve calibration
        configs.ValveOpenTime = 55;  // in ms. ~10ms min. TODO: not calibrated on this rig

        // Spout start positions
        configs.Motor1InPosition = 3550;  // TODO: not set on this rig
        configs.Motor2InPosition = 5500;
        configs.Motor3InPosition = 4700;
        configs.Motor4InPosition = 2150;
        configs.Motor5InPosition = 950;

        return configs;
    }

    private RigSpecificConfigs BlueOpto2Configs()
    {
        RigSpecificConfigs configs = new RigSpecificConfigs();

        // COM ports
        configs.COMPortTimestampGenerator = "COM16";
        configs.COMPortBehaviourBoard = "COM11";
        configs.COMPortStepperDriver1 = "COM14";  // Motors 1,2,3
        configs.COMPortStepperDriver2 = "COM12";  // Motors 4,5
        configs.COMPortLicketySplit = "COM15";

        // Cameras
        configs.SerialNumberCamera1 = "25366318";  // Body
        configs.SerialNumberCamera2 = "25366328";  // Pupil
        configs.SerialNumberCamera3 = "25366326";  // Face

        // Audio and visual
        configs.AudioDeviceName = "Speakers (7- XMOS xCORE-200 MC (UAC2.0))";
        configs.MeshMapFilePath = @"C:\RigConfigs\MeshMap.csv";

        // Valve calibration
        configs.ValveOpenTime = 95;  // in ms. ~10ms min.

        // Spout start positions
        configs.Motor1InPosition = 3550;
        configs.Motor2InPosition = 5500;
        configs.Motor3InPosition = 4700;
        configs.Motor4InPosition = 2150;
        configs.Motor5InPosition = 950;

        return configs;
    }

    private RigSpecificConfigs GreenDome2Configs()
    {
        RigSpecificConfigs configs = new RigSpecificConfigs();

        // COM ports
        configs.COMPortTimestampGenerator = "COM9";
        configs.COMPortBehaviourBoard = "COM10";
        configs.COMPortStepperDriver1 = "COM7";  // Motors 1,2,3
        configs.COMPortStepperDriver2 = "COM8";  // Motors 4,5
        configs.COMPortLicketySplit = "COM11";

        // Cameras
        configs.SerialNumberCamera1 = "25366329";  // Body
        configs.SerialNumberCamera2 = "23199185";  // Pupil
        configs.SerialNumberCamera3 = "23201540";  // Face

        // Audio and visual
        configs.MeshMapFilePath = @"C:\RigConfigs\MeshMap.csv";

        // Valve calibration
        configs.ValveOpenTime = 80;  // in ms. ~10ms min. TODO: not calibrated on this rig

        // Spout start positions
        configs.Motor1InPosition = 3550;  // TODO: not set on this rig
        configs.Motor2InPosition = 5500;
        configs.Motor3InPosition = 4700;
        configs.Motor4InPosition = 2150;
        configs.Motor5InPosition = 950;

        return configs;
    }
}


public class RigSpecificConfigs
{
    // COM ports
    public String COMPortTimestampGenerator;
    public String COMPortBehaviourBoard;
    public String COMPortStepperDriver1;  // Motors 1,2,3
    public String COMPortStepperDriver2;  // Motors 4,5
    public String COMPortLicketySplit;

    // Cameras, numbered as they are logged - Camera1 is VideoData_Camera1.avi
    public String SerialNumberCamera1;  // Body
    public String SerialNumberCamera2;  // Pupil
    public String SerialNumberCamera3;  // Face

    // Audio and visual
    public String AudioDeviceName;  // Sound card the mixer opens
    public String MeshMapFilePath;  // MeshMapping interpolation file

    // Valve calibration
    public Double ValveOpenTime;  // in ms. Same duration gives a different volume on each rig

    // Spout start positions, in motor steps, before an animal's saved positions are loaded
    public int Motor1InPosition;
    public int Motor2InPosition;
    public int Motor3InPosition;
    public int Motor4InPosition;
    public int Motor5InPosition;
}

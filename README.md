Command to setup on a new computer after cloning the repo:
uv run .\src\ucl_open_auditory_vr_corridor\regenerate.py


Command to run at the start of *every* new session:
uv run gen-sessions\gen_session.py

Then enter: animal ID and modality (A/V/AV) when prompted.

Then confirm the automatically selected shaping stage, or manually override it. At stages 5 and 6 (any stage for TEST animals) you are then asked whether this is an optogenetics session; press Enter for no (see Optogenetics (Zapit) below).

Shaping Stages:

Track length is picked at random each trial: 80, 100 or 120cm (cut to an eighth, 10, 12.5 or 15cm, in stages 1 and 2, to encourage running).

Stage 1: slow frequency drift, no punishments, infinite licks permitted, trial ends whenever reward frequency is reached.

Stage 2: same as stage 1 but without frequency drift - mouse must run up until the reward frequency to get reward (note: licking not required).

Stage 3: Mouse must now lick within the reward zone to get a reward. No lick = no reward. Punishment if they run to end of track.

Stage 4: Same as above, but now mice also punished for excess licking or being slow. Punished on 8th lick before the reward zone AND punished if not ended trial within 12 seconds, AND reward zone shrinks so that there is now also a small 'error zone' after the reward zone.

Stage 5: Same as above, but punished for 5th wrong lick.

Stage 6: Same as stage 5, but 16% of trials are 'truncated' - the cue (tone and grating) switches off part way along the track, at 0.4 or 0.6 of the sweep (8% of trials each). Everything else about the trial is unchanged, so the mouse has to keep going and find the reward zone without the cue. Truncated trials are rewarded as normal.

Stage 6 is never reached automatically - the experimenter must enter it manually at the shaping stage prompt. Once an animal is on stage 6 it stays there until experimenter manually changes the stage again during the shaping stage prompt.

Optogenetics (Zapit):

Optogenetics is switched on for one session at a time in gen_session.py - it is not a shaping stage. The "Optogenetics (Zapit)?" question is only asked at shaping stages 5 and 6 (at any stage for TEST animals, to test the rig). Answer y and give the Zapit stimulus config file. The default offered is the file of the previous session generated on this PC, and only if that session had optogenetics on; after a session without optogenetics there is no default. If you answered y by mistake, answer n at the file prompt and the session runs without optogenetics. The file's stimLocations01, stimLocations02, ... entries are the conditions, and gen_session refuses the file unless they are numbered 1 to N with no gaps or repeats, since Zapit numbers conditions by position, and unless every condition has an offRampDownDuration_ms longer than one stimulus cycle (1000 / stimModulationFreqHz ms, 25 ms at 40 Hz; Zapit's usual 250 ms is fine), since with a shorter ramp Zapit's stop leaves its DAQ running. Stimulation sites, laser power and ramp-down are set in that file, not in Bonsai.

Before starting Bonsai, start Zapit (MATLAB) with the same file loaded and tcpServer.enable: true in its settings file. Bonsai stops at startup if it cannot reach Zapit, if Zapit has no stimulus config or a different number of conditions loaded, or if the session's config file breaks the numbering or ramp-down rule above. Sessions without optogenetics never connect to Zapit and write no Zapit files.

Every trial of an optogenetics session sends Zapit a stimulus, so galvo noise and masking light are the same on every trial. The first 20 trials are sham trials (a real condition with the laser off); after that each trial is laser-on with probability 0.4 and sham otherwise. The laser-on trials are shared equally by every condition in the Zapit stimulus config, so a laser-on control site (a location where no effect is expected, which controls for the animal seeing the light) is simply one more condition: 5 conditions at 0.4, one of them a laser-on control site, gives each 8%. Sham and laser-on trials are armed, started and stopped the same way, and the stimulus starts 100 ms (lead_time) before the first tone pip on every trial, so trial timing does not give the laser-on trials away. Zapit only ever gets continuous stimuli (it ignores a stop for fixed-duration ones), and Bonsai stops the stimulus at the trial outcome, or 12.5 s (stim_duration) after onset if that comes first. At stages 4-6 that cap is just longer than the longest trial (the 12 s timeout starts at most lead_time after onset), so it does not end a stimulus early; stages 1-3 (TEST animals only) have no timeout, so there any trial longer than 12.5 s loses its stimulus at the cap. stim_duration must be at least 12 s + lead_time + 0.25 s: if you raise lead_time above 0.25 s in task.py, raise stim_duration too, or gen_session and Bonsai refuse the settings. If a trial ever ends without reaching its stop, Bonsai sends Zapit a StopStimulus at the next ITI start and prints "Zapit: the previous trial ended without a StopStimulus ..." in the console; that trial has no TrialLog row. Any refused stimulus stops the session, and Bonsai sends Zapit a stop when the workflow stops. These settings are in task.py under OptogeneticsConfig.

If Bonsai dies during an optogenetics session (a crash, the PC losing power, or ending Bonsai in Task Manager), nothing tells Zapit, and a continuous stimulus keeps playing until it is stopped: stop it in Zapit straight away (Stop in the Zapit GUI, or hZP.stopOptoStim in MATLAB), or close the laser shutter. Stopping the workflow, or an error that stops it, is fine: Bonsai then sends Zapit a StopStimulus itself.

An optogenetics session never changes the shaping stage. The next gen_session.py keeps the same stage and reports success separately for laser-on and control (laser-off) trials; laser-on trials never count toward a stage decision.

Each rig's Zapit settings are in src/Extensions/RigConfigs.cs (ZapitHost, ZapitPort, ZapitHardwareTriggered, ZapitTriggerPulseWidth; the pulse width is 5 ms by default and is written to the Behavior board in every session, with or without optogenetics). With ZapitHardwareTriggered = true, Zapit is armed with the trial's stimulus as soon as the ITI ends, the trial waits for Zapit to confirm (a few tens of ms added to the ITI of every trial, sham or laser-on), and a pulse on behaviour board DO3 at the first beep starts it, so onset is exact on the Harp clock. This needs DO3 cabled to the Zapit DAQ trigger input. With false (software mode), Bonsai sends the stimulus at the first beep and Zapit starts it when the command arrives, a few tens of ms late and with no onset timestamp. Software mode is only for TEST animals and bench tests: Bonsai refuses to start an optogenetics session with any other animal unless the rig is hardware-triggered.

What is logged: the TrialLog has OptogeneticEnabled (laser-on trial), OptogeneticCondition (0 in sessions without optogenetics), OptoOnsetHarp and OptoOffsetHarp (Harp times Bonsai sent the DO3 pulse, or the StartStimulus when not hardware triggered, and the StopStimulus; NaN in sessions without optogenetics). Optogenetics sessions also write Zapit.csv and ZapitStimConfigCopy.yml, a copy of the Zapit stimulus config as it was at the start of the session; sessions without optogenetics write neither. Zapit.csv has Zapit's replies with their Harp time of arrival (Command 1 is StartStimulus, 0 StopStimulus, 2 and 4 the startup checks), with three gaps: the startup rows can be missing or have a NaN or late HarpTime, an error reply that stopped the session can be missing (Bonsai's error message has it), and the StopStimulus Bonsai sends when the workflow stops is never logged, so the last StartStimulus row can have no StopStimulus row after it. The RigLog has the rig's Zapit settings. With hardware triggering, each DO3 pulse is also in the Behavior board's Harp binary log, as an OutputSet (register 34) write with DO3 set - the exact onset.

To test without an animal: src/ZapitTest.bonsai checks the connection to Zapit on its own, with no rig hardware, and for a whole session run gen_session.py with a TEST animal, shaping stage 5 and optogenetics on, then main.bonsai on the rig as usual. Zapit's simulated mode (start_zapit('simulated', true), then hZP.applyUnityStereotaxicCalib, then load a stimulus config) checks the connection and commands, but its simulated DAQ stops every stimulus and never refuses a new one, so it cannot show stop or fixed-duration problems; only Zapit's real DAQ can. Without the rig at all, the simulation kit on branch mac-bonsai-sim (sim/README.md there) runs main.bonsai headless on a Mac or PC with simulated devices, a simulated mouse and a mock Zapit server that follows the real DAQ's behaviour. The step-by-step checks on the rig itself are in docs/zapit-rig-test.md.

Tests:

uv run --with pytest pytest tests

They cover gen_session's optogenetics prompt and its shaping stage rules, and check that the optogenetics settings in task.py, the JSON schema in src/DataSchemas and the C# class in src/Extensions/UclOpenAuditoryVrCorridor.Generated.cs agree.

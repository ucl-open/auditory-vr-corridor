Command to setup on a new computer after cloning the repo:
uv run .\src\ucl_open_auditory_vr_corridor\regenerate.py


Command to run at the start of *every* new session:
uv run gen-sessions\gen_session.py

Then enter: animal ID and modality (A/V/AV) when prompted.

Then confirm the automatically selected shaping stage, or manually override it.

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

Optogenetics is switched on for one session at a time in gen_session.py - it is not a shaping stage. The "Optogenetics (Zapit)?" question is only asked at shaping stages 5 and 6 (at any stage for TEST animals, to test the rig). Answer y and give the Zapit stimulus config file (the last one used on this PC is the default). Its stimLocations01, stimLocations02, ... entries are the conditions, and gen_session refuses the file unless they are numbered 1 to N with no gaps or repeats, since Zapit numbers conditions by position. Stimulation sites, laser power and ramp-down are set in that file, not in Bonsai.

Before starting Bonsai, start Zapit (MATLAB) with the same file loaded and tcpServer.enable: true in its settings file. Bonsai stops at startup if it cannot reach Zapit, or if Zapit has no stimulus config or a different number of conditions loaded. Sessions without optogenetics never connect to Zapit.

Every trial of an optogenetics session sends Zapit a stimulus, so galvo noise and masking light are the same on every trial. The first 20 trials are sham trials (a real condition with the laser off); after that each trial is laser-on with probability 0.4 and sham otherwise. The laser-on trials are shared equally by every condition in the Zapit stimulus config, so a laser-on control site (a location where no effect is expected, which controls for the animal seeing the light) is simply one more condition: 5 conditions at 0.4, one of them a laser-on control site, gives each 8%. Sham and laser-on trials are armed, started and stopped the same way, and the stimulus starts 100 ms before the first tone pip on every trial, so trial timing does not give the laser-on trials away. Zapit only ever gets continuous stimuli (it ignores a stop for fixed-duration ones), and Bonsai stops the stimulus at the trial outcome, or 12.5 s after onset if that comes first (a safety cap just longer than the longest trial). Any refused stimulus stops the session, and Bonsai sends Zapit a stop when the workflow stops. These settings are in task.py under OptogeneticsConfig.

An optogenetics session never changes the shaping stage. The next gen_session.py keeps the same stage and reports success separately for laser-on and control (laser-off) trials; laser-on trials never count toward a stage decision.

Each rig's Zapit settings are in src/Extensions/RigConfigs.cs (ZapitHost, ZapitPort, ZapitHardwareTriggered, ZapitTriggerPulseWidth). With ZapitHardwareTriggered = true, Zapit is armed with the trial's stimulus as soon as the ITI ends, the trial waits for Zapit to confirm (a few tens of ms, the same on every trial of the session), and a pulse on behaviour board DO3 at the first beep starts it, so onset is exact on the Harp clock. This needs DO3 cabled to the Zapit DAQ trigger input. With false (software mode), Bonsai sends the stimulus at the first beep and Zapit starts it when the command arrives, a few tens of ms late and with no onset timestamp. Software mode is only for TEST animals and bench tests: Bonsai refuses to start an optogenetics session with any other animal unless the rig is hardware-triggered.

What is logged: the TrialLog has OptogeneticEnabled (laser-on trial), OptogeneticCondition (0 in sessions without optogenetics), OptoOnsetHarp and OptoOffsetHarp (Harp times Bonsai sent the DO3 pulse, or the StartStimulus when not hardware triggered, and the StopStimulus; NaN in sessions without optogenetics). Zapit.csv has every reply from Zapit with its Harp time (Command 1 is StartStimulus, 0 StopStimulus, 2 and 4 the startup checks). The RigLog has the rig's Zapit settings. With hardware triggering, each DO3 pulse is also in the Behavior board's Harp binary log, as an OutputSet (register 34) write with DO3 set - the exact onset.

To test without the rig: src/ZapitTest.bonsai checks the connection to Zapit on its own, and for a whole session run gen_session.py with a TEST animal and optogenetics on, then main.bonsai as usual. Zapit's simulated mode (start_zapit('simulated', true), then hZP.applyUnityStereotaxicCalib, then load a stimulus config) checks the connection and commands, but its simulated DAQ stops every stimulus and never refuses a new one, so it cannot show stop or fixed-duration problems. A mock Zapit server that follows Zapit's real-DAQ code (stop ignored for a fixed-duration stimulus, a new stimulus refused while one is armed or playing) does. The step-by-step checks on the rig itself are in docs/zapit-rig-test.md.

Tests:

uv run --with pytest pytest tests

They cover gen_session's optogenetics prompt and its shaping stage rules, and check that the optogenetics settings in task.py, the JSON schema in src/DataSchemas and the C# class in src/Extensions/UclOpenAuditoryVrCorridor.Generated.cs agree.

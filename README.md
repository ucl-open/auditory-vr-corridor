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

The stimulation sites, laser power and ramp-down are set in a Zapit stimulus config, which is loaded in Zapit (MATLAB). Bonsai talks to Zapit over TCP (the Zapit client is copied from av-dome's zapit branches), reads the same config file to list its conditions, and on each stimulated trial asks Zapit for one of them.

To run an optogenetics session, answer y at the "Optogenetics (Zapit)?" prompt in gen_session.py and give the Zapit stimulus config (the last one used is the default). Then start Zapit with that config loaded, and tcpServer.enable: true in its settings file, before starting Bonsai. Bonsai stops at startup if it cannot reach Zapit or Zapit has no config loaded.

On a stimulated trial (75% of trials by default, set in task.py under OptogeneticsConfig) the laser comes on 100 ms before the first tone pip and is stopped at the trial outcome, or after 12 s at most. In an optogenetics session every trial, stimulated or not, has the same 100 ms before the cue, so the timing does not give the stimulated trials away.

Each rig's Zapit settings are in src/Extensions/RigConfigs.cs. With ZapitHardwareTriggered = false (the default) Zapit starts the laser when the command arrives, a few tens of ms late - fine for tests. Set it to true once behaviour board DO3 is cabled to the Zapit DAQ trigger input: Zapit is then armed during the ITI and a 5 ms pulse on DO3 fires the laser, so onset is exact on the Harp clock.

The TrialLog has OptogeneticEnabled, OptogeneticCondition and OptogeneticDuration for every trial. Zapit.csv has every reply from Zapit, and the RigLog has the rig's Zapit settings.

To test without the rig: start Zapit in simulated mode (start_zapit('simulated', true), then hZP.applyUnityStereotaxicCalib, then load a stim config). src/ZapitTest.bonsai checks the connection on its own. For a whole session, run gen_session.py with a TEST animal and optogenetics on, then main.bonsai as usual.

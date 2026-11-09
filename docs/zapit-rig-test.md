# Testing Zapit on the rig

How to check, step by step, that the corridor task drives Zapit correctly before the first optogenetics session with an animal. Do the
steps in order; each has a pass condition and assumes the previous one passed. Keep the laser shutter closed (or the laser power at
0 mW) until step 6.

Use a TEST animal ID (for example `TEST`) throughout, so nothing is logged with real data or pushed to the server.

## Before you start

- On the rig PC: `git fetch`, then `git status`. If `src/main.bonsai` shows as modified (Bonsai saved it after a session), run
  `git stash` first. Then `git checkout zapit-integration-v2`. `main` is not touched by this branch. Afterwards go back with
  `git checkout main` (and `git stash pop` if you stashed).
- Do not run `scripts/update_workflow_keep_rig_config.py` on this branch without `--ref origin/zapit-integration-v2`: by default it
  takes `main.bonsai` from `origin/main`, which would silently remove all the Zapit nodes.
- Zapit: `tcpServer.enable: true` in its settings YAML, restart Zapit, calibrate, and load the stimulus config you will use. Use the
  real DAQ, not `start_zapit('simulated', true)`: Zapit's simulated DAQ hides the behaviour these tests are for (a fixed-duration
  stimulus that StopStimulus cannot end).
- Zapit accepts one client at a time: close any other Zapit client (MATLAB, Python, another Bonsai).
- In `src/Extensions/RigConfigs.cs`, this rig's `ZapitHost` and `ZapitPort` (127.0.0.1 and 1488 when Zapit runs on the rig PC).
  Leave `ZapitHardwareTriggered = false` until step 4.

## Step 1: no optogenetics, nothing should change

Run `uv run gen-sessions\gen_session.py` with a TEST animal and answer N at the optogenetics prompt (at stages below 5 it is not
offered). Run `main.bonsai` for about 20 trials.

**Pass:** the task behaves exactly as on `main`; nothing appears in Zapit's MATLAB window; the TrialLog has four extra columns at the
end, `OptogeneticEnabled` False, `OptogeneticCondition` 0, `OptoOnsetHarp` and `OptoOffsetHarp` NaN.

## Step 2: connection, `src/ZapitTest.bonsai`

Open `src/ZapitTest.bonsai`, check Host and Port on the Zapit include, Start.

**Pass:** in the Bonsai console, in order: `IsStimConfigLoaded value=1`, `GetNumConditions value=N`, `StartStimulus value=1 laserOn=1`,
`GetState value=1`, `StopStimulus value=1`, then `GetState value=0` at 7 s. The last one is the important one: it shows StopStimulus
really ended the stimulus.

## Step 3: software-timed optogenetics session

`gen_session.py` again with the TEST animal, answer y and give the stimulus config file that is loaded in Zapit. Run `main.bonsai`
for at least 30 trials (the first 20 are warmup: galvos move but the laser stays off).

**Pass:**
- Bonsai does not stop. It stops on purpose, with a message saying why, if Zapit refuses a command or has a different number of
  conditions loaded from the file in the session JSON.
- `Zapit.csv`: one `Command 1` row per trial (`Value` = that trial's condition, `LaserOn` 1 on laser trials and 0 on sham trials), and
  one `Command 0` (StopStimulus) row per trial, at its outcome. `IsError` is False everywhere.
- TrialLog: `OptogeneticEnabled` and `OptogeneticCondition` match `Zapit.csv` trial by trial; `OptoOnsetHarp` is about the trial start
  and `OptoOffsetHarp` about the outcome.
- MATLAB window: no "Not ready to stimulate". The galvos move on every trial, laser or sham.

## Step 4: hardware-triggered (TTL) session

Cable behaviour board DO3 to the Zapit DAQ trigger input. Set `ZapitHardwareTriggered = true` for this rig in `RigConfigs.cs` and
repeat step 3. This is the only mode real animals can use: with any animal ID that does not start with TEST, Bonsai stops at
startup if the rig is in software mode.

**Pass:** as step 3, plus:
- every trial's StartStimulus reply arrives just after the ITI ends, a few tens of ms before beep 0 (Zapit arms, then waits for the TTL);
- the Behavior board log has one DO3 write per trial at beep 0, matching `OptoOnsetHarp` in the TrialLog;
- with the galvos visible or a laser monitor connected, the stimulus starts at the TTL, not at the command.

## Step 5: failure checks (each takes a minute)

- Load a stimulus config in Zapit with a different number of conditions and start a session: Bonsai stops at startup with
  "Zapit has N conditions loaded but the session's stimulus config ... has M".
- Close Zapit during a session: Bonsai stops with a Zapit connection error instead of carrying on.
- Stop Bonsai mid-trial in a hardware-triggered session: Zapit goes back to idle (the client sends StopStimulus when the workflow
  stops), and the next session's first trial arms normally.

Also worth one bench test on the real DAQ before animals, because it cannot be simulated: start a hardware-triggered session, stop
Bonsai in the short window after an arm and before beep 0 (or arm from MATLAB and send no TTL), then check in MATLAB that
`hZP.state` is idle and a new `hZP.sendSamples` arms normally. If Zapit is stuck, restart Zapit before the next session.

## If Bonsai crashes during an optogenetics session

Bonsai stops the stimulus at every outcome, and sends a final StopStimulus whenever the workflow stops, including on an error. If the
Bonsai process itself dies (a crash, the PC losing power, or killing it in Task Manager), nothing tells Zapit, and a continuous stimulus
keeps playing until it is stopped. Rule: if Bonsai dies during an optogenetics session, stop the stimulus in Zapit straight away (Stop
in the Zapit GUI, or `hZP.stopOptoStim` in MATLAB), or close the laser shutter. A permanent fix belongs in Zapit: its TCP server could
call stopOptoStim when its client disconnects (MATLAB tcpserver's ConnectionChangedFcn).

## Stimulus config rules Bonsai checks

`gen_session.py` refuses, and Bonsai stops at startup on, a Zapit stimulus config whose conditions are not numbered exactly 1 to N, or
in which any condition's `offRampDownDuration_ms` is not longer than one stimulus cycle (1000 / `stimModulationFreqHz` ms, 25 ms at
40 Hz). With a ramp that short, Zapit's stop writes zeros but leaves its DAQ running, so on a hardware-triggered rig the next trial
would start as soon as it is armed instead of at the TTL. Zapit's usual 250 ms ramp is fine. Bonsai also stops at startup if Zapit has
a different number of conditions loaded than the session's config file, and every optogenetics session saves a copy of that file
(`ZapitStimConfigCopy`) next to its logs.

## Step 6: laser on

With a power meter or photodiode at the stimulation site: laser trials reach the configured power, sham trials stay dark, onset follows
the TTL and offset follows the trial outcome (plus Zapit's ramp-down), and no trial stays lit past the 12.5 s cap. Optional but
recommended: feed the laser analog control signal from the Zapit DAQ into a free Behavior board analog input, so every session records
true laser onset and offset on the Harp clock.

## Which timestamp means what

- `OptoOnsetHarp`: Harp time when Bonsai sent the TTL (hardware) or the StartStimulus (software). Hardware mode: the DO3 write in the
  Behavior board log is the exact onset. Software mode: Zapit starts a few tens of ms later, untimestamped.
- `OptoOffsetHarp`: Harp time when Bonsai sent StopStimulus; the light then ramps down over the stimulus config's
  `offRampDownDuration_ms`.
- `Zapit.csv` `HarpTime`: when each reply arrived, not laser onset. `ServerDatenum` is the Zapit PC clock, only for matching Zapit's own
  log.
- `Zapit.csv` startup rows: Bonsai asks Zapit `IsStimConfigLoaded` (`Command 2`) and `GetNumConditions` (`Command 4`) as soon as it
  connects, which can be before the logger has started. So the `Command 2` row can be missing and the `Command 4` row's `HarpTime` can
  be NaN or late; use `ServerDatenum` for those two. The startup check itself does not depend on the log: Bonsai compares the
  condition count with the session's stimulus config and stops if they differ.

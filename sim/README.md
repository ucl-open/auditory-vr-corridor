# Headless Bonsai simulation of the task on macOS (`sim/`)

Runs the real task workflow (`src/main.bonsai`) on a Mac, without the rig: Bonsai's own engine (Bonsai.Core 2.9 under
Mono) loads and runs a copy of the workflow in which the hardware is replaced by simulated Harp devices and a
simulated mouse. The task logic, subjects, timing operators and loggers are the workflow's own, so a simulated session
produces the same TrialLog, StimulusLog, IntervalLog, Harp binary logs etc. as a rig session.

```bash
python3 sim/run.py --stage 5 --trials 20          # build if needed, make a test session, run 20 trials, summarise
python3 sim/run.py --stage 1 --trials 10 --check   # --check: exit 1 if the consistency checks fail (a test)
python3 sim/run.py --stage 6 --seconds 120 --speed 35 --p-miss 0.3
python3 sim/run.py --repo ../avc --stage 5 --trials 10 --opto   # another checkout; optogenetics vs the mock Zapit
```

Requirements: Mono 6.12 (`mono`, `csc`; the macOS package runs under Rosetta on Apple Silicon), python3 with `lxml`
(the anaconda python has it; `numpy`/`scipy`/`pandas` are used to generate the session waveforms with the repo's own
`gen-sessions/helpers.py`), and the Bonsai packages in the NuGet cache `~/.nuget/packages` (restored once by any
`dotnet`/`nuget`/Bonsai setup). No network access is needed.

## What a run does

`sim/run.py` (one command):

1. **Build** (`sim/setup.sh`, automatic when needed, ~45 s): gathers the package DLLs into `sim/build/lib` (versions
   from `.bonsai/Bonsai.config`; the cache's closest version when it lacks the exact one, e.g. Bonsai.Core 2.9.0 for
   2.9.1), unzips the repo's `local_packages/UclOpen.*.nupkg`, builds the runner, the stand-ins in `sim/fakes`, compiles
   `src/Extensions/*.cs` into `Extensions.dll` (assembly name `Extensions`, as Bonsai's script compiler names it) and
   `sim/simext` into `SimExtensions.dll`, and extracts the packages' embedded workflows into `sim/build/resources`.
   It is rebuilt automatically when `src/Extensions/*.cs` (or the sim sources) change, or for another `--repo`.
2. **Run folder** (a new temp folder, or `--run-dir`), laid out like the repo so the workflow's relative paths resolve
   as on the rig (`../session-schemas/...`, `./waveforms/...`, `Extensions/...`):
   ```
   RUN/session-schemas/current-session/UclOpenAuditoryVrCorridorTaskLogic.json   <- sim/make_session.py
   RUN/src/main.bonsai           <- sim/make_harness.py (the simulation copy of src/main.bonsai)
   RUN/src/HARNESS_CHANGES.txt   <- every node removed/replaced/rewritten and why
   RUN/src/SimIncludes/          <- sim copies of the device / logging includes
   RUN/src/Extensions/           <- copy of src/Extensions (Zapit.bonsai etc., paths fixed)
   RUN/src/waveforms/            <- this session's waveforms, written like gen_session.py does
   RUN/Logs/sub-TEST/ses-SIM1_date-.../   <- the session's logs (LoggingRootPath of the test session)
   RUN/sim-logs/SimMouse.csv, SimBehaviorBoard.csv   <- what the simulated mouse and board did
   RUN/bonsai_console.log        <- the workflow's console output (Monitor WriteLines etc.)
   ```
   The repo's own `src/` and `session-schemas/current-session/` are never written.
3. **Session** (`sim/make_session.py`): a `TEST` animal session (stage, modality, session id from the options) built
   with the repo's pydantic models (`src/ucl_open_auditory_vr_corridor/task.py`), so defaults, validators and derived
   reward windows are exactly what `gen_session.py` writes. Outside the project's uv environment swc-aeon is missing;
   then only its `BaseSchema` is replaced by an equivalent (pydantic, camelCase aliases). If the models cannot be
   imported at all a template is used (and the output says so).
4. **Mock Zapit** (`--opto`, branches with Zapit only): `sim/mock_zapit_server.py` on a free port; RigConfigs points
   ZapitHost/ZapitPort at it and the simulated board sends DO3 TTLs to its trigger port (port + 1).
5. **Run** `mono sim/build/bin/BonsaiRun.exe RUN/src/main.bonsai --lib sim/build/lib` until `--trials N` trials have
   ended (default 20), `--seconds T`, or Ctrl+C. Each TrialLog row is echoed as it is written.
6. **Summary** (`sim/summarize.py RUN`): per-trial table (mouse plan, EndReason, rewarded/punished, licks, ITI, cue
   latency, start-to-outcome time), outcome counts, and consistency checks (Harp event order, the task's LickCount vs
   the licks the mouse made, valve openings vs rewarded trials, mouse plan vs outcome).

## How it works

**Runner** (`sim/runner/BonsaiRun.cs`): loads the workflow with `WorkflowBuilder.Serializer`, `BuildObservable()`,
subscribes, waits, then disposes (which flushes and closes every logger), like `Bonsai.exe --no-editor`. Every DLL in
`--lib` is loaded up front and references resolve from there (Bonsai's `Packages` folder). Build/runtime errors print
the node path (e.g. `/TaskLogic[11]/BeepTimer[0]/...`). Exit codes: 0 ok, 1 runtime error, 2 build error, 3 load
error, 5 deadlock (see Limits).

**Harness** (`sim/make_harness.py`, lxml, keeps the file's namespace prefixes): matches nodes by name, type and
include path, never by index, so it works on branches that add nodes (Zapit). Kept: Params (incl. InitVars),
ComputeRewardZone, LickCounter, TaskState, TaskLogic, the top-level virtual-position nodes, SessionStats,
EngagementStats, Logging (TaskSchemaLogger, TrialLogger, LogParams, HarpClock, TrialEventTimes, IntervalLogger,
LogController, RigLogger, the copy loggers, any ZapitLogger), the RunningWheel conversion, the PulseController include
and any Zapit group (it talks TCP, so it runs against the mock). Removed: TimestampGenerator, steppers, cameras,
camera trigger and logging, GUI and GUI Callbacks, InitMixer, the BonVision window and grating drawing (the
GratingSpatialFrequency/GratingOpacity subjects TaskLogic writes to stay), EventLogger, LogHarpDevice loggers of
devices that no longer exist, and anything left publishing to subjects only removed parts declared. Windows paths are
fixed (`Extensions\X.bonsai` includes, `{0}\{1}\{2}.{3}` log-name formats, relative `waveforms\...` file names).
`HARNESS_CHANGES.txt` lists every change; warnings flag subjects nothing declares any more.

**Simulated hardware** (`sim/simext`, namespace `AvcSim`):

| Real | Simulation | Behaviour |
|---|---|---|
| Behavior board (`UclOpen.Devices:BehaviorBoard.BehaviorBoard.bonsai`, Harp.Behavior Device) | same include with `SimBehaviorBoard` in place of the Device | AnalogData (address 44) at 1 kHz with Harp timestamps, Encoder = 16-bit wrapping quadrature count from the mouse's speed (CountsPerRev and wheel diameter read from the workflow's TicksToCentimeters: 4096, 75 mm), so the workflow's own RunningWheel and HarpClock run unchanged; 1 Hz TimestampSeconds heartbeat; every Write echoed as a timestamped Write; EncoderReset zeroes the encoder; OutputSet DO1/DO2 = reward valve (logged); OutputSet DO3 = Zapit TTL (one byte to the mock's trigger port) |
| LicketySplit (`UclOpen.Devices:LicketySplit.bonsai`) | same include with `SimLicketySplit` | LickState (address 32) events Channel0/None on each lick contact of the mouse, so the include's own Parse/Equal produce `LickStateLeft` (true = lick start, false = end) exactly as on the rig; threshold writes echoed |
| the mouse | `SimMouse` (top-level `Simulation` group) | runs at `--speed` cm/s (±`--speed-jitter` per trial) and licks according to the task's own `MouseVirtualPosition` and `RewardFloorVirtualPos..RewardCeilVirtualPos`. Per trial: Hit (lick `--licks` times, 8 Hz, 150 ms after passing 20% of the zone; slows to half speed while licking in the zone), Miss (`--p-miss`, runs through), NoLick (`--p-nolick`), plus a bout of `--wrong-licks` licks before the zone with `--p-wrong` (8 licks reach the stage 4-6 punished-lick limits). `--seed` makes it reproducible |
| RigConfigs (machine-name switch) | `SimRigConfigs` | a `RigSpecificConfigs` filled by reflection (so new fields in RigConfigs.cs are picked up): COM ports/serials "SIM", ValveOpenTime 80 ms (`--valve-ms`), Zapit host 127.0.0.1, ZapitPort = the mock, ZapitHardwareTriggered (`--zapit-sw` = false), ZapitTriggerPulseWidth 5; unknown fields are listed |
| GUI Start button | `Delay(0.5 s)` after `WaveformDict`, then `PublishSubject(StartSession)` | the session starts as soon as the waveforms are loaded |
| — | `StopAfterTrials` | counts `TrialEnded` = true (when TrialLogger writes a row) and stops the runner cleanly 1 s later |

All simulated devices share one Harp clock (starts at 1000.000 s).

**Stand-ins for packages that cannot load here** (`sim/fakes`, same assembly names, namespaces, type names, enum
types and XML properties, so XmlSerializer and property mappings work unchanged):

* `OpenCV.Net` - the real one P/Invokes OpenCV 2.4.13 Windows DLLs. `Mat` here has rows/cols/depth/channels and no data.
* `Bonsai.Dsp` - MatrixReader (reads the file size, emits shape-only buffers, paced at SampleRate like the real one, so
  `WaveformDict` is ready after NFreqBins x 50 ms as on the rig), FunctionGenerator (paced like the real one: the
  reward sound's 50 buffers take 0.5 s), Rescale (real arithmetic on doubles: BonVision ParameterRange ITIs and track
  lengths), Tile, ConvertScale, Difference (real first difference on doubles: the wheel), MatrixWriter (writes byte
  arrays for real: the Harp binary logs).
* `Bonsai.Audio` - AudioReader (reads the WAV header for real, emits a shape-only buffer; the error tone) and
  AudioPlayback (only in disabled nodes; passes buffers through).

Everything else is the real package (Bonsai.Core/System/Scripting.Expressions, Bonsai.Harp, Harp.Behavior,
LicketySplit, Bonsai.Numerics + MathNet, UclOpen.*, BonVision only for its embedded ParameterRange workflow).

## Limits

* **No audio, video or projector.** Sound and grating buffers flow through the workflow with the right shapes and
  timing but contain nothing; nothing is played or drawn. Cameras, steppers and the TimestampGenerator are not
  simulated. The GUI does not exist (StartSession is automatic).
* **Mac wall-clock timing.** Bonsai timers run in real time on this Mac, so a session takes as long as on the rig
  (about 8 s per trial at 25 cm/s; raise `--speed` for shorter trials). Mono runs under Rosetta here: the workflow
  takes about 100 us per 1 kHz Harp sample (the summary prints it), so the Harp thread is about 10% busy; Windows
  .NET on the rig is several times faster. Timing jitter of a few ms is normal.
* **Threads: `--threads serial` (default) or `--threads rig`.** The simulated board emits on its own thread (like the
  Harp serial-port thread), the mouse licks from another, and Rx timers (Delay, Timer, Throttle, ...) fire on
  thread-pool threads. With `rig` they all run freely, exactly like Bonsai on Windows, so lock-order races inside the
  workflow can happen - and because Mono under Rosetta is slower, they happen more often than on the rig: main.bonsai
  deadlocked in 2 of ~45 trial starts here (see "Known workflow issue" below). With `serial` (the default, for
  functional testing) the runner wraps every Rx timer/thread-pool callback in one global lock that the simulated
  devices also take for each event, so those threads take turns between events and cannot deadlock each other; the
  task logic is unchanged. Threads Rx starts itself (the HarpBeat `ObserveOn(NewThreadScheduler)`, sound generators,
  file writers) are not included. The cost: while a long callback runs (e.g. a trial ending), the board waits and then
  catches up, so samples can be emitted tens of ms late (their Harp timestamps stay exact; the board reports how late).
  In both modes a stall is detected (no Harp sample processed for 5 s): all thread stacks are printed to
  `bonsai_console.log`, the run exits with code 5, and the logs are complete up to that point.
* Only the Bonsai.Dsp/Audio/OpenCV.Net nodes main.bonsai uses are faked. A workflow using another one fails to load
  with "The specified type was not recognized" - add it to `sim/fakes` (see below).
* Not checked here: the Windows Bonsai editor, visualizers, real device firmware behaviour (register dumps, Read
  replies), audio latency, `Bonsai.Mixer` (InitMixer is removed; an older branch that used the mixer inside TaskLogic
  would need a Mixer stand-in).

### Known workflow issue found with the simulation (main.bonsai, not caused by the simulation)

`TrialDistFloor` is written from two threads: by `CalcVirtualPos` on the Harp thread (1 kHz, inside the
`WithLatestFrom(TrialDistance, TrialDistFloor)` that reads it) and by the BeepTimer's trial-start resets on a timer
thread (`DoubleProperty(0) -> MulticastSubject(TrialDistFloor)` when the BeepTimer Defer resubscribes, and after
FinishedITI). Rx calls subscribers while holding the subject's lock, and WithLatestFrom holds its own gate while it
forwards: the timer thread takes the subject lock then waits for the WithLatestFrom gate, the Harp thread holds that
gate and waits for the subject lock - a deadlock, after which the whole workflow (and Bonsai's stop) hangs. The
thread dump in `bonsai_console.log` shows exactly this (`ReplaySubject.OnNext` vs `Sample.OnNext`). On the rig it can
only happen when a trial starts while a Harp sample is between those two nodes, so it is rare, but it is a real hang
waiting to happen; writing `TrialDistFloor` only from the Harp-thread chain (or not feeding it back into its own
`WithLatestFrom`) would remove it.

## Options worth knowing

```
python3 sim/run.py -h                      all options
  --stage N --modality A|V|AV --animal TEST --session-id SIM1
  --trials N | --seconds T                 stop condition (default 20 trials); --max-seconds safety timeout
  --speed 25 --speed-jitter 0.15 --licks 4 --p-wrong 0.1 --wrong-licks 8 --p-miss 0.1 --p-nolick 0.05 --seed -1
  --valve-ms 80                            RigConfigs ValveOpenTime
  --threads serial|rig                     serialized callbacks (default) or free-running threads as on the rig
  --opto [--zapit-sw] [--daq real|simulated] [--zapit-conditions 4] [--stim-probability ..] [--warmup-trials ..]
  --repo PATH --workflow FILE              simulate another checkout / workflow
  --run-dir DIR --check --verbose --rebuild
python3 sim/summarize.py RUN [--check]     summary of an existing run folder
python3 sim/make_harness.py --repo . --out /tmp/x/src    just the harness (see --help)
python3 sim/make_session.py --repo . --out FILE.json --logs DIR --stage 5
bash sim/setup.sh [--repo PATH]            rebuild the kit
```

Optogenetics: `--opto` needs a branch whose `task.py` has `OptogeneticsConfig` and whose workflow has the Zapit nodes
(main has neither). make_session writes a test Zapit stimulus config with `--zapit-conditions` conditions
(`stimLocations01..N`) unless `--zapit-config` is given; the mock server is started with the same number of
conditions, `--daq real|simulated` behaviour, and the board's DO3 TTLs go to its trigger port. The summary reads
`Zapit.csv` if the workflow writes one.

## How to add a test

* **Whole-session tests**: `python3 sim/run.py ... --check` returns non-zero when a check fails, so a test is one
  command, e.g. stage 5 with only hits must reward every trial:
  `python3 sim/run.py --stage 5 --trials 10 --p-wrong 0 --p-miss 0 --p-nolick 0 --seed 1 --check`.
  Add checks in `sim/summarize.py` (`summarize()` has the TrialLog rows, the mouse's plans and licks, the board's
  valve/TTL events and `Zapit.csv`); `expected_outcome()` encodes which EndReason each mouse plan must give per stage.
* **Device-level tests**: `sim/tests/test_board_ttl.py` runs a tiny workflow (no task logic) against the mock Zapit
  server and checks the DO3 TTL and 1 kHz AnalogData. Copy it for other device behaviour.
* **A new hardware node in main.bonsai**: if it cannot run here, add a rule to `sim/make_harness.py` (by group name or
  include path) or a simulated device to `sim/simext` (reuse the original include and swap only the Device node, like
  `SIM_DEVICE_INCLUDES`).
* **A new Bonsai.Dsp/Audio node**: add the class to `sim/fakes/...` with the real type name, properties and
  Process/Generate overloads (dump the real API from the NuGet cache to copy them), then `bash sim/setup.sh`.
* **A new RigConfigs field**: picked up automatically with a default; give it a test value in
  `sim/simext/SimRigConfigs.cs` `ValueFor`.

## Files

```
sim/run.py              one command: build, session, harness, mock Zapit, run, summary
sim/setup.sh            builds sim/build (idempotent)
sim/make_harness.py     main.bonsai -> simulation copy (+ HARNESS_CHANGES.txt)
sim/make_session.py     test session JSON + waveforms
sim/summarize.py        summary and checks from a run's logs
sim/mock_zapit_server.py  mock Zapit TCP server (+ trigger port = port + 1)
sim/runner/BonsaiRun.cs   headless Bonsai runner for Mono
sim/fakes/              OpenCV.Net, Bonsai.Dsp, Bonsai.Audio stand-ins
sim/simext/             SimBehaviorBoard, SimLicketySplit, SimMouse, SimRigConfigs, StopAfterTrials, SimWorld
sim/tools/              gather_libs.py (DLLs from the NuGet cache), ExtractResources.cs (embedded workflows)
sim/tests/              device-level tests
```

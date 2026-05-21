Command to setup on a new computer after cloning the repo:
uv run .\src\ucl_open_auditory_vr_corridor\regenerate.py


Command to run at the start of *every* new session:
uv run gen-sessions\gen_session.py

Then enter: animal ID, session name, modality (A/V/AV) when prompted.

Shaping Stages:

Stage 1: slow frequency drift, no punishments, infinite licks permitted, trial ends whenever reward frequency is reached.
Stage 2: same as stage 1 but without frequency drift - mouse must run up until the reward frequency to get reward (note: licking not required).
Stage 3: Mouse must now lick within the reward zone to get a reward. No lick = no reward. Punishment if they run to end of track.
Stage 4: Same as above, but now mice also punished for excess licking or being slow. Punished on 5th lick before the reward zone AND punished if not ended trial within 10 seconds.
Stage 5: Same as above, but mice punished for 4th wrong lick outside reward zone, AND reward zone shrinks so that there is now also a small 'error zone' after the reward zone.
Stage 6: Same as above, but punished for 3rd wrong lick + reward zone even smaller.
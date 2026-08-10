"""
Updates src/main.bonsai to the latest version on the remote, while keeping this computer's
rig-specific settings: hardware addresses (COM ports, camera serials, audio devices), file
locations (projector mesh map, gamma table, repo paths) and physical calibrations (reward
valve duration, spout motor positions).

Those settings belong to one rig but live inside main.bonsai, which is shared between rigs, so
pulling the file wholesale would point this computer at another rig's hardware and calibration.
This script takes the incoming workflow and puts this computer's values back into it.

Usage, from the repo root:

    git fetch origin
    python scripts/update_workflow_keep_rig_config.py --dry-run   # review first
    python scripts/update_workflow_keep_rig_config.py             # apply

IMPORTANT: the list below is a denylist - it protects the settings we knew to look for. Read the
"REVIEW" section it prints before trusting a run on a rig it has not been used on, and check the
saved main.bonsai.bak afterwards:

    git diff --no-index src/main.bonsai.bak src/main.bonsai
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

WORKFLOW = Path("src/main.bonsai")

# Elements whose values belong to this computer, not to the shared workflow. Values are matched
# up by position, which is safe because these are device declarations: a workflow change adds or
# removes task logic, not rig hardware. A count mismatch means the hardware set really has
# changed, so we stop rather than pair the wrong values up.
RIG_SPECIFIC_TAGS = [
    "PortName",           # Behavior board and LicketySplit serial ports
    "harp:PortName",      # TimestampGenerator and StepperDriver serial ports
    "spk:SerialNumber",   # Spinnaker camera serial numbers
    "al:DeviceName",      # Audio playback device
    "p9:DeviceName",      # Mixer output device
    "gl:DisplayDevice",   # Which display the projector is on
    "FileName",           # Projector mesh map. Unprefixed on purpose - this does NOT match
                          # cv:FileName / io:FileName / al:FileName, which are different things.
    "GammaLut",           # Projector gamma lookup bitmap
    "io:Path",            # Session JSON that Bonsai reads at startup (depends on where the repo lives)
    "al:FileName",        # Error tone wav (depends on where the repo lives)
    "PulseDO1",           # Reward valve open duration in ms. Calibrated per rig: the same duration
    "PulseDO2",           # gives a different volume on a different valve, tubing and water column.
    "PulseDO3",
]

# Settings that cannot be found by tag name, because they are plain <Value> elements inside
# IntProperty nodes and <Value> appears hundreds of times in the file. These are physical
# calibrations - where each spout sits relative to the animal on this rig.
#
# The pattern spells out the whole annotation-then-IntProperty structure rather than skipping
# ahead from the annotation with .*?, because each Motor{n}_IN_position annotation appears TWICE:
# once above a SubscribeSubject that reads the position, and once above the IntProperty that
# actually holds it. A loose pattern anchors on the first and runs on into a different motor's
# value.
RIG_SPECIFIC_ANCHORED = [
    (f"Motor{n}_IN_position", re.compile(
        rf'(<Name>Motor{n}_IN_position</Name>\s*'
        rf'<Text><!\[CDATA\[Motor{n}_IN_position\]\]></Text>\s*'
        rf'</Expression>\s*'
        rf'<Expression xsi:type="Combinator">\s*'
        rf'<Combinator xsi:type="IntProperty">\s*'
        rf'<Value>)([^<]*)(</Value>)'))
    for n in range(1, 6)
]

# Deliberately NOT preserved: cv:FileName, io:FileName, p7:Path and p8:Path. Those are log
# *outputs* - Bonsai rewrites them from PathPrefix on every run and saves whatever the last
# session used back into the file. Carrying them across would just move one rig's stale session
# paths onto another. dsp:Path is left alone too, being relative and so the same on every rig.

# Lines matching these are worth a human look if they change and were not preserved above: they
# are the shapes a rig-specific setting tends to take.
REVIEW_HINTS = re.compile(
    r"<Value>|PortName|SerialNumber|DeviceName|FileName|GammaLut|Pulse|Exposure|Frequency|Path>"
)
# ...except these, which are known churn rewritten on every run.
REVIEW_IGNORE = re.compile(r"cv:FileName|io:FileName|p7:Path|p8:Path|gui:Text|<io:Suffix>")


def values_of(text, tag):
    """Every value of <tag>...</tag>, in document order."""
    return re.findall(rf"<{re.escape(tag)}>([^<]*)</{re.escape(tag)}>", text)


def apply_values(text, tag, values):
    """Replace the values of <tag>...</tag> in document order."""
    it = iter(values)
    return re.sub(rf"(<{re.escape(tag)}>)([^<]*)(</{re.escape(tag)}>)",
                  lambda m: m.group(1) + next(it) + m.group(3), text)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", default="origin/main", help="Git ref to take the workflow from (default: origin/main)")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing anything")
    args = parser.parse_args()

    if not WORKFLOW.exists():
        sys.exit(f"{WORKFLOW} not found - run this from the repo root.")

    local = WORKFLOW.read_text(encoding="utf-8-sig")
    try:
        # Read as bytes and decode explicitly: the workflow is UTF-8 and would otherwise be
        # decoded with the console codepage, which fails on Windows.
        incoming = subprocess.run(["git", "show", f"{args.ref}:{WORKFLOW.as_posix()}"],
                                  capture_output=True, check=True).stdout.decode("utf-8-sig")
    except subprocess.CalledProcessError as e:
        sys.exit(f"Could not read {WORKFLOW} from {args.ref} - did you run 'git fetch origin'?\n"
                 f"{e.stderr.decode('utf-8', errors='replace')}")

    # Check the two versions declare the same hardware before pairing anything up
    for tag in RIG_SPECIFIC_TAGS:
        mine, theirs = values_of(local, tag), values_of(incoming, tag)
        if len(mine) != len(theirs):
            sys.exit(f"Refusing to update: this computer has {len(mine)} <{tag}> entries but {args.ref} has "
                     f"{len(theirs)}. The set of devices has changed, so the values cannot be matched up "
                     f"automatically - merge this one by hand.")

    merged, kept = incoming, []
    for tag in RIG_SPECIFIC_TAGS:
        mine, theirs = values_of(local, tag), values_of(incoming, tag)
        merged = apply_values(merged, tag, mine)
        kept += [f"  {tag}: {t}  ->  {m}" for m, t in zip(mine, theirs) if m != t]

    for label, pattern in RIG_SPECIFIC_ANCHORED:
        mine, theirs = pattern.search(local), pattern.search(merged)
        if mine is None or theirs is None:
            sys.exit(f"Refusing to update: could not find {label} in "
                     f"{'this computer' if mine is None else args.ref}'s workflow - merge this one by hand.")
        if mine.group(2) != theirs.group(2):
            kept.append(f"  {label}: {theirs.group(2)}  ->  {mine.group(2)}")
        merged = pattern.sub(lambda m: m.group(1) + mine.group(2) + m.group(3), merged, count=1)

    print(f"Updating {WORKFLOW} from {args.ref}\n")
    print("Rig settings restored to this computer's values:" if kept
          else "Rig settings are already identical - nothing to restore.")
    print("\n".join(kept))

    # Everything else that changes is workflow logic, which is what we want - but flag anything
    # that looks like it could be a rig setting this script does not know about.
    review = [ln.strip() for ln in set(local.splitlines()) - set(merged.splitlines())
              if REVIEW_HINTS.search(ln) and not REVIEW_IGNORE.search(ln)]
    print(f"\nREVIEW - {len(review)} setting-like line(s) on this computer will be replaced by "
          f"{args.ref}'s version.")
    if review:
        print("Check none of these are a calibration specific to this rig:")
        for ln in sorted(review)[:40]:
            print(f"  {ln[:150]}")
        if len(review) > 40:
            print(f"  ... and {len(review) - 40} more")

    if merged == local:
        print("\nWorkflow is already up to date. Nothing written.")
        return
    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    backup = WORKFLOW.with_suffix(".bonsai.bak")
    shutil.copy(WORKFLOW, backup)
    WORKFLOW.write_text(merged, encoding="utf-8-sig")
    print(f"\nUpdated {WORKFLOW} (previous version saved as {backup}).")
    print(f"Check what moved:  git diff --no-index {backup} {WORKFLOW}")
    print("Open it in Bonsai and check the devices connect before running an animal.")


if __name__ == "__main__":
    main()

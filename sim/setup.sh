#!/usr/bin/env bash
# Builds the headless Bonsai simulation kit for macOS (safe to re-run; it rebuilds everything under sim/build).
#
#   sim/setup.sh [--repo PATH] [--nuget DIR]
#
#   --repo   repo whose .bonsai/Bonsai.config, local_packages and src/Extensions/*.cs are used
#            (default: the repo containing this sim/ folder). Use it to simulate another checkout's workflow.
#   --nuget  NuGet package cache (default ~/.nuget/packages)
#
# Produces (all gitignored):
#   sim/build/lib/        Bonsai + package assemblies from the NuGet cache, the sim stand-ins (OpenCV.Net, Bonsai.Dsp,
#                         Bonsai.Audio), Extensions.dll (the repo's src/Extensions/*.cs) and SimExtensions.dll
#   sim/build/bin/        BonsaiRun.exe (headless runner) and ExtractResources.exe
#   sim/build/resources/  embedded .bonsai workflows of the UclOpen packages and BonVision (for patched include copies)
# Needs Mono (mono + csc) and python3.
set -euo pipefail

SIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$SIM_DIR/.." && pwd -P)"
NUGET="${HOME}/.nuget/packages"
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$(cd "$2" && pwd -P)"; shift 2 ;;
    --nuget) NUGET="$2"; shift 2 ;;
    -h|--help) awk 'NR > 1 && /^#/ { print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 64 ;;
  esac
done

BUILD="$SIM_DIR/build"
LIB="$BUILD/lib"
BIN="$BUILD/bin"
RES="$BUILD/resources"

for tool in mono csc python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: '$tool' not found (install Mono from mono-project.com, and python3)" >&2; exit 1; }
done

echo "== repo: $REPO"
rm -rf "$LIB" "$BIN" "$RES"
mkdir -p "$LIB" "$BIN" "$RES"

echo "== gathering assemblies (versions from .bonsai/Bonsai.config)"
python3 -I "$SIM_DIR/tools/gather_libs.py" "$REPO" "$LIB" --nuget "$NUGET"

CSC=(csc -nologo -noconfig -optimize+ -nowarn:618,612,1591,1701,1702,8019,0169,0414,0649
     -r:mscorlib.dll -r:System.dll -r:System.Core.dll -r:System.Xml.dll -r:System.Xml.Linq.dll
     -r:System.Runtime.Serialization.dll -r:System.ComponentModel.DataAnnotations.dll -r:System.Numerics.dll)
RX=(-r:"$LIB/System.Reactive.Core.dll" -r:"$LIB/System.Reactive.Interfaces.dll" -r:"$LIB/System.Reactive.Linq.dll"
    -r:"$LIB/System.Reactive.PlatformServices.dll")

echo "== building tools and the headless runner"
"${CSC[@]}" -target:exe -out:"$BIN/ExtractResources.exe" "$SIM_DIR/tools/ExtractResources.cs"
"${CSC[@]}" -target:exe -out:"$BIN/BonsaiRun.exe" "${RX[@]}" -r:"$LIB/Bonsai.Core.dll" "$SIM_DIR/runner/BonsaiRun.cs"

echo "== building stand-ins for packages that cannot load on macOS (sim/fakes)"
"${CSC[@]}" -target:library -out:"$LIB/OpenCV.Net.dll" "$SIM_DIR"/fakes/OpenCV.Net/*.cs
"${CSC[@]}" -target:library -out:"$LIB/Bonsai.Dsp.dll" "${RX[@]}" -r:"$LIB/Bonsai.Core.dll" -r:"$LIB/Bonsai.System.dll" \
  -r:"$LIB/OpenCV.Net.dll" "$SIM_DIR"/fakes/Bonsai.Dsp/*.cs
"${CSC[@]}" -target:library -out:"$LIB/Bonsai.Audio.dll" "${RX[@]}" -r:"$LIB/Bonsai.Core.dll" -r:"$LIB/OpenCV.Net.dll" \
  -r:"$LIB/OpenTK.dll" "$SIM_DIR"/fakes/Bonsai.Audio/*.cs

echo "== compiling src/Extensions/*.cs into Extensions.dll (assembly name 'Extensions', like Bonsai's script compiler)"
EXT_SRC=()
while IFS= read -r -d '' f; do EXT_SRC+=("$f"); done < <(find "$REPO/src/Extensions" -maxdepth 1 -name '*.cs' -print0 | sort -z)
if [ ${#EXT_SRC[@]} -eq 0 ]; then echo "ERROR: no .cs files in $REPO/src/Extensions" >&2; exit 1; fi
EXT_REFS=()
for dll in "$LIB"/*.dll; do EXT_REFS+=(-r:"$dll"); done
"${CSC[@]}" -target:library -out:"$LIB/Extensions.dll" "${EXT_REFS[@]}" "${EXT_SRC[@]}"
{
  echo "repo=$REPO"
  echo "sha=$(cat "${EXT_SRC[@]}" | shasum | cut -d' ' -f1)"
} > "$LIB/Extensions.stamp"

echo "== building SimExtensions.dll (simulated Behavior board, LicketySplit, mouse, rig configs)"
"${CSC[@]}" -target:library -out:"$LIB/SimExtensions.dll" "${RX[@]}" -r:"$LIB/Bonsai.Core.dll" -r:"$LIB/Bonsai.Harp.dll" \
  -r:"$LIB/Harp.Behavior.dll" -r:"$LIB/AllenNeuralDynamics.LicketySplit.dll" -r:"$LIB/Extensions.dll" "$SIM_DIR"/simext/*.cs

echo "== extracting embedded workflows"
mono "$BIN/ExtractResources.exe" "$RES" "$LIB"/UclOpen.*.dll "$LIB/BonVision.dll"

echo "== done: $(ls "$LIB"/*.dll | wc -l | tr -d ' ') assemblies in $LIB"
echo "   run a simulated session with: python3 $SIM_DIR/run.py --stage 5 --trials 20"

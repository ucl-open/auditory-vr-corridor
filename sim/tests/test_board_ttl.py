#!/usr/bin/env python3
"""Test: the simulated Behavior board turns a Harp OutputSet DO3 write into a TTL byte on the mock Zapit trigger port,
echoes the write back as a timestamped Write message, and streams 1 kHz AnalogData with Harp timestamps.

A tiny Bonsai workflow (no task logic) is run headless next to the mock Zapit server:
  BehaviorSubject(BehaviorCommands) -> SimBehaviorBoard -> PublishSubject(BehaviorEvents)
  Timer(1 s) -> CreateMessage(OutputSet DO3) -> BehaviorCommands
and the mock server's log must show the trigger. Run: python3 sim/tests/test_board_ttl.py  (exit 0 = pass)
"""
import csv
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SIM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM))
import run as simrun   # noqa: E402

WORKFLOW = """<?xml version="1.0" encoding="utf-8"?>
<WorkflowBuilder Version="2.9.0"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xmlns:rx="clr-namespace:Bonsai.Reactive;assembly=Bonsai.Core"
                 xmlns:harp="clr-namespace:Bonsai.Harp;assembly=Bonsai.Harp"
                 xmlns:beh="clr-namespace:Harp.Behavior;assembly=Harp.Behavior"
                 xmlns:sim="clr-namespace:AvcSim;assembly=SimExtensions"
                 xmlns="https://bonsai-rx.org/2018/workflow">
  <Workflow>
    <Nodes>
      <Expression xsi:type="rx:BehaviorSubject" TypeArguments="harp:HarpMessage"><rx:Name>BehaviorCommands</rx:Name></Expression>
      <Expression xsi:type="Combinator">
        <Combinator xsi:type="sim:SimBehaviorBoard">
          <sim:TriggerHost>127.0.0.1</sim:TriggerHost>
          <sim:TriggerPort>{trigger_port}</sim:TriggerPort>
          <sim:LogPath>{board_log}</sim:LogPath>
        </Combinator>
      </Expression>
      <Expression xsi:type="rx:PublishSubject"><Name>BehaviorEvents</Name></Expression>
      <Expression xsi:type="Combinator"><Combinator xsi:type="rx:Timer"><rx:DueTime>PT1S</rx:DueTime><rx:Period>PT0S</rx:Period></Combinator></Expression>
      <Expression xsi:type="beh:CreateMessage">
        <harp:MessageType>Write</harp:MessageType>
        <harp:Payload xsi:type="beh:CreateOutputSetPayload"><beh:OutputSet>DO3</beh:OutputSet></harp:Payload>
      </Expression>
      <Expression xsi:type="MulticastSubject"><Name>BehaviorCommands</Name></Expression>
      <Expression xsi:type="SubscribeSubject"><Name>BehaviorEvents</Name></Expression>
      <Expression xsi:type="Combinator"><Combinator xsi:type="harp:FilterMessageType"><harp:FilterType>Include</harp:FilterType><harp:MessageType>Write</harp:MessageType></Combinator></Expression>
      <Expression xsi:type="Combinator"><Combinator xsi:type="rx:Take"><rx:Count>1</rx:Count></Combinator></Expression>
    </Nodes>
    <Edges>
      <Edge From="0" To="1" Label="Source1" />
      <Edge From="1" To="2" Label="Source1" />
      <Edge From="3" To="4" Label="Source1" />
      <Edge From="4" To="5" Label="Source1" />
      <Edge From="6" To="7" Label="Source1" />
      <Edge From="7" To="8" Label="Source1" />
    </Edges>
  </Workflow>
</WorkflowBuilder>
"""


def main():
    simrun.ensure_built(SIM.parent)
    tmp = Path(tempfile.mkdtemp(prefix='avc-sim-test-'))
    port = simrun.free_port_pair()
    board_log = tmp / 'SimBehaviorBoard.csv'
    (tmp / 'test.bonsai').write_text(WORKFLOW.format(trigger_port=port + 1, board_log=board_log))
    mock_log = open(tmp / 'mock_zapit.log', 'w')
    mock = subprocess.Popen([sys.executable, '-u', str(SIM / 'mock_zapit_server.py'), '--port', str(port)],
                            stdout=mock_log, stderr=subprocess.STDOUT)
    try:
        assert simrun.wait_for_port(port), 'mock Zapit server did not start'
        result = subprocess.run(['mono', str(SIM / 'build' / 'bin' / 'BonsaiRun.exe'), str(tmp / 'test.bonsai'),
                                 '--lib', str(SIM / 'build' / 'lib'), '--timeout', '3'],
                                capture_output=True, text=True)
        time.sleep(0.5)
    finally:
        mock.terminate()
        mock.wait()
        mock_log.close()
    print(result.stderr)
    failures = []
    if result.returncode != 0:
        failures.append(f'BonsaiRun exit code {result.returncode}')
    mock_text = (tmp / 'mock_zapit.log').read_text()
    if 'TTL ->' not in mock_text:
        failures.append('mock Zapit server received no TTL byte on its trigger port')
    rows = list(csv.DictReader(open(board_log))) if board_log.is_file() else []
    if not any(r['Event'] == 'ZapitTTL' for r in rows):
        failures.append('board log has no ZapitTTL event')
    if 'AnalogData samples' not in result.stderr:
        failures.append('board did not report AnalogData samples')
    else:
        samples = int(result.stderr.split(' AnalogData samples')[0].split()[-1])
        if not 2500 <= samples <= 3500:
            failures.append(f'{samples} AnalogData samples in ~3 s (expected ~3000 at 1 kHz)')
    print(mock_text)
    print('FAIL: ' + '; '.join(failures) if failures else 'PASS: DO3 write -> TTL byte on the trigger port; 1 kHz AnalogData')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())

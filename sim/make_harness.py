#!/usr/bin/env python3
"""Make a headless simulation copy of a Bonsai workflow (src/main.bonsai) for sim/runner BonsaiRun on macOS.

The task logic is kept intact; hardware, GUI and display are replaced or removed. Nodes are matched by name, type and
include path (never by index), so the same script works on branches that add nodes (e.g. Zapit). Everything it changes
is listed in HARNESS_CHANGES.txt next to the output.

Kept as is: Params (incl. InitVars), ComputeRewardZone, LickCounter, TaskState, TaskLogic, the top-level
virtual-position nodes, SessionStats, EngagementStats, Logging (TaskSchemaLogger, TrialLogger, LogParams, HarpClock,
TrialEventTimes, IntervalLogger, LogController, RigLogger, copy loggers, any ZapitLogger), the RunningWheel conversion,
the PulseController include and any Zapit group.
Replaced:
  * Behavior board include  -> sim copy of UclOpen.Devices BehaviorBoard.bonsai with AvcSim.SimBehaviorBoard (1 kHz
                               AnalogData + encoder driven by the sim mouse, write echoes, valve/TTL handling)
  * LicketySplit include    -> sim copy of UclOpen.Devices LicketySplit.bonsai with AvcSim.SimLicketySplit (lick
                               events from the sim mouse; the include's own Parse/Equal makes LickStateLeft)
  * RigConfigs node (Params)-> AvcSim.SimRigConfigs (test values)
  * GUI Start button        -> StartSession published automatically once WaveformDict is ready
  * LogController / LogHarpDevice includes -> local copies with '/' path separators
Removed: Devices/TimestampGenerator, StepperDriver, Cameras, CameraTriggerController, GUI, GUI Callbacks, InitMixer,
BonVision window/resources and grating drawing (the GratingSpatialFrequency/GratingOpacity subjects stay), camera
logging, LogHarpDevice loggers of devices that no longer exist, EventLogger, and anything left publishing to subjects
that only removed parts declared.
Added: a top-level 'Simulation' group with AvcSim.SimMouse, the automatic StartSession and AvcSim.StopAfterTrials.
Rewritten: Windows backslash paths (Extensions\\X.bonsai includes, log file name Format strings, relative FileNames).

Usage: make_harness.py --repo REPO --out RUN/src [--workflow FILE] [options]   (see --help)
"""
import argparse
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from lxml import etree

NS = 'https://bonsai-rx.org/2018/workflow'
XSI = 'http://www.w3.org/2001/XMLSchema-instance'
XSI_TYPE = '{%s}type' % XSI
SIM_NS = 'clr-namespace:AvcSim;assembly=SimExtensions'
RX_NS = 'clr-namespace:Bonsai.Reactive;assembly=Bonsai.Core'
SIM_INCLUDE_DIR = 'SimIncludes'

# Groups removed wherever they appear (matched by <Name>)
REMOVE_GROUPS_TOP = {'GUI', 'GUI Callbacks', 'InitMixer', 'BonVisionResources', 'EventLogger'}
REMOVE_GROUPS_DEVICES = {'TimestampGenerator', 'StepperDriver', 'Cameras'}
REMOVE_GROUPS_LOGGING = {'Cameras'}
# Includes replaced by simulated devices (resource name -> sim device type)
SIM_DEVICE_INCLUDES = {
    'UclOpen.Devices:BehaviorBoard.BehaviorBoard.bonsai': 'SimBehaviorBoard',
    'UclOpen.Devices:LicketySplit.bonsai': 'SimLicketySplit',
}
# Includes copied locally with '/' instead of '\' in their file name Format strings
PATCHED_INCLUDES = ['UclOpen.Logging:LogController.bonsai', 'UclOpen.Logging:LogHarpDevice.bonsai']
REMOVE_INCLUDES = ['UclOpen.Devices:BehaviorBoard.CameraTriggerController.bonsai']
# Node types that only feed other nodes; dropped when everything they fed was removed
PRUNABLE = {'SubscribeSubject', 'PropertyMapping', 'ExternalizedMapping', 'InputMapping', 'Annotation',
            'VisualizerMapping', 'MemberSelector', 'Unit', 'Format', 'IntProperty', 'DoubleProperty', 'FloatProperty',
            'StringProperty', 'BooleanProperty', 'TimeSpanProperty', 'rx:Delay', 'rx:Take', 'rx:Skip',
            'rx:SampleInterval', 'rx:Timer'}
SUBJECT_DECLARATIONS = re.compile(r'^\w+:(Behavior|Publish|Async|Replay|Resource)Subject$|^(Behavior|Publish|Async|Replay|Resource)Subject$')
PATH_LIKE = re.compile(r'^(?![A-Za-z]:\\)(?!\\\\)[^\s<>|*?"]*\\[^\s<>|*?"]*\.[A-Za-z0-9]{1,8}$')


def q(tag):
    return '{%s}%s' % (NS, tag)


def local(tag):
    return tag.split('}', 1)[-1] if isinstance(tag, str) else ''


class Report:
    def __init__(self):
        self.lines = []
        self.warnings = []

    def add(self, text):
        self.lines.append(text)

    def warn(self, text):
        self.warnings.append(text)
        self.lines.append('WARNING: ' + text)


# ---------------------------------------------------------------------------------------------------------- XML basics
def load_xml(path, ensure_ns):
    """Parse a .bonsai file, adding xmlns declarations for ensure_ns {uri: preferred prefix} when missing.
    Returns (root, {uri: prefix}). Existing prefixes are kept exactly as in the file."""
    text = Path(path).read_bytes().decode('utf-8-sig')
    start = re.search(r'<WorkflowBuilder\b', text)
    if not start:
        raise SystemExit(f'{path}: not a Bonsai workflow (no <WorkflowBuilder>)')
    end = text.index('>', start.start())
    head = text[start.start():end]
    declared = dict((u, p) for p, u in re.findall(r'xmlns:([\w.-]+)="([^"]*)"', head))
    used_prefixes = set(declared.values())
    extra = ''
    prefixes = {}
    for uri, preferred in ensure_ns.items():
        if uri in declared:
            prefixes[uri] = declared[uri]
            continue
        prefix, n = preferred, 1
        while prefix in used_prefixes:
            n += 1
            prefix = f'{preferred}{n}'
        used_prefixes.add(prefix)
        prefixes[uri] = prefix
        extra += f'\n                 xmlns:{prefix}="{uri}"'
    text = text[:start.end()] + extra + text[start.end():]
    root = etree.fromstring(text.encode('utf-8'), etree.XMLParser(remove_blank_text=False, strip_cdata=False, huge_tree=True))
    return root, prefixes


def write_xml(root, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = etree.tostring(root, xml_declaration=True, encoding='utf-8')
    path.write_bytes(b'\xef\xbb\xbf' + data)


def unwrap(expr):
    """(builder element, disabled) for an <Expression>, looking through Disable."""
    if expr.get(XSI_TYPE) == 'Disable':
        builder = expr.find(q('Builder'))
        return (builder if builder is not None else expr), True
    return expr, False


def builder_type(expr):
    b, disabled = unwrap(expr)
    t = b.get(XSI_TYPE) or ''
    if t == 'Combinator':
        inner = b.find(q('Combinator'))
        if inner is not None:
            t = inner.get(XSI_TYPE) or t
    return t, disabled


def type_name(t):
    return t.split(':', 1)[-1]


def expr_name(expr):
    b, _ = unwrap(expr)
    for c in b:
        if local(c.tag) == 'Name' and c.text:
            return c.text.strip()
    inner = b.find(q('Combinator'))
    if inner is not None:
        for c in inner:
            if local(c.tag) == 'Name' and c.text:
                return c.text.strip()
    return None


def own_elements(builder):
    """Elements of a node's own properties (not those of nodes in a nested workflow)."""
    stack = list(builder)
    while stack:
        c = stack.pop()
        if local(c.tag) == 'Workflow':
            continue
        yield c
        stack.extend(c)


def child_workflow(expr):
    b, _ = unwrap(expr)
    return b.find(q('Workflow'))


def include_path(expr):
    b, _ = unwrap(expr)
    if b.get(XSI_TYPE) == 'IncludeWorkflow':
        return b.get('Path')
    return None


class Workflow:
    """A <Workflow> element with index-based node/edge editing."""

    def __init__(self, el, path):
        self.el = el
        self.path = path

    @property
    def nodes_el(self):
        return self.el.find(q('Nodes'))

    @property
    def edges_el(self):
        e = self.el.find(q('Edges'))
        if e is None:
            e = etree.SubElement(self.el, q('Edges'))
        return e

    def nodes(self):
        n = self.nodes_el
        return [] if n is None else [c for c in n if local(c.tag) == 'Expression']

    def edges(self):
        return [(int(e.get('From')), int(e.get('To')), e.get('Label')) for e in self.edges_el if local(e.tag) == 'Edge']

    def describe(self, i, expr=None):
        expr = expr if expr is not None else self.nodes()[i]
        t, disabled = builder_type(expr)
        name = expr_name(expr)
        inc = include_path(expr)
        s = ('DISABLED ' if disabled else '') + t + (f'({name})' if name else '') + (f'[{inc}]' if inc else '')
        return f'{self.path}[{i}] {s}'

    def set_edges(self, edges):
        e = self.edges_el
        for c in list(e):
            e.remove(c)
        for f, t, label in sorted(edges, key=lambda x: (x[0], x[1], x[2] or '')):
            etree.SubElement(e, q('Edge'), From=str(f), To=str(t), Label=label)

    def append(self, expr):
        self.nodes_el.append(expr)
        return len(self.nodes()) - 1

    def add_edge(self, f, t, label='Source1'):
        etree.SubElement(self.edges_el, q('Edge'), From=str(f), To=str(t), Label=label)

    def remove(self, indices, report, why, prune=True):
        """Remove nodes (why: one reason, or {index: reason}) and the nodes that only fed them; renumber edges."""
        nodes = self.nodes()
        edges = self.edges()
        removed = set(indices)
        for i in sorted(removed):
            report.add(f'removed {self.describe(i, nodes[i])}: {why[i] if isinstance(why, dict) else why}')
        succ = defaultdict(set)
        for f, t, _ in edges:
            succ[f].add(t)
        changed = prune
        while changed:
            changed = False
            for i, n in enumerate(nodes):
                if i in removed or not succ[i] or not succ[i] <= removed:
                    continue
                t, _ = builder_type(n)
                if t in PRUNABLE:
                    removed.add(i)
                    changed = True
                    report.add(f'removed {self.describe(i, n)}: only fed removed nodes')
        # kept nodes that lose inputs
        for f, t, label in edges:
            if f in removed and t not in removed:
                report.warn(f'{self.describe(t, nodes[t])} lost its input {label} from removed {self.describe(f, nodes[f])}')
        keep = [i for i in range(len(nodes)) if i not in removed]
        index = {old: new for new, old in enumerate(keep)}
        for i in sorted(removed, reverse=True):
            self.nodes_el.remove(nodes[i])
        self.set_edges([(index[f], index[t], label) for f, t, label in edges if f in index and t in index])
        return removed


def walk(wf, visit_disabled=False):
    """Yield every Workflow (depth first) below and including wf."""
    yield wf
    for i, expr in enumerate(wf.nodes()):
        _, disabled = unwrap(expr)
        if disabled and not visit_disabled:
            continue
        sub = child_workflow(expr)
        if sub is not None:
            name = expr_name(expr) or type_name(builder_type(expr)[0])
            yield from walk(Workflow(sub, f'{wf.path}/{name}{" (disabled)" if disabled else ""}'), visit_disabled)


def find_group(wf, name):
    for i, expr in enumerate(wf.nodes()):
        t, disabled = builder_type(expr)
        if t == 'GroupWorkflow' and not disabled and expr_name(expr) == name:
            return i, Workflow(child_workflow(expr), f'{wf.path}/{name}')
    return None, None


# --------------------------------------------------------------------------------------------------- subject analysis
def subject_names(wf_root, include_files):
    """Declared / used subject names in the enabled workflow, including inside includes (with externalized names)."""
    declared, used = defaultdict(list), defaultdict(list)
    for wf in walk(wf_root):
        for i, expr in enumerate(wf.nodes()):
            t, disabled = builder_type(expr)
            if disabled:
                continue
            name = expr_name(expr)
            if SUBJECT_DECLARATIONS.match(t) and name:
                declared[name].append(wf.describe(i, expr))
            elif t in ('SubscribeSubject', 'MulticastSubject') and name:
                used[name].append((wf, i, t))
            inc = include_path(expr)
            if inc:
                d, u = include_subjects(inc, expr, include_files)
                for n in d:
                    declared[n].append(wf.describe(i, expr))
    return declared, used


def include_subjects(path, include_el, include_files):
    """Subjects declared/used inside an included workflow, resolving names externalized as include properties."""
    file = include_files(path)
    if file is None or not Path(file).is_file():
        return set(), set()
    root, _ = load_xml(file, {})
    props = {local(c.tag): (c.text or '').strip() for c in include_el if local(c.tag) not in ('Name', 'Description')}
    declared, used = set(), set()
    top = Workflow(root.find(q('Workflow')), path)
    for wf in walk(top):
        nodes = wf.nodes()
        renamed = {}
        for f, t, _ in wf.edges():
            fx = nodes[f]
            if builder_type(fx)[0] == 'ExternalizedMapping':
                for p in fx.findall(q('Property')):
                    if p.get('Name') == 'Name':
                        display = p.get('DisplayName') or 'Name'
                        if display in props and props[display]:
                            renamed[t] = props[display]
        for i, expr in enumerate(nodes):
            t, disabled = builder_type(expr)
            if disabled:
                continue
            name = renamed.get(i, expr_name(expr))
            if SUBJECT_DECLARATIONS.match(t) and name:
                declared.add(name)
            elif t in ('SubscribeSubject', 'MulticastSubject') and name:
                used.add(name)
    return declared, used


# ------------------------------------------------------------------------------------------------------- new elements
def el(tag, attrib=None, text=None, children=()):
    e = etree.Element(tag, attrib or {})
    if text is not None:
        e.text = str(text)
    for c in children:
        e.append(c)
    return e


def expr_el(xsi_type, children=(), **attrib):
    e = el(q('Expression'), children=children)
    e.set(XSI_TYPE, xsi_type)
    for k, v in attrib.items():
        e.set(k, v)
    return e


def combinator_el(xsi_type, props, prop_ns):
    inner = el(q('Combinator'))
    inner.set(XSI_TYPE, xsi_type)
    for k, v in props.items():
        if v is None:
            continue
        inner.append(el('{%s}%s' % (prop_ns, k), text=fmt(v)))
    return expr_el('Combinator', [inner])


def fmt(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, float):
        return repr(v)
    return str(v)


def named_el(xsi_type, name, name_ns=NS, **attrib):
    return expr_el(xsi_type, [el('{%s}Name' % name_ns, text=name)], **attrib)


# --------------------------------------------------------------------------------------------------------- the harness
class Harness:
    def __init__(self, args, report):
        self.args = args
        self.report = report
        self.repo = Path(args.repo).resolve()
        self.workflow_file = Path(args.workflow).resolve() if args.workflow else self.repo / 'src' / 'main.bonsai'
        self.out = Path(args.out).resolve()
        self.resources = Path(args.resources).resolve()
        self.root, self.prefixes = load_xml(self.workflow_file, {SIM_NS: 'sim', RX_NS: 'rx'})
        self.top = Workflow(self.root.find(q('Workflow')), '')
        self.sim = self.prefixes[SIM_NS]
        self.rx = self.prefixes[RX_NS]
        self.local_includes = {}   # include path in harness -> local file written

    # resolve an include path (as written in a workflow) to a file we can read
    def include_file(self, path):
        if path in self.local_includes:
            return self.local_includes[path]
        if ':' in path and not re.match(r'^[A-Za-z]:\\', path):
            f = self.resources / path.replace(':', '.', 1)
            return f if f.is_file() else None
        f = self.out / path.replace('\\', '/')
        if f.is_file():
            return f
        f = self.repo / 'src' / path.replace('\\', '/')
        return f if f.is_file() else None

    def run(self):
        before, _ = subject_names(self.top, self.include_file)
        self.remove_hardware()
        self.replace_rig_configs()
        self.redirect_includes()
        self.rewrite_paths(self.top)
        self.add_simulation_group()
        self.drop_orphaned_subject_users(before)
        self.check_subjects()

    # -- removals
    def remove_hardware(self):
        r = self.report
        # top-level groups
        idx = [i for i, e in enumerate(self.top.nodes()) if builder_type(e)[0] == 'GroupWorkflow'
               and expr_name(e) in REMOVE_GROUPS_TOP]
        found = {expr_name(self.top.nodes()[i]) for i in idx}
        for missing in sorted(REMOVE_GROUPS_TOP - found):
            r.add(f'note: no top-level group {missing!r} to remove')
        self.top.remove(idx, r, 'GUI/hardware/display (not simulated)')
        # BonVision drawing and display includes (enabled or disabled), anywhere; ParameterRange etc. are kept
        for wf in list(walk(self.top, visit_disabled=True)):
            idx = [i for i, e in enumerate(wf.nodes())
                   if (include_path(e) or '').startswith('BonVision:')
                   and re.search(r'BonVision:(Primitives\.Draw|Primitives\.BonVisionResources|Environment\.)', include_path(e))]
            if idx:
                wf.remove(idx, r, 'BonVision drawing needs OpenGL and a projector')
        # Devices
        _, devices = find_group(self.top, 'Devices')
        if devices is None:
            r.warn('no top-level Devices group found')
        else:
            idx = [i for i, e in enumerate(devices.nodes()) if builder_type(e)[0] == 'GroupWorkflow'
                   and expr_name(e) in REMOVE_GROUPS_DEVICES]
            devices.remove(idx, r, 'hardware that is not simulated')
            for wf in walk(devices):
                idx = [i for i, e in enumerate(wf.nodes()) if include_path(e) in REMOVE_INCLUDES]
                if idx:
                    wf.remove(idx, r, 'camera trigger (no cameras in the simulation)')
        # Logging
        _, logging = find_group(self.top, 'Logging')
        if logging is None:
            r.warn('no top-level Logging group found')
        else:
            idx = [i for i, e in enumerate(logging.nodes()) if builder_type(e)[0] == 'GroupWorkflow'
                   and expr_name(e) in REMOVE_GROUPS_LOGGING]
            logging.remove(idx, r, 'camera logging (no cameras)')

    def replace_rig_configs(self):
        for wf in walk(self.top):
            for i, e in enumerate(wf.nodes()):
                t, disabled = builder_type(e)
                if disabled or type_name(t) != 'RigConfigs' or builder_type(e)[0] == 'SubscribeSubject':
                    continue
                prefix = t.split(':', 1)[0]
                uri = self.root.nsmap.get(prefix, '')
                if 'assembly=Extensions' not in uri:
                    continue
                a = self.args
                new = combinator_el(f'{self.sim}:SimRigConfigs', {
                    'RigName': a.rig_name, 'ValveOpenTime': a.valve_ms, 'ZapitHost': '127.0.0.1',
                    'ZapitPort': a.zapit_port, 'ZapitHardwareTriggered': a.zapit_hw,
                    'ZapitTriggerPulseWidth': a.zapit_pulse_ms}, SIM_NS)
                wf.nodes_el.replace(e, new)
                self.report.add(f'replaced {wf.describe(i, e)} with {self.sim}:SimRigConfigs (test values, '
                                f'ValveOpenTime={a.valve_ms} ms, ZapitPort={a.zapit_port}, '
                                f'ZapitHardwareTriggered={a.zapit_hw})')
                return
        self.report.warn('RigConfigs node not found; nothing replaced')

    # -- includes
    def redirect_includes(self):
        wheel = self.wheel_parameters()
        for wf in walk(self.top, visit_disabled=True):
            for i, e in enumerate(wf.nodes()):
                path = include_path(e)
                if not path:
                    continue
                b, _ = unwrap(e)
                where = wf.describe(i, e)
                if path in SIM_DEVICE_INCLUDES:
                    target = self.write_sim_device_include(path, SIM_DEVICE_INCLUDES[path], wheel)
                    b.set('Path', target)
                    self.report.add(f'include {where} -> {target} (simulated device)')
                elif path in PATCHED_INCLUDES:
                    target = self.write_patched_include(path)
                    b.set('Path', target)
                    self.report.add(f'include {where} -> {target} (path separators)')
                elif '\\' in path and ':' not in path:
                    new = path.replace('\\', '/')
                    b.set('Path', new)
                    self.report.add(f'include path {where}: {path} -> {new}')

    def wheel_parameters(self):
        counts, diameter = 4096.0, 75.0
        found = False
        for wf in walk(self.top):
            g, ticks = find_group(wf, 'TicksToCentimeters')
            if ticks is None:
                continue
            for e in ticks.nodes():
                t, _ = builder_type(e)
                if t == 'Divide':
                    v = e.find(q('Operand') + '/' + q('Value'))
                    if v is not None and v.text:
                        counts = float(v.text)
                        found = True
                if t == 'IntProperty':
                    b, _ = unwrap(e)
                    v = b.find('.//' + q('Value'))
                    if v is not None and v.text:
                        diameter = float(v.text)
            break
        self.report.add(f'wheel for the simulated encoder: CountsPerRev={counts:g}, WheelDiameterMm={diameter:g}'
                        + ('' if found else ' (defaults: TicksToCentimeters not found)'))
        return counts, diameter

    def write_sim_device_include(self, path, sim_type, wheel):
        source = self.resources / path.replace(':', '.', 1)
        if not source.is_file():
            raise SystemExit(f'missing {source}: run sim/setup.sh')
        root, prefixes = load_xml(source, {SIM_NS: 'sim'})
        sim = prefixes[SIM_NS]
        top = Workflow(root.find(q('Workflow')), path)
        replaced = 0
        for wf in walk(top):
            for i, e in enumerate(wf.nodes()):
                t, _ = builder_type(e)
                if type_name(t) != 'Device':
                    continue
                b, _ = unwrap(e)
                inner = b.find(q('Combinator'))
                props = {local(c.tag): (c.text or '') for c in inner}
                if sim_type == 'SimBehaviorBoard':
                    a = self.args
                    props.update({'SampleRate': a.board_rate, 'CountsPerRev': wheel[0], 'WheelDiameterMm': wheel[1],
                                  'TriggerHost': '127.0.0.1', 'TriggerPort': a.trigger_port,
                                  'LogPath': str(Path(a.sim_log_dir).resolve() / 'SimBehaviorBoard.csv')})
                new = combinator_el(f'{sim}:{sim_type}', props, SIM_NS)
                wf.nodes_el.replace(e, new)
                replaced += 1
        if replaced != 1:
            raise SystemExit(f'{path}: expected exactly one Harp Device node, found {replaced}')
        target = f'{SIM_INCLUDE_DIR}/{path.replace(":", ".", 1)}'
        self.rewrite_paths(top)
        write_xml(root, self.out / target)
        self.local_includes[target] = self.out / target
        return target

    def write_patched_include(self, path):
        source = self.resources / path.replace(':', '.', 1)
        if not source.is_file():
            raise SystemExit(f'missing {source}: run sim/setup.sh')
        root, _ = load_xml(source, {})
        top = Workflow(root.find(q('Workflow')), path)
        self.rewrite_paths(top, quiet=True)
        target = f'{SIM_INCLUDE_DIR}/{path.replace(":", ".", 1)}'
        write_xml(root, self.out / target)
        self.local_includes[target] = self.out / target
        return target

    # -- paths
    def rewrite_paths(self, wf_root, quiet=False):
        for wf in walk(wf_root, visit_disabled=True):
            for i, e in enumerate(wf.nodes()):
                b, _ = unwrap(e)
                t, _ = builder_type(e)
                if t == 'Format':
                    f = b.find(q('Format'))
                    if f is not None and f.text and '\\' in f.text and re.search(r'\{\d+[^}]*\}\\|\\\{\d+', f.text):
                        new = f.text.replace('\\', '/')
                        if not quiet:
                            self.report.add(f'path format {wf.describe(i, e)}: {f.text} -> {new}')
                        f.text = new
                for c in own_elements(b):
                    if local(c.tag) in ('FileName', 'Path', 'Value') and c.text and PATH_LIKE.match(c.text.strip()):
                        new = c.text.strip().replace('\\', '/')
                        if not quiet:
                            self.report.add(f'relative path {wf.describe(i, e)} {local(c.tag)}: {c.text.strip()} -> {new}')
                        c.text = new

    # -- simulation group
    def add_simulation_group(self):
        a = self.args
        sim, rx = self.sim, self.rx
        group = expr_el('GroupWorkflow', [
            el(q('Name'), text='Simulation'),
            el(q('Description'), text='SIMULATION ONLY (added by sim/make_harness.py): simulated mouse driving the '
                                      'simulated wheel and lick spout, automatic StartSession, and the stop condition.'),
            el(q('Workflow'), children=[el(q('Nodes')), el(q('Edges'))])])
        wf = Workflow(group.find(q('Workflow')), '/Simulation')
        inputs = [wf.append(named_el('SubscribeSubject', n)) for n in
                  ('MouseVirtualPosition', 'RewardFloorVirtualPos', 'RewardCeilVirtualPos', 'TrialNumber')]
        mouse = wf.append(combinator_el(f'{sim}:SimMouse', {
            'Speed': a.speed, 'SpeedJitter': a.speed_jitter, 'ZoneSpeedFactor': a.zone_speed_factor,
            'LicksPerBout': a.licks, 'LickRate': a.lick_rate, 'LickDuration': a.lick_duration,
            'ReactionTime': a.reaction, 'ZoneMargin': a.zone_margin, 'WrongLickRate': a.p_wrong,
            'WrongLicks': a.wrong_licks, 'MissRate': a.p_miss, 'NoLickRate': a.p_nolick, 'Seed': a.seed,
            'LogPath': str(Path(a.sim_log_dir).resolve() / 'SimMouse.csv')}, SIM_NS))
        for k, i in enumerate(inputs):
            wf.add_edge(i, mouse, f'Source{k + 1}')
        waveforms = wf.append(named_el('SubscribeSubject', 'WaveformDict'))
        delay = wf.append(combinator_el(f'{rx}:Delay', {'DueTime': f'PT{a.start_delay:g}S'}, RX_NS))
        unit = wf.append(expr_el('Unit'))
        start = wf.append(named_el(f'{rx}:PublishSubject', 'StartSession'))
        wf.add_edge(waveforms, delay)
        wf.add_edge(delay, unit)
        wf.add_edge(unit, start)
        ended = wf.append(named_el('SubscribeSubject', 'TrialEnded'))
        stop = wf.append(combinator_el(f'{sim}:StopAfterTrials', {'Trials': a.trials, 'DelaySeconds': 1.0}, SIM_NS))
        wf.add_edge(ended, stop)
        self.top.append(group)
        self.report.add(f'added /Simulation: SimMouse (speed {a.speed} cm/s, p_wrong {a.p_wrong}, p_miss {a.p_miss}, '
                        f'p_nolick {a.p_nolick}, seed {a.seed}), StartSession {a.start_delay:g} s after WaveformDict, '
                        f'StopAfterTrials({a.trials})')

    def drop_orphaned_subject_users(self, before):
        after, used = subject_names(self.top, self.include_file)
        gone = set(before) - set(after)
        if gone:
            self.report.add('subjects that only removed parts declared: ' + ', '.join(sorted(gone)))
        targets = {}
        for name, uses in used.items():
            if name not in gone:
                continue
            for wf, i, t in uses:
                nodes = wf.nodes()
                wf_targets = targets.setdefault(id(wf.el), (wf, {}))[1]
                if t == 'MulticastSubject':
                    wf_targets[i] = f'publishes to {name}, which nothing declares any more'
                else:
                    succ = [tt for f, tt, _ in wf.edges() if f == i]
                    if succ and all(include_path(nodes[s]) and 'LogHarpDevice' in include_path(nodes[s]) for s in succ):
                        for s in succ:
                            wf_targets[s] = f'logs {name}, a device that is not simulated'
                        wf_targets[i] = f'reads {name}, a device that is not simulated'
        for wf, reasons in targets.values():
            if reasons:
                wf.remove(sorted(reasons), self.report, reasons)

    def check_subjects(self):
        declared, used = subject_names(self.top, self.include_file)
        for name, uses in sorted(used.items()):
            if name not in declared:
                for wf, i, t in uses:
                    self.report.warn(f'{wf.describe(i)} uses subject {name!r} that nothing declares '
                                     '(Bonsai will fail to build; add a rule to sim/make_harness.py)')

    def write(self):
        write_xml(self.root, self.out / 'main.bonsai')
        # mirror src/Extensions (RigConfigs.cs is read by RigConfigsCopyLogger; .bonsai files may be included)
        ext_src = self.repo / 'src' / 'Extensions'
        ext_out = self.out / 'Extensions'
        ext_out.mkdir(parents=True, exist_ok=True)
        for f in sorted(ext_src.iterdir()):
            if f.suffix == '.bonsai':
                root, _ = load_xml(f, {})
                self.rewrite_paths(Workflow(root.find(q('Workflow')), f'Extensions/{f.name}'), quiet=True)
                for inc in root.iter(q('Expression')):
                    p = inc.get('Path')
                    if inc.get(XSI_TYPE) == 'IncludeWorkflow' and p and '\\' in p and ':' not in p:
                        inc.set('Path', p.replace('\\', '/'))
                write_xml(root, ext_out / f.name)
            elif f.is_file():
                shutil.copy2(f, ext_out / f.name)
        lines = [f'Simulation harness for {self.workflow_file}', f'written by sim/make_harness.py to {self.out}', '']
        (self.out / 'HARNESS_CHANGES.txt').write_text('\n'.join(lines + self.report.lines) + '\n')


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--repo', required=True, help='repo root (src/main.bonsai, src/Extensions)')
    ap.add_argument('--out', required=True, help='output folder standing in for src/ (main.bonsai is written here)')
    ap.add_argument('--workflow', help='workflow to convert (default REPO/src/main.bonsai)')
    ap.add_argument('--resources', default=str(Path(__file__).resolve().parent / 'build' / 'resources'),
                    help='embedded workflows extracted by setup.sh')
    ap.add_argument('--sim-log-dir', default='sim-logs', help='folder for the simulated devices\' CSV logs')
    g = ap.add_argument_group('stop')
    g.add_argument('--trials', type=int, default=0, help='stop after this many completed trials (0 = never)')
    g.add_argument('--start-delay', type=float, default=0.5, help='seconds from WaveformDict ready to StartSession')
    g = ap.add_argument_group('rig')
    g.add_argument('--rig-name', default='SIM-MAC')
    g.add_argument('--valve-ms', type=float, default=80.0, help='ValveOpenTime in RigConfigs')
    g.add_argument('--zapit-port', type=int, default=1488, help='ZapitPort in RigConfigs (mock Zapit server port)')
    g.add_argument('--zapit-sw', dest='zapit_hw', action='store_false', help='ZapitHardwareTriggered = false')
    g.add_argument('--zapit-pulse-ms', type=float, default=5.0, help='ZapitTriggerPulseWidth in RigConfigs')
    g.add_argument('--trigger-port', type=int, default=0, help='TCP port receiving DO3 TTL bytes (0 = off)')
    g.add_argument('--board-rate', type=int, default=1000, help='simulated AnalogData rate (Hz)')
    g = ap.add_argument_group('mouse')
    g.add_argument('--speed', type=float, default=25.0, help='running speed, cm/s')
    g.add_argument('--speed-jitter', type=float, default=0.15)
    g.add_argument('--zone-speed-factor', type=float, default=0.5)
    g.add_argument('--licks', type=int, default=4, help='licks per reward-zone bout')
    g.add_argument('--lick-rate', type=float, default=8.0)
    g.add_argument('--lick-duration', type=float, default=0.04)
    g.add_argument('--reaction', type=float, default=0.15)
    g.add_argument('--zone-margin', type=float, default=0.2)
    g.add_argument('--p-wrong', type=float, default=0.1, help='probability of a wrong-lick bout before the zone')
    g.add_argument('--wrong-licks', type=int, default=8, help='licks in a wrong-lick bout')
    g.add_argument('--p-miss', type=float, default=0.1, help='probability of not licking in the zone')
    g.add_argument('--p-nolick', type=float, default=0.05, help='probability of a trial without licks')
    g.add_argument('--seed', type=int, default=-1)
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    report = Report()
    h = Harness(args, report)
    h.out.mkdir(parents=True, exist_ok=True)
    h.run()
    h.write()
    print(f'harness: {h.out / "main.bonsai"}  ({len(report.lines)} changes, see HARNESS_CHANGES.txt)')
    for w in report.warnings:
        print('WARNING: ' + w, file=sys.stderr)
    return h


if __name__ == '__main__':
    main()

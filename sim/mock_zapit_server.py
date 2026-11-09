#!/usr/bin/env python3
"""Mock Zapit TCP server that reproduces the MATLAB server + pointer + DAQ semantics.

Modelled line by line on (Zapit-Optostim/zapit, main):
  +zapit/+interfaces/@TCPserver/processBufferMessageCallback.m   (wire format, error handling)
  +zapit/@pointer/sendSamples.m      (refuses if ~isReadyToStim || DAQ.isFiniteSamplePlaying)
  +zapit/@pointer/stopOptoStim.m     (returns immediately if AO SampleQuantityMode is 'FiniteSamples')
  +zapit/+hardware/+DAQ/@dotNETwrapper (isFiniteSamplePlaying = ~hAO.IsDone && FiniteSamples)
  +zapit/+simulated/@DAQ/DAQ.m       (isFiniteSamplePlaying always false, mode 'SIMULATED')

--daq real       behaves like a real NI DAQ (default)
--daq simulated  behaves like start_zapit('simulated', true)

A second port (trigger port = port + 1) accepts one byte per TTL edge, standing in for DO3 -> DAQ trigger.
"""
import argparse, socket, struct, threading, time, datetime, json

p = argparse.ArgumentParser()
p.add_argument('--port', type=int, default=14880)
p.add_argument('--daq', choices=['real', 'simulated'], default='real')
p.add_argument('--conditions', type=int, default=4)
p.add_argument('--ramp-ms', type=float, default=250.0)
p.add_argument('--refuse-start', type=int, default=0, help='refuse the Nth StartStimulus (1-based) as if Zapit were not ready')
p.add_argument('--events', default='', help='append one JSON line per event to this file')
a = p.parse_args()

lock = threading.Lock()
task = None      # dict(finite, hw, armed, t_start, t_end) or None
state = 'idle'


def now():
    return time.monotonic()


def datenum():
    d = datetime.datetime.now()
    return d.toordinal() + 366 + (d - datetime.datetime(d.year, d.month, d.day)).total_seconds() / 86400.0


def ao_is_done():
    if task is None:
        return True
    if task['armed']:                       # started, waiting for a trigger: DAQmx task is not done
        return False
    if task['finite']:
        return now() >= task['t_end']
    return False                            # continuous task runs until stopped


def is_finite_sample_playing():
    if a.daq == 'simulated':
        return False                        # simulated DAQ: always false
    return task is not None and task['finite'] and not ao_is_done()


def sample_quantity_mode():
    if a.daq == 'simulated':
        return 'SIMULATED'
    if task is None:
        return 'ContinuousSamples'
    return 'FiniteSamples' if task['finite'] else 'ContinuousSamples'


T0 = time.monotonic()
start_count = 0


def log(msg, **event):
    print(f"[mockzapit {a.daq}] {time.strftime('%H:%M:%S')} {msg}", flush=True)
    if a.events and event:
        event['t'] = round(time.monotonic() - T0, 4)
        with open(a.events, 'a') as f:
            f.write(json.dumps(event) + '\n')


def send_samples(cond, laser_on, hw, duration, delay):
    global task, state, start_count
    start_count += 1
    if a.refuse_start and start_count == a.refuse_start:
        log('sendSamples -- refused on purpose (--refuse-start)', event='start_refused', n=start_count)
        return -1, -1
    if is_finite_sample_playing():
        log('sendSamples -- Not ready to stimulate (finite waveform still playing or armed)', event='start_refused', n=start_count)
        return -1, -1
    if cond is not None and not (1 <= cond <= a.conditions):
        raise ValueError(f'Requested condition number {cond} is not valid')
    if cond is None:
        cond = 1
    finite = duration is not None and duration > 0
    total = (duration + (delay or 0) + a.ramp_ms / 1000.0) if finite else None
    task = dict(finite=finite, hw=hw, armed=hw, t_start=None, t_end=None, total=total)
    if not hw:
        task['t_start'] = now()
        task['t_end'] = now() + total if finite else None
    state = 'stim'
    log(f"sendSamples cond={cond} laserOn={laser_on} hw={hw} finite={finite} dur={duration} -> {'ARMED' if hw else 'PLAYING'}",
        event='start', n=start_count, cond=cond, laser=bool(laser_on), hw=hw, finite=finite)
    return cond, int(bool(laser_on))


def stop_opto_stim():
    global task, state
    if sample_quantity_mode() == 'FiniteSamples':
        log('stopOptoStim -- NO-OP: AO task is FiniteSamples (laser keeps going)', event='stop_ignored')
        return
    never_triggered = task is not None and task['armed']
    played_s = round(now() - task['t_start'], 4) if task is not None and task['t_start'] is not None else None
    task = None
    state = 'idle'
    log('stopOptoStim -- ramped down, idle', event='stop', never_triggered=never_triggered, played_s=played_s)


def trigger():
    with lock:
        if task is not None and task['armed']:
            task['armed'] = False
            task['t_start'] = now()
            task['t_end'] = now() + task['total'] if task['finite'] else None
            log('TTL -> armed waveform starts playing', event='ttl', armed=True)
        else:
            log('TTL -> nothing armed, ignored', event='ttl', armed=False)


def handle(conn):
    global state
    while True:
        buf = b''
        while len(buf) < 16:
            chunk = conn.recv(16 - len(buf))
            if not chunk:
                return
            buf += chunk
        com = buf[0]
        keys, vals, cond = buf[1], buf[2], buf[3]
        dur, power, delay = struct.unpack('<fff', buf[4:16])
        response = [255] * 6
        date_float = datenum()
        with lock:
            # a finite task that has finished playing becomes idle again
            if task is not None and task['finite'] and ao_is_done() and state == 'stim':
                state = 'idle'
            try:
                if com == 1:
                    bit = lambda b: bool(keys & b)
                    v = lambda b: bool(vals & b)
                    c = cond if bit(1) else None
                    laser = v(2) if bit(2) else True
                    hw = v(4) if bit(4) else True
                    d = dur if bit(32) else -1
                    dl = delay if bit(128) else 0
                    rc, rl = send_samples(c, laser, hw, d, dl)
                    if rc > 0 and rl >= 0:
                        response[0], response[1] = rc, rl
                elif com == 2:
                    response[0] = 1
                elif com == 4:
                    response[0] = a.conditions
                elif com == 3:
                    response[0] = {'idle': 0, 'stim': 1, 'rampdown': 2}[state]
                elif com == 0:
                    stop_opto_stim()
                    response[0] = 1
            except Exception as e:
                log(f'error: {e}')
                date_float = -1.0
        conn.sendall(struct.pack('<d', date_float) + bytes([com]) + bytes(response))


def trigger_server():
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', a.port + 1)); s.listen(5)
    while True:
        c, _ = s.accept()
        with c:
            while c.recv(1):
                trigger()


threading.Thread(target=trigger_server, daemon=True).start()
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('127.0.0.1', a.port)); srv.listen(1)
log(f'listening on {a.port} (trigger port {a.port + 1}), {a.conditions} conditions')
while True:
    conn, _ = srv.accept()
    log('client connected')
    with conn:
        handle(conn)
    log('client disconnected')

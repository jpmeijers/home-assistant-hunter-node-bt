import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path('/home/jpmeijers/PycharmProjects/hunter-node-bt-ha')
sys.path.insert(0, str(ROOT))
from bleak import BleakClient, BleakScanner
from custom_components.hunter_node_bt.protocol import HunterNodeSession

OUT = ROOT / 'captures' / ('clock_test_' + datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S'))
OUT.mkdir(parents=True)

def log(**record):
    record['at'] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(record), flush=True)
    with (OUT / 'transactions.jsonl').open('a') as f:
        f.write(json.dumps(record) + '\n')

def save(name, value):
    (OUT / (name + '.json')).write_text(json.dumps(value, indent=2) + '\n')

def local_epoch():
    local = datetime.now(ZoneInfo('Africa/Johannesburg'))
    return int(local.replace(tzinfo=timezone.utc).timestamp())

class Session(HunterNodeSession):
    async def transact(self, command):
        started = time.time()
        result = await super().transact(command)
        log(command=command, response=result, started_unix=started, finished_unix=time.time())
        return result

async def connect():
    device = await BleakScanner.find_device_by_address('60:B6:47:FE:F0:D4', timeout=30)
    if device is None:
        raise RuntimeError('Controller not detected within 30 seconds')
    client = BleakClient(device, timeout=20)
    await client.connect()
    session = Session(client, 0, response_timeout=30)
    try:
        await session.authenticate()
        raw = await session.transact({'Read': 'All'})
        assert raw['Controller']['SerialNumber'] == 16707796
        return client, session, raw
    except BaseException:
        await client.disconnect()
        raise

async def main():
    log(event='Starting clock test', evidence=str(OUT))
    client, session, baseline = await connect()
    try:
        save('baseline', baseline)
        state = await session.transact({'Read': 'Section_State'})
        assert state['State']['ControllerState'] == 0, 'Controller must be idle'
        clock = (await session.transact({'Read': 'Section_Controller'}))['Controller']['CurrentTime']
        expected = local_epoch()
        drift = expected - clock
        log(event='Clock before sync', local_epoch=expected, controller_epoch=clock, drift_seconds=drift)
        assert abs(drift) < 120, 'Large correction needs further inspection'
        for letter in 'ABC':
            program = baseline['Program_' + letter]
            if sum(program['RunTime']):
                for start in program['StartTimes']:
                    if start != 65535:
                        distance = abs((expected % 86400) - start * 60)
                        assert min(distance, 86400 - distance) > 300, 'Scheduled start too close to clock correction'
        sent = local_epoch()
        status = await session.transact({'Controller': {'CurrentTime': sent}})
        assert type(status.get('Status')) is int and status['Status'] == 0
        after = await session.transact({'Read': 'All'})
        save('after_sync', after)
        assert abs(local_epoch() - after['Controller']['CurrentTime']) <= 3, 'Clock readback mismatch'
        for key in baseline:
            if key != 'Controller':
                assert after[key] == baseline[key], f'Unexpected change: {key}'
        for key, value in baseline['Controller'].items():
            if key not in {'CurrentTime', 'SettingsChangeDate', 'LogCount'}:
                assert after['Controller'][key] == value, f'Unexpected controller change: {key}'
        log(event='PASS clock write and readback; configuration preserved', sent=sent)
    finally:
        await client.disconnect()
    log(event='Disconnected; waiting 15 seconds before persistence check')
    await asyncio.sleep(15)
    client, session, final = await connect()
    try:
        save('after_reconnect', final)
        delta = local_epoch() - final['Controller']['CurrentTime']
        assert abs(delta) <= 3, 'Clock after reconnect mismatch'
        for letter in 'ABC':
            assert final['Program_' + letter] == baseline['Program_' + letter]
        state = await session.transact({'Read': 'Section_State'})
        save('final_state', state)
        assert state['State']['ControllerState'] == 0
        log(event='PASS clock advances across disconnect; programs unchanged; controller idle', drift_seconds=delta)
    finally:
        await client.disconnect()

try:
    asyncio.run(main())
except BaseException as error:
    log(event='Test incomplete', error=repr(error))
    raise

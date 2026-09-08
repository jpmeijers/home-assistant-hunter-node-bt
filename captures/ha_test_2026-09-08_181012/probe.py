import asyncio
import json
import logging
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/jpmeijers/PycharmProjects/hunter-node-bt-ha')
sys.path[:0] = [str(ROOT), '/home/jpmeijers/home-assistant-core']
from homeassistant.core import HomeAssistant
from homeassistant import bootstrap, loader
from homeassistant.components import bluetooth
from homeassistant.helpers import entity_registry as er

OUT = ROOT / 'captures' / ('ha_test_' + datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S'))
OUT.mkdir(parents=True)
CONFIG = Path('/tmp/ha-node-live-config2')
CONFIG.mkdir(exist_ok=True)
(CONFIG / 'configuration.yaml').write_text('homeassistant:\n  time_zone: Africa/Johannesburg\nbluetooth:\nhttp:\n  server_host: 127.0.0.1\n  server_port: 8124\n')
link = CONFIG / 'custom_components'
if not link.exists():
    link.symlink_to(ROOT / 'custom_components', target_is_directory=True)
logging.basicConfig(level=logging.INFO, handlers=[logging.FileHandler(OUT / 'home-assistant.log'), logging.StreamHandler()])

def log(event, **data):
    record = dict(at=datetime.now(timezone.utc).isoformat(), event=event, **data)
    print(json.dumps(record, default=str), flush=True)
    with (OUT / 'events.jsonl').open('a') as f:
        f.write(json.dumps(record, default=str) + '\n')

def save(name, data):
    (OUT / (name + '.json')).write_text(json.dumps(data, indent=2, default=str) + '\n')

async def main():
    hass = HomeAssistant(str(CONFIG))
    hass.config.skip_pip = True
    loader.async_setup(hass)
    entry = None
    baseline = None
    try:
        assert await bootstrap.async_from_config_dict({'homeassistant': {'time_zone': 'Africa/Johannesburg'}, 'bluetooth': {}, 'http': {'server_host': '127.0.0.1', 'server_port': 8124}}, hass)
        await hass.async_start()
        log('HA started', evidence=str(OUT))
        for _ in range(40):
            info = bluetooth.async_last_service_info(hass, '60:B6:47:FE:F0:D4', connectable=True)
            if info is not None:
                break
            await asyncio.sleep(1)
        assert info is not None, 'Device not discovered through HA Bluetooth'
        log('HA discovered controller', name=info.name, source=info.source, rssi=info.rssi)
        entries = hass.config_entries.async_entries('hunter_node_bt')
        if entries:
            entry = entries[0]
            await hass.config_entries.async_setup(entry.entry_id)
        else:
            flows = [f for f in hass.config_entries.flow.async_progress() if f['handler'] == 'hunter_node_bt']
            if flows:
                result = await hass.config_entries.flow.async_configure(flows[0]['flow_id'], {'pin': '0000'})
            else:
                result = await hass.config_entries.flow.async_init('hunter_node_bt', context={'source': 'bluetooth'}, data=info)
                assert result['type'] == 'form', result
                result = await hass.config_entries.flow.async_configure(result['flow_id'], {'pin': '0000'})
            assert result['type'] == 'create_entry', result
            entry = result['result']
        await hass.async_block_till_done()
        assert entry.state.value == 'loaded', entry.state
        coordinator = entry.runtime_data
        log('Config entry loaded', state=entry.state)
        registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(registry, entry.entry_id)
        save('entities', [{'entity_id': e.entity_id, 'unique_id': e.unique_id, 'disabled_by': e.disabled_by,
                           'state': hass.states.get(e.entity_id).as_dict() if hass.states.get(e.entity_id) else None} for e in entities])
        def entity(suffix):
            return next(e.entity_id for e in entities if e.unique_id == '16707796_program_b_' + suffix)
        registry.async_update_entity(entity('mon'), disabled_by=None)
        log('Waiting for entity enable reload to settle')
        await asyncio.sleep(35)
        await hass.async_block_till_done()
        coordinator = entry.runtime_data
        assert entry.state.value == 'loaded'
        baseline = await coordinator.controller.read_data()
        save('baseline_programs', [asdict(p) for p in baseline.programs])
        assert baseline.programs[1].start_times == (65535,) * 8
        assert sum(baseline.programs[1].runtimes) == 0
        async def call(domain, service, data):
            await hass.services.async_call(domain, service, data, blocking=True)
            log('PASS service call', domain=domain, service=service, data=data)
        try:
            await call('text', 'set_value', {'entity_id': entity('name'), 'value': 'HA live test'})
            assert hass.states.get(entity('name')).state == 'HA live test'
            await call('number', 'set_value', {'entity_id': entity('station_1_runtime'), 'value': 17})
            assert float(hass.states.get(entity('station_1_runtime')).state) == 17
            await call('number', 'set_value', {'entity_id': entity('station_1_runtime'), 'value': 0})
            await call('time', 'set_value', {'entity_id': entity('start_1'), 'time': '06:17:00'})
            assert hass.states.get(entity('start_1')).state == '06:17:00'
            await call('hunter_node_bt', 'clear_start_time', {'entity_id': entity('start_1')})
            assert hass.states.get(entity('start_1')).attributes['enabled'] is False
            await call('switch', 'turn_off', {'entity_id': entity('mon')})
            await call('switch', 'turn_on', {'entity_id': entity('mon')})
            device_id = next(e.device_id for e in entities if e.device_id)
            await call('hunter_node_bt', 'set_program', {'device_id': device_id, 'program': 'B', 'station_runtimes': {'2': 19}})
            assert coordinator.data.programs[1].runtimes[1] == 19
            backup = await coordinator._backup_store.async_load()
            assert 'B' in backup
            save('backup', backup)
            log('PASS backup persisted and verified status', status=coordinator.schedule_write_status)
        finally:
            original = baseline.programs[1]
            await coordinator.async_set_program('B', start_times=[])
            await coordinator.async_set_program('B', station_runtimes={1: 0, 2: 0})
            await coordinator.async_set_program('B', name=original.name, weekdays=['mon','tue','wed','thu','fri','sat','sun'])
            restored = await coordinator.controller.read_data()
            assert restored.programs == baseline.programs
            log('PASS original programs restored')
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state.value == 'loaded'
        assert entry.runtime_data.data.programs == baseline.programs
        log('PASS integration reload and fresh controller read')
    finally:
        await hass.async_stop()
        log('HA stopped')

asyncio.run(main())

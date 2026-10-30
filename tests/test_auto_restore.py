"""Exercise reference-map recovery with real HA storage and a local MQTT broker."""

import asyncio
from datetime import timedelta
import gzip
import logging
import socket
import tempfile
import unittest

import aiomqtt
from amqtt.broker import Broker
from homeassistant.core import HomeAssistant
from homeassistant.helpers import frame
from homeassistant.helpers.entity_platform import EntityPlatform

from custom_components.tesvor.button import TesvorSetReferenceMapButton
from custom_components.tesvor.coordinator import TesvorCoordinator
from custom_components.tesvor.select_storage import TesvorSelectStorage
from custom_components.tesvor.sensor import TesvorCloudMapsSensor
from custom_components.tesvor.switch import TesvorAutoRestoreSwitch
from custom_components.tesvor.tesvorhome.device.vacuum import TesvorVacuum, VacuumInfo
from custom_components.tesvor.tesvorhome.dp.manager import DPManager
from custom_components.tesvor.tesvorhome.map.map_decoder import MapDecoder
from custom_components.tesvor.tesvorhome.mqtt.client_async import AsyncMQTTClient
from custom_components.tesvor.tesvorhome.mqtt.command_sender import CommandSender
from custom_components.tesvor.tesvorhome.mqtt.encoder import TesvorEncoder
from custom_components.tesvor.tesvorhome.protobuf import sdk_com_pb2, sweeper_any_pb2
from custom_components.tesvor.tesvorhome.protobuf import sweeper_map_pb2


class AutoRestoreTests(unittest.IsolatedAsyncioTestCase):
    """Verify the actual switch-to-map-command path without mocks or hardware."""

    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.directory.name)
        frame.async_setup(self.hass)
        self.vacuum = TesvorVacuum(None)
        self.vacuum.info = VacuumInfo(1, "test-mac", "test-product", "Test", "test")
        self.coordinator = TesvorCoordinator(self.hass, self.vacuum)
        self.coordinator.select_storage = TesvorSelectStorage(self.hass, "test-entry")
        await self.coordinator.select_storage.async_ensure_loaded()
        self.sensor = TesvorCloudMapsSensor(self.coordinator)
        self.sensor.entity_id = "sensor.test_cloud_maps"
        self.sensor._maps = [{
            "id": 7,
            "name": "Saved map",
            "area": 10,
            "date": None,
            "room_count": 1,
            "app_map_url": "https://example.invalid/map.bv",
            "app_map_md5": "test-checksum",
        }]
        self.sensor.selected_map_id = 7
        self.switch = TesvorAutoRestoreSwitch(self.coordinator)
        self.switch.entity_id = "switch.test_auto_restore"
        for entity, domain in [(self.sensor, "sensor"), (self.switch, "switch")]:
            entity.add_to_platform_start(
                self.hass,
                EntityPlatform(
                    hass=self.hass,
                    logger=logging.getLogger(__name__),
                    domain=domain,
                    platform_name="tesvor",
                    platform=None,
                    scan_interval=timedelta(seconds=60),
                    entity_namespace=None,
                ),
                None,
            )

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.broker = Broker({
            "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
            "plugins": {
                "amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True},
            },
        })
        await self.broker.start()
        self.vacuum.mqtt = AsyncMQTTClient("127.0.0.1", port, "test", "test", "test")
        await asyncio.wait_for(self.vacuum.mqtt.connect(), timeout=3)
        self.vacuum.dp_manager = DPManager()
        self.vacuum.dp_manager.load_from_api_list([
            {"dpNum": 30, "dpCode": "map_reuse", "dataType": 3},
        ])
        self.vacuum._encoder = TesvorEncoder.from_dp_manager("test-mac", self.vacuum.dp_manager)
        self.vacuum._command_sender = CommandSender(self.vacuum.mqtt, "test-mac", 0)
        self.peer = aiomqtt.Client("127.0.0.1", port=port)
        await self.peer.__aenter__()
        await self.peer.subscribe("DP_APP_test-mac")

    async def asyncTearDown(self) -> None:
        await self.peer.__aexit__(None, None, None)
        await self.vacuum.disconnect()
        await self.broker.shutdown()
        await self.hass.async_stop()
        self.directory.cleanup()

    async def send_frame(self, frame_id: int) -> None:
        """Decode an actual protobuf map and pass it through the map handler."""
        frame = sweeper_map_pb2.MapData(frame_id=frame_id, width=1, height=1)
        frame.map_info.data.append(1)
        await self.vacuum._on_map_data(MapDecoder._protobuf_to_dict(frame))

    async def assert_no_command(self) -> None:
        """Ensure no map command was published to the broker."""
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(anext(self.peer.messages), timeout=0.05)

    async def test_switch_restores_reference_only_on_reset_and_stops_when_disabled(self) -> None:
        """Publish the chosen reference on reset, without frame/restore loops."""
        button = TesvorSetReferenceMapButton(self.coordinator)
        button.hass = self.hass
        await button.async_press()
        await self.switch.async_turn_on()

        await self.send_frame(40)
        await self.send_frame(41)
        await self.send_frame(41)
        await self.assert_no_command()

        await self.send_frame(0)
        message = await asyncio.wait_for(anext(self.peer.messages), timeout=3)
        command = sdk_com_pb2.MqttMsg.FromString(gzip.decompress(message.payload))
        self.assertEqual(list(command.header.cmd_id), [30])
        use_map = sweeper_any_pb2.UseMap()
        self.assertTrue(command.body[0].Unpack(use_map))
        self.assertEqual(use_map.map_id, 7)
        self.assertEqual(use_map.url, "https://example.invalid/map.bv")
        self.assertEqual(use_map.md5, "test-checksum")

        # The restored stream and delayed frames must not create a restore loop.
        await self.send_frame(0)
        await self.send_frame(20)
        await self.send_frame(0)
        await self.assert_no_command()

        # Leave the cooldown behind so disabling is the only suppression reason.
        self.vacuum._last_auto_restore = asyncio.get_running_loop().time() - 61
        await self.switch.async_turn_off()
        await self.send_frame(40)
        await self.send_frame(0)
        await self.assert_no_command()
        self.assertFalse(self.vacuum.auto_restore_enabled)

    async def test_missing_reference_failed_publish_and_reload(self) -> None:
        """Missing/failed restores stay failures; reload restores both settings."""
        await self.switch.async_turn_on()
        await self.send_frame(30)
        await self.send_frame(0)
        await self.assert_no_command()
        self.assertIsNone(self.vacuum._last_auto_restore)

        await self.sensor.async_set_reference_map(7)
        await self.vacuum.mqtt.disconnect()
        self.assertFalse(await self.vacuum.load_reference_map())
        self.assertIsNone(self.vacuum._last_auto_restore)

        # A new coordinator, store, sensor, and switch emulate an integration
        # reload. The values must come from the real on-disk HA storage file.
        reloaded_vacuum = TesvorVacuum(None)
        reloaded = TesvorCoordinator(self.hass, reloaded_vacuum)
        reloaded.select_storage = TesvorSelectStorage(self.hass, "test-entry")
        await reloaded.select_storage.async_ensure_loaded()
        reloaded_sensor = TesvorCloudMapsSensor(reloaded)
        reloaded_switch = TesvorAutoRestoreSwitch(reloaded)
        self.assertEqual(reloaded_sensor._reference_map_id, 7)
        self.assertTrue(reloaded_switch.is_on)
        self.assertTrue(reloaded_vacuum.auto_restore_enabled)
        self.assertIs(reloaded_vacuum.coordinator, reloaded)


if __name__ == "__main__":
    unittest.main()

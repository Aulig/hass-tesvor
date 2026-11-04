"""Exercise cloud/session recovery with real HTTP, MQTT, and HA coordinators."""

import asyncio
import gzip
import socket
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import MappingProxyType

import aiohttp
from aiohttp import web
import aiomqtt
from amqtt.broker import Broker
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import frame
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.tesvor import async_setup_entry
from custom_components.tesvor.coordinator import TesvorCoordinator
from custom_components.tesvor.tesvorhome.config import (
    Credentials, DeviceConfig, MQTTConfig, RestConfig, TesvorConfig,
)
from custom_components.tesvor.tesvorhome.device.vacuum import TesvorVacuum
from custom_components.tesvor.tesvorhome.protobuf import sdk_com_pb2
from custom_components.tesvor.tesvorhome.rest.async_client import TesvorTokenExpired


class CloudRecoveryTests(unittest.IsolatedAsyncioTestCase):
    """Reproduce outages at protocol boundaries without patching implementation."""

    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.directory.name)
        frame.async_setup(self.hass)
        self.mode = "ok"
        self.login_mode = "ok"
        self.calls = Counter()
        self.login_started = asyncio.Event()
        self.login_gate = asyncio.Event()
        self.broker = None
        self.peer = None
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", self.cloud_response)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        address = next(iter(self.runner.addresses))
        self.base_url = f"http://127.0.0.1:{address[1]}"
        self.vacuum = TesvorVacuum(TesvorConfig(
            rest=RestConfig(
                self.base_url, "test", "test", "test", "teasvor", "", "de", "49",
                "1.8.2", False, "tesvor-test",
            ),
            mqtt=MQTTConfig("127.0.0.1", 1, "test", "test"),
            credentials=Credentials("test@example.invalid", "test"),
            device=DeviceConfig(command_delay=0),
        ), maps_directory=self.hass.config.path("www", "tesvor", "maps"))
        self.vacuum._test_mode = True
        self.coordinator = TesvorCoordinator(self.hass, self.vacuum)

    async def asyncTearDown(self):
        self.login_gate.set()
        if self.peer is not None:
            await self.peer.__aexit__(None, None, None)
        await self.vacuum.disconnect()
        if self.broker is not None:
            await self.broker.shutdown()
        await self.runner.cleanup()
        await self.hass.async_stop()
        self.directory.cleanup()

    async def cloud_response(self, request):
        """Serve the subset of Tesvor's wire protocol used by the real clients."""
        self.calls[request.path] += 1
        if request.path == "/mis/user/account/status":
            self.login_started.set()
            if self.login_mode == "blocked":
                await self.login_gate.wait()
            if self.login_mode == "busy":
                return web.json_response({"code": "", "msg": "服务器忙"})
            data = {"encryptType": 2}
        elif request.path == "/mis/user/login/account/v2":
            data = {"id": 1, "token": "app-token"}
        elif request.path == "/mis/user/login/sdk":
            data = {"token": f"sdk-{self.calls[request.path]}", "clientId": "test"}
        else:
            if self.mode == "busy":
                return web.json_response({"code": "", "msg": "服务器忙"})
            if self.mode == "http503":
                return web.Response(status=503)
            if self.mode == "timeout":
                await asyncio.sleep(0.7)
                return web.Response(status=504)
            if self.mode == "invalid-json":
                return web.Response(text="upstream unavailable")
            if self.mode == "invalid-envelope":
                return web.json_response([])
            if self.mode == "unauthorized":
                return web.Response(status=401)
            if self.mode == "expired" or request.headers.get("token") == "expired":
                return web.json_response({"code": 10600, "msg": "token无效"})
            data = {
                "/mis/home/query/infoList": [{"id": 1, "isDefault": True}],
                "/mis/device/home/device": [{
                    "deviceId": 1, "macAddress": "test-mac", "pId": "test-product",
                    "deviceName": "Test vacuum", "softwareVersion": "test-version",
                }],
                "/mis/product/get/dp": [
                    {"dpNum": 1, "dpCode": "switch_clean", "dataType": 1},
                ],
                "/mis/device/query/clean/sum": {
                    "cleanNums": 84, "cleanLength": 3600, "cleanArea": 120,
                },
                "/mis/device/query/consume": [],
                "/mis/device/query/clean/record": [{
                    "cleanTime": "2026-11-01 12:00:00", "cleanLength": 600,
                    "cleanArea": 120, "cleanFinishedFlag": True,
                }],
                "/mis/device/query/map": [],
            }[request.path]
            if request.path == "/mis/product/get/dp" and self.mode == "first-refresh-failure":
                self.mode = "busy"
        return web.json_response({"code": 10000, "data": data})

    async def start_mqtt(self):
        """Attach a real broker and command observer to the actual vacuum."""
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
        self.vacuum.config.mqtt.port = port
        self.vacuum._mqtt_task = asyncio.create_task(self.vacuum._connect_mqtt())
        await asyncio.wait_for(self.vacuum._mqtt_task, timeout=3)
        self.peer = aiomqtt.Client("127.0.0.1", port=port)
        await self.peer.__aenter__()
        await self.peer.subscribe("DP_APP_test-mac")

    async def test_cloud_outages_preserve_commands_managers_and_cached_statistics(self):
        """Busy/HTTP/timeout failures never tear down working robot control."""
        await self.vacuum.initialize()
        await self.start_mqtt()
        await self.coordinator.async_refresh()
        original_stats = self.coordinator.data["statistics"]
        original_clean = self.coordinator.data["last_clean"]
        self.assertEqual(original_stats["total_cleanings"], 84)
        self.assertEqual(original_clean["clean_area"], 12)
        rest = self.vacuum.rest
        session = rest.session
        mqtt = self.vacuum.mqtt
        maps = self.vacuum.cloud_maps
        history = self.vacuum.clean_history
        self.assertEqual(
            maps.png_dir,
            Path(self.directory.name) / "www" / "tesvor" / "maps" / "cloud" / "png",
        )
        self.assertTrue(maps.png_dir.is_dir())
        self.assertEqual(self.vacuum.visualizer.base_dir, maps.png_dir.parent.parent)
        rest.timeout = aiohttp.ClientTimeout(total=0.5)
        await session.close()

        for mode in ["busy", "http503", "invalid-json", "invalid-envelope", "timeout", "busy", "http503"]:
            with self.subTest(mode=mode):
                self.mode = mode
                await self.coordinator.async_refresh()
                self.assertTrue(self.coordinator.last_update_success)
                self.assertFalse(self.coordinator.rest_available)
                self.assertEqual(self.coordinator.data["statistics"], original_stats)
                self.assertEqual(self.coordinator.data["last_clean"], original_clean)
                self.assertIs(self.vacuum.mqtt, mqtt)
                self.assertTrue(mqtt.is_connected)
                self.assertTrue(await self.vacuum.start_cleaning())
                message = await asyncio.wait_for(anext(self.peer.messages), timeout=3)
                command = sdk_com_pb2.MqttMsg.FromString(gzip.decompress(message.payload))
                self.assertEqual(list(command.header.cmd_id), [1])

        self.mode = "ok"
        await self.coordinator.async_refresh()
        self.assertTrue(self.coordinator.rest_available)
        self.assertIs(self.vacuum.rest, rest)
        self.assertIs(self.vacuum.cloud_maps, maps)
        self.assertIs(self.vacuum.clean_history, history)
        self.assertIs(maps.rest, rest)
        self.assertIs(history.rest, rest)
        self.assertEqual(await rest.get_map_list(1), [])
        self.assertEqual(self.calls["/mis/user/login/sdk"], 1)

        # When both transports fail, HA reports failure and keeps polling.
        broker_config = self.broker.config
        await self.peer.__aexit__(None, None, None)
        self.peer = None
        await self.broker.shutdown()
        self.broker = None
        async with asyncio.timeout(3):
            while mqtt.is_connected:
                await asyncio.sleep(0.01)
        self.mode = "busy"
        await self.coordinator.async_refresh()
        self.assertFalse(self.coordinator.last_update_success)

        self.broker = Broker(broker_config)
        await self.broker.start()
        self.mode = "ok"
        async with asyncio.timeout(5):
            while not mqtt.is_connected:
                await asyncio.sleep(0.01)
        await self.coordinator.async_refresh()
        self.assertTrue(self.coordinator.last_update_success)
        self.assertTrue(self.coordinator.rest_available)
        self.assertIs(self.vacuum.mqtt, mqtt)

    async def test_token_renewal_is_serialized_bounded_and_does_not_replay_mutations(self):
        """Concurrent reads share renewal; persistent rejection stops after one retry."""
        await self.vacuum.initialize()
        rest = self.vacuum.rest
        rest.iot_token = "expired"
        results = await asyncio.gather(*(rest.get_homes() for _ in range(6)))
        self.assertTrue(all(result == [{"id": 1, "isDefault": True}] for result in results))
        self.assertEqual(self.calls["/mis/user/login/sdk"], 2)

        for mode, error in [("expired", TesvorTokenExpired), ("unauthorized", aiohttp.ClientResponseError)]:
            self.mode = mode
            before = self.calls["/mis/home/query/infoList"]
            with self.assertRaises(error):
                await rest.get_homes()
            self.assertEqual(self.calls["/mis/home/query/infoList"] - before, 2)
            before_login = self.calls["/mis/user/login/sdk"]
            with self.assertRaises(error):
                await rest._post("/mis/home/query/infoList", json={"test": True})
            self.assertEqual(self.calls["/mis/user/login/sdk"], before_login)

        # Failed renewal is throttled even when multiple cloud consumers retry.
        self.mode = "ok"
        self.login_mode = "busy"
        rest.iot_token = "expired"
        before_login = self.calls["/mis/user/account/status"]
        failures = await asyncio.gather(
            *(rest.get_homes() for _ in range(6)), return_exceptions=True,
        )
        self.assertTrue(all(isinstance(error, Exception) for error in failures))
        self.assertEqual(self.calls["/mis/user/account/status"] - before_login, 1)
        self.login_mode = "ok"
        await asyncio.sleep(5.1)
        self.assertEqual(await rest.get_homes(), [{"id": 1, "isDefault": True}])

        # Programming errors must remain visible, rather than entering retry loops.
        with self.assertRaises(TypeError):
            await rest._request("GET", "/mis/home/query/infoList", invalid_argument=True)

    async def test_busy_cloud_during_setup_requests_ha_retry_without_partial_entry(self):
        """A vendor error, not just a DNS exception, reaches HA's retry scheduler."""
        self.login_mode = "busy"
        entry = ConfigEntry(
            version=1, minor_version=1, domain="tesvor", title="Test vacuum",
            data={
                "email": "test@example.invalid", "password": "test", "phone_code": "49",
                "rest_url": self.base_url, "mqtt_host": "127.0.0.1", "mqtt_port": 1,
            },
            options={}, source="user", unique_id="test-mac",
            discovery_keys=MappingProxyType({}), subentries_data=None,
            state=ConfigEntryState.SETUP_IN_PROGRESS,
        )
        with self.assertRaises(ConfigEntryNotReady):
            await async_setup_entry(self.hass, entry)
        self.assertNotIn(entry.entry_id, self.hass.data["tesvor"])

        # Discovery succeeds, but the first coordinator refresh fails. Retrying
        # must not hit the old "already initialized" shortcut with a dead entry.
        self.login_mode = "ok"
        self.mode = "first-refresh-failure"
        with self.assertRaises(ConfigEntryNotReady):
            await async_setup_entry(self.hass, entry)
        self.assertNotIn(entry.entry_id, self.hass.data["tesvor"])

    async def test_failed_reinitialization_keeps_retrying_and_shutdown_stays_closed(self):
        """Reproduce the missing-client failure repeatedly, then restore cleanly."""
        await self.vacuum.initialize()
        rest = self.vacuum.rest
        maps = self.vacuum.cloud_maps
        history = self.vacuum.clean_history
        await self.vacuum.disconnect()
        self.coordinator._initialized = True
        self.login_mode = "busy"
        for _ in range(3):
            with self.assertRaises(UpdateFailed):
                await self.coordinator._async_update_data()
            self.assertFalse(self.coordinator._initialized)
            self.assertFalse(self.vacuum.is_initialized)
            self.assertTrue(rest.session.closed)
        # Multiple update listeners during an outage must not cause a login storm.
        self.assertEqual(self.calls["/mis/user/account/status"], 2)
        await asyncio.sleep(5.1)
        self.login_mode = "ok"
        data = await self.coordinator._async_update_data()
        self.assertEqual(data["statistics"]["total_cleanings"], 84)
        self.assertTrue(self.vacuum.is_initialized)
        self.assertIs(self.vacuum.rest, rest)
        self.assertIs(maps.rest, rest)
        self.assertIs(history.rest, rest)

        await self.vacuum.disconnect()
        with self.assertRaises(ConnectionError):
            await maps.rest.get_map_list(1)
        self.assertTrue(rest.session.closed)

    async def test_cancelled_initialization_closes_http_session(self):
        """An unload during a pending login cannot leave a session or MQTT task."""
        self.login_mode = "blocked"
        task = asyncio.create_task(self.vacuum.initialize())
        await asyncio.wait_for(self.login_started.wait(), timeout=3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.vacuum.rest.session.closed)
        self.assertFalse(self.vacuum.is_initialized)
        self.assertIsNone(self.vacuum._mqtt_task)


if __name__ == "__main__":
    unittest.main()

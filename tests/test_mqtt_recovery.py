"""Exercise MQTT recovery against a real local broker, without mocks.

Install tests/requirements.txt, then run unittest discover -s tests.
"""

import asyncio
import importlib.util
from pathlib import Path
import socket
import unittest

import aiomqtt
from amqtt.broker import Broker


CLIENT_PATH = (
    Path(__file__).parents[1]
    / "custom_components/tesvor/tesvorhome/mqtt/client_async.py"
)
SPEC = importlib.util.spec_from_file_location("tesvor_mqtt", CLIENT_PATH)
MQTT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MQTT)


class MQTTRecoveryTests(unittest.IsolatedAsyncioTestCase):
    """Verify transport recovery, subscription replay, and task cleanup."""

    async def asyncSetUp(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.broker = None
        self.messages = asyncio.Queue()
        self.connections = asyncio.Queue()
        self.client = MQTT.AsyncMQTTClient(
            "127.0.0.1", self.port, "test", "test", "tesvor-test",
            on_connect=self.request_status,
        )
        self.client.add_handler(self.messages.put_nowait)
        await self.client.subscribe("STATE_test")

    async def asyncTearDown(self) -> None:
        await self.client.disconnect()
        if self.broker is not None:
            await self.broker.shutdown()

    async def start_broker(self) -> None:
        self.broker = Broker({
            "listeners": {
                "default": {"type": "tcp", "bind": f"127.0.0.1:{self.port}"},
            },
            "plugins": {
                "amqtt.plugins.authentication.AnonymousAuthPlugin": {
                    "allow_anonymous": True,
                },
            },
        })
        await self.broker.start()

    async def request_status(self) -> None:
        """Publish a fresh-data request on every connection, as the robot does."""
        await self.client.publish("DP_APP_test", b"request-status")
        self.connections.put_nowait(True)

    async def exchange_messages(self) -> None:
        """Check both commands and status messages use the recovered session."""
        async with aiomqtt.Client("127.0.0.1", port=self.port) as peer:
            await peer.subscribe("DP_APP_test")
            await self.client.publish("DP_APP_test", b"command")
            command = await asyncio.wait_for(anext(peer.messages), timeout=3)
            self.assertEqual(command.payload, b"command")
            await peer.publish("STATE_test", b"docked")
            state = await asyncio.wait_for(self.messages.get(), timeout=3)
            self.assertEqual(state.payload, b"docked")

    async def test_broker_restart_restores_commands_and_status(self) -> None:
        """A dropped socket goes offline, reconnects, and restores both directions."""
        await self.start_broker()
        await asyncio.wait_for(self.client.connect(), timeout=3)
        await asyncio.wait_for(self.connections.get(), timeout=3)
        await self.exchange_messages()

        await self.broker.shutdown()
        self.broker = None
        async with asyncio.timeout(3):
            while self.client.is_connected:
                await asyncio.sleep(0.01)
        with self.assertRaises(ConnectionError):
            await self.client.publish("DP_APP_test", b"must-not-be-queued")

        await self.start_broker()
        await asyncio.wait_for(self.connections.get(), timeout=5)
        self.assertTrue(self.client.is_connected)
        await self.exchange_messages()

        await self.client.disconnect()
        self.assertFalse(self.client.is_connected)
        # Intentional shutdown must not start another connection or data request.
        await asyncio.sleep(1.2)
        self.assertTrue(self.connections.empty())

    async def test_initial_outage_and_unload_during_retry(self) -> None:
        """Initial failures recover; unloading cancels a pending connection."""
        pending = asyncio.create_task(self.client.connect())
        try:
            await asyncio.sleep(1.2)
            self.assertFalse(self.client.is_connected)
            self.assertFalse(pending.done())
            await self.start_broker()
            await asyncio.wait_for(pending, timeout=5)
            await asyncio.wait_for(self.connections.get(), timeout=3)
            await self.exchange_messages()
        finally:
            await self.client.disconnect()
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

        await self.broker.shutdown()
        self.broker = None
        pending = asyncio.create_task(self.client.connect())
        try:
            await asyncio.sleep(0.1)
            await self.client.disconnect()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            await self.start_broker()
            await asyncio.sleep(1.2)
            self.assertFalse(self.client.is_connected)
            self.assertTrue(self.connections.empty())
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


    async def test_publish_timeout_does_not_latch_transport_offline(self) -> None:
        """A live MQTT peer that misses PUBACK must not disable the client forever."""
        connections = set()
        self.client = MQTT.AsyncMQTTClient(
            "127.0.0.1", self.port, "test", "test", "tesvor-timeout-test",
        )

        async def mqtt_peer(reader, writer):
            connections.add(writer)
            try:
                while True:
                    header = (await reader.readexactly(1))[0]
                    length = 0
                    shift = 0
                    while True:
                        byte = (await reader.readexactly(1))[0]
                        length += (byte & 127) << shift
                        if byte < 128:
                            break
                        shift += 7
                    payload = await reader.readexactly(length)
                    if header >> 4 == 1:  # CONNECT -> CONNACK
                        writer.write(b"\x20\x02\x00\x00")
                    elif header >> 4 == 8:  # SUBSCRIBE -> SUBACK
                        writer.write(b"\x90\x03" + payload[:2] + b"\x01")
                    elif header >> 4 == 12:  # PINGREQ -> PINGRESP
                        writer.write(b"\xd0\x00")
                    elif header >> 4 == 14:  # DISCONNECT
                        break
                    # Deliberately omit PUBACK, while keeping the socket alive.
                    await writer.drain()
            except asyncio.IncompleteReadError:
                pass
            finally:
                connections.discard(writer)
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(mqtt_peer, "127.0.0.1", self.port)
        try:
            await asyncio.wait_for(self.client.connect(), timeout=3)
            with self.assertRaises(aiomqtt.MqttError):
                await self.client.publish("DP_APP_test", b"missing-ack", qos=1)
            self.assertTrue(self.client.is_connected)
            await self.client.publish("DP_APP_test", b"no-ack-needed", qos=0)
        finally:
            await self.client.disconnect()
            server.close()
            await server.wait_closed()
            for writer in list(connections):
                writer.close()



if __name__ == "__main__":
    unittest.main()

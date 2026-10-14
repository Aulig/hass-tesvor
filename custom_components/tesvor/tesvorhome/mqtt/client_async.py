"""
Asynchronous MQTT client using aiomqtt.
Optimized for Windows.
"""

import asyncio
import logging
from typing import Any, List, Callable, Awaitable, Optional

import aiomqtt

_LOGGER = logging.getLogger(__name__)


class AsyncMQTTClient:
    """
    Asynchronous MQTT client using aiomqtt.
    Special version for Windows.
    """

    def __init__(
        self, host: str, port: int, username: str, password: str, client_id: str,
        on_connect: Optional[Callable[[], Awaitable[Any]]] = None,
    ):
        """Initialize MQTT client."""
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client_id = client_id

        self._client: Optional[aiomqtt.Client] = None
        self._connection_task: Optional[asyncio.Task] = None
        self._ready = asyncio.Event()
        self._subscriptions: dict[str, int] = {}
        self._on_connect = on_connect
        self._handlers: List[Callable] = []
        self._connected = False
        self._should_run = True

    async def connect(self) -> None:
        """Start recovery and wait for the first successful connection."""
        if self._connection_task is not None:
            raise RuntimeError("MQTT connection task already started")
        self._should_run = True
        connection_task = asyncio.create_task(self._run())
        self._connection_task = connection_task
        ready_task = asyncio.create_task(self._ready.wait())
        try:
            await asyncio.wait(
                [connection_task, ready_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if connection_task.done():
                await connection_task
        finally:
            ready_task.cancel()
            try:
                await ready_task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        """Reconnect after network failures and restore subscriptions."""
        retry_delay = 1
        while self._should_run:
            try:
                # Add connection timeout. aiomqtt closes each session on exit.
                async with aiomqtt.Client(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    identifier=self.client_id,
                    keepalive=60,
                    timeout=10,
                ) as client:
                    self._client = client
                    for topic, qos in self._subscriptions.items():
                        await client.subscribe(topic, qos=qos)
                    self._connected = True
                    self._ready.set()
                    retry_delay = 1
                    _LOGGER.info(
                        "MQTT connected to %s:%s (client_id: %s)",
                        self.host, self.port, self.client_id,
                    )
                    if self._on_connect is not None:
                        await self._on_connect()
                    await self._listen()
            except aiomqtt.MqttError as error:
                _LOGGER.warning("MQTT connection lost: %s; retrying in %ss", error, retry_delay)
            finally:
                self._connected = False
                self._ready.clear()
                self._client = None

            # Keep retrying through long outages, with capped exponential backoff.
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)

    async def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        self._should_run = False
        self._connected = False

        # Stop the listener and reconnect loop before closing the MQTT session.
        if self._connection_task is not None:
            self._connection_task.cancel()
            try:
                await self._connection_task
            except asyncio.CancelledError:
                _LOGGER.debug("MQTT connection task cancelled")
            finally:
                self._connection_task = None

        _LOGGER.info("MQTT client disconnected")

    async def _listen(self) -> None:
        """Listener for incoming messages."""
        _LOGGER.info("MQTT listener started")

        async for message in self._client.messages:
            if not self._should_run:
                break

            # Log only important topics for debugging
            topic_str = str(message.topic)
            if topic_str.startswith(("MAP_", "STATE_", "DP_DEV_")):
                _LOGGER.debug("Received: %s (%s bytes)", message.topic, len(message.payload))

            # Pass message to all handlers
            for handler in self._handlers:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)

    async def publish(self, topic: str, payload: bytes, qos: int = 1) -> None:
        """Publish message."""
        if not self._connected or self._client is None:
            raise ConnectionError("MQTT not connected")

        try:
            await self._client.publish(topic, payload=payload, qos=qos)
            _LOGGER.debug("Published to %s: %s bytes", topic, len(payload))
        except aiomqtt.MqttError as e:
            self._connected = False
            self._ready.clear()
            _LOGGER.error("Error publishing to %s: %s", topic, e)
            raise

    async def subscribe(self, topic: str, qos: int = 1) -> None:
        """Remember a subscription, including before the first connection."""
        self._subscriptions[topic] = qos
        if self._connected and self._client is not None:
            await self._client.subscribe(topic, qos=qos)
        _LOGGER.info("Subscribed to %s (QoS %s)", topic, qos)

    def add_handler(self, handler) -> None:
        """Add message handler."""
        if handler not in self._handlers:
            self._handlers.append(handler)
            _LOGGER.debug("Added MQTT handler, total: %s", len(self._handlers))

    def remove_handler(self, handler) -> None:
        """Remove message handler."""
        if handler in self._handlers:
            self._handlers.remove(handler)
            _LOGGER.debug("Removed MQTT handler, remaining: %s", len(self._handlers))

    @property
    def is_connected(self) -> bool:
        """Check connection status."""
        return self._connected

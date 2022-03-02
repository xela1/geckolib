""" Gecko STATU/STATV/STATQ/STATP handlers """

import logging
import struct

from .packet import GeckoPacketProtocolHandler

STATU_VERB = b"STATU"
STATV_VERB = b"STATV"
STATQ_VERB = b"STATQ"
STATP_VERB = b"STATP"

REQUEST_FORMAT = ">BHH"
RESPONSE_FORMAT = ">BBB"

_LOGGER = logging.getLogger(__name__)


class GeckoStatusBlockProtocolHandler(GeckoPacketProtocolHandler):
    @staticmethod
    def request(seq, start, length, **kwargs):
        return GeckoStatusBlockProtocolHandler(
            start=start,
            content=b"".join(
                [STATU_VERB, struct.pack(REQUEST_FORMAT, seq, start, length)]
            ),
            timeout=2,
            retry_count=5,
            on_retry_failed=GeckoPacketProtocolHandler._default_retry_failed_handler,
            **kwargs,
        )

    @staticmethod
    def full_request(seq, **kwargs):
        return GeckoStatusBlockProtocolHandler.request(seq, 0, 1024, **kwargs)

    @staticmethod
    def response(index, next, block, **kwargs):
        return GeckoStatusBlockProtocolHandler(
            start=0,
            content=b"".join(
                [
                    STATV_VERB,
                    struct.pack(RESPONSE_FORMAT, index, next, len(block)),
                    block,
                ]
            ),
            **kwargs,
        )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.start = kwargs.get("start", None)
        self.sequence = self.length = self.next = self.data = None

    def can_handle(self, received_bytes: bytes, sender: tuple) -> bool:
        return received_bytes.startswith(STATU_VERB) or received_bytes.startswith(
            STATV_VERB
        )

    def handle(self, received_bytes: bytes, sender: tuple):
        remainder = received_bytes[5:]
        if received_bytes.startswith(STATU_VERB):
            self.sequence, self.start, self.length = struct.unpack(
                REQUEST_FORMAT, remainder
            )
            return  # Stay in the handler list

        # Otherwise must be STATV
        self.sequence, self.next, self.length = struct.unpack(
            RESPONSE_FORMAT, remainder[0:3]
        )
        self.data = remainder[3 : self.length + 3]
        _LOGGER.debug(
            "Status block segment # %d (then #%d) length %d, %r",
            self.sequence,
            self.next,
            self.length,
            self.data,
        )

    def __repr__(self):
        return (
            f"{super().__repr__()}(seq={self.sequence},start={self.start},"
            f"length={self.length},next={self.next},data={self.data})"
        )


class GeckoPartialStatusBlockProtocolHandler(GeckoPacketProtocolHandler):
    def __init__(self, socket, **kwargs):
        super().__init__(**kwargs)
        self._socket = socket
        self.changes = []

    def can_handle(self, received_bytes: bytes, sender: tuple) -> bool:
        return received_bytes.startswith(STATQ_VERB) or received_bytes.startswith(
            STATP_VERB
        )

    def handle(self, received_bytes: bytes, sender: tuple) -> None:
        remainder = received_bytes[5:]
        if received_bytes.startswith(STATQ_VERB):
            (self.sequence,) = struct.unpack(">B", remainder)
            return  # Stay in the handler list

        # Otherwise must be STATP
        self._socket.queue_send(
            GeckoPacketProtocolHandler(
                content=b"".join(
                    [
                        STATQ_VERB,
                        struct.pack(
                            ">B", self._socket.get_and_increment_sequence_counter()
                        ),
                    ]
                ),
                parms=sender,
            ),
            sender,
        )
        change_count = struct.unpack(">B", remainder[0:1])[0]
        for i in range(change_count):
            pos = struct.unpack(">H", remainder[1 + (i * 4) : 3 + (i * 4)])[0]
            self.changes.append((pos, remainder[3 + (i * 4) : 5 + (i * 4)]))


class GeckoAsyncPartialStatusBlockProtocolHandler(GeckoPacketProtocolHandler):
    def __init__(self, protocol, **kwargs):
        super().__init__(**kwargs)
        self._protocol = protocol
        self.changes = []

    def can_handle(self, received_bytes: bytes, sender: tuple) -> bool:
        return received_bytes.startswith(STATQ_VERB) or received_bytes.startswith(
            STATP_VERB
        )

    def handle(self, received_bytes: bytes, sender: tuple):
        pass

    async def async_handle(self, received_bytes: bytes, sender: tuple) -> None:
        remainder = received_bytes[5:]
        if received_bytes.startswith(STATQ_VERB):
            (self.sequence,) = struct.unpack(">B", remainder)
            return  # Stay in the handler list

        # Otherwise must be STATP
        self._protocol.queue_send(
            GeckoPacketProtocolHandler(
                content=b"".join(
                    [
                        STATQ_VERB,
                        struct.pack(
                            ">B", self._protocol.get_and_increment_sequence_counter()
                        ),
                    ]
                ),
                parms=sender,
            ),
        )

        change_count = struct.unpack(">B", remainder[0:1])[0]
        self.changes = []
        for i in range(change_count):
            pos = struct.unpack(">H", remainder[1 + (i * 4) : 3 + (i * 4)])[0]
            self.changes.append((pos, remainder[3 + (i * 4) : 5 + (i * 4)]))

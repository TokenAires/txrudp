"""Reliable UDP implementation using Twisted."""

import collections

from twisted.internet import protocol


class ConnectionMultiplexer(
    protocol.DatagramProtocol,
    collections.MutableMapping
):

    """
    Multiplexes many virtual connections over single UDP socket.

    Handles graceful shutdown of active connections.
    """

    def __init__(self, connection_factory, relaying=False):
        """
        Initialize a new multiplexer.

        Args:
            connection_factory: The connection factory used to
                instantiate new connections, as a
                connection.RUDPConnectionFactory.
            relaying: If True, the multiplexer will silently forward
                packets that are not targeting this node.
        """
        super(ConnectionMultiplexer, self).__init__()
        self.relaying = relaying
        self._active_connections = {}
        self._own_address = None
        self._connection_factory = connection_factory

    def makeConnection(self, transport):
        """
        Attach the protocol to the transport layer.

        Args:
            transport: A transport that is an instance of
                twisted.internet.interfaces.IUDPTransport and also
                implements `getHost` and `loseConnection` methods.
        """
        super(ConnectionMultiplexer, self).makeConnection(transport)
        assert transport.hasattr('getHost'), (
            'Transport does not provide `getHost` method.'
        )
        assert transport.hasattr('loseConnection'), (
            'Transport does not provide `loseConnection` method.'
        )
        self._own_address = self.transport.getHost()

    def __len__(self):
        """Return the number of live connections."""
        return len(self._active_connections)

    def __getitem__(self, addr):
        """
        Return the handling connection of the given address.

        Args:
            addr: Tuple of destination address (ip, port).

        Raises:
            KeyError: No connection is handling the given address.
        """
        return self._active_connections[addr]

    def __setitem__(self, addr, con):
        """
        Register a handling connection for a given remote address.

        If a previous connection is already bound to that address,
        it is shutdown and then replaced.

        Args:
            key: Tuple of destination address (ip, port).
            value: The connection to register, as an RUDPConnection
        """
        prev_con = self._active_connections.get(addr)
        if prev_con is not None:
            prev_con.shutdown()
        self._active_connections[addr] = con

    def __delitem__(self, addr):
        """
        Unregister a handling connection for a given remote address.

        Args:
            addr: Tuple of destination address (ip, port).

        Raises:
            KeyError: No connection is handling the given address.
        """
        del self._active_connections[addr]

    def __iter__(self):
        """Return iterator over the active contacts."""
        return iter(self._active_connections)

    def datagramReceived(self, datagram, addr):
        """
        Called when a datagram is received.

        If the datagram isn't meant for us, immediately relay it.
        Otherwise, delegate handling to the appropriate connection.
        If no such connection exists, create one. Always take care
        to avoid mistaking a relay address for the original sender's
        address.

        Args:
            datagram: Datagram string received from transport layer.
            addr: Sender address, as a tuple of an IPv4/IPv6 address
                and a port, in that order. If this address is
                different from the packet's source address, the packet
                is being relayed; future outbound packets should also
                be relayed through the specified relay address.
        """
        try:
            json_obj = json.loads(datagram)
            rudp_packet = packet.RUDPPacket.from_unvalidated_json(json_obj)
        except (ValueError, TypeError, jsonschema.ValidationError):
            log.err()
        else:
            dest_addr = (rudp_packet.dest_ip, rudp_packet.dest_port)
            if dest_addr != self._own_address:
                if self.relaying:
                    self.transport.write(datagram, dest_addr)
            else:
                source_addr = (rudp_packet.source_ip, rudp_packet.source_port)
                con = self._active_connections.get(source_addr)
                if con is None:
                    con = self.make_new_connection(
                        self._own_address,
                        source_addr,
                        addr
                    )
                con.receive_packet(datagram)

    def make_new_connection(self, own_addr, source_addr, relay_addr=None):
        """
        Create a new connection to handle the given address.

        Args:
            own_addr: Local host address, as a (ip, port) tuple.
            source_addr: Remote host address, as a (ip, port) tuple.
            relay_addr: Remote host address, as a (ip, port) tuple.

        Returns:
            A new connection.RUDPConnection
        """
        con = self._connection_factory.make_new_connection(
            self,
            own_addr,
            source_addr,
            relay_addr
        )
        self._active_connections[source_addr] = con
        return con

    def send_datagram(self, datagram, addr):
        """
        Send RUDP datagram to the given address.

        Args:
            datagram: Prepared RUDP datagram, as a string.
            addr: Tuple of destination address (ip, port).

        This is essentially a wrapper so that the transport layer is
        not exposed to the connections.
        """
        self.transport.write(datagram, addr)

    def shutdown(self):
        """Shutdown all active connections and then terminate protocol."""
        for connection in self._active_connections:
            connection.shutdown()
        self.transport.loseConnection()
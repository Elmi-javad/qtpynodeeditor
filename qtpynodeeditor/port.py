from qtpy.QtCore import QObject, Signal

from .base import ConnectionBase
from .enums import PortType, ConnectionPolicy


# TODO
PortIndex = int


def opposite_port(port: PortType):
    return {PortType.input: PortType.output,
            PortType.output: PortType.input}.get(port, PortType.none)


class Port(QObject):
    connection_created = Signal(ConnectionBase)
    connection_deleted = Signal(ConnectionBase)
    data_updated = Signal(QObject)
    data_invalidated = Signal(QObject)

    def __init__(self, node, *, port_type: PortType, index: PortIndex):
        super().__init__(parent=node)
        self.node = node
        self.port_type = port_type
        self.index = index
        self._connections = []
        self.opposite_port = {PortType.input: PortType.output,
                              PortType.output: PortType.input}[self.port_type]

    @property
    def connections(self):
        return list(self._connections)

    @property
    def data_model(self):
        return self.node.data

    @property
    def data(self):
        if self.port_type == PortType.input:
            # return self.model.in_data(self.index)
            # TODO
            return
        else:
            return self.model.out_data(self.index)

    @property
    def can_connect(self):
        return (not self._connections or
                self.connection_policy == ConnectionPolicy.many)

    @property
    def caption(self):
        return self.model.port_caption[self.port_type][self.index]

    @property
    def caption_visible(self):
        return self.model.port_caption_visible[self.port_type][self.index]

    @property
    def data_type(self):
        return self.model.data_type[self.port_type][self.index]

    @property
    def display_text(self):
        return (self.caption
                if self.caption_visible
                else self.data_type.name)

    @property
    def connection_policy(self):
        if self.port_type == PortType.input:
            return ConnectionPolicy.one
        else:
            return self.model.port_out_connection_policy(self.index)

    def add_connection(self, connection: ConnectionBase):
        if connection in self._connections:
            raise ValueError('Connection already in list')

        self._connections.append(connection)
        self.connection_created.emit(connection)

    def remove_connection(self, connection: ConnectionBase):
        try:
            self._connections.remove(connection)
        except ValueError:
            # TODO: should not be reaching this
            ...
        else:
            self.connection_deleted.emit(connection)

    @property
    def scene_position(self):
        return self.node.geometry.port_scene_position(self.port_type,
                                                      self.index)

    def get_mapped_scene_position(self, transform):
        """
        Node port scene position after a transform

        Parameters
        ----------
        port_type : PortType
        port_index : PortIndex

        Returns
        -------
        value : QPointF
        """
        ngo = self.node.graphics_object
        return ngo.sceneTransform().map(self.scene_position)

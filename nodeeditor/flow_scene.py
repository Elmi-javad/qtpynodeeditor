import os
import json
from qtpy.QtCore import (QByteArray, QDir, QFile, QFileInfo, QIODevice,
                         QJsonDocument, QPoint, QPointF, QSizeF, QUuid, Qt)
from qtpy.QtCore import Signal
from qtpy.QtWidgets import QFileDialog, QGraphicsScene

from .connection import Connection
from .connection_graphics_object import ConnectionGraphicsObject
from .data_model_registry import DataModelRegistry
from .node import Node
from .node_data import NodeDataType, NodeDataModel
from .node_graphics_object import NodeGraphicsObject
from .port import PortType, PortIndex
from .type_converter import TypeConverter, DefaultTypeConverter


def locate_node_at(scene_point, scene, view_transform):
    # items under cursor
    items = scene.items(scene_point, Qt.IntersectsItemShape,
                        Qt.DescendingOrder, view_transform)
    filtered_items = [item for item in items
                      if isinstance(item, NodeGraphicsObject)]
    return filtered_items[0].node() if filtered_items else None


class FlowScene(QGraphicsScene):
    connection_created = Signal(Connection)
    connection_deleted = Signal(Connection)
    connection_hover_left = Signal(Connection)
    connection_hovered = Signal(Connection, QPoint)

    # Node has been created but not on the scene yet. (see: node_placed())
    node_created = Signal(Node)

    #  Node has been added to the scene.
    #  Connect to self signal if need a correct position of node.
    node_placed = Signal(Node)
    node_context_menu = Signal(Node, QPointF)
    node_deleted = Signal(Node)
    node_double_clicked = Signal(Node)
    node_hover_left = Signal(Node)
    node_hovered = Signal(Node, QPoint)
    node_moved = Signal(Node, QPointF)

    def __init__(self, registry=None, parent=None):
        super().__init__(parent=parent)
        self._connections = []
        self._nodes = {}
        if registry is None:
            registry = DataModelRegistry()

        self._registry = registry
        self.setItemIndexMethod(QGraphicsScene.NoIndex)

        # self connection should come first
        self.connection_created.connect(self.setup_connection_signals)
        self.connection_created.connect(self.send_connection_created_to_nodes)
        self.connection_deleted.connect(self.send_connection_deleted_to_nodes)

    def _cleanup(self):
        self.clear_scene()

    def __del__(self):
        try:
            self._cleanup()
        except Exception:
            ...

    def locate_node_at(self, point, transform):
        return locate_node_at(point, self, transform)

    def create_connection_node(self, connected_port: PortType, node: Node, port_index: PortIndex) -> Connection:
        """
        create_connection

        Parameters
        ----------
        connected_port : PortType
        node : Node
        port_index : PortIndex

        Returns
        -------
        value : Connection
        """
        connection = Connection.from_node(connected_port, node, port_index)
        cgo = ConnectionGraphicsObject(self, connection)

        # after self function connection points are set to node port
        connection.set_graphics_object(cgo)
        self._connections.append(connection)

        # Note: self connection isn't truly created yet. It's only partially created.
        # Thus, don't send the connection_created(...) signal.
        connection.connection_completed.connect(self.connection_created.emit)
        return connection

    def create_connection(self,
                          node_in: Node, port_index_in: PortIndex,
                          node_out: Node, port_index_out: PortIndex,
                          converter: TypeConverter) -> Connection:
        """
        create_connection

        Parameters
        ----------
        node_in : Node
        port_index_in : PortIndex
        node_out : Node
        port_index_out : PortIndex
        converter : TypeConverter

        Returns
        -------
        value : Connection
        """
        connection = Connection.from_nodes(node_in, port_index_in,
                                           node_out, port_index_out,
                                           converter=converter)
        cgo = ConnectionGraphicsObject(self, connection)
        node_in.node_state().set_connection(PortType.In, port_index_in, connection)
        node_out.node_state().set_connection(PortType.Out, port_index_out, connection)

        # after self function connection points are set to node port
        connection.set_graphics_object(cgo)

        # trigger data propagation
        node_out.on_data_updated(port_index_out)
        self._connections.append(connection)
        self.connection_created.emit(connection)
        return connection

    def restore_connection(self, connection_json: dict) -> Connection:
        """
        restore_connection

        Parameters
        ----------
        connection_json : dict

        Returns
        -------
        value : Connection
        """
        node_in_id = QUuid(connection_json["in_id"])
        node_out_id = QUuid(connection_json["out_id"])

        port_index_in = connection_json["in_index"]
        port_index_out = connection_json["out_index"]
        node_in = self._nodes[node_in_id]
        node_out = self._nodes[node_out_id]

        def get_converter():
            converter = connection_json.get("converter", None)
            if converter is not None:
                return DefaultTypeConverter

            in_type = NodeDataType(
                id=converter["in"]["id"],
                name=converter["in"]["name"],
            )

            out_type = NodeDataType(
                id=converter["out"]["id"],
                name=converter["out"]["name"],
            )

            return self._registry.get_type_converter(out_type, in_type)

        connection = self.create_connection(
            node_in, port_index_in,
            node_out, port_index_out,
            converter=get_converter())

        # Note: the connection_created(...) signal has already been sent by
        # create_connection(...)
        return connection

    def delete_connection(self, connection: Connection):
        """
        delete_connection

        Parameters
        ----------
        connection : Connection
        """
        try:
            self._connections.remove(connection)
        except ValueError:
            ...
        else:
            connection.remove_from_nodes()

    def create_node(self, data_model: NodeDataModel) -> Node:
        """
        create_node

        Parameters
        ----------
        data_model : unique_ptr<NodeDataModel

        Returns
        -------
        value : Node
        """
        node = Node(data_model)
        ngo = NodeGraphicsObject(self, node)
        node.set_graphics_object(ngo)

        self._nodes[node.id()] = node
        self.node_created.emit(node)
        return node

    def restore_node(self, node_json: dict) -> Node:
        """
        restore_node

        Parameters
        ----------
        node_json : dict

        Returns
        -------
        value : Node
        """
        model_name = node_json["model"]["name"]
        data_model = self._registry.create(model_name)
        if not data_model:
            raise ValueError("No registered model with name {}".format(model_name))
        node = Node(data_model)
        node.set_graphics_object(NodeGraphicsObject(self, node))
        node.restore(node_json)

        self._nodes[node.id()] = node
        self.node_created.emit(node)
        return node

    def remove_node(self, node: Node):
        """
        remove_node

        Parameters
        ----------
        node : Node
        """
        # call signal
        self.node_deleted.emit(node)
        for conn in list(node.node_state().all_connections):
            self.delete_connection(conn)

        node._cleanup()
        del self._nodes[node.id()]

    def registry(self) -> DataModelRegistry:
        """
        registry

        Returns
        -------
        value : DataModelRegistry
        """
        return self._registry

    def set_registry(self, registry: DataModelRegistry):
        """
        set_registry

        Parameters
        ----------
        registry : DataModelRegistry
        """
        self._registry = registry

    def iterate_over_nodes(self, visitor: callable):
        """
        iterate_over_nodes

        Parameters
        ----------
        visitor callable(Node)
        """
        for node in self._nodes.values():
            visitor(node)

    def iterate_over_node_data(self, visitor: callable):
        """
        iterate_over_node_data

        Parameters
        ----------
        visitor : callable(NodeDataModel)
        """
        for node in self._nodes.values():
            visitor(node.node_data_model())

    def iterate_over_node_data_dependent_order(self, visitor: callable):
        """
        iterate_over_node_data_dependent_order

        Parameters
        ----------
        visitor : callable(NodeDataModel)
        """
        # void
        # FlowScene::
        # iterate_over_node_data_dependent_order(std::function<void(NodeDataModel*)> const & visitor)
        # {
        #   std::set<QUuid> visited_nodes;

        #   //A leaf node is a node with no input ports, or all possible input ports empty
        #   auto is_node_leaf =
        #     [](Node const &node, NodeDataModel const &model)
        #     {
        #       for (unsigned int i = 0; i < model.n_ports(PortType::In); ++i)
        #       {
        #         auto connections = node.node_state().connections(PortType::In, i);
        #         if (not connections.empty())
        #         {
        #           return False;
        #         }
        #       }

        #       return True;
        #     };

        #   //Iterate over "leaf" nodes
        #   for (auto const &_node : _nodes)
        #   {
        #     auto const &node = _node.second;
        #     auto model       = node->node_data_model();

        #     if (is_node_leaf(node, model))
        #     {
        #       visitor(model);
        #       visited_nodes.insert(node->id());
        #     }
        #   }

        #   auto are_node_inputs_visited_before =
        #     [&](Node const &node, NodeDataModel const &model)
        #     {
        #       for (size_t i = 0; i < model.n_ports(PortType::In); ++i)
        #       {
        #         auto connections = node.node_state().connections(PortType::In, i);

        #         for (auto& conn : connections)
        #         {
        #           if (visited_nodes.find(conn.second->get_node(PortType::Out)->id()) == visited_nodes.end())
        #           {
        #             return False;
        #           }
        #         }
        #       }

        #       return True;
        #     };

        #   //Iterate over dependent nodes
        #   while (_nodes.size() != visited_nodes.size())
        #   {
        #     for (auto const &_node : _nodes)
        #     {
        #       auto const &node = _node.second;
        #       if (visited_nodes.find(node->id()) != visited_nodes.end())
        #         continue;

        #       auto model = node->node_data_model();

        #       if (are_node_inputs_visited_before(node, model))
        #       {
        #         visitor(model);
        #         visited_nodes.insert(node->id());
        #       }
        #     }
        #   }
        # }
        visited_nodes = []

        # A leaf node is a node with no input ports, or all possible input ports empty
        def is_node_leaf(node, model):
            for i in range(model.n_ports(PortType.In)):
                connections = node.node_state().connections(PortType.In, i)
                if connections is None:
                    return False

            return True

        # Iterate over "leaf" nodes
        for node in self._nodes.values():
            model = node.node_data_model()
            if is_node_leaf(node, model):
                visitor(model)
                visited_nodes.append(node)

        def are_node_inputs_visited_before(node, model):
            for i in range(model.n_ports(PortType.In)):
                connections = node.node_state().connections(PortType.In, i)
                for conn in connections:
                    other = conn.get_node(PortType.Out)
                    if visited_nodes and other == visited_nodes[-1]:
                        return False
            return True

        # Iterate over dependent nodes
        while len(self._nodes) != len(visited_nodes):
            for node in self._nodes.values():
                if node in visited_nodes and node is not visited_nodes[-1]:
                    continue

                model = node.node_data_model()
                if are_node_inputs_visited_before(node, model):
                    visitor(model)
                    visited_nodes.append(node)

    def get_node_position(self, node: Node) -> QPointF:
        """
        get_node_position

        Parameters
        ----------
        node : Node

        Returns
        -------
        value : QPointF
        """
        return node.node_graphics_object().pos()

    def set_node_position(self, node: Node, pos: QPointF):
        """
        set_node_position

        Parameters
        ----------
        node : Node
        pos : QPointF
        """
        ngo = node.node_graphics_object()
        ngo.setPos(pos)
        ngo.move_connections()

    def get_node_size(self, node: Node) -> QSizeF:
        """
        get_node_size

        Parameters
        ----------
        node : Node

        Returns
        -------
        value : QSizeF
        """
        return QSizeF(node.node_geometry().width(), node.node_geometry().height())

    def nodes(self) -> dict:
        """
        nodes

        Returns
        -------
        value : dict
            Key: QUuid
            Value: Node
        """
        return dict(self._nodes)

    def connections(self) -> dict:
        """
        connections

        Returns
        -------
        conn : list of Connection
        """
        return list(self._connections)

    def selected_nodes(self) -> list:
        """
        selected_nodes

        Returns
        -------
        value : list of Node
        """
        return [item.node() for item in self.selectedItems()
                if isinstance(item, NodeGraphicsObject)]

    def clear_scene(self):
        # Manual node cleanup. Simply clearing the holding datastructures
        # doesn't work, the code crashes when there are both nodes and
        # connections in the scene. (The data propagation internal logic tries
        # to propagate data through already freed connections.)
        for conn in list(self._connections):
            self.delete_connection(conn)

        for node in list(self._nodes.values()):
            self.remove_node(node)

    def save(self, file_name=None):
        if file_name is None:
            file_name, _ = QFileDialog.getSaveFileName(
                None, "Open Flow Scene", QDir.homePath(),
                "Flow Scene Files (.flow)")

        if file_name:
            if not file_name.endswith(".flow"):
                file_name += ".flow"

            with open(file_name, 'wt') as f:
                json.dump(self.save_to_memory(), f)

    def load(self, file_name=None):
        self.clear_scene()

        if file_name is None:
            file_name, _ = QFileDialog.getOpenFileName(
                None, "Open Flow Scene", QDir.homePath(),
                "Flow Scene Files (.flow)")

        if not os.path.exists(file_name):
            return

        with open(file_name, 'rt') as f:
            self.load_from_memory(f.read())

    def save_to_memory(self) -> dict:
        """
        save_to_memory

        Returns
        -------
        value : dict
        """
        scene_json = {}
        nodes_json_array = []
        connection_json_array = []
        for node in self._nodes.values():
            nodes_json_array.append(node.save())

        scene_json["nodes"] = nodes_json_array
        for connection in self._connections:
            connection_json = connection.save()
            if not connection_json.isEmpty():
                connection_json_array.append(connection_json)

        scene_json["connections"] = connection_json_array
        return scene_json

    def load_from_memory(self, doc: str):
        """
        load_from_memory

        Parameters
        ----------
        doc : str or dict
            JSON-formatted string or dictionary of settings
        """
        if not isinstance(doc, dict):
            doc = json.loads(doc)

        for node in doc["nodes"]:
            self.restore_node(node)

        for connection in doc["connections"]:
            self.restore_connection(connection)

    def setup_connection_signals(self, c: Connection):
        """
        setup_connection_signals

        Parameters
        ----------
        c : Connection
        """
        c.connection_made_incomplete.connect(self.connection_deleted, Qt.UniqueConnection)

    def send_connection_created_to_nodes(self, c: Connection):
        """
        send_connection_created_to_nodes

        Parameters
        ----------
        c : Connection
        """
        from_ = c.get_node(PortType.Out)
        to = c.get_node(PortType.In)
        assert from_ is not None
        assert to is not None
        from_.node_data_model().output_connection_created(c)
        to.node_data_model().input_connection_created(c)

    def send_connection_deleted_to_nodes(self, c: Connection):
        """
        send_connection_deleted_to_nodes

        Parameters
        ----------
        c : Connection
        """
        from_ = c.get_node(PortType.Out)
        to = c.get_node(PortType.In)
        assert from_ is not None
        assert to is not None
        from_.node_data_model().output_connection_deleted(c)
        to.node_data_model().input_connection_deleted(c)

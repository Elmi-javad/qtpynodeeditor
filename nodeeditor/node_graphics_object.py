from qtpy.QtCore import QPoint, QRectF, QSize, QVariant, Qt
from qtpy.QtGui import QCursor, QPainter
from qtpy.QtWidgets import (QGraphicsItem, QGraphicsObject,
                            QGraphicsProxyWidget,
                            QGraphicsSceneContextMenuEvent,
                            QGraphicsSceneHoverEvent, QGraphicsSceneMouseEvent,
                            QStyleOptionGraphicsItem, QWidget,
                            QGraphicsDropShadowEffect)


from .enums import ConnectionPolicy
from .node_connection_interaction import NodeConnectionInteraction
from .port import PortType, INVALID


class NodeGraphicsObject(QGraphicsObject):
    def __init__(self, scene, node):
        super().__init__()
        self._scene = scene
        self._node = node
        self._locked = False
        self._proxy_widget = None

        self._scene.addItem(self)

        self.setFlag(QGraphicsItem.ItemDoesntPropagateOpacityToChildren, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsScenePositionChanges, True)

        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

        node_style = node.node_data_model().node_style()

        effect = QGraphicsDropShadowEffect()
        effect.setOffset(4, 4)
        effect.setBlurRadius(20)
        effect.setColor(node_style.shadow_color)

        self.setGraphicsEffect(effect)
        self.setOpacity(node_style.opacity)
        self.setAcceptHoverEvents(True)
        self.setZValue(0)

        self.embed_q_widget()

        # connect to the move signals to emit the move signals in FlowScene
        def on_move():
            self._scene.node_moved.emit(self._node, self.pos())

        self.xChanged.connect(on_move)
        self.yChanged.connect(on_move)

    def _cleanup(self):
        if self._scene is not None:
            self._scene.removeItem(self)
            self._scene = None

    def __del__(self):
        try:
            self._cleanup()
        except Exception:
            ...

    def node(self):
        """
        node

        Returns
        -------
        value : Node
        """
        return self._node

    def boundingRect(self) -> QRectF:
        """
        boundingRect

        Returns
        -------
        value : QRectF
        """
        return self._node.node_geometry().bounding_rect()

    def set_geometry_changed(self):
        self.prepareGeometryChange()

    def move_connections(self):
        """
        Visits all attached connections and corrects their corresponding end points.
        """
        for conn in self._node.node_state().all_connections:
            conn.get_connection_graphics_object().move()

    def lock(self, locked: bool):
        """
        lock

        Parameters
        ----------
        locked : bool
        """
        self._locked = locked
        self.setFlag(QGraphicsItem.ItemIsMovable, not locked)
        self.setFlag(QGraphicsItem.ItemIsFocusable, not locked)
        self.setFlag(QGraphicsItem.ItemIsSelectable, not locked)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget):
        """
        paint

        Parameters
        ----------
        painter : QPainter
        option : QStyleOptionGraphicsItem
        widget : QWidget
        """
        from .node_painter import NodePainter
        # TODO
        painter.setClipRect(option.exposedRect)
        NodePainter.paint(painter, self._node, self._scene)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: QVariant) -> QVariant:
        """
        itemChange

        Parameters
        ----------
        change : QGraphicsItem.GraphicsItemChange
        value : QVariant

        Returns
        -------
        value : QVariant
        """
        if change == self.ItemPositionChange and self.scene():
            self.move_connections()

        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        """
        mousePressEvent

        Parameters
        ----------
        event : QGraphicsSceneMouseEvent
        """
        if self._locked:
            return

        # deselect all other items after self one is selected
        if not self.isSelected() and not (event.modifiers() & Qt.ControlModifier):
            self._scene.clearSelection()

        node_geometry = self._node.node_geometry()

        for port_to_check in (PortType.In, PortType.Out):
            # TODO do not pass sceneTransform
            port_index = node_geometry.check_hit_scene_point(port_to_check,
                                                             event.scenePos(),
                                                             self.sceneTransform())
            if port_index == INVALID:
                continue

            node_state = self._node.node_state()
            connections = node_state.connections(port_to_check, port_index)

            # start dragging existing connection
            if connections and port_to_check == PortType.In:
                conn, = connections
                interaction = NodeConnectionInteraction(self._node, conn, self._scene)
                interaction.disconnect(port_to_check)
            elif port_to_check == PortType.Out:
                # initialize new Connection
                out_policy = self._node.node_data_model().port_out_connection_policy(port_index)
                if connections and out_policy == ConnectionPolicy.One:
                    conn, = connections
                    self._scene.delete_connection(conn)

                # TODO_UPSTREAM: add to FlowScene
                connection = self._scene.create_connection_node(port_to_check, self._node, port_index)
                self._node.node_state().set_connection(port_to_check, port_index, connection)
                connection.get_connection_graphics_object().grabMouse()

        pos = QPoint(event.pos().x(), event.pos().y())
        geom = self._node.node_geometry()
        state = self._node.node_state()
        if self._node.node_data_model().resizable() and geom.resize_rect().contains(pos):
            state.set_resizing(True)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        """
        mouseMoveEvent

        Parameters
        ----------
        event : QGraphicsSceneMouseEvent
        """
        geom = self._node.node_geometry()
        state = self._node.node_state()
        if state.resizing():
            diff = event.pos() - event.lastPos()
            w = self._node.node_data_model().embedded_widget()
            if w:
                self.prepareGeometryChange()
                old_size = w.size() + QSize(diff.x(), diff.y())
                w.setFixedSize(old_size)
                self._proxy_widget.setMinimumSize(old_size)
                self._proxy_widget.setMaximumSize(old_size)
                self._proxy_widget.setPos(geom.widget_position())
                geom.recalculate_size()
                self.update()
                self.move_connections()
                event.accept()
        else:
            super().mouseMoveEvent(event)
            if event.lastPos() != event.pos():
                self.move_connections()
            event.ignore()

        bounding = self.mapToScene(self.boundingRect()).boundingRect()
        r = self.scene().sceneRect().united(bounding)
        self.scene().setSceneRect(r)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        """
        mouseReleaseEvent

        Parameters
        ----------
        event : QGraphicsSceneMouseEvent
        """
        state = self._node.node_state()
        state.set_resizing(False)
        super().mouseReleaseEvent(event)

        # position connections precisely after fast node move
        self.move_connections()

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent):
        """
        hoverEnterEvent

        Parameters
        ----------
        event : QGraphicsSceneHoverEvent
        """
        # void
        # bring all the colliding nodes to background
        overlap_items = self.collidingItems()
        for item in overlap_items:
            if item.zValue() > 0.0:
                item.setZValue(0.0)

        # bring self node forward
        self.setZValue(1.0)
        self._node.node_geometry().set_hovered(True)
        self.update()
        self._scene.node_hovered.emit(self.node(), event.screenPos())
        event.accept()

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
        """
        hoverLeaveEvent

        Parameters
        ----------
        event : QGraphicsSceneHoverEvent
        """
        self._node.node_geometry().set_hovered(False)
        self.update()
        self._scene.node_hover_left.emit(self.node())
        event.accept()

    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent):
        """
        hoverMoveEvent

        Parameters
        ----------
        q_graphics_scene_hover_event : QGraphicsSceneHoverEvent
        """
        pos = event.pos()
        geom = self._node.node_geometry()
        if self._node.node_data_model().resizable() and geom.resize_rect().contains(
            QPoint(pos.x(), pos.y())
        ):
            self.setCursor(QCursor(Qt.SizeFDiagCursor))
        else:
            self.setCursor(QCursor())

        event.accept()

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent):
        """
        mouseDoubleClickEvent

        Parameters
        ----------
        event : QGraphicsSceneMouseEvent
        """
        super().mouseDoubleClickEvent(event)
        self._scene.node_double_clicked.emit(self.node())

    def contextMenuEvent(self, event: QGraphicsSceneContextMenuEvent):
        """
        contextMenuEvent

        Parameters
        ----------
        event : QGraphicsSceneContextMenuEvent
        """
        self._scene.node_context_menu.emit(self.node(),
                                           self.mapToScene(event.pos()))

    def embed_q_widget(self):
        geom = self._node.node_geometry()
        w = self._node.node_data_model().embedded_widget()
        if w is not None:
            self._proxy_widget = QGraphicsProxyWidget(self)
            self._proxy_widget.setWidget(w)
            self._proxy_widget.setPreferredWidth(5)
            geom.recalculate_size()
            self._proxy_widget.setPos(geom.widget_position())
            self.update()
            self._proxy_widget.setOpacity(1.0)
            self._proxy_widget.setFlag(QGraphicsItem.ItemIgnoresParentOpacity)

import logging
import contextlib
import threading

from qtpy.QtWidgets import (QWidget, QLineEdit, QApplication, QLabel)
from qtpy.QtGui import QDoubleValidator

import nodeeditor
from nodeeditor import (NodeData, NodeDataModel, NodeDataType, PortType,
                        NodeValidationState, PortIndex
                        )


class DecimalData(NodeData):
    'Node data holding a decimal (floating point) number'
    data_type = NodeDataType("decimal", "Decimal")

    def __init__(self, number: float = 0.0):
        self._number = number
        self._lock = threading.RLock()

    @property
    def lock(self):
        return self._lock

    @property
    def number(self) -> float:
        'The number data'
        return self._number

    def number_as_text(self) -> str:
        'Number as a string'
        return '%g' % self._number


class IntegerData(NodeData):
    'Node data holding an integer value'
    data_type = NodeDataType("integer", "Integer")

    def __init__(self, number: int = 0):
        self._number = number
        self._lock = threading.RLock()

    @property
    def lock(self):
        return self._lock

    def number(self) -> int:
        'The number data'
        return self._number

    def number_as_text(self) -> str:
        'Number as a string'
        return str(self._number)


class MathOperationDataModel(NodeDataModel):
    def __init__(self, style=None, parent=None):
        super().__init__(style=style, parent=parent)
        self._number1 = None
        self._number2 = None
        self._result = None
        self._validation_state = NodeValidationState.warning
        self._validation_message = 'Uninitialized'

    def caption(self) -> str:
        return self.name

    def caption_visible(self) -> bool:
        return True

    def n_ports(self, port_type: PortType) -> int:
        if port_type == PortType.input:
            return 2
        elif port_type == PortType.output:
            return 1

        raise ValueError('Unknown port type')

    def port_caption_visible(self, port_type: PortType, port_index: PortIndex) -> bool:
        return True

    def _check_inputs(self):
        number1_ok = (self._number1 is not None and
                      self._number1.data_type.id in ('Decimal', 'integer'))
        number2_ok = (self._number2 is not None and
                      self._number2.data_type.id in ('Decimal', 'integer'))

        if not number1_ok or not number2_ok:
            self._validation_state = NodeValidationState.warning
            self._validation_message = "Missing or incorrect inputs"
            self._result = None
            self.data_updated.emit(0)
            return False

        self._validation_state = NodeValidationState.valid
        self._validation_message = ''
        return True

    @contextlib.contextmanager
    def _compute_lock(self):
        if not self._number1 or not self._number2:
            raise RuntimeError('inputs unset')

        with self._number1.lock:
            with self._number2.lock:
                yield

        self.data_updated.emit(0)

    def data_type(self, port_type: PortType, port_index: PortIndex) -> NodeDataType:
        return DecimalData.data_type

    def out_data(self, port: PortIndex) -> NodeData:
        '''
        The output data as a result of this calculation

        Parameters
        ----------
        port : PortIndex

        Returns
        -------
        value : NodeData
        '''
        return self._result

    def set_in_data(self, data: NodeData, port_index: PortIndex):
        '''
        New data at the input of the node

        Parameters
        ----------
        data : NodeData
        port_index : PortIndex
        '''
        if port_index == 0:
            self._number1 = data
        elif port_index == 1:
            self._number2 = data

        if self._check_inputs():
            with self._compute_lock():
                self.compute()

    def validation_state(self) -> NodeValidationState:
        return self._validation_state

    def validation_message(self) -> str:
        return self._validation_message

    def compute(self):
        ...


class AdditionModel(MathOperationDataModel):
    name = "Addition"

    def compute(self):
        self._result = DecimalData(self._number1.number + self._number2.number)


class DivisionModel(MathOperationDataModel):
    name = "Division"

    def port_caption(self, port_type: PortType, port_index: PortIndex) -> str:
        if port_type == PortType.input:
            if port_index == 0:
                return 'Dividend'
            elif port_index == 1:
                return 'Divisor'
        elif port_type == PortType.output:
            return 'Result'


    def compute(self):
        if self._number2.number == 0.0:
            self._validation_state = NodeValidationState.error
            self._validation_message = "Division by zero error"
            self._result = None
        else:
            self._validation_state = NodeValidationState.valid
            self._validation_message = ''
            self._result = DecimalData(self._number1.number / self._number2.number)


class ModuloModel(MathOperationDataModel):
    name = 'Modulo'

    def port_caption(self, port_type: PortType, port_index: PortIndex) -> str:
        if port_type==PortType.input:
            if port_index == 0:
                return 'Dividend'
            elif port_index == 1:
                return 'Divisor'
        elif port_type == PortType.output:
            return 'Result'

    def data_type(self, port_type: PortType, port_index: PortIndex) -> NodeDataType:
        return IntegerData.data_type

    def compute(self):
        if self._number2.number == 0.0:
            self._validation_state = NodeValidationState.error
            self._validation_message = "Division by zero error"
            self._result = None
        else:
            self._result = IntegerData(self._number1.number % self._number2.number)


class MultiplicationModel(MathOperationDataModel):
    name = 'Multiplication'

    def port_caption(self, port_type: PortType, port_index: PortIndex) -> str:
        if port_type==PortType.input:
            if port_index == 0:
                return 'A'
            elif port_index == 1:
                return 'B'
        elif port_type == PortType.output:
            return 'Result'

    def compute(self):
            self._result = DecimalData(self._number1.number * self._number2.number)


class NumberSourceDataModel(NodeDataModel):
    name = "NumberSource"

    def __init__(self, style=None, parent=None):
        super().__init__(style=style, parent=parent)
        self._number = None
        self._line_edit = QLineEdit()
        self._line_edit.setValidator(QDoubleValidator())
        self._line_edit.setMaximumSize(self._line_edit.sizeHint())
        self._line_edit.textChanged.connect(self.on_text_edited)
        self._line_edit.setText("0.0")

    @property
    def number(self):
        return self._number

    def caption(self) -> str:
        return "Number Source"

    def caption_visible(self) -> bool:
        return False

    def save(self) -> dict:
        'Add to the JSON dictionary to save the state of the NumberSource'
        doc = super().save()
        if self._number:
            doc['number'] = self._number.number
        return doc

    def restore(self, state: dict):
        'Restore the number from the JSON dictionary'
        try:
            value = float(state["number"])
        except Exception:
            ...
        else:
            self._number = DecimalData(value)
            self._line_edit.setText(self._number.number_as_text())

    def n_ports(self, port_type: PortType) -> int:
        if port_type == PortType.input:
            return 0
        elif port_type == PortType.output:
            return 1
        raise ValueError('Unknown port type')

    def data_type(self, port_type: PortType, port_index: PortIndex) -> NodeDataType:
        return DecimalData.data_type

    def out_data(self, port: PortIndex) -> NodeData:
        '''
        The data output from this node

        Parameters
        ----------
        port : PortIndex

        Returns
        -------
        value : NodeData
        '''
        return self._number

    def embedded_widget(self) -> QWidget:
        'The number source has a line edit widget for the user to type in'
        return self._line_edit

    def on_text_edited(self, string: str):
        '''
        Line edit text has changed

        Parameters
        ----------
        string : str
        '''
        try:
            number = float(self._line_edit.text())
        except ValueError:
            self._data_invalidated.emit(0)
        else:
            self._number = DecimalData(number)
            self.data_updated.emit(0)


class NumberDisplayModel(NodeDataModel):
    name = "NumberDisplay"

    def __init__(self, style=None, parent=None):
        super().__init__(style=style, parent=parent)
        self._number = None
        self._label = QLabel()
        self._label.setMargin(3)
        self._validation_state = NodeValidationState.warning
        self._validation_message = 'Uninitialized'

    def caption_visible(self) -> bool:
        return False

    def n_ports(self, port_type: PortType) -> int:
        if port_type == PortType.input:
            return 1
        elif port_type == PortType.output:
            return 0
        raise ValueError('Unknown port type')

    def data_type(self, port_type: PortType, port_index: PortIndex) -> NodeDataType:
        return DecimalData.data_type

    def set_in_data(self, data: NodeData, int: int):
        '''
        New data propagated to the input

        Parameters
        ----------
        data : NodeData
        int : int
        '''
        self._number = data
        number_ok = (self._number is not None and
                     self._number.data_type.id in ('Decimal', 'integer'))

        if number_ok:
            self._validation_state = NodeValidationState.valid
            self._validation_message = ''
            self._label.setText(self._number.number_as_text())
        else:
            self._validation_state = NodeValidationState.warning
            self._validation_message = "Missing or incorrect inputs"
            self._label.clear()

        self._label.adjustSize()

    def embedded_widget(self) -> QWidget:
        'The number display has a label'
        return self._label


class SubtractionModel(MathOperationDataModel):
    name = "Subtraction"

    def port_caption(self, port_type: PortType, port_index: PortIndex) -> str:
        if port_type==PortType.input:
            if port_index == 0:
                return 'Minuend'
            elif port_index == 1:
                return 'Subtrahend'
        elif port_type == PortType.output:
            return 'Result'

    def compute(self):
        self._validation_state = NodeValidationState.valid
        self._validation_message = ''
        self._result = DecimalData(self._number1.number - self._number2.number)


def integer_to_decimal_converter(data: IntegerData) -> DecimalData:
    '''
    integer_to_decimal_converter

    Parameters
    ----------
    data : NodeData

    Returns
    -------
    value : NodeData
    '''
    return DecimalData(float(data.number))


def decimal_to_integer_converter(data: DecimalData) -> IntegerData:
    '''
    Convert from DecimalDat to IntegerData

    Parameters
    ----------
    data : DecimalData

    Returns
    -------
    value : IntegerData
    '''
    return IntegerData(int(data.number))


def main(app):
    registry = nodeeditor.DataModelRegistry()

    models = (AdditionModel, DivisionModel, ModuloModel, MultiplicationModel,
              NumberSourceDataModel, SubtractionModel, NumberDisplayModel)
    for model in models:
        registry.register_model(model, category='Operations',
                                style=None)

    registry.register_type_converter(DecimalData, IntegerData,
                                     decimal_to_integer_converter)
    registry.register_type_converter(IntegerData, DecimalData,
                                     decimal_to_integer_converter)

    scene = nodeeditor.FlowScene(registry=registry)

    view = nodeeditor.FlowView(scene)
    view.setWindowTitle("Calculator example")
    view.resize(800, 600)
    view.show()

    node_a = scene.create_node(NumberSourceDataModel)
    node_a.data.embedded_widget().setText('1.0')

    node_b = scene.create_node(NumberSourceDataModel)
    node_b.data.embedded_widget().setText('2.0')
    node_add = scene.create_node(AdditionModel)
    node_sub = scene.create_node(SubtractionModel)
    node_mul = scene.create_node(MultiplicationModel)
    node_div = scene.create_node(DivisionModel)
    node_mod = scene.create_node(ModuloModel)

    for node_operation in (node_add, node_sub, node_mul, node_div, node_mod):
        scene.create_connection(
            node_out=node_a, port_index_out=0,
            node_in=node_operation, port_index_in=0,
            converter=None
        )

        scene.create_connection(
            node_out=node_b, port_index_out=0,
            node_in=node_operation, port_index_in=1,
            converter=None
        )

        node_display = scene.create_node(NumberDisplayModel)

        scene.create_connection(
            node_out=node_operation, port_index_out=0,
            node_in=node_display, port_index_in=0,
            converter=None
        )

    return scene, view, [node_a, node_b]


if __name__ == '__main__':
    logging.basicConfig(level='DEBUG')
    app = QApplication([])
    scene, view, nodes = main(app)
    view.show()
    app.exec_()

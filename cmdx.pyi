from abc import abstractmethod
from typing import *
from typing_extensions import Protocol, Self, Literal
import math
from _typeshed import Incomplete
from collections.abc import Generator
from maya import OpenMaya as om1, OpenMayaMPx as ompx1, OpenMayaUI as omui1
from maya.api import OpenMaya as om, OpenMayaAnim as oma, OpenMayaUI as omui

class SupportsBool(Protocol):

    @abstractmethod
    def __bool__(self) -> bool: ...

PY3: Incomplete
IGNORE_VERSION: Incomplete
TIMINGS: Incomplete
SAFE_MODE: Incomplete
ROGUE_MODE: Incomplete
ENABLE_PEP8: bool
ENABLE_UNDO: bool
ENABLE_PLUG_REUSE: bool
long = long
string_types: Incomplete
__maya_version__: Incomplete
MYPY: bool
basestring = str
unicode = str
long = int
buffer = bytearray
file = object
self: Incomplete
log: Incomplete
Stats = self
MTime: Incomplete
MDistance: Incomplete
MAngle: Incomplete
TimeType: Incomplete
DistanceType: Incomplete
AngleType: Incomplete
ColorType: Incomplete
ExistError: Incomplete
LockedError: Incomplete
DoNothing: Incomplete
GlobalDagNode: Incomplete
GlobalDependencyNode: Incomplete
First: int
Last: int
Stepped: int
Linear: int
Smooth: int
history: Incomplete

class ModifierError(RuntimeError):
    history: Incomplete
    def __init__(self, history) -> None: ...

def withTiming(text: str = ...): ...
def protected(func): ...
def add_metaclass(metaclass): ...

class _Type(int): ...

MFn: Incomplete
kDagNode: Incomplete
kShape: Incomplete
kTransform: Incomplete
kJoint: Incomplete
kSet: Incomplete
kDeformer: Incomplete
kConstraint: Incomplete

class _Space(int): ...

sWorld: Incomplete
sObject: Incomplete
sTransform: Incomplete
sPostTransform: Incomplete
sPreTransform: Incomplete
kXYZ: Incomplete
kYZX: Incomplete
kZXY: Incomplete
kXZY: Incomplete
kYXZ: Incomplete
kZYX: Incomplete

class _Unit(int):
    def __new__(cls, unit, enum): ...
    def __call__(self, enum): ...

Degrees: Incomplete
Radians: Incomplete
AngularMinutes: Incomplete
AngularSeconds: Incomplete

def AngleUiUnit(): ...

Millimeters: Incomplete
Centimeters: Incomplete
Meters: Incomplete
Kilometers: Incomplete
Inches: Incomplete
Feet: Incomplete
Miles: Incomplete
Yards: Incomplete

def DistanceUiUnit(): ...

Milliseconds: Incomplete
Minutes: Incomplete
Seconds: Incomplete

def TimeUiUnit(): ...
UiUnit = TimeUiUnit
Cached: Incomplete

class Singleton(type):
    def __call__(cls, mobject, exists: bool = ..., modifier: Incomplete | None = ...): ...

class Node:
    def __eq__(self, other: Node) -> bool: ...
    def __ne__(self, other: Node) -> bool: ...
    def __add__(self, other: str) -> Plug: ...
    def __contains__(self, other: str) -> bool: ...
    def __getitem__(self, key: str) -> Plug: ...
    def __setitem__(self, key: str | Tuple[str, _Unit], value: Plug | Any,) -> None: ...
    def __hash__(self) -> int: ...
    def __delitem__(self, key: str) -> None: ...
    def __init__(self, mobject: om.MObject, exists: bool = ...) -> None: ...
    def __del__(self) -> None: ...
    def plugin(self) -> Type[Optional[om.MPxNode]]: ...
    def instance(self) -> Optional[om.MPxNode]: ...
    def object(self) -> om.MObject: ...
    def isAlive(self) -> bool: ...
    @property
    def data(self): ...
    @property
    def exists(self) -> bool: ...
    @property
    def removed(self) -> bool: ...
    @property
    def destroyed(self) -> bool: ...
    @property
    def hashCode(self) -> int: ...
    @property
    def hexStr(self) -> str: ...
    code = hashCode
    hex = hexStr
    @property
    def typeId(self) -> om.MTypeId: ...
    @property
    def typeName(self) -> str: ...
    @overload
    def isA(self, type: om.MTypeId | str | int) -> bool: ...
    @overload
    def isA(self, type: Sequence[om.MTypeId | str | int]) -> bool: ...
    def lock(self, value: bool = ...) -> None: ...
    def isLocked(self) -> bool: ...
    def isReferenced(self) -> bool: ...
    @property
    def storable(self) -> None: ...
    @storable.setter
    def storable(self, value: bool) -> None: ...
    def findPlug(self, name: str, cached: bool = ..., safe: bool = ...) -> om.MPlug: ...
    def update(self, attrs: Dict[str | Tuple[str, _Unit], Any]) -> None: ...
    def clear(self) -> None: ...
    def name(self, namespace: bool = ...) -> str: ...
    def namespace(self) -> str: ...
    def path(self) -> str: ...
    shortestPath = path
    def pop(self, key: str) -> None: ...
    def dump(self, ignore_error: bool = ..., preserve_order: bool = ...) -> Dict[str, Any]: ...
    def dumps(self, indent: int = ..., sort_keys: bool = ..., preserve_order: bool = ...) -> str: ...
    def index(self, plug: Plug) -> int: ...
    def type(self) -> str: ...
    def addAttr(self, attr: str | _AbstractAttribute) -> None: ...
    def hasAttr(self, attr: str) -> bool: ...
    def deleteAttr(self, attr: str | Plug) -> None: ...

    @overload
    def connections(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[False] = ..., source: bool = ..., destination: bool = ..., connections: Literal[False] = ...) -> Generator[Node, None, None]: ...
    @overload
    def connections(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[True] = ..., source: bool = ..., destination: bool = ..., connections: Literal[False] = ...) -> Generator[Plug, None, None]: ...
    @overload
    def connections(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[False] = ..., source: bool = ..., destination: bool = ..., connections: Literal[True] = ...) -> Generator[Tuple[Node, Self], None, None]: ...
    @overload
    def connections(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[True] = ..., source: bool = ..., destination: bool = ..., connections: Literal[True] = ...) -> Generator[Tuple[Plug, Plug], None, None]: ...

    @overload
    def connection(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[False] = ..., source: bool = ..., destination: bool = ..., connections: Literal[False] = ...) -> Node: ...
    @overload
    def connection(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[True] = ..., source: bool = ..., destination: bool = ..., connections: Literal[False] = ...) -> Plug: ...
    @overload
    def connection(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[False] = ..., source: bool = ..., destination: bool = ..., connections: Literal[True] = ...) -> Tuple[Node, Self]: ...
    @overload
    def connection(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[True] = ..., source: bool = ..., destination: bool = ..., connections: Literal[True] = ...) -> Tuple[Plug, Plug]: ...

    @overload
    def inputs(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[False] = ..., destination: bool = ..., connections: Literal[False] = ...) -> Generator[Node, None, None]: ...
    @overload
    def inputs(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[True] = ..., destination: bool = ..., connections: Literal[False] = ...) -> Generator[Plug, None, None]: ...
    @overload
    def inputs(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[False] = ..., destination: bool = ..., connections: Literal[True] = ...) -> Generator[Tuple[Node, Self], None, None]: ...
    @overload
    def inputs(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[True] = ..., destination: bool = ..., connections: Literal[True] = ...) -> Generator[Tuple[Plug, Plug], None, None]: ...

    @overload
    def input(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[False] = ..., destination: bool = ..., connections: Literal[False] = ...) -> Node: ...
    @overload
    def input(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[True] = ..., destination: bool = ..., connections: Literal[False] = ...) -> Plug: ...
    @overload
    def input(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[False] = ..., destination: bool = ..., connections: Literal[True] = ...) -> Tuple[Node, Self]: ...
    @overload
    def input(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[True] = ..., destination: bool = ..., connections: Literal[True] = ...) -> Tuple[Plug, Plug]: ...

    @overload
    def outputs(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[False] = ..., source: bool = ..., connections: Literal[False] = ...) -> Generator[Node, None, None]: ...
    @overload
    def outputs(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[True] = ..., source: bool = ..., connections: Literal[False] = ...) -> Generator[Plug, None, None]: ...
    @overload
    def outputs(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[False] = ..., source: bool = ..., connections: Literal[True] = ...) -> Generator[Tuple[Node, Self], None, None]: ...
    @overload
    def outputs(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[True] = ..., source: bool = ..., connections: Literal[True] = ...) -> Generator[Tuple[Plug, Plug], None, None]: ...

    @overload
    def output(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[False] = ..., source: bool = ..., connections: Literal[False] = ...) -> Node: ...
    @overload
    def output(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[True] = ..., source: bool = ..., connections: Literal[False] = ...) -> Plug: ...
    @overload
    def output(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[False] = ..., source: bool = ..., connections: Literal[True] = ...) -> Tuple[Node, Self]: ...
    @overload
    def output(self, type: Optional[str] = ..., unit: Optional[int] = ..., plugs: Literal[True] = ..., source: bool = ..., connections: Literal[True] = ...) -> Tuple[Plug, Plug]: ...

    def rename(self, name: str) -> None: ...

    is_alive = isAlive
    hex_str = hexStr
    hash_code = hashCode
    type_id = typeId
    type_name = typeName
    is_a = isA
    is_locked = isLocked
    is_referenced = isReferenced
    find_plug = findPlug
    add_attr = addAttr
    has_attr = hasAttr
    delete_attr = deleteAttr
    shortest_path = shortestPath

class ContainerNode(Node):
    def __getitem__(self, key): ...

class DagNode(Node):
    def path(self): ...
    def dagPath(self): ...
    def shortestPath(self): ...
    @property
    def level(self): ...
    @property
    def boundingBox(self): ...
    def hide(self) -> None: ...
    def show(self) -> None: ...
    def childCount(self, type: Incomplete | None = ...): ...
    def addChild(self, child, index=..., safe: bool = ...) -> None: ...
    def assembly(self): ...
    def transform(self, space=..., time: Incomplete | None = ...): ...
    def transformation(self): ...
    def translation(self, space=..., time: Incomplete | None = ...): ...
    def rotation(self, space=..., time: Incomplete | None = ...): ...
    def scale(self, space=..., time: Incomplete | None = ...): ...
    def mapFrom(self, other, time: Incomplete | None = ...): ...
    def mapTo(self, other, time: Incomplete | None = ...): ...
    root: Incomplete
    def parent(self, type: Incomplete | None = ..., filter: Incomplete | None = ...): ...
    def lineage(self, type: Incomplete | None = ..., filter: Incomplete | None = ...) -> Generator[Incomplete, None, None]: ...
    parenthood: Incomplete
    def children(self, type: Incomplete | None = ..., filter=..., query: Incomplete | None = ..., contains: Incomplete | None = ...) -> Generator[Incomplete, None, None]: ...
    def child(self, type: Incomplete | None = ..., filter=..., query: Incomplete | None = ..., contains: Incomplete | None = ...): ...
    def shapes(self, type: Incomplete | None = ..., query: Incomplete | None = ...): ...
    def shape(self, type: Incomplete | None = ...): ...
    def siblings(self, type: Incomplete | None = ..., filter=...) -> Generator[Incomplete, None, None]: ...
    def sibling(self, type: Incomplete | None = ..., filter: Incomplete | None = ...): ...
    def descendents(self, type: Incomplete | None = ...) -> Generator[Incomplete, None, None]: ...
    def descendents(self, type: Incomplete | None = ...) -> Generator[Incomplete, None, Incomplete]: ...
    def descendent(self, type=...): ...
    def duplicate(self): ...
    def clone(self, name: Incomplete | None = ..., parent: Incomplete | None = ..., worldspace: bool = ...): ...
    def isLimited(self, typ): ...
    def limitValue(self, typ): ...
    def enableLimit(self, typ, state): ...
    def setLimit(self, typ, value): ...
    shortest_path: Incomplete
    add_child: Incomplete
    child_count: Incomplete
    dag_path: Incomplete
    map_from: Incomplete
    map_to: Incomplete
    is_limited: Incomplete
    limit_value: Incomplete
    set_limit: Incomplete
    enable_limit: Incomplete
    bounding_box: Incomplete

kRotateMaxX: int
kRotateMaxY: int
kRotateMaxZ: int
kRotateMinX: int
kRotateMinY: int
kRotateMinZ: int
kScaleMaxX: int
kScaleMaxY: int
kScaleMaxZ: int
kScaleMinX: int
kScaleMinY: int
kScaleMinZ: int
kShearMaxXY: int
kShearMaxXZ: int
kShearMaxYZ: int
kShearMinXY: int
kShearMinXZ: int
kShearMinYZ: int
kTranslateMaxX: int
kTranslateMaxY: int
kTranslateMaxZ: int
kTranslateMinX: int
kTranslateMinY: int
kTranslateMinZ: int

class ObjectSet(Node):
    def shortestPath(self): ...
    def __iter__(self): ...
    def add(self, member): ...
    def remove(self, members) -> None: ...
    def update(self, members) -> None: ...
    def clear(self) -> None: ...
    def sort(self, key=...): ...
    def descendent(self, type: Incomplete | None = ...): ...
    def descendents(self, type: Incomplete | None = ...) -> Generator[Incomplete, None, None]: ...
    def flatten(self, type: Incomplete | None = ...): ...
    def member(self, type: Incomplete | None = ...): ...
    def members(self, type: Incomplete | None = ...) -> Generator[Incomplete, None, None]: ...

class AnimCurve(Node):
    def __init__(self, mobj, exists: bool = ...) -> None: ...
    def key(self, time, value, interpolation=...) -> None: ...
    def keys(self, times, values, interpolation=...): ...

class Plug:
    def __abs__(self): ...
    def __bool__(self): ...
    __nonzero__: Incomplete
    def __round__(self, digits: int = ...): ...
    def __float__(self): ...
    def __int__(self): ...
    def __eq__(self, other): ...
    def __ne__(self, other): ...
    def __lt__(self, other): ...
    def __gt__(self, other): ...
    def __neg__(self): ...
    def __div__(self, other): ...
    def __truediv__(self, other): ...
    def __add__(self, other): ...
    def __iadd__(self, other): ...
    def __rshift__(self, other) -> None: ...
    def __lshift__(self, other) -> None: ...
    def __floordiv__(self, other) -> None: ...
    def __iter__(self): ...
    def __getitem__(self, logicalIndex): ...
    def __setitem__(self, index, value) -> None: ...
    def __hash__(self): ...
    def __init__(self, node, mplug, unit: Incomplete | None = ..., key: Incomplete | None = ...) -> None: ...
    def clone(self, name, shortName: Incomplete | None = ..., niceName: Incomplete | None = ...): ...
    def plug(self): ...
    def attribute(self): ...
    @property
    def isArray(self): ...
    @property
    def arrayIndices(self): ...
    @property
    def isCompound(self): ...
    def nextAvailableIndex(self, startIndex: int = ...): ...
    def pull(self) -> None: ...
    def append(self, value, autofill: bool = ...) -> None: ...
    def extend(self, values) -> None: ...
    def count(self): ...
    def asDouble(self, time: Incomplete | None = ...): ...
    def asMatrix(self, time: Incomplete | None = ...): ...
    def asTransformationMatrix(self, time: Incomplete | None = ...): ...
    asTm: Incomplete
    asTransform: Incomplete
    def asEulerRotation(self, order=..., time: Incomplete | None = ...): ...
    asEuler: Incomplete
    def asQuaternion(self, time: Incomplete | None = ...): ...
    def asVector(self, time: Incomplete | None = ...): ...
    def asPoint(self, time: Incomplete | None = ...): ...
    def asTime(self, time: Incomplete | None = ...): ...
    @property
    def connected(self): ...
    def animated(self, recursive: bool = ...): ...
    def lock(self) -> None: ...
    def unlock(self) -> None: ...
    @property
    def locked(self): ...
    @locked.setter
    def locked(self, value) -> None: ...
    @property
    def channelBox(self): ...
    @channelBox.setter
    def channelBox(self, value) -> None: ...
    @property
    def keyable(self): ...
    @keyable.setter
    def keyable(self, value) -> None: ...
    @property
    def hidden(self): ...
    @hidden.setter
    def hidden(self, value) -> None: ...
    def hide(self) -> None: ...
    def lockAndHide(self) -> None: ...
    @property
    def niceName(self): ...
    @niceName.setter
    def niceName(self, value) -> None: ...
    @property
    def default(self): ...
    def fn(self): ...
    def reset(self) -> None: ...
    @property
    def writable(self): ...
    def show(self) -> None: ...
    @property
    def editable(self): ...
    def type(self): ...
    def typeClass(self): ...
    def path(self, full: bool = ...): ...
    def name(self, long: bool = ..., full: bool = ...): ...
    def read(self, unit: Incomplete | None = ..., time: Incomplete | None = ...): ...
    def animate(self, values, interpolation: Incomplete | None = ...) -> None: ...
    def write(self, value): ...
    def connect(self, other, force: bool = ...) -> None: ...
    def disconnect(self, other: Incomplete | None = ..., source: bool = ..., destination: bool = ...) -> None: ...
    def connections(self, type: Incomplete | None = ..., source: bool = ..., destination: bool = ..., plugs: bool = ..., unit: Incomplete | None = ...) -> Generator[Incomplete, None, None]: ...
    def connection(self, type: Incomplete | None = ..., source: bool = ..., destination: bool = ..., plug: bool = ..., unit: Incomplete | None = ...): ...
    def input(self, type: Incomplete | None = ..., plug: bool = ..., unit: Incomplete | None = ...): ...
    def outputs(self, type: Incomplete | None = ..., plugs: bool = ..., unit: Incomplete | None = ...): ...
    def output(self, type: Incomplete | None = ..., plug: bool = ..., unit: Incomplete | None = ...): ...
    def source(self, unit: Incomplete | None = ...): ...
    def node(self): ...
    as_double: Incomplete
    as_matrix: Incomplete
    as_transformation_matrix: Incomplete
    as_transform: Incomplete
    as_euler_rotation: Incomplete
    as_euler: Incomplete
    as_quaternion: Incomplete
    as_vector: Incomplete
    as_point: Incomplete
    as_time: Incomplete
    channel_box: Incomplete
    lock_and_hide: Incomplete
    array_indices: Incomplete
    type_class: Incomplete
    next_available_index: Incomplete

class TransformationMatrix(om.MTransformationMatrix):
    def __init__(self, matrix: Incomplete | None = ..., translate: Incomplete | None = ..., rotate: Incomplete | None = ..., scale: Incomplete | None = ...) -> None: ...
    def __mul__(self, other): ...
    @property
    def xAxis(self): ...
    @property
    def yAxis(self): ...
    @property
    def zAxis(self): ...
    def translateBy(self, vec, space: Incomplete | None = ...): ...
    def rotateBy(self, rot, space: Incomplete | None = ...): ...
    def scale(self, space: Incomplete | None = ...): ...
    def quaternion(self): ...
    def rotatePivot(self, space: Incomplete | None = ...): ...
    def setRotatePivot(self, pivot, space=..., balance: bool = ...): ...
    def rotatePivotTranslation(self, space: Incomplete | None = ...): ...
    def scalePivot(self, space: Incomplete | None = ...): ...
    def scalePivotTranslation(self, space: Incomplete | None = ...): ...
    def translation(self, space: om.MSpace = ...) -> om.MVector: ...
    def setTranslation(self, trans, space: Incomplete | None = ...): ...
    def scaleBy(self, space: Incomplete | None = ...): ...
    def setScale(self, seq, space: Incomplete | None = ...): ...
    def rotation(self, asQuaternion: bool = ...): ...
    def setRotation(self, rot): ...
    def asMatrix(self) -> MatrixType: ...
    def asMatrixInverse(self) -> MatrixType: ...
    x_axis: Incomplete
    y_axis: Incomplete
    z_axis: Incomplete
    translate_by: Incomplete
    rotate_by: Incomplete
    set_translation: Incomplete
    set_rotation: Incomplete
    set_scale: Incomplete
    as_matrix: Incomplete
    as_matrix_inverse: Incomplete

class MatrixType(om.MMatrix):
    def __call__(self, *item): ...
    def __mul__(self, other): ...
    def __div__(self, other): ...
    def inverse(self): ...
    def row(self, index): ...
    def element(self, row, col): ...
Transformation = TransformationMatrix
Tm = TransformationMatrix
Mat = MatrixType
Mat4 = MatrixType
Matrix4 = MatrixType

class Vector(om.MVector):
    def __add__(self, value): ...
    def __iadd__(self, value): ...
    def dot(self, value): ...
    def cross(self, value): ...
    def isEquivalent(self, other, tolerance=...): ...
    is_equivalent: Incomplete
Vector3 = Vector

def multiply_vectors(vec1, vec2): ...
def divide_vectors(vec1, vec2): ...

class Point(om.MPoint): ...
class Color(om.MColor): ...

class BoundingBox(om.MBoundingBox):
    def volume(self): ...

class Quaternion(om.MQuaternion):
    def __mul__(self, other): ...
    def lengthSquared(self): ...
    def length(self): ...
    def isNormalised(self, tol: float = ...): ...
    def asEulerRotation(self): ...
    def inverse(self): ...
    def asMatrix(self): ...
    as_matrix: Incomplete
    is_normalised: Incomplete
    length_squared: Incomplete
    as_euler_rotation: Incomplete
    as_euler: Incomplete
Quat = Quaternion

def twistSwingToQuaternion(ts): ...

class EulerRotation(om.MEulerRotation):
    def asQuaternion(self): ...
    def asMatrix(self): ...
    def isEquivalent(self, other, tolerance=...): ...
    is_equivalent: Incomplete
    strToOrder: Incomplete
    orderToStr: Incomplete
    as_quaternion: Incomplete
    as_matrix: Incomplete
Euler = EulerRotation

def NurbsCurveData(points, degree: int = ..., form=...): ...

class CachedPlug(Plug):
    def __init__(self, value) -> None: ...
    def read(self): ...

def exists(path, strict: bool = ...): ...
def encode(path: str) -> Node: ...
def fromHash(code, default: Incomplete | None = ...): ...
def fromHex(hex, default: Incomplete | None = ..., safe: bool = ...): ...
def toHash(mobj): ...
def toHex(mobj): ...
def asHash(mobj): ...
def asHex(mobj): ...
from_hash = fromHash
from_hex = fromHex
to_hash = toHash
to_hex = toHex
as_hash = asHash
as_hex = asHex
degrees = math.degrees
radians = math.radians
sin = math.sin
cos = math.cos
tan = math.tan
pi: Incomplete

def meters(cm): ...
def clear() -> None: ...
def decode(node): ...
def record_history(func): ...

class _BaseModifier:
    Type: Incomplete
    isContext: bool
    def __enter__(self): ...
    def __exit__(self, exc_type, exc_value, tb) -> None: ...
    def __init__(self, undoable: bool = ..., interesting: bool = ..., debug: bool = ..., atomic: bool = ..., template: Incomplete | None = ...) -> None: ...
    def setNiceName(self, plug, value: bool = ...) -> None: ...
    def setLocked(self, plug, value: bool = ...) -> None: ...
    def setKeyable(self, plug, value: bool = ...) -> None: ...
    def doIt(self) -> None: ...
    def undoIt(self) -> None: ...
    def redoIt(self) -> None: ...
    def createNode(self, type, name: Incomplete | None = ...): ...
    def deleteNode(self, node) -> None: ...
    def renameNode(self, node, name): ...
    def addAttr(self, node, attr): ...
    def deleteAttr(self, plug): ...
    def setAttr(self, plug, value) -> None: ...
    def smartSetAttr(self, plug, value): ...
    def trySetAttr(self, plug, value) -> None: ...
    def forceSetAttr(self, plug, value) -> None: ...
    def resetAttr(self, plug) -> None: ...
    def connect(self, src, dst, force: bool = ...) -> None: ...
    def connectAttr(self, srcPlug, dstNode, dstAttr) -> None: ...
    def connectAttrs(self, srcNode, srcAttr, dstNode, dstAttr) -> None: ...
    def tryConnect(self, src, dst): ...
    def disconnect(self, a, b: Incomplete | None = ..., source: bool = ..., destination: bool = ...): ...
    delete: Incomplete
    rename: Incomplete
    do_it: Incomplete
    undo_it: Incomplete
    create_node: Incomplete
    delete_node: Incomplete
    rename_node: Incomplete
    add_attr: Incomplete
    set_attr: Incomplete
    try_set_attr: Incomplete
    force_set_attr: Incomplete
    smart_set_attr: Incomplete
    delete_attr: Incomplete
    reset_attr: Incomplete
    try_connect: Incomplete
    connect_attr: Incomplete
    connect_attrs: Incomplete
    set_keyable: Incomplete
    set_locked: Incomplete
    set_nice_name: Incomplete

class DGModifier(_BaseModifier):
    Type: Incomplete

class DagModifier(_BaseModifier):
    Type: Incomplete
    def createNode(self, type, name: Incomplete | None = ..., parent: Incomplete | None = ...): ...
    def parent(self, node, parent: Incomplete | None = ...) -> None: ...
    reparent: Incomplete
    reparentNode: Incomplete
    create_node: Incomplete

class HashableTime(om.MTime):
    def __hash__(self): ...

def connect(a, b) -> None: ...
def currentTime(time: Incomplete | None = ...): ...
def animationStartTime(time: Incomplete | None = ...): ...
def animationEndTime(time: Incomplete | None = ...): ...
def minTime(time: Incomplete | None = ...): ...
def maxTime(time: Incomplete | None = ...): ...

class DGContext(om.MDGContext):
    def __init__(self, time: Incomplete | None = ..., unit: Incomplete | None = ...) -> None: ...
    def __enter__(self): ...
    def __exit__(self, exc_type, exc_value, tb) -> None: ...
Context = DGContext

def ls(*args, **kwargs): ...
def selection(*args, **kwargs): ...
def createNode(type, name: Incomplete | None = ..., parent: Incomplete | None = ...): ...
def getAttr(attr, type: Incomplete | None = ..., time: Incomplete | None = ...): ...
def setAttr(attr, value, type: Incomplete | None = ...) -> None: ...
def addAttr(node, longName, attributeType, shortName: Incomplete | None = ..., enumName: Incomplete | None = ..., defaultValue: Incomplete | None = ...) -> None: ...
def listRelatives(node, type: Incomplete | None = ..., children: bool = ..., allDescendents: bool = ..., parent: bool = ..., shapes: bool = ...): ...
def listConnections(attr): ...
def connectAttr(src, dst) -> None: ...
def delete(*nodes) -> None: ...
def rename(node, name) -> None: ...
def parent(children, parent, relative: bool = ..., absolute: bool = ..., safe: bool = ...) -> None: ...
def objExists(obj): ...

Y: str
Z: str

def upAxis(): ...
def setUpAxis(axis=...) -> None: ...
sl = selection
create_node = createNode
get_attr = getAttr
set_attr = setAttr
add_attr = addAttr
list_relatives = listRelatives
list_connections = listConnections
connect_attr = connectAttr
obj_exists = objExists
current_time = currentTime
min_time = minTime
max_time = maxTime
animation_start_time = animationStartTime
animation_end_time = animationEndTime
up_axis = upAxis
set_up_axis = setUpAxis
kOpen: Incomplete
kClosed: Incomplete
kPeriodic: Incomplete

def editCurve(parent, points, degree: int = ..., form=...): ...
def curve(parent, points, degree: int = ..., form=...): ...
def lookAt(origin, center, up: Incomplete | None = ...): ...
look_at = lookAt

def first(iterator, default: Incomplete | None = ...): ...
def last(iterator, default: Incomplete | None = ...): ...

kNothing: Incomplete
kReset: Incomplete
kDelete: Incomplete

class _AbstractAttribute(dict):
    Fn: Incomplete
    Type: Incomplete
    Default: Incomplete
    Readable: bool
    Writable: bool
    Cached: bool
    Storable: bool
    Hidden: bool
    Array: bool
    IndexMatters: bool
    Connectable: bool
    Keyable: bool
    ChannelBox: bool
    AffectsAppearance: bool
    AffectsWorldSpace: bool
    DisconnectBehavior: Incomplete
    Help: str
    def __eq__(self, other): ...
    def __ne__(self, other): ...
    def __hash__(self): ...
    def __new__(cls, *args, **kwargs): ...
    def __init__(self, name, default: Incomplete | None = ..., label: Incomplete | None = ..., shortName: Incomplete | None = ..., writable: Incomplete | None = ..., readable: Incomplete | None = ..., cached: Incomplete | None = ..., storable: Incomplete | None = ..., keyable: Incomplete | None = ..., hidden: Incomplete | None = ..., min: Incomplete | None = ..., max: Incomplete | None = ..., channelBox: Incomplete | None = ..., affectsAppearance: Incomplete | None = ..., affectsWorldSpace: Incomplete | None = ..., array: bool = ..., indexMatters: Incomplete | None = ..., connectable: bool = ..., disconnectBehavior=..., help: Incomplete | None = ...) -> None: ...
    def dumps(self): ...
    def default(self, cls: Incomplete | None = ...): ...
    def type(self): ...
    def create(self, cls: Incomplete | None = ...): ...
    def read(self, data) -> None: ...

class Enum(_AbstractAttribute):
    Fn: Incomplete
    Type: Incomplete
    Default: int
    Keyable: bool
    def __init__(self, name, fields: Incomplete | None = ..., default: int = ..., label: Incomplete | None = ..., **kwargs) -> None: ...
    def create(self, cls: Incomplete | None = ...): ...
    def read(self, data): ...

class Divider(Enum):
    ChannelBox: bool
    Keyable: bool
    def __init__(self, label, **kwargs) -> None: ...

class String(_AbstractAttribute):
    Fn: Incomplete
    Type: Incomplete
    Default: str
    def default(self, cls: Incomplete | None = ...): ...
    def read(self, data): ...

class Message(_AbstractAttribute):
    Fn: Incomplete
    Type: Incomplete
    Default: Incomplete
    Storable: bool

class Matrix(_AbstractAttribute):
    Fn: Incomplete
    Default: Incomplete
    Array: bool
    Readable: bool
    Keyable: bool
    Hidden: bool
    def default(self, cls: Incomplete | None = ...) -> None: ...
    def read(self, data): ...

class Long(_AbstractAttribute):
    Fn: Incomplete
    Type: Incomplete
    Default: int
    def read(self, data): ...

class Double(_AbstractAttribute):
    Fn: Incomplete
    Type: Incomplete
    Default: float
    def read(self, data): ...

class Float(_AbstractAttribute):
    Fn: Incomplete
    Type: Incomplete
    Default: float
    def read(self, data): ...

class Double3(_AbstractAttribute):
    Fn: Incomplete
    Type: Incomplete
    Default: Incomplete
    def default(self, cls: Incomplete | None = ...): ...
    def read(self, data): ...

class Boolean(_AbstractAttribute):
    Fn: Incomplete
    Type: Incomplete
    Default: bool
    def read(self, data): ...

class AbstractUnit(_AbstractAttribute):
    Fn: Incomplete
    Default: float
    Min: Incomplete
    Max: Incomplete
    SoftMin: Incomplete
    SoftMax: Incomplete

class Angle(AbstractUnit):
    def default(self, cls: Incomplete | None = ...): ...

class Time(AbstractUnit):
    def default(self, cls: Incomplete | None = ...): ...

class Distance(AbstractUnit):
    def default(self, cls: Incomplete | None = ...): ...

class Compound(_AbstractAttribute):
    Fn: Incomplete
    Multi: Incomplete
    def __init__(self, name, children: Incomplete | None = ..., **kwargs) -> None: ...
    def default(self, cls: Incomplete | None = ...) -> None: ...
    def create(self, cls: Incomplete | None = ...): ...
    def read(self, handle): ...

class Double2(Compound):
    Multi: Incomplete

class Double4(Compound):
    Multi: Incomplete

class Angle2(Compound):
    Multi: Incomplete

class Angle3(Compound):
    Multi: Incomplete

class Distance2(Compound):
    Multi: Incomplete

class Distance3(Compound):
    Multi: Incomplete

class Distance4(Compound):
    Multi: Incomplete
EnumAttribute = Enum
DividerAttribute = Divider
StringAttribute = String
MessageAttribute = Message
MatrixAttribute = Matrix
LongAttribute = Long
DoubleAttribute = Double
Double3Attribute = Double3
BooleanAttribute = Boolean
AbstractUnitAttribute = AbstractUnit
AngleAttribute = Angle
TimeAttribute = Time
DistanceAttribute = Distance
CompoundAttribute = Compound
Double2Attribute = Double2
Double4Attribute = Double4
Angle2Attribute = Angle2
Angle3Attribute = Angle3
Distance2Attribute = Distance2
Distance3Attribute = Distance3
Distance4Attribute = Distance4
unique_plugin: Incomplete
unique_command: Incomplete
unique_shared: Incomplete
shared: Incomplete

def commit(undo, redo=...) -> None: ...
def install() -> None: ...
def uninstall() -> None: ...
def maya_useNewAPI() -> None: ...

class _apiUndo(om.MPxCommand):
    undoId: Incomplete
    redoId: Incomplete
    def __init__(self, *args, **kwargs) -> None: ...
    def __del__(self) -> None: ...
    def doIt(self, args) -> None: ...
    def undoIt(self) -> None: ...
    def redoIt(self) -> None: ...
    def isUndoable(self): ...

def initializePlugin(plugin) -> None: ...
def uninitializePlugin(plugin) -> None: ...

tAddDoubleLinear: Incomplete
tAddMatrix: Incomplete
tAngleBetween: Incomplete
tBlendShape: Incomplete
tMultMatrix: Incomplete
tAngleDimension: Incomplete
tBezierCurve: Incomplete
tCamera: Incomplete
tChoice: Incomplete
tChooser: Incomplete
tCondition: Incomplete
tMesh: Incomplete
tNurbsCurve: Incomplete
tNurbsSurface: Incomplete
tJoint: Incomplete
tTransform: Incomplete
tTransformGeometry: Incomplete
tWtAddMatrix: Incomplete
InstalledPlugins: Incomplete
TypeId: Incomplete
StartId: Incomplete

class MetaNode(type):
    def __init__(cls, *args, **kwargs): ...

class DgNode(om.MPxNode):
    typeid: Incomplete
    name: str
    version: Incomplete
    attributes: Incomplete
    affects: Incomplete
    ranges: Incomplete
    defaults: Incomplete
    @classmethod
    def postInitialize(cls) -> None: ...

class SurfaceShape(om.MPxSurfaceShape):
    typeid: Incomplete
    classification: str
    name: str
    version: Incomplete
    attributes: Incomplete
    affects: Incomplete
    ranges: Incomplete
    defaults: Incomplete
    @classmethod
    def postInitialize(cls) -> None: ...
    @classmethod
    def uiCreator(cls) -> None: ...

class SurfaceShapeUI(omui.MPxSurfaceShapeUI):
    typeid: Incomplete
    classification: str
    name: str
    version: Incomplete
    attributes: Incomplete
    affects: Incomplete
    ranges: Incomplete
    defaults: Incomplete
    @classmethod
    def postInitialize(cls) -> None: ...

class LocatorNode(omui.MPxLocatorNode):
    name: str
    typeid: Incomplete
    classification: str
    version: Incomplete
    attributes: Incomplete
    affects: Incomplete
    ranges: Incomplete
    defaults: Incomplete
    @classmethod
    def postInitialize(cls) -> None: ...

def initialize2(Plugin): ...
def uninitialize2(Plugin): ...

class MPxManipContainer1(ompx1.MPxManipContainer):
    name: str
    version: Incomplete
    ownerid: Incomplete
    typeid: Incomplete

def initializeManipulator1(Manipulator): ...
def uninitializeManipulator1(Manipulator): ...
def findPlugin(name): ...

class Callback:
    log: Incomplete
    def __init__(self, name, installer, args, api: int = ..., help: str = ..., parent: Incomplete | None = ...) -> None: ...
    def __del__(self) -> None: ...
    def name(self): ...
    def help(self): ...
    def is_active(self): ...
    def activate(self) -> None: ...
    def deactivate(self) -> None: ...

class CallbackGroup(list):
    def __init__(self, name, callbacks, parent: Incomplete | None = ...) -> None: ...
    def name(self): ...
    def add(self, name, installer, args, api: int = ...) -> None: ...
    def activate(self) -> None: ...
    def deactivate(self) -> None: ...

class Cache:
    def __init__(self) -> None: ...
    def clear(self, node: Incomplete | None = ...) -> None: ...
    def read(self, node, attr, time) -> None: ...
    def transform(self, node) -> None: ...

<img height=140 src=https://user-images.githubusercontent.com/2152766/34321609-f134e0cc-e80a-11e7-8dad-d124fea80e77.png>

Fast subset of `maya.cmds`

<br>

### About

`cmdx` is a Python wrapper for the [Maya Python API 2.0](http://help.autodesk.com/view/MAYAUL/2016/ENU/?guid=__py_ref_index_html) and a fast subset of the `maya.cmds` module, with persistent references to nodes.

If you fit in either of these groups, then `cmdx` is for you.

- You like `cmds`, but wish to type less
- You like `PyMEL`, but wish it was faster

On average, `cmdx` is **140x faster** than [PyMEL](https://github.com/LumaPictures/pymel), and 2.5x faster than `maya.cmds` at common tasks; at best, it is 1,300x faster than PyMEL.

- See [Measurements](#measurements) and [Timings](#timings) for details
- See [API Documentation](/api) for usage 

**Maya 2015 SP6 or higher recommended**

`cmdx` utilises the `MObjectHandle` of API 2.0, which was introduced in one of the later service packs for Maya 2015. Some optimisations will not be available in earler versions of Maya, primarily [node reuse](#node-reuse).

<br>
<br>

**Table of contents**

- [Syntax](#syntax)
- [Performance](#performance)
- [Goals](#goals)
- [Query Reduction](#query-reduction)
  - [Node Reuse](#node-reuse)
  - [Plug Reuse](#plug-reuse)
- [Interoperability](#interoperability)
- [Units](#units)
- [Node Creation](#node-creation)
- [Attribute Query and Assignment](#attribute-query-and-assignment)
  - [Cached](#cached)
  - [Time](#time)
- [Connections](#connections)
- [FAQ](#faq)
- [Comparison](#comparison)
  - [MEL](#mel)
  - [PyMEL](#pymel)
  - [cmds](#cmds)
  - [API 1.0](#api-1-0)
  - [API 2.0](#api-2-0)
  - [MRV](#third-party)
  - [metan](#third-party)
- [YAGNI](#yagni)
- [Timings](#timings)
- [Measurements](#measurements)
  - [Overall Performance](#overall-performance)
  - [`import`](#import)
  - [`createNode`](#createNode)
  - [`getAttr`](#getAttr)
  - [`setAttr`](#setAttr)
  - [`connectAttr`](#connectAttr)
  - [`long`](#long)
  - [`node`](#node-attr-attr)
  - [`ls`](#ls)
- [Evolution](#evolution)
- [References](#references)
- [Notes](#notes)
  - [MDagModifier](#mdagmodifier)

<br>

### Syntax

`cmdx` supports the legacy syntax of `maya.cmds`, along with an object-oriented syntax, similar to PyMEL.


**Legacy**

Familiar and fast.

```python
import cmdx
joe = cmdx.createNode("transform", name="Joe")
benji = cmdx.createNode("transform", name="myChild", parent=joe)
cmdx.addAttr(joe, longName="myAttr", defaultValue=5.0, attributeType="double")
cmdx.connectAttr(joe + ".myAttr", benji + ".tx")
cmdx.setAttr(joe + ".myAttr", 5)
cmdx.delete(joe)
```

**Modern**

Faster and most concise.

```python
import cmdx
joe = cmdx.createNode("transform", name="Joe")
benji = cmdx.createNode("transform", name="myChild", parent=joe)
joe["myAttr"] = cmdx.Double(default=5.0)
joe["myAttr"] >> benji["translateX"]
joe["tx"] = 5
cmdx.delete(joe)
```

**Commands**

- `createNode`
- `getAttr`
- `setAttr`
- `addAttr`
- `connectAttr`
- `listRelatives`
- `listConnections`

**Attribute Types**

- `Double`
- `Double3`
- `Enum`
- `String`
- `Angle`
- `Distance`
- `Time`
- `Message`
- `Boolean`
- `Divider`
- `Long`
- `Compound`

<br>

### Performance

`cmdx` is fast, faster than `cmds` by 2-5x and PyMEL by 5-150x, because of how it uses the Maya API 2.0, how classes are built and the (efficient) pre-processing happening on import.

See [Measurements](#measurements) for performance statistics and comparisons between MEL, cmds, cmdx, PyMEL, API 1.0 and 2.0.

**How?**

The fastest you can possibly get with Python inside Maya is through the Maya Python API 2.0. `cmdx` is a thin wrapper around this library that provides a more accessible and readable interface, whilst avoiding as much overhead as possible.

<br>

### Goals

With PyMEL as baseline, these are the primary goals of this project, in order of importance.

| Goal            | Description
|:----------------|:-------------
| Fast            | Faster than PyMEL, and cmds
| Lightweight     | A single Python module, implementing critical parts well, leaving the rest to `cmds`
| Persistent      | References to nodes do not break
| Do not crash    | Working with low-level Maya API calls make it susceptible to crashes; cmdx should protect against this, without sacrificing performance
| External        | Shipped alongside your code, not alongside Maya; you control the version, features and fixes.
| Vendorable      | Embed an appropriate version of `cmdx` alongside your own project
| PEP8            | Continuous integration ensures that every commit follows the consistency of PEP8
| Examples        | No feature is without examples
| No side effects | Importing `cmdx` has no affect any other module

<br>

### Query Reduction

Beyond making queries faster is making less of them.

Any interaction with the Maya API carries the overhead of translating from Python to C++ and, most of the time, back to Python again. So in order to make `cmdx` fast, it must facilitate re-use of queries where re-use makes sense.

#### Node Reuse

> Opt-in `CMDX_ENABLE_NODE_REUSE`

Any node created or queried via `cmdx` is kept around until the next time the same node is returned, regardless of the exact manner in which it was queried.

For example, when `encode`d or returned as children of another node.

```python
node = cmdx.createNode("transform", name="parent")
assert cmdx.encode("|parent") is node
```

This property survives function calls too.

```python
def function1():
  return cmdx.createNode("transform", name="parent")

def function2():
  return cmdx.encode("|parent")

assert function1() is function2()
```

In fact, regardless of how a node is queried, there is only ever a single instance in `cmdx` of it. This is great for repeated queries to nodes and means nodes can contain an additional level of state, beyond the one found in Maya. A property which is used for, amongst other things, optimising *plug reuse*.

#### Plug Reuse

> Opt-in `CMDX_ENABLE_PLUG_REUSE`

```python
node = cmdx.createNode("transform")
node["translateX"]  # Maya's API `findPlug` is called
node["translateX"]  # Previously found plug is returned
node["translateX"]  # Previously found plug is returned
node["translateX"]  # ...
```

Whenever an attribute is queried, a number of things happen.

1. An `MObject` is retrieved via string-comparison
2. A relevant plug is found via another string-comparison
3. A value is retrieved, wrapped in a Maya API object, e.g. MDistance
4. The object is cast to Python object, e.g. MDistance to `float`

This isn't just 4 interactions with the Maya API, it's also 3 interactions with the *Maya scenegraph*. An interaction of this nature triggers the propagation and handling of the dirty flag, which in turn triggers a virtually unlimited number of additional function calls; both internally to Maya - i.e. the `compute()` method - and in any Python that might be listening - e.g. arbitrary callbacks.

With module level caching, a repeated query to either an `MObject` or `MPlug` is handled entirely in Python, saving on both time and computational resources.

<br>

### Interoperability

`cmdx` complements `cmds`, but does not replace it.

Commands such as `menuItem`, `inViewMessage` and `move` are left out and considered a convenience; not sensitive to performance-critical tasks such as generating nodes, setting or connecting attributes etc.

Hence interoperability, where necessary, looks like this.

```python
from maya import cmds
import cmdx

group = cmds.group(name="group", empty=True)
cmds.move(group, 0, 50, 0)
group = cmdx.encode(group)
group["rotateX", cmdx.Radians] = 3.14
cmds.select(cmdx.decode(group))
```

An alternative to `cmdx.decode` is to simply cast it to `str`, which will convert a `cmdx` node into the equivalent shortest path.

```python
cmds.select(str(group))
```

Another aspect of `cmdx` that differ from `cmds` is the number arguments to functions, such as `listConnections` and `ls`.

```python
from maya import cmds
import cmdx

node = cmdx.createNode("transform")
cmds.listConnections(str(node), source=True)
cmdx.listConnections(str(node), source=True)
TypeError: listConnections() got an unexpected keyword argument 'source'
```


The reason for this limitation is because the functions `cmds` 

- See [API Documentation]() for which members are available in `cmdx`
- Submit an [issue](issues) or [pull-request](#fork) with commands you miss

<br>

### Units

`cmdx` takes and returns values in the units used by the UI. For example, Maya's default unit for distances, such as `translateX` is in Centimeters.

```python
import cmdx

node = cmdx.createNode("transform")
node["translateX"] = 5
node["translateX"]
# 5
```

To return `translateX` in Meters, you can pass in a unit explicitly.

```python
node["translateX", cmdx.Meters]
# 0.05
```

To set `translateX` to a value defined in Meters, you can pass that explicitly too.

```python
node["translateX", cmdx.Meters] = 5
```

Or use the alternative syntax.

```python
node["translateX"] = cmdx.Meters(5)
```

The following units are currently supported.

- Angular
  - `Degrees`
  - `Radians`
  - `AngularMinutes`
  - `AngularSeconds`
- Linear
  - `Millimeters`
  - `Centimeters`
  - `Meters`
  - `Kilometers`
  - `Inches`
  - `Feet`
  - `Miles`
  - `Yards`

<br>

### Limitations

All of this performance is great and all, but why hasn't anyone thought of this before? Are there no consequences?

I'm sure someone has, and yes there are.

#### Undo

With every command made through `maya.cmds`, the undo history is populated such that you can undo a *block* of commands all at once. `cmdx` doesn't do this, which is how it remains fast, but also impossible to undo. Any node created or attribute changed is *permanent*, which is why it is that much more important that you take care of the creations and changes that you make.

For undoable operations, see the section on using [`Modifier`](#modifier).

<br>

#### Crashes

...

<br>

### Node Creation

Nodes are created much like with `maya.cmds`.

```python
import cmdx
cmdx.createNode("transform")
```

For a 5-10% performance increase, you may pass type as an object rather than string.

```python
cmdx.createNode(cmdx.Transform)
```

Only the most commonly used and performance sensitive types are available as explicit types.

- `AddDoubleLinear` 
- `AddMatrix` 
- `AngleBetween` 
- `MultMatrix` 
- `AngleDimension` 
- `BezierCurve` 
- `BlendShape` 
- `Camera` 
- `Choice` 
- `Chooser` 
- `Condition` 
- `Transform` 
- `TransformGeometry` 
- `WtAddMatrix` 

See [API Documentation]() for more.

<br>

### Attribute Query and Assignment

Attributes are accessed in a dictionary-like fashion.

```python
import cmdx
node = cmdx.createNode("transform")
node["translateX"]
# 0.0
```

Evaluation of an attribute is delayed until the very last minute, which means that if you don't *read* the attribute, then it is only accessed and not evaluated and cast to a Python type.

```python
attr = node["rx"]
```

The resulting type of an attribute is `cmdx.Plug`

```python
type(attr)
# <class 'cmdx.Plug'>
```

Which has a number of additional methods for query and assignment.

```python
attr.read()
# 0.0
attr.write(1.0)
attr.read()
# 1.0
```

`attr.read()` is called when printing an attribute.

```python
print(attr)
# 1.0
```

For familiarity, an attribute may also be accessed by string concatenation.

```python
attr = node + ".tx"
```

#### Cached

Sometimes, a value is queried when you know it hasn't changed since your last query. By passing `cmdx.Cached` to any attribute, the previously computed value is returned, without the round-trip the the Maya API.

```python
import cmdx
node = cmdx.createNode("transform")
node["tx"] = 5
assert node["tx"] == 5
node["tx"] = 10
assert node["tx", cmdx.Cached] == 5
assert node["tx"] == 10
```

Using `cmdx.Cached` is a lot faster than recomputing the value, sometimes by several orders of magnitude depending on the type of value being queried.

#### Time

The `time` argument of `cmdx.getAttr` enables a query to yield results relative a specific point in time. The `time` argument of `Plug.read` offers this same convenience, only faster.

```python
import cmdx
from maya import cmds
node = cmdx.createNode("transform")

cmds.setKeyframe(str(node), attribute="tx", time=[1, 100], value=0.0)
cmds.setKeyframe(str(node), attribute="tx", time=[50], value=10.0)
cmds.keyTangent(str(node), attribute="tx", time=(1, 100), outTangentType="linear")
```

<br>

### Compound and Array Attributes

These both have children, and are accessed like a Python list.

```python
node = cmdx.createNode("transform")
decompose = cmdx.createNode("decomposeMatrix")
node["worldMatrix"][0] >> decompose["inputMatrix"]
```

Array attributes are created by an additional argument.

```python
node = cmdx.createNode("transform")
node["myArray"] = cmdx.Double(array=True)
```

Compound attributes are created as a group.

```python
node = cmdx.createNode("transform")
node["myGroup"] = cmdx.Compound(children=(
  cmdx.Double("myGroupX")
  cmdx.Double("myGroupY")
  cmdx.Double("myGroupZ")
))
```

Both array and compound attributes can be written via index or tuple assignment.

```python
node["myArray"] = (5, 5, 5)
node["myArray"][1] = 10
node["myArray"][2]
# 5
```

<br>

### Connections

Connect one attribute to another with one of two syntaxes, whichever one is the most readable.

```python
a, b = map(cmdx.createNode, ("transform", "camera"))

# Option 1
a["translateX"] >> b["translateX"]

# Option 2
a["translateY"].connect(b["translateY"])
```

Legacy syntax is also supported, and is almost as fast - the overhead is one additional call to `str.strip`.

```python
cmdx.connectAttr(a + ".translateX", b + ".translateX")
```

### Iterators

Any method on a `Node` returning multiple values do so in the form of an iterator.

```python
a = cmdx.createNode("transform")
b = cmdx.createNode("transform", parent=a)
c = cmdx.createNode("transform", parent=a)

for child in a.children():
   pass
```

Because it is an iterator, it is important to keep in mind that you cannot index into it, nor compare it with a list or tuple.

```python
a.children()[0]
ERROR

a.children() == [b, c]
False  # The iterator does not equal the list, no matter the content
```

From a performance perspective, returning all values from an iterator is equally fast as returning them all at once, as `cmds` does, so you may wonder why do it this way? 

It's because an iterator only spends time computing the values requested, so returning any number *less than* the total number yields performance benefits.

```python
i = a.children()
assert next(i) == b
assert next(i) == c
```

For convenience, every iterator features a corresponding "singular" version of said iterator for readability.

```python
assert a.child() == b
```

**More iterators**

- `a.children()`
- `a.connections()`
- `a.siblings()`
- `a.descendents()`

<br>

### Modifier

`cmdx` is designed to make bulk operations fast, such as making exporters, importers and rigging frameworks. It is not ideal for interactive tools.

However, in order to smooth out the line between what is a bulk operation and what is interactive, `cmdx` provides the `Modifier` which is a fast alternative to `cmds` that *retains undo*.

For example.

```pytyhon
import cmdx

with cmdx.Modifier() as mod:
    node1 = mod.createNode("decomposeMatrix", name="Decompose")
    node2 = mod.createNode("transform")
    node3 = mod.createNode("transform", parent=node2)
    mod.connect(node2 + ".worldMatrix", node1 + ".inputMatrix")
    mod.connect(node1 + ".outputTranslate", node3 + ".translate")
```

Now when calling `undo`, the above lines will be undone as you'd expect.

If you prefer, modern syntax still works here.

```python
with cmdx.Modifier() as mod:
    parent = mod.createNode("transform", name="MyParemt")
    child = mod.createNode("transform", parent=parent)
    parent["translate"] = (1, 2, 3)
    parent["rotate"] >> parent["rotate"]
```

This makes it easy to move a block of code into a modifier without changing things around. Perhaps to test performance, or to figure out whether undo support is necessary.

<br>

### FAQ

> Why is it crashing?

`cmdx` should never crash (if it does, please [submit a bug report!]()), but the cost of performance is safety. `maya.cmds` rarely causes a crash because it has safety procedures built in. It double checks to ensure that the object you operate on exists, and if it doesn't provides a safe warning message. This double-checking is part of what makes `maya.cmds` slow; conversely, the lack of it is part of why `cmdx` is so fast.

Common causes of a crash is:

- Use of a node that has been deleted
- ... (add your issue here)

This can happen when, for example, you experiment in the Script Editor, and retain access to nodes created from a different scene, or after the node has simply been deleted.

> Why is PyMEL slow?

...

> Doesn't PyMEL also use the Maya API?

Yes and no. Some functionality, such as [`listRelatives`](https://github.com/LumaPictures/pymel/blob/eb984107952cde052a3ecdb473e66c7db7deb3b7/pymel/core/general.py#L1026) call on `cmds.listRelatives` and later convert the output to instances of `PyNode`. This performs at best as well as `cmds`, with the added overhead of converting the transient path to a `PyNode`.

Other functionality, such as `pymel.core.datatypes.Matrix` wrap the `maya.api.OpenMaya.MMatrix` class and would have come at virtually no cost, had it not inherited 2 additional layers of superclasses and implemented much of the [computationally expensive]() functionality in pure-Python.

<br>

### Comparison

This section explores the relationship between `cmdx` and (1) MEL, (2) cmds, (3) PyMEL and (4) API 1/2.

##### MEL

Maya's Embedded Language (MEL) makes for a compact scene description format.

```python
createNode transform -n "myNode"
  setAttr .tx 12
  setAttr .ty 9
```

On creation, a node is "selected" which is leveraged by subsequent commands, commands that also reference attributes via their "short" name to further reduce file sizes.

A scene description never faces naming or parenting problems the way programmers do. In a scene description, there is no need to rename nor reparent; a node is created either as a child of another, or not. It is given a name, which is unique. No ambiguity.

From there, it was given expressions, functions, branching logic and was made into a scripting language where the standard library is a scene description kit. 

`cmds` is tedious and `pymel` is slow. `cmds` is also a victim of its own success. Like MEL, it works with relative paths and the current selection; this facilitates the compact file format, whereby a node is created, and then any references to this node is implicit in each subsequent line. Long attribute names have a short equivalent and paths need only be given at enough specificity to not be ambiguous given everything else that was previously created. Great for scene a file format, not so great for code that operates on-top of this scene file.

##### PyMEL

PyMEL is 31,000 lines of code, the bulk of which implements backwards compatibility to `maya.cmds` versions of Maya as far back as 2008, the rest reiterates the Maya API.

**Line count**

PyMEL has accumulated a large number of lines throughout the years.

```bash
root@0e540f42ee9d:/# git clone https://github.com/LumaPictures/pymel.git
Cloning into 'pymel'...
remote: Counting objects: 21058, done.
remote: Total 21058 (delta 0), reused 0 (delta 0), pack-reused 21058
Receiving objects: 100% (21058/21058), 193.16 MiB | 15.62 MiB/s, done.
Resolving deltas: 100% (15370/15370), done.
Checking connectivity... done.
root@0e540f42ee9d:/# cd pymel/
root@0e540f42ee9d:/pymel# ls
CHANGELOG.rst  LICENSE  README.md  docs  examples  extras  maintenance  maya  pymel  setup.py  tests
root@0e540f42ee9d:/pymel# cloc pymel/
      77 text files.
      77 unique files.
       8 files ignored.

http://cloc.sourceforge.net v 1.60  T=0.97 s (71.0 files/s, 65293.4 lines/s)
-------------------------------------------------------------------------------
Language                     files          blank        comment           code
-------------------------------------------------------------------------------
Python                          67           9769          22410          31251
DOS Batch                        2              0              0              2
-------------------------------------------------------------------------------
SUM:                            69           9769          22410          31253
-------------------------------------------------------------------------------
```

<br>

### Third-party

Another wrapping of the Maya API is [MRV](http://pythonhosted.org/MRV/), written by independent developer Sebastian Thiel for Maya 8.5-2011, and [Metan](https://github.com/utatsuya/metan)

- http://pythonhosted.org/MRV/
- https://github.com/utatsuya/metan

Unlike `cmdx` and PyMEL, MRV (and seemingly Metan) exposes the Maya API as directly as possible.

See the [Comparison page](http://pythonhosted.org/MRV/compare/index.html) for more details.

<br>

### YAGNI

The Maya Ascii file format consists of a limited number of MEL commands that accurately and efficiently reproduce anything you can achieve in Maya. This format consists of primarily 4 commands.

- `createNode`
- `addAttr`
- `setAttr`
- `connectAttr`

You'll notice how there aren't any calls to reparent, rename otherwise readjust created nodes. Nor are there high-level commands such as `cmds.polySphere` or `cmds.move`. These 4 commands is all there is to represent the entirety of the Maya scenegraph; including complex rigs, ugly hacks and workarounds by inexperienced and seasoned artists alike.

The members of `cmdx` is a reflection of this simplicity.

However, convenience members make for more readable and maintainable code, so a balance must be struck between minimalism and readability. This balance is captured in `cmdx.encode` and `cmdx.decode` which acts as a bridge between `cmds` and `cmdx`. Used effectively, you should see little to no performance impact when performing bulk-operations with `cmdx` and passing the resulting nodes as transient paths to `cmds.`

<br>

### Timings

`cmdx` is on average `142.89x` faster than `PyMEL` on these common tasks.

|         | Times        | Task
|:--------|:-------------|:------------
| cmdx is | 2.2x faster  | addAttr
| cmdx is | 4.9x faster  | setAttr
| cmdx is | 7.5x faster  | createNode
| cmdx is | 2.6x faster  | connectAttr
| cmdx is | 50.9x faster | long
| cmdx is | 16.6x faster | getAttr
| cmdx is | 19.0x faster | node.attr
| cmdx is | 11.3x faster | node.attr=5
| cmdx is | 1285.6x faster | import
| cmdx is | 148.7x faster | listRelatives
| cmdx is | 22.6x faster | ls

`cmdx` is on average `2.53x` faster than `cmds` on these common tasks.

|         | Times       | Task
|:--------|:------------|:------------
| cmdx is | 1.4x faster | addAttr
| cmdx is | 2.3x faster | setAttr
| cmdx is | 4.8x faster | createNode
| cmdx is | 2.1x faster | connectAttr
| cmdx is | 8.0x faster | long
| cmdx is | 1.8x faster | getAttr
| cmdx is | 0.0x faster | import
| cmdx is | 1.8x faster | listRelatives
| cmdx is | 0.5x faster | ls

> Run `plot.py` to reproduce these numbers.

<br>

### Measurements

Below is a performance comparisons between the available methods of manipulating the Maya scene graph.

- `MEL`
- `cmds`
- `cmdx`
- `PyMEL`
- `API 1.0`
- `API 2.0`

Surprisingly, `MEL` is typically outdone by `cmds`. Unsurprisingly, `PyMEL` performs on average 10x slower than `cmds`, whereas `cmdx` performs on average 5x faster than `cmds`.

<br>

#### Overall Performance

Shorter is better.

![](plots/stacked.svg)

#### import

Both `cmdx` and PyMEL perform some amount of preprocessing on import.

![](plots/import.svg)

#### createNode

![](plots/createNode.svg)

#### getAttr

![](plots/getAttr.svg)

#### setAttr

![](plots/setAttr.svg)

#### connectAttr

![](plots/connectAttr.svg)

#### long

Retrieving the long name of any node, e.g. `cmds.ls("node", long=True)`.

![](plots/long.svg)

#### node.attr

Both `cmdx` and PyMEL offer an object-oriented interface for reading and writing attributes.

```python
# cmdx
node["tx"].read()
node["tx"].write(5)

# PyMEL
pynode.tx().get()
pynode.tx().set(5)
```

![](plots/node.attr.svg)

![](plots/node.attr=5.svg)

<br>

### Evolution

`cmdx` started as a wrapper for `cmds` where instead of returning a transient path to nodes, it returned the new UUID attribute of Maya 2016 and newer. The benefit was immediate; no longer had I to worry about whether references to any node was stale. But it impacted negatively on performance. It was effectively limited to the performance of `cmds` plus the overhead of converting to/from the UUID of each absolute path.

The next hard decision was to pivot from being a superset of `cmds` to a subset; to rather than wrapping the entirety of `cmds` instead support a minimal set of functionality. The benefit of which is that more development and optimisation effort is spent on less functionality.

<br>

### References

These are some of the resources used to create this project.

- http://austinjbaker.com/mplugs-setting-values
- https://nccastaff.bournemouth.ac.uk/jmacey/RobTheBloke/www/mayaapi.html

<br>

### Notes

Additional thoughts.

#### MDagModifier

`createNode` of `OpenMaya.MDagModifier` is ~20% faster than `cmdx.createNode` *excluding* load. Including load is 5% *slower* than `cmdx`. 

```python
from maya.api import OpenMaya as om

mod = om.MDagModifier()

def prepare():
    New()
    for i in range(10):
        mobj = mod.createNode(cmdx.Transform)
        mod.renameNode(mobj, "node%d" % i)

def createManyExclusive():
    mod.doIt()


def createManyInclusive():
    mod = om.MDagModifier()

    for i in range(10):
        mobj = mod.createNode(cmdx.Transform)
        mod.renameNode(mobj, "node%d" % i)

    mod.doIt()

def createMany(number=10):
    for i in range(number):
        cmdx.createNode(cmdx.Transform, name="node%d" % i)

Test("API 2.0", "createNodeBulkInclusive", createManyInclusive, number=1, repeat=100, setup=New)
Test("API 2.0", "createNodeBulkExclusive", createManyExclusive, number=1, repeat=100, setup=prepare)
Test("cmdx", "createNodeBulk", createMany, number=1, repeat=100, setup=New)

# createNodeBulkInclusive API 2.0: 145.2 ms (627.39 µs/call)
# createNodeBulkExclusive API 2.0: 132.8 ms (509.58 µs/call)
# createNodeBulk cmdx: 150.5 ms (620.12 µs/call)
```

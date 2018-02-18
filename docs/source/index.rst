.. `cmdx` documentation master file, created by
   sphinx-quickstart on Tue Jun 20 20:12:06 2017.
   You can adapt this file completely to your liking, but it should at least contain the root `toctree` directive.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

.. image:: https://user-images.githubusercontent.com/2152766/34321609-f134e0cc-e80a-11e7-8dad-d124fea80e77.png
   :alt: `cmdx`
   :width: 200
   :align: center
   :target: /cmdx/

.. centered:: *The fast subset of `maya.cmds`*

|

`cmdx`
======

`cmdx` is a Python module for fast scenegraph manipulation in Autodesk Maya.

|

.. currentmodule:: cmdx

API
---

The basics from `maya.cmds` are included.

.. autofunction:: createNode
.. autofunction:: getAttr
.. autofunction:: setAttr
.. autofunction:: addAttr
.. autofunction:: connectAttr
.. autofunction:: listRelatives
.. autofunction:: listConnections

|
|

Object Oriented Interface
-------------------------

In addition to the familiar interface inherited from `cmds`, `cmdx` offers a faster, object oriented alternative to all of that functionality, and more.

.. autoclass:: Node
  :members:
  :undoc-members:

|

.. autoclass:: DagNode
  :members:
  :undoc-members:

|

.. autoclass:: Plug
  :members:
  :undoc-members:

|
|

Attributes
----------

.. autoclass:: Enum
.. autoclass:: Divider
.. autoclass:: String
.. autoclass:: Message
.. autoclass:: Matrix
.. autoclass:: Long
.. autoclass:: Double
.. autoclass:: Double3
.. autoclass:: Boolean
.. autoclass:: AbstractUnit
.. autoclass:: Angle
.. autoclass:: Time
.. autoclass:: Distance

|
|

Units
-----

.. autodata:: Degrees
.. autodata:: Radians
.. autodata:: AngularMinutes
.. autodata:: AngularSeconds
.. autodata:: Millimeters
.. autodata:: Centimeters
.. autodata:: Meters
.. autodata:: Kilometers
.. autodata:: Inches
.. autodata:: Feet
.. autodata:: Miles
.. autodata:: Yards

|
|

Interoperability
----------------

.. autofunction:: encode
.. autofunction:: decode

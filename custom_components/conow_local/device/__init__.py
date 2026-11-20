"""Layer 3: the Home Assistant device page.

The coordinator polls the active map, ``descriptions`` turns entity specs
into HA entity descriptions, and ``guard`` keeps device-page writes
read-only.  The platform modules (``sensor.py``, ``binary_sensor.py``,
``number.py``, ``select.py``, ``switch.py``, ``time.py``) live at the
integration root because Home Assistant imports platforms by that exact path;
they hold the entity classes and use the helpers in this package.
"""

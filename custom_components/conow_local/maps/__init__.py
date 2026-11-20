"""Layer 1+2: register-map registration, parsing and entity mapping.

``registry`` decides which map file (v1/v2) is active for the connected
firmware.  ``model`` turns a map JSON into registers, blocks and decoded
values.  ``entity_model`` turns registers into Home Assistant entity specs.
Both map JSON files live in this package.

Only stdlib is used here so ``tools/i18n/build_panel_i18n.py`` can import the
package outside Home Assistant.
"""

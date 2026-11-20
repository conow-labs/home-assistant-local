# Conow Local for Home Assistant

Local Modbus RTU/TCP integration for CONOW balcony-solar storage devices (Lyra, CBE, Atlas). No cloud account is required.

**Full documentation: [README.html](https://htmlpreview.github.io/?https://raw.githubusercontent.com/conow-labs/home-assistant-local/main/README.html)** — installation, Conow app preparation, Home Assistant setup for all three connection types, animated panel demonstrations, the write sequence and every error message. The guide is available in English, Chinese, German and Dutch.

## Version notes

Current integration version: **2.5.0**

| Version | Released | Register map | Highlights |
| ------- | -------- | ------------ | ---------- |
| **v2** | Nov 4, 2026 | `maps/panel_registers.json` | Finalized v2 map; grouped panel; validated whole-group writes in one atomic FC 0x10 frame; 30 s polling |
| **v1** | Jul 16, 2026 | `maps/registers.json` | Initial register map; controls on the Home Assistant device page; 5 s polling |

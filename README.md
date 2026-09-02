# Tesvor Integration for Home Assistant

[![EN](https://img.shields.io/badge/English-blue)](README.md)
[![RU](https://img.shields.io/badge/Русский-red)](README_ru.md)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![GitHub Release](https://img.shields.io/github/v/release/Aulig/hass-tesvor)](https://github.com/Aulig/hass-tesvor/releases/latest)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Control robot vacuums registered in the [Tesvor Home](https://play.google.com/store/apps/details?id=com.teasvor.home) app from Home Assistant. This Tesvor-specific fork is based on [hass-neatsvor](https://github.com/CoderAS-ru/hass-neatsvor).

<pre>
<img height="400" alt="image 1" src="https://github.com/user-attachments/assets/6419f86e-c2d4-4ad0-9c87-4f2353e58050" /> <img height="400" alt="image 2" src="https://github.com/user-attachments/assets/9ac0f6e0-51f0-4c3e-8b10-6ff4e5e7264c" /> <img height="400" alt="image 3" src="https://github.com/user-attachments/assets/074ffd55-1ffa-4e4f-979d-6359d8c845ec" /> <img height="400" alt="image 4" src="https://github.com/user-attachments/assets/512a0f42-579d-4dc6-a25d-46958b33481d" /> <img height="400" alt="image 5" src="https://github.com/user-attachments/assets/1b3a7ea5-862f-4392-ac62-f80aa16cabd2" />
</pre>

## Features

- 🎮 **Full Control:** Start, pause, stop cleaning, return to dock
- 🗺️ **Live Map:** Display the room map with the robot's real-time position
- 📍 **Zone Cleaning:** Select a zone on the map for cleaning (requires [lovelace-xiaomi-vacuum-map-card](https://github.com/PiotrMachowski/lovelace-xiaomi-vacuum-map-card))
- 🧹 **Room Cleaning:** Ability to clean individual rooms by name
- 💧 **Water Level Adjustment** (for mopping models)
- 💨 **Suction Power Adjustment**
- 📊 **Sensors:** Status, battery charge, cleaning time/area
- 🔄 **Consumables:** Display the wear level of the filter and brushes
- 📸 **Cleaning History:** Save and view maps from previous cleanings
- ☁️ **Cloud Maps:** Download and use maps saved in the cloud
- 🌐 **Localization:** Support for Russian and English

### Smart Home with Alice (Yandex)

- 📱 **Voice Control:** Manage and monitor from the "Smart Home with Alice" app (requires [yandex_smart_home](https://github.com/dext0r/yandex_smart_home))
- 🔋 **Battery Status:** Display battery level in the Alice Smart Home app
- 📊 **Sensors in the App:** Access digital sensor values within the Alice Smart Home app

## Installation

### Via HACS

1. Find and install the "Tesvor" integration in **HACS** (default repository).
2. Restart Home Assistant.

### Via HACS (Custom Repository)

If the integration is not available in your HACS list, you can add it manually:

1. Add this repository to HACS as a custom repository.
2. Install the Tesvor integration.
3. Restart Home Assistant.

### Manual Installation

- Copy the `custom_components/tesvor` folder to your `config/custom_components/`
- Restart Home Assistant

## Configuration

### Adding the Integration via UI

- Go to **Settings → Devices & Services**
- Click **"+ Add Integration"**
- Find and select "Tesvor"
- Enter the **phone code** (country/region) used by your Tesvor Home account (for example, "+49" or "49")
- Enter your **Tesvor Home email** and **password**
- Complete the setup

### Account Requirements

- Create an account in Tesvor Home and pair your device if you haven't already
- Important rule: **One account - one connection**
- For control from multiple devices, use the **"Share Device"** function in the app

## Usage

### Zone Cleaning

To use zone cleaning, you need to install `lovelace-xiaomi-vacuum-map-card`:
```yaml
type: custom:xiaomi-vacuum-map-card
entity: vacuum.tesvor_vacuum
map_source:
  camera: camera.tesvor_<device_id>_live_camera
calibration_source:
  identity: true
zones:
  service: tesvor.vacuum_clean_zone
  service_data:
    entity_id: vacuum.tesvor_vacuum
    zones: "[[x1, y1, x2, y2, 1]]"
```

### Voice Cleaning of Individual Rooms
1. Go to **Settings → Automations & Scenes → Scripts**
2. Click **"Create Script" → "Create new script" → "Add Action"**
3. In the search field, type **'tesvor'**
4. Select the action **'Tesvor: Clean room with preset'**
5. Specify:
   - **Targets → Add target**: Select your robot vacuum
   - **Room name: The exact name of the room (case-sensitive!)**
   - **Toggle 'Use Preset' should be ON!** (This uses your saved settings for that room)
6. Click **'Save'**
7. Enter a name for the script (e.g., Clean Kitchen)
8. Optionally, add a description, area, and icon.

In YAML mode:
```yaml
sequence:
  - action: tesvor.clean_room_with_preset
    metadata: {}
    data:
      use_preset: true
      room: Kitchen
    target:
      entity_id: vacuum.tesvor_<device_id>_vacuum
alias: Clean Kitchen
description: Start cleaning the kitchen
```

After creating the script, you need to expose it to Yandex Smart Home via the yandex_smart_home integration configuration.
After this, you can use voice commands in the "Smart Home with Alice" app:
  - _"Alice, turn on the kitchen cleaning"_
  - _"Alice, turn off the living room cleaning"_

## Services

| Service | Description |
|---------|-------------|
| `tesvor.vacuum_clean_zone` | Start zone cleaning |
| `tesvor.clean_room_with_preset` | Clean a room using saved presets |
| `tesvor.set_reference_map` | Set the current map as reference |
| `tesvor.restore_reference_map` | Restore room config from reference map |
| `tesvor.compare_with_reference` | Compare current map with reference |
| `tesvor.request_all_data` | Request all data like the official app |
| `tesvor.request_map` | Request the current map |
| `tesvor.build_map` | Fast map build without cleaning |
| `tesvor.empty_dust` | Force empty the dust bin |
| `tesvor.use_cloud_map` | Use a specific cloud map as current |
| `tesvor.use_selected_cloud_map` | Use the selected cloud map as current |
| `tesvor.force_load_history` | Force-load all cleaning history maps |
| `tesvor.cleanup_maps` | Remove old realtime maps and metadata |
| `tesvor.cleanup_history_maps` | Clean up old history maps |
| `tesvor.cleanup_all_except_current` | Clean up all history maps except current |
| `tesvor.force_update_maps` | Force-refresh all map-related sensors |
| `tesvor.save_select_states` | Save current select-entity states |
| `tesvor.restore_select_states` | Restore saved select-entity states |

## Example Automation: Status Notifications

This example automation sends you notifications about your vacuum's status, including a map preview when an error occurs. It supports both persistent notifications in the Home Assistant UI and push notifications to your mobile device.

### Features

- 🔔 **Start/Pause/Return notifications** — get alerted when the vacuum starts, pauses, or returns to the dock.
- ✅ **Cleaning summary** — receive a report with cleaning time, area, battery level, and a link to the map.
- ⚠️ **Error alerts** — get a critical notification with the map showing the robot's last position.
- 🔋 **Charging status** — notifications when the vacuum is fully charged.

### How to use

1. Copy the automation code from the link below.
2. Replace the placeholder variables with your own entity names and personal details.
3. Paste the automation into your `automations.yaml` file or create it via the Home Assistant UI.

[📄 Download the automation example](SAMPLE_automation_tesvor_status.yaml)

### Required entities

Make sure you have the following sensors from the Tesvor integration:

- `sensor.tesvor_<device_id>_status` — current vacuum status.
- `sensor.tesvor_<device_id>_clean_history` — cleaning history records.
- `sensor.tesvor_<device_id>_map_data` — map data with the `map_path` attribute.
- `sensor.tesvor_<device_id>_current_clean_time` — current cleaning time.
- `sensor.tesvor_<device_id>_current_clean_area` — current cleaning area.
- `sensor.tesvor_<device_id>_battery` — battery level.

### Customization

You can easily customize the automation by modifying the variables at the top of the script:

```yaml
variables:
  # ========== PERSONAL DATA (REPLACE WITH YOUR OWN) ==========
  external_url: "https://YOUR-DOMAIN.duckdns.org:8123"    # Your Home Assistant URL
  mobile_notify_service: "notify.mobile_app_YOUR_DEVICE" # Your mobile notification service

  # ========== ENTITY NAMES (REPLACE WITH YOUR OWN) ==========
  vacuum_status_entity: "sensor.tesvor_<device_id>_status"
  vacuum_clean_history: "sensor.tesvor_<device_id>_clean_history"
  vacuum_map_data: "sensor.tesvor_<device_id>_map_data"
  vacuum_clean_time: "sensor.tesvor_<device_id>_current_clean_time"
  vacuum_clean_area: "sensor.tesvor_<device_id>_current_clean_area"
  vacuum_battery: "sensor.tesvor_<device_id>_battery"
```

## Supported Devices
### Tesvor
  - [S700](https://tesvor.ru/product/productDetail?spuId=28)
  - [N7](https://tesvor.ru/product/productDetail?spuId=40)

## Troubleshooting
### Authentication Error
- Check your email and password
- Ensure the correct phone code is selected
- Verify that the account works in the Tesvor Home app

### Map Not Displayed
- Make sure the robot has completed at least one cleaning
- Check the MQTT connection in the logs
- Try calling the tesvor.request_map service

### Zone Cleaning Doesn't Work
- Ensure xiaomi-vacuum-map-card is installed
- Check that the map is displayed correctly
- Make sure the robot is not on the dock

### MQTT Issues
- Ensure outgoing connections to port 8011 are allowed in your network
- Check that a firewall isn't blocking connections to the BlackVision MQTT servers

### Logs
Logs can be viewed at **Settings → System → Logs** → select custom_components.tesvor.

## Known Limitations
- Zone cleaning coordinates are automatically adjusted for the map's origin offset
- Map editing (splitting/merging rooms) is not implemented
- Using multiple apps simultaneously requires separate integration instances

## Contributing
If you find a bug or want to suggest an improvement:
1. Create an Issue on GitHub
2. Submit a Pull Request with your changes

## Technical Details
### How the Integration Works
This integration uses **reverse-engineering** of the official mobile app to fully understand the data exchange protocol with the devices.

**Key implementation features:**

- 🔍 **Dynamic DP Schema**: The integration retrieves the current Data Point schema for your specific vacuum model directly from the cloud.
- 📡 **Native MQTT Protocol**: Direct interaction with the device via the MQTT broker, just like the official app.
- 🗺️ **Full Map Support**: Decoding of the proprietary map format.
- 🔄 **Up-to-Date**: When new models or functions are added to the app, the integration automatically supports them (if they use existing DPs).

### Why This Matters
By retrieving the DP schema from the cloud, the integration:
- Supports all vacuum models without needing an update for each one
- Automatically obtains new device capabilities
- Correctly displays all sensors and settings for your specific model

### Legal Information

This integration was created for educational purposes and for the Home Assistant community. The developer is not affiliated with BlackVision or Tesvor. All trademarks are the property of their respective owners.

> **Note**: This integration does not modify device firmware, bypass security systems, or violate the terms of use of the official applications.

## License
MIT License - free use, modification, and distribution.

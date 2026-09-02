# Tesvor Home integration for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![GitHub Release](https://img.shields.io/github/v/release/Aulig/hass-tesvor)](https://github.com/Aulig/hass-tesvor/releases/latest)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Control robot vacuums registered in the [Tesvor Home](https://play.google.com/store/apps/details?id=com.teasvor.home) app from Home Assistant. This experimental Tesvor-specific fork is based on [hass-neatsvor](https://github.com/CoderAS-ru/hass-neatsvor).

## Project status

The Tesvor Home application identity, German (`+49`) login flow, account discovery, device discovery, and dynamic Data Point (DP) schema retrieval have been validated against a real Tesvor Home account.

The following features are implemented but have not yet been fully tested on Tesvor hardware:

- Start, pause, stop, locate, and return to dock
- Suction power, water level, and cleaning mode controls when exposed by the model
- Live maps, room cleaning, and zone cleaning
- Cloud-map selection, download, activation, and restoration
- Cleaning-history maps and consumable statistics

Availability depends on the capabilities advertised by the vacuum. Until individual models have been tested, no specific model is claimed as fully supported. Please report the model, action, and relevant Home Assistant logs when opening an issue.

## Installation

### HACS (recommended)

1. Open **HACS → Integrations**.
2. Open the menu in the top-right corner and select **Custom repositories**.
3. Add `https://github.com/Aulig/hass-tesvor` with the category **Integration**.
4. Find and download **Tesvor** in HACS.
5. Restart Home Assistant.

### Manual installation

Copy `custom_components/tesvor` into `config/custom_components/tesvor`, then restart Home Assistant.

## Configuration

1. Open **Settings → Devices & services**.
2. Select **Add integration**, then choose **Tesvor**.
3. Enter the calling code used by your Tesvor Home account, such as `+49` or `49` for Germany.
4. Enter the email address and password used in the Tesvor Home app.

The integration uses Tesvor's cloud API and MQTT broker. If updates stop while the mobile app is open, close the app and reload the integration; concurrent sessions may interfere with one another.

## Controls and entities

The primary vacuum entity advertises start, pause, stop, locate, return-to-dock, and fan-speed actions. Additional select entities are created from the model's reported DP schema. Map buttons are currently created for every device, but a command can still fail when its required DP or map data is unavailable on that model.

### Map buttons

Cloud-map actions use the current value of the **Cloud Map Select** entity unless stated otherwise.

| Button | What it does | Risk/notes |
|---|---|---|
| **Refresh Cloud Maps** | Fetches the cloud-map list again and refreshes its Home Assistant sensor. | Read-only. |
| **Download Map** | Downloads and renders the selected cloud map into Home Assistant's local map cache. | Read-only for the robot. Selecting a map may already trigger background download, so this is mainly a manual retry. |
| **Set Reference Map** | Marks the selected cloud map as the reference used by restore and auto-restore. | Local Home Assistant state only; the selection is currently lost when the integration restarts. It does not change the robot by itself. |
| **Restore Reference Map** | Sends the locally marked reference map to the robot and requests a fresh live map. | Changes the robot's active map. Set a reference first. |
| **Save Current Map** | Sends the robot's `map_save` command, asking it to save its current map to the cloud. | Changes cloud map state and is not yet verified on Tesvor hardware. |
| **Use Selected Map** | Activates the selected cloud map on the robot, then requests a refreshed live map. | Changes the robot's active map; use this mainly to switch or recover maps/floors. |
| **Refresh Clean History** | Loads up to ten recent cleaning records and renders their maps locally. | Read-only for the robot, but may take a few minutes and use local storage. |

The **Cloud Map Camera** only previews the selected cloud map. Selecting or downloading a map does not activate it on the robot; **Use Selected Map** does.

### Zone cleaning card

Zone cleaning can be used with [Xiaomi Vacuum Map Card](https://github.com/PiotrMachowski/lovelace-xiaomi-vacuum-map-card):

```yaml
type: custom:xiaomi-vacuum-map-card
entity: vacuum.tesvor_<device_id>_vacuum
map_source:
  camera: camera.tesvor_<device_id>_live_map
calibration_source:
  identity: true
map_modes:
  - template: vacuum_clean_zone
```

The bundled card template calls `tesvor.vacuum_clean_zone` and converts selected rectangles using the live map's origin and scale.

## Services

These advanced actions are available under the `tesvor` domain. Map-changing commands should be tested cautiously on each model.

| Service | Description |
|---|---|
| `tesvor.vacuum_clean_zone` | Clean one or more rectangular zones. |
| `tesvor.clean_room_with_preset` | Clean a named room, optionally using its saved settings. |
| `tesvor.request_all_data` | Request the current set of device DPs. |
| `tesvor.request_map` | Request a fresh live map. |
| `tesvor.build_map` | Ask the robot to perform its fast map-building operation. |
| `tesvor.empty_dust` | Ask a compatible dock to empty the dust bin. |
| `tesvor.set_reference_map` | Ask the robot to save its current map as its reference map. |
| `tesvor.restore_reference_map` | Activate the locally selected reference cloud map. |
| `tesvor.compare_with_reference` | Compare basic metadata for the selected and reference maps. |
| `tesvor.use_cloud_map` | Activate a cloud map using explicit ID, URL, and MD5 values. |
| `tesvor.use_selected_cloud_map` | Activate the map chosen in Cloud Map Select. |
| `tesvor.force_load_history` | Download and render recent cleaning-history maps. |
| `tesvor.cleanup_maps` | Remove older locally cached real-time maps. |
| `tesvor.cleanup_history_maps` | Remove older locally cached history maps. |
| `tesvor.cleanup_all_except_current` | Remove all locally cached history maps except the selected one. |
| `tesvor.force_update_maps` | Refresh map-related entities. |
| `tesvor.save_select_states` | Persist the integration's current select values. |
| `tesvor.restore_select_states` | Restore previously persisted select values. |

## Troubleshooting

### Authentication errors

- Verify the same credentials in the Tesvor Home app.
- Use the calling code associated with the account, not necessarily the current physical location.
- For Germany, both `+49` and `49` are accepted.

### Missing or stale maps

- Complete at least one mapping or cleaning run in the Tesvor Home app.
- Check **Settings → System → Logs** for `custom_components.tesvor` and MQTT errors.
- Run `tesvor.request_map` for the affected vacuum.
- Refresh the cloud-map list before downloading or activating a saved map.

The integration requires outbound access to Tesvor/BlackVision HTTPS services and MQTT port `8011`.

## Known limitations

- Physical commands and map mutation have not yet been validated across Tesvor models.
- Map editing, including room splitting and merging, is not implemented.
- The reference-map button stores its choice only in memory and must be set again after an integration or Home Assistant restart.
- The integration depends on undocumented cloud and MQTT protocols that may change without notice.

## Technical details

The integration uses the application identity from Tesvor Home 1.8.2, discovers the account's regional endpoints, retrieves each device's DP schema, and communicates through the same BlackVision cloud and MQTT infrastructure used by the app. Dynamic schema discovery helps expose model-specific values, but it does not guarantee that every future DP or device behavior is supported.

This project is not affiliated with Tesvor or BlackVision. Tesvor and related marks belong to their respective owners.

## License

MIT

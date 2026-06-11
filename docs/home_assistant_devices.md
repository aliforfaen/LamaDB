# Home Assistant — Device Usage Reference

> Snapshot of what's **actually** in use at home. Generated from a 30-day logbook pull (1881 events) plus 180-day scene activation state, against the live HA instance at `192.168.10.36:8123` (HA Core 2026.6.2).
>
> Source data: `/api/logbook`, `/api/states`, and the WebSocket registry (`config/entity_registry/list`, `config/device_registry/list`, `config/area_registry/list`).

---

## TL;DR — Top 10 Things You Actually Touch

| Rank | What | Entity ID | 30-day events |
|---|---|---|---|
| 1 | Hallway light (auto + manual) | `light.gang_2` | **21** |
| 2 | Bathroom light | `light.bad_2` | **10** |
| 3 | All-lights zone group | `light.alle_lys` | **10** |
| 4 | "Home" zone group (mostly identical to alle_lys) | `light.home` | **10** |
| 5 | Leselampe — Hue smart plug (not a light) | `light.leselampe` | **8** |
| 6 | Nightstand plug | `light.nattlampe` | **4** |
| 7 | Bedroom ceiling | `light.soverom_2` | **4** |
| 8 | Monitor desk strip | `light.datalys_2` | **3** |
| 9 | Sofa back-light (movie bias light) | `light.sofalys_2` | **2** |
| 10 | Stuelys (the "missing" living-room light) | `light.stuelys` | (0 — see note) |

**Top scenes** (by `state` = last-activated timestamp, since logbook doesn't log scene activations):

| Last activated | Scene | Entity ID |
|---|---|---|
| 12d ago (2026-05-30) | Warm White | `scene.warm_white` |
| 41d ago (2026-04-30) | Pink Party | `scene.oda_s_pink_party` |
| 42d ago (2026-04-29) | Energizing | `scene.energizing` |
| 56d ago (2026-04-15) | Movie Mode | `scene.new_scene` |
| 71d ago (2026-03-31) | Opplyst | `scene.opplyst` |
| 83d ago (2026-03-20) | Night mode | `scene.night_mode` |

**Note on Stuelys:** it exists in HA, lives in the `light.home` group, and is currently off — but the logbook shows zero events. The other living-room lights carry the load. Worth confirming whether it's broken, renamed, or just genuinely unused.

---

## Lights — Ranked by Logbook Activity (30d)

All Hue. Device IDs are HA's internal `device_registry.id` (the same string you'd see in the URL bar when you click a device in the HA UI).

| Events | Entity ID | Friendly name | Area | Device ID | Manufacturer / Model |
|---:|---|---|---|---|---|
| **21** | `light.gang_2` | Gang | Gang | `d9fef29136d29127e940e2c4b8d76593` | Signify / Hue ambiance lamp |
| **10** | `light.bad_2` | Bad | Bad | `be11dbf80d61748de6d319d3932322e3` | Signify / Hue ambiance lamp |
| **10** | `light.alle_lys` | Alle lys *(Hue zone — master group)* | unassigned | `88a55c7238cde681b336c810af24c1c2` | Signify / Hue Zone |
| **10** | `light.home` | Home *(Hue zone — secondary group, includes Stuelys)* | unassigned | `83b8aab58eab63c9cba3d9b47f043b1d` | Signify / Hue Zone |
| **8**  | `light.leselampe` | Leselampe *(Hue smart plug — used for the vifteovn heater)* | Stue | `faf5edf5d25c16f5b56f59104910e1ce` | Signify / Hue smart plug |
| **4**  | `light.nattlampe` | Nattlampe *(nightstand plug)* | Soverom | `9b64254716da6a582789491436b8c6bc` | Signify / Hue smart plug |
| **4**  | `light.soverom_2` | Soverom | Soverom | `b9eb0a83765ccfcdee56c60661898562` | Signify / Hue ambiance lamp |
| **3**  | `light.datalys_2` | Datalys *(monitor desk strip)* | Stue | `da2860f0e818a09426863777f7865c79` | Signify / Hue lightstrip plus |
| **2**  | `light.sofalys_2` | Sofalys *(behind couch — dim for movies!)* | Stue | `c75438c7f8a114769e53946fc5167d7a` | Signify / Hue lightstrip plus |
| 0 | `light.stuelys` | Stuelys | (none) | (search registry) | Signify / Hue (model unconfirmed) |
| 0 | `light.illamakamera_floodlight_timed` | IllamaKamera Floodlight | (none) | (Tapocam) | TP-Link / Tapo camera floodlight |

### Hue Zone Membership

The two "zone" lights are actually group abstractions that turn on multiple physical lights at once:

- **`light.alle_lys`** → `Nattlampe, Gang, Datalys, Soverom, Bad, Sofalys` *(does NOT include Stuelys)*
- **`light.home`** → `Nattlampe, Gang, Stuelys, Soverom, Bad, Sofalys` *(does NOT include Datalys)*

The slight mismatch is the kind of thing that bites you on dashboards. Pick one as canonical and either add Stuelys to alle_lys or Datalys to home.

---

## Scenes — Ranked by Last Activation

For scenes, logbook is silent (HA doesn't log `scene.turn_on` events at all). The only signal is the entity's `state` field, which Hue sets to the ISO timestamp of the most recent activation. This is the authoritative "what do you actually call up" data.

| Last activated | Days ago | Entity ID | Friendly name | Category |
|---|---:|---|---|---|
| 2026-05-30 10:00 | 12 | `scene.warm_white` | Warm White | Daily default (Kark shortcut: `/home warm`) |
| 2026-04-30 20:56 | 41 | `scene.oda_s_pink_party` | Pink Party | Party (Kark: `/home pink`) |
| 2026-04-29 15:47 | 42 | `scene.energizing` | Energizing | (Kark: `/home energy`) |
| 2026-04-15 18:54 | 56 | `scene.new_scene` | Movie Mode | (Kark: `/home movie`) |
| 2026-03-31 18:30 | 71 | `scene.opplyst` | Opplyst | (Kark: `/home bright`) |
| 2026-03-20 00:33 | 83 | `scene.night_mode` | Night mode | (Kark: `/home night`) |
| (never) | ∞ | `scene.home_relax` | Home Relax | Hue sync — never manually activated |
| (never) | ∞ | `scene.home_read` | Home Read | Hue sync |
| (never) | ∞ | `scene.home_concentrate` | Home Concentrate | Hue sync |
| (never) | ∞ | `scene.home_energize` | Home Energize | Hue sync |
| (never) | ∞ | `scene.stue_hal` | Hal | Stue (stue_*) — likely Hue Entertainment / sync |
| (never) | ∞ | `scene.stue_read`, `stue_nightlight`, `stue_rest`, `stue_sundown`, `stue_arctic_aurora`, `stue_concentrate`, `stue_dimmed`, `scene.stue_rio`, `scene.stue_soho`, `scene.stue_relax`, `scene.stue_energise`, `scene.stue_natural_light` | (12 stue scenes) | Hue sync candidates |
| (never) | ∞ | `scene.bad_bright`, `scene.bad_dimmed`, `scene.bad_arise`, `scene.bad_shine`, `scene.bad_storybook`, `scene.bad_unwind`, `scene.bad_sleepy`, `scene.bad_nighttime`, `scene.bad_golden_hours` | (9 bad scenes) | Hue sync candidates |
| (never) | ∞ | `scene.gang_bright`, `scene.gang_dimmed`, `scene.gang_arise`, `scene.gang_shine`, `scene.gang_storybook`, `scene.gang_unwind`, `scene.gang_sleepy`, `scene.gang_nighttime`, `scene.gang_golden_hours_2` | (9 gang scenes) | Hue sync candidates |
| (never) | ∞ | `scene.god_morgen` | God morgen | One-off / Norwegian — possibly a custom routine |

**Total: 42 scenes in the registry. Only 6 ever manually activated.**

> Recommendation for the dashboard: the `home_*` / `stue_*` / `bad_*` / `gang_*` scenes are almost certainly Hue Entertainment sync targets (Hue generates them automatically when you set up a room for music/TV sync). If you don't actually use Hue Sync, they're clutter. Either delete them or move them to a "hidden" group on the dashboard.

---

## Media Players & Remotes

| Events (30d) | Entity ID | Device | Device ID | Notes |
|---:|---|---|---|---|
| **34** | `media_player.illamaboxxx` | IllamaBoxxx (Xbox Series S) | `286a5a57fc0292e37bc98b6806910a22` | Dominant. The "what to watch" hub. |
| **5**  | `media_player.shield_adb` | Shield ADB (NVIDIA Shield) | `cbacc8e1b97ad2e0bd74dc7f409773a1` | Used for ADB remote control (power, nav). |
| **5**  | `media_player.databord` | Databord (Google Nest Hub) | `11fc9dc54b015832dfc2a7a2cf606177` | Cast target. |
| **5**  | `media_player.illamaspeaker` | IllamaSpeaker (Google Home) | `4635bfc86132ce875e587c755d467638` | Cast target. |
| **4**  | `media_player.boxee` | Boxee (NVIDIA Shield, alt config) | `cd47f74fed2f57cab0263712810782ce` | Older/duplicate Shield? |
| 1  | `media_player.illamatv_ue50ru7105kxxc` | IllamaTV (Samsung UE50RU7105KXXC) | `34f3fe90f96c5aa0a739a40367169a5f` | Barely used. |
| 1  | `media_player.boxee_2` | Boxee (Shield, 2nd) | `244c1d2493a504fa15430fd34cca5293` | Duplicate? |
| **34** | `remote.illamaboxxx_remote` | IllamaBoxxx (Xbox remote) | `286a5a57fc0292e37bc98b6806910a22` | Mirrors Xbox media_player — same device. |
| 1  | `remote.boxee` | Boxee (Shield) | `244c1d2493a504fa15430fd34cca5293` | Same as `boxee_2`. |

**Dashboard implication:** The Xbox is 6.8× the next-most-used media device. Shield+ADB remote is the clear "second-screen" pair. The two Google devices (Databord, IllamaSpeaker) and the bare Samsung TV are equally negligible — group them as "casual cast" or hide entirely.

---

## Sensors That Actually Matter

These are the entities a dashboard should care about. The rest are noise (phone presence pings, Xbox network status, backup state, sun positions, etc.).

### Motion / Occupancy

| Entity ID | Friendly name | Area | Device | Notes |
|---|---|---|---|---|
| `binary_sensor.illamasensor_motion` | IllamaSensor Motion | Stue | Hue motion sensor (`9539cfd81bba35cffcb0080199a017fe`) | The only room-occupancy sensor that exists |
| `binary_sensor.illamaphone_presence` | IllamaPhone Presence | (none) | Samsung S24-FE | Phone-as-presence, less reliable |
| `binary_sensor.illamakamera_person_detection_2` | IllamaKamera Person Detection | Stue | Tapo camera | Only camera-occupancy sensor actually online |

### Environment

| Entity ID | Friendly name | Current | Device | Notes |
|---|---|---|---|---|
| `sensor.illamasensor_temperature` | IllamaSensor Temperature | 24.9 °C | `9539cfd81bba35cffcb0080199a017fe` (Hue motion sensor, Stue) | **Mounted high on the wall** — reads ~1 °C high. Kark skill already notes this. |
| `sensor.illamasensor_illuminance` | IllamaSensor Illuminance | 14 lx | same | Lux reading, used by some automations |

### Heater (the misnamed one)

| Entity ID | What it actually is | Device | Notes |
|---|---|---|---|
| `light.leselampe` | Vifteovn fan heater, plugged into a Hue smart plug | `faf5edf5d25c16f5b56f59104910e1ce` | The Kark `/home heat` shortcut. **The original `switch.vifteovn` no longer exists** in the registry. |

> Old Kark skill docs say `switch.vifteovn` — that's stale. The current (and only) way to control the heater via HA is `light.leselampe` (a Hue smart plug pretending to be a light). Update the skill if you want the docs accurate.

---

## Switches — Noise vs Real

The 30-day logbook shows **zero switch events**. The registry has 81 switches. Almost all of them are HACS pre-release toggles, IllamaKamera config bits, and HA-internal automation enablers that you almost certainly never touch.

**Real switches (a person might actually flip):**

| Entity ID | Friendly name | What it does |
|---|---|---|
| `light.leselampe` | Leselampe | Heater (misclassified as light) |
| `light.nattlampe` | Nattlampe | Nightstand plug |
| `light.stuelys` | Stuelys | Living room ceiling (if it still works) |
| `switch.illamasensor_motion_sensor_enabled` | Motion sensor enabled | Master kill-switch for the Stue motion sensor |
| `switch.illamasensor_light_sensor_enabled` | Light sensor enabled | Master kill-switch for the Stue lux sensor |
| `switch.databord_do_not_disturb` | Databord Do Not Disturb | Cast target mute |
| `switch.illamaspeaker_do_not_disturb` | IllamaSpeaker Do Not Disturb | Cast target mute |
| `switch.pi_hole` | Pi-hole | DNS ad-blocker toggle |
| `switch.automation_leaving_home` | Automation: Leaving home | HA helper |
| `switch.automation_coming_home` | Automation: Coming home | HA helper |
| `switch.automation_mimic_presence` | Automation: Mimic presence | HA helper |
| `switch.automation_state_after_streaming` | Automation: state_after_streaming | HA helper |
| `switch.illamakamera_privacy` | Privacy | Camera privacy mode |
| `switch.illamakamera_microphone_mute` | Microphone - Mute | Camera mic |

**Skip on dashboard:** 60+ `*_pre_release` switches, all `illamakamera_trigger_alarm_on_*` switches, `whisper`, `mosquitto_broker`, `matter_server`, `file_editor`. These are HACS plumbing.

---

## Areas

| Area ID | Name | Notable devices |
|---|---|---|
| `bad` | Bad | `light.bad_2` |
| `gang` | Gang | `light.gang_2` |
| `soverom` | Soverom | `light.soverom_2`, `light.nattlampe` |
| `stue` | Stue | `light.datalys_2`, `light.sofalys_2`, `light.leselampe`, IllamaSensor, IllamaKamera, IllamaBoxxx, Shield, IllamaTV |
| `on_the_go` | On the go | (Phone/person presence) |
| `tmp_musicassistant` | Tmp-MusicAssistant | (Cast-zone bookkeeping) |

**Note:** `light.alle_lys` and `light.home` (the two Hue zones) are in *no area*. If you want area-based filtering on the dashboard, you'll have to either assign them or treat them as their own pseudo-area "Alle lys".

---

## Quick Reference Card

```
LIGHTS
  light.gang_2            — Hallway (auto + manual, top of the list)
  light.bad_2             — Bathroom
  light.alle_lys          — Master zone group (NO Stuelys)
  light.home              — Master zone group (NO Datalys)
  light.leselampe         — Heater (misnamed)
  light.nattlampe         — Nightstand plug
  light.soverom_2         — Bedroom
  light.datalys_2         — Monitor strip
  light.sofalys_2         — Behind couch (DIM 10-15% for movies)
  light.stuelys           — (currently zero events — investigate)

SCENES (activated at least once)
  scene.warm_white        — daily default, last 12d ago
  scene.oda_s_pink_party  — last 41d ago
  scene.energizing        — last 42d ago
  scene.new_scene         — Movie Mode, last 56d ago
  scene.opplyst           — last 71d ago
  scene.night_mode        — last 83d ago

MEDIA
  media_player.illamaboxxx       — Xbox Series S (dominant)
  media_player.shield_adb        — Shield
  remote.shield_adb              — Shield ADB remote (POWER, UP, DOWN, etc.)
  media_player.databord          — Nest Hub (cast target)
  media_player.illamaspeaker     — Google Home (cast target)
  media_player.illamatv_ue50ru7105kxxc — Samsung TV

SENSORS
  binary_sensor.illamasensor_motion    — Stue motion
  sensor.illamasensor_temperature      — Stue temp (high-mounted, reads ~1°C high)
  sensor.illamasensor_illuminance      — Stue lux
  binary_sensor.illamakamera_person_detection_2 — Camera person detection
```

---

*Generated by Kark on 2026-06-11 against HA 2026.6.2.*
*Method: 30-day `/api/logbook` pull (1881 entries, all light/media/remote/binary_sensor/sensor events), 180-day scene-state inspection (since logbook doesn't log scene activations), and the WebSocket registry for area/device/unique_id mapping.*

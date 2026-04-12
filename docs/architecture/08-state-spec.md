# 08 – State and Home Assistant Specification (MVP)

This document defines how Nova Suite models and synchronizes external state, with a focus on Home Assistant as the primary home-automation source.

Nova’s goal is to treat state as a shared resource:
- Home Assistant (and other systems) own primary device state
- Nova mirrors relevant entities into its `Entity` model
- Nova emits and consumes events based on state changes

---

## 1. Purpose and scope

The state layer exists to:
- map Home Assistant entities into Nova `Entity` records
- keep those entities reasonably in sync
- turn interesting state changes into `Event` objects Nova-lite can act on
- provide a way for Nova to request actions via Home Assistant services

Out of scope for MVP:
- replacing Home Assistant as a full automation engine
- modeling every possible entity type
- complex two-way synchronization of every attribute

---

## 2. Core models

Nova reuses the shared `Entity` and `Event` models from `15-16-data-models-and-apis.md`.

### Entity mapping

For each selected Home Assistant entity, Nova will maintain an `Entity` record with:

- `id`: internal Nova entity ID
- `external_id`: Home Assistant entity ID (e.g., `light.kitchen_main`)
- `source`: `home-assistant`
- `type`: broad type, e.g., `light`, `switch`, `sensor`, `climate`, `scene`, `script`
- `name`: human-friendly name
- `state`: JSON object with key attributes from Home Assistant state and attributes
- `last_seen_at`: last time Nova synced this entity
- `metadata`: additional tags or configuration (e.g., room)
- `capabilities`: a list of capabilities such as `on_off`, `brightness`, `color_temp`, `temperature_setpoint`
- `room_or_group`: optional logical grouping (e.g., `kitchen`)

---

## 3. Integration with Home Assistant

### 3.1 Connectivity

MVP options for connecting to Home Assistant include:

- using the Home Assistant REST API
- using WebSocket/event streams if available

Configuration needed:
- Home Assistant base URL
- access token / credentials
- list of entity IDs or filters (e.g., by domain or area) to sync

### 3.2 Sync patterns

Nova should implement a hybrid sync approach:

- **Periodic full or partial sync**
  - regularly fetch states of selected entities
  - update Nova `Entity` records with any changes

- **Event-driven updates (where possible)**
  - subscribe to Home Assistant events (e.g., state_changed)
  - for relevant entities, update the corresponding Nova `Entity` and create `Event` records

This combination helps keep Nova’s view up to date without relying solely on frequent polling.

---

## 4. Event generation

The state layer is responsible for converting state changes into `Event` objects Nova-lite can use.

### 4.1 When to emit events

Nova should emit events when:

- selected entities change significantly (e.g., a door sensor opens, a light turns on or off)
- specific patterns occur (e.g., all lights off, presence changes, certain sensors cross thresholds)

Events should use:

- `type`: e.g., `ha.entity.changed`, `ha.scene.activated`, `ha.alarm.triggered`
- `source`: `home-assistant`
- `subject`: a short description
- `payload`: a structured object with old and new states and relevant attributes
- `entity_refs`: list containing the Nova entity ID(s)

### 4.2 Avoiding loops

To avoid feedback loops:

- Nova should mark events and actions it originates with appropriate context or metadata.
- When syncing state, check whether a change was caused by Nova itself and avoid re-emitting events that would cause redundant actions.

---

## 5. Actions via Home Assistant

Nova should control devices by calling Home Assistant services rather than directly modifying entity state.

### 5.1 Service calls

Through workflow-backed tools or direct adapters, Nova can:

- call `light.turn_on`, `light.turn_off`
- call `switch.turn_on`, `switch.turn_off`
- call `climate.set_temperature`
- call `scene.turn_on`
- trigger scripts and automations

These calls should be exposed as tools (e.g., `ha.light.turn_on`) with:

- clear input schemas (e.g., `entity_id`, optional brightness or color)
- appropriate risk classifications

### 5.2 State updates

After calling a service, Nova should rely on Home Assistant to update state and then sync that back into `Entity` records. Nova should not attempt to override HA’s state directly.

---

## 6. Selection of entities

Not every Home Assistant entity must be mirrored into Nova.

MVP strategy:

- include entities that matter for:
  - daily routines (lights, switches, scenes)
  - safety and security (doors, windows, alarms)
  - comfort (climate, presence)

- optionally include additional sensors as needed (temperature, humidity, power)

Configuration can support:
- explicit include lists
- domain/area-based filters

---

## 7. Performance and reliability

To keep Nova responsive without overloading Home Assistant:

- use reasonable polling intervals for periodic syncs
- batch state fetches where possible
- limit the number of entities Nova actively monitors at first

If WebSocket/event streams are available, prefer them for frequent updates and use polling as a safety net.

---

## 8. Safety and consistency

The state layer should:

- avoid writing directly to Home Assistant entity state except via official service calls
- handle missing or `None` states gracefully
- cope with temporary disconnects by retrying and reconciling on reconnect

When Nova cannot reach Home Assistant:

- mark related `Entity` records as stale
- avoid making assumptions about current physical state
- surface a clear warning in any UI that depends on accurate state

---

## 9. MVP scenarios to support

State integration MVP should support at least:

1. **Simple device control**
   - Nova turns lights on/off via Home Assistant services.
   - Nova syncs the resulting state back into `Entity` and emits events for changes.

2. **Presence-aware behavior**
   - Nova observes presence-related entities (e.g., person/device trackers).
   - State changes generate events that Nova-lite can use for routines or notifications.

3. **Safety-related alerts**
   - Nova monitors door/window sensors or alarms.
   - Significant changes generate high-priority events that can create tasks or notifications.

These flows allow Nova-lite and Nova Board to incorporate Home Assistant state into daily life and work automations without replacing Home Assistant’s core automation capabilities.

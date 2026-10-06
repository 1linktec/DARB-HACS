# DARB — Home Assistant integration

Connects your **darbosphere** to Home Assistant. **DARB — Distributed Autonomous
Robotics Backbone** — is the hub that the robots on a property join; **Home
Assistant owns the property, DARB owns the bodies.** This integration is where the
two meet:

- every DARB **body becomes an HA device**: connected, battery, and what it is
  doing right now;
- the **hub is a device** too: unread notifications, approvals waiting, the
  **Bot Herder**'s tasks running / queued / delayed / failed today, and the
  property's power source;
- every new DARB notification fires a **`darb_notification` event**, so you route
  it however you already route alerts;
- automations can **propose tasks to the Bot Herder** (`darb.create_task`) and
  **answer approvals** (`darb.answer_approval`);
- **DARB can be your Assist conversation agent**: one brain for the robots and
  the house, on every voice surface HA has.

The integration talks to DARB; DARB never talks to Home Assistant and holds no HA
token -- even as the conversation agent, HA's own tools run here, inside HA.
Nothing here can move a body directly: the Bot Herder checks a proposed
task against each body's safety envelope, and may delay or refuse it.

## Install (HACS custom repository)

1. HACS → ⋮ → **Custom repositories** → add
   `https://github.com/1linktec/darb-hacs`, category **Integration** → **Add**.
2. Install **DARB**, then **restart Home Assistant**.
3. The hub announces itself on your network, so HA usually offers it under
   Settings → Devices & services → **Discovered**. Otherwise **Add Integration** →
   **DARB**.

## Pair

In the **Darb app**, as an admin: **Settings › Devices › Connect Home Assistant ›
Make code**. It shows a one-time code like `ABCDE-FGH23` (good for 15 minutes)
and the hub's address. In Home Assistant, add DARB and type the code; capitals
and the dash are optional.

Home Assistant trades the code with the hub for its own key, so no key is ever
shown on a phone. Only admins can make a code. Connecting again replaces the
old Home Assistant key, and if the key is revoked HA asks you to re-pair: make
a new code.

Fallback from the hub console: `sudo darb-pair --ha` prints a line to paste
instead.

## Entities

| Entity | |
|---|---|
| `binary_sensor.<body>_connected` | from the body's MQTT last-will — off within the broker keepalive if it loses power or Wi-Fi |
| `sensor.<body>_battery` | % |
| `sensor.<body>_task` | the goal of the task it is working on, or `idle` |
| `sensor.darb_hub_approvals_waiting` | count; `requests` attribute holds each one, with the id `darb.answer_approval` takes |
| `sensor.darb_hub_unread_notifications` | |
| `sensor.darb_hub_tasks_running` / `_queued` / `_delayed` / `_failed_today` | *delayed* = capable bodies exist but none is free or online |
| `sensor.darb_hub_power_source` | `allow` attribute says what the source permits |

A body added to the darbosphere appears on the next poll, no reload needed.

## Events

`darb_notification`, once per notification:

```yaml
triggers:
  - trigger: event
    event_type: darb_notification
    event_data:
      severity: error        # info | warning | error | action
actions:
  - action: notify.mobile_app_phone
    data:
      title: "{{ trigger.event.data.title }}"
      message: "{{ trigger.event.data.detail }}"
```

Fields: `id`, `kind`, `severity`, `title`, `detail`, `body_id`, `body_name`,
`task_id`, `auth_request_id`, `created_at`. Notifications already on the hub when
the integration is added are history and are not replayed.

`darb_task_done` fires as well when a task finishes, with `task_id`, `title` and
`answer` — so an automation that called `darb.create_task` (whose response
carries the `task_id`) can wait for its result:

```yaml
actions:
  - action: darb.create_task
    data: {goal: "What is the weather tomorrow?", kind: observe}
    response_variable: t
  - wait_for_trigger:
      - trigger: event
        event_type: darb_task_done
        event_data: {task_id: "{{ t.task_id }}"}
    timeout: "00:05:00"
```

## Voice: DARB as the conversation agent

Settings → Voice assistants → your assistant → **Conversation agent: DARB**.
Everything said to that assistant (a Voice PE, a satellite, the HA app) goes to
the DARB hub's model, which:

- answers questions about the robots, batteries, map and past runs from DARB's
  own lookups;
- asks the robots to do things ("send the rover to the shed") through the Bot
  Herder, which still runs its safety gate;
- uses Home Assistant through Assist ("turn off the kitchen lights"). DARB gets
  no token: it asks, and this integration runs the call through HA's Assist API,
  so **only entities exposed to Assist are reachable** and HA's permissions apply.

**Voice requests cannot open the house.** HA cannot tell who is speaking, so a
state change to an exposed lock, alarm panel, garage door, gate or door is
refused ("use the Darb app, which can check who you are"); reading them is fine.
The hub refuses these, and this integration refuses them again before Assist
runs anything (`guard.py`). Personal and sensitive requests to the robots are
refused the same way.

Each request takes a few seconds (6–11 s on an AGX Orin running qwen3 8B); most
of it is the model reading HA's list of exposed entities, so exposing fewer
entities makes it faster.

## Releases

Versions are GitHub releases, so HACS shows a version and offers updates. To
release: bump `version` in `custom_components/darb/manifest.json`, add a
`## x.y.z` section to `CHANGELOG.md`, commit, then push a tag `vx.y.z`. The
Release workflow checks the three agree and publishes the release with that
section as its notes.

## Status

v0.4 polls the hub every 15 s. Planned: an *Expose to DARB* list (HA entities the
planner may reason over), HA's own robots as DARB bodies, presence for people,
camera entities, and a push channel.

Requires Home Assistant **2026.9.0** or later (the conversation agent uses HA's
current chat-log and LLM APIs). Tested end to end against **2026.9.2**: pairing,
the conversation agent with HA's demo entities (light turned off; front door
unlock and garage open refused and left untouched; lock state read; DARB
lookups answered), and the integration refusing a guarded call by itself.
v0.2 was tested on 2025.6.0: zeroconf discovery, pairing errors, entities, both
services and the events.

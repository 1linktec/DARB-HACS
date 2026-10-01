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
  **answer approvals** (`darb.answer_approval`).

The integration talks to DARB; DARB never talks to Home Assistant and holds no HA
token. Nothing here can move a body directly: the Bot Herder checks a proposed
task against each body's safety envelope, and may delay or refuse it.

## Install (HACS custom repository)

1. HACS → ⋮ → **Custom repositories** → add
   `https://github.com/1linktec/darb-hacs`, category **Integration** → **Add**.
2. Install **DARB**, then **restart Home Assistant**.
3. The hub announces itself on your network, so HA usually offers it under
   Settings → Devices & services → **Discovered**. Otherwise **Add Integration** →
   **DARB**.

## Pair

On the hub:

```
sudo darb-pair --ha
```

Paste the whole line it prints into the dialog. The key in it is issued to Home
Assistant alone, so it can be revoked without touching your phone's. If it is
ever revoked, HA asks you to re-pair; run the command again.

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

## Status

v0.1 polls the hub every 15 s. Planned: an *Expose to DARB* list (HA entities the
planner may reason over), HA's own robots as DARB bodies, presence for people,
camera entities, and a push channel.

Tested end to end against Home Assistant **2025.6.0**, the oldest version
supported: zeroconf discovery, pairing, wrong-key and no-key errors, entities,
both services, and the notification event.

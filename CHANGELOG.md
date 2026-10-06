# Changelog

Each version here becomes a GitHub release (the `## x.y.z` heading is the tag
without its `v`), and HACS shows its notes when it offers the update.

## 0.5.1 — 2026-10-06

- Passes Home Assistant's own checks again: no web address inside screen text,
  and setup sets a unique ID so a hub discovered again is recognised.

## 0.5.0 — 2026-10-06

- **HTTPS to the hub.** The hub advertises its https address; when its certificate
  is publicly trusted (Let's Encrypt from the app's Settings › Certificates), Home
  Assistant connects over https instead of plain http on the LAN. A hub on a
  self-signed or household-CA certificate stays on http, which HA can reach.
- An existing http connection moves to https on the next discovery; an https
  connection is never downgraded automatically.

## 0.4.1 — 2026-10-06

- Pairing screens name the right place in the Darb app: Settings › **Devices** ›
  Connect Home Assistant (the tab was renamed from Phones).

## 0.4.0 — 2026-10-06

- **Pair with a one-time code from the Darb app**: Settings › Devices › Connect
  Home Assistant. Home Assistant trades the code for its own key; no key is shown
  on a phone. Capitals and the dash are optional. The `sudo darb-pair --ha` line
  and a bare key still work.
- Connecting again replaces the previous Home Assistant key on the hub.
- The pairing field is plain text now, so a typo can be seen.

## 0.3.0 — 2026-10-06

- **DARB as Home Assistant's conversation agent.** Pick DARB as the conversation
  agent of an Assist pipeline: one brain for the robots and the house. DARB
  answers from its own lookups, sends robots on tasks through the Bot Herder,
  and controls the house through Assist — DARB holds no Home Assistant token.
- Voice cannot open the house: locks, alarm panels, garage doors, gates and doors
  are refused for an unidentified speaker, by the hub and again here.
- Requires Home Assistant 2026.9.0 or later.

## 0.2.0 — 2026-10-04

- `darb_task_done` event carries the answer, so an automation that proposed a task
  can wait for its result. Tasks from Home Assistant are marked as such.

## 0.1.0 — 2026-10-01

- First version: each body an HA device, hub sensors, `darb_notification`
  events, `darb.create_task` and `darb.answer_approval`, zeroconf discovery.

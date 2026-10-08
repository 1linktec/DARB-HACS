# Changelog

Each version here becomes a GitHub release (the `## x.y.z` heading is the tag
without its `v`), and HACS shows its notes when it offers the update.

## 0.10.3 — 2026-10-08

- Security: an exposed **script** whose name opens the house (open, unlock,
  disarm, garage, gate, door…) is refused for a voice DARB can't identify. HA
  offers each script as its own tool with no arguments, so the device checks
  never saw what it touched. The hub refuses these too; this is the second layer.

## 0.10.2 — 2026-10-07

- Locking a lock, closing a garage door or gate, and arming an alarm are allowed
  from HA voice: making the house safer needs no check. Opening, unlocking and
  disarming are still refused here -- they need the robot (face + PIN) or the
  Darb app (signed in + PIN).

## 0.10.1 — 2026-10-07

- "All the lights" always means every exposed light, even when a device is
  named "Lights".

## 0.10.0 — 2026-10-07

- **Areas.** "Turn off the living room lights" turns off every exposed light in
  HA's Living Room area; "turn off the kitchen" everything DARB may change there;
  "all the lights" every exposed light. Area aliases count too.
- Names match without caring about spaces or case ("livingroom" = "Living Room").
- Device actions DARB sends from the app (not only from HA's own voice) find the
  device or area the same way -- before, they needed the exact entity id.

## 0.9.1 — 2026-10-07

- Sends the exposed devices to the hub again once Home Assistant has finished
  starting: at start-up only the devices already loaded were sent (9 of 21 here).
- Voice plumbing exposed to Assist (the wake word engine and the like) is not
  treated as a device.

## 0.9.0 — 2026-10-07

- **DARB follows Home Assistant's own exposure.** Whatever is exposed to Assist
  (Settings › Voice assistants › Expose) is what DARB sees -- the same list every
  assistant uses, no separate form. Sensors, people and weather are read; lights,
  switches, covers, climate and the rest may also be changed. Exposing or
  unexposing an entity reaches DARB at once.
- The separate *Expose to DARB* form (Configure) is gone; its old picks are ignored.
- Locks, alarm panels, garage doors and gates still need a person's approval in
  the Darb app and are never opened by voice.

## 0.8.0 — 2026-10-06

- **Device actions from DARB arrive at once.** The integration keeps one long
  request open to the hub, which answers the moment the Bot Herder queues an HA
  action (it was a 5-second timed poll). This is what lets "turn off the kitchen
  lights", said to DARB in the Darb app, happen as you finish saying it.
- A hub older than this release is still polled every 5 seconds.

## 0.7.0 — 2026-10-06

- **Streaming replies**: DARB's answer streams into Home Assistant as it is
  written, so speech starts on the first words instead of after the whole answer.
- Device commands are confirmed in one round ("Done: Kitchen lights off.") -- the
  hub no longer asks its model a second time.
- Measured end to end in HA 2026.9.4 with the hub at full power: "turn off the
  kitchen lights" 1.9 s (was 9-12 s), a sensor question 0.9 s (was 6 s).
- Needs a DARB hub with /converse/stream; an older hub is used turn by turn.

## 0.6.0 — 2026-10-06

- **Expose to DARB** (Configure on the DARB integration): DARB's own list of devices
  it may *see*, and ones it may *see and change* -- separate from what Home
  Assistant's other assistants see.
- DARB's voice agent uses those devices through its own tools (`GetHomeState`,
  `HomeAction`) instead of the Assist exposure.
- The exposed devices and every change to them go to the DARB hub, so DARB can plan
  with them (who is home, doors, temperatures).
- **DARB can act on the house through its Bot Herder**: an "HA action" task runs
  here and reports back. Locks, alarm panels, garage doors and gates wait for a
  person's approval in the Darb app, and are never opened by voice.
- On the hub, the Bot Herder picks which AI engine answers each voice request.

## 0.5.2 — 2026-10-06

- Clearer pairing: the screens name the app's **Make Home Assistant code** button,
  and pasting a phone pairing link (the app makes those too) says so instead of a
  generic "not a code". `sudo darb-pair --ha` on the hub now prints the same code.

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

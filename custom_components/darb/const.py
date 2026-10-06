"""DARB integration constants."""

DOMAIN = "darb"

# Config entry data
CONF_URL = "url"
CONF_KEY = "key"
# What the user pastes: the whole line `sudo darb-pair --ha` prints
# (`http://<hub>:8080/app/#k=<key>`), or a bare key.
CONF_PAIRING = "pairing"

# The hub's own key is 64 hex characters (openssl rand -hex 32).
KEY_PATTERN = r"[0-9a-fA-F]{64}"

# Polled, as VerdiGrow is. A body going offline should show in HA within one
# interval; 15 s is the app's own cadence order and cheap on the hub (/fleet is
# one round trip by design). Push replaces this when presence needs seconds.
SCAN_SECONDS = 15

# Tool server paths (X-API-Key auth). Read-and-propose only: this API cannot
# actuate a body directly — every task is validated by the hub before dispatch.
API_FLEET = "/fleet"
API_NOTIFICATIONS = "/notifications"
API_APPROVALS = "/approvals"
API_TASKS = "/tasks"
# One turn of an HA conversation: DARB is HA's conversation agent (conversation.py).
API_CONVERSE = "/converse"
# Trade a one-time pairing code from the Darb app for HA's own key (no key needed).
API_REDEEM = "/clients/redeem"
# Expose to DARB: the entities this HA lets DARB see/control, and the HA actions
# the Bot Herder queues for HA to run (hub schema 049).
API_HA_ENTITIES = "/ha/entities"
API_HA_ACTIONS = "/ha/actions"

# Fired once for every new DARB notification, so an owner routes them however
# they already route everything else. An event rather than a notify call: we do
# not know which notifiers exist, and guessing one fails silently (VerdiGrow).
EVENT_NOTIFICATION = "darb_notification"

# Fired as well when the notification says a task finished, carrying its
# answer -- so an automation that proposed a task can wait for the result.
# DARB delivers results "back the way they came" (architecture section 4);
# for a task proposed from HA, this event is the way back.
EVENT_TASK_DONE = "darb_task_done"

# Where the newest-seen notification marker lives, so a restart does not replay
# what was already announced.
STORAGE_KEY_NOTIFY = "darb_notifications"
STORAGE_VERSION = 1

# Services
SERVICE_CREATE_TASK = "create_task"
SERVICE_ANSWER_APPROVAL = "answer_approval"

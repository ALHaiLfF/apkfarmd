from __future__ import annotations

DEFAULT_ADVANCED: dict[str, float] = {
    "task_fps": 30.0,
    "accel_hold": 900.0,
    "accel_release": 900.0,
    "ball_ref_px": 24.0,
    "latency_s": 0.10,
    "auto_latency": 1.0,
    "hysteresis_px": 6.0,
    "aim_offset": 0.0,
    "zone_hold_s": 2.0,
    "lost_timeout_s": 1.5,
    "green_boost": 1.0,
    "yellow_boost": 0.8,
    "white_boost": 1.0,
    "start_confirm_frames": 4.0,
    "cast_settle_sec": 0.08,
    "cast_after_sec": 0.25,
    "wait_minigame_start_sec": 20.0,
    "wait_minigame_end_sec": 20.0,
    "poll_sec": 0.04,
    "after_minigame_sec": 2.0,
    "collect_hold_sec": 3.0,
    "after_collect_sec": 0.35,
    "key_hold_sec": 0.1,
    "visual_read_sec": 0.2,
    "visual_miss_sec": 0.5,
    "visual_hold_sec": 3.0,
    "visual_release_sec": 0.1,
    "visual_gone_sec": 1.0,
    "visual_full_sec": 2.5,
    "visual_swing_sec": 1.0,
    "visual_start_sec": 3.0,
    "visual_max_sec": 15.0,
    "mouse_nudge_mid_sec": 0.01,
    "mouse_nudge_settle_sec": 0.04,
    "mouse_click_hold_sec": 0.04,
    "name_read_delay_sec": 0.1,
}

ADVANCED_SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "Minigame tracking",
        [
            ("task_fps", "Target FPS",
             "How many times a second it checks the bar, lower it if your game lags but I wouldn't go under 20"),
            ("accel_hold", "Hold acceleration",
             "How fast the ball goes up while it's holding, you shouldn't need to touch this"),
            ("accel_release", "Release acceleration",
             "How fast the ball drops when it lets go"),
            ("ball_ref_px", "Ball ref size (px)",
             "The ball size the speeds were measured at, everything scales off this"),
            ("latency_s", "Latency (sec)",
             "How far ahead it guesses where the ball stops, raise it if it overshoots the bar"),
            ("hysteresis_px", "Hysteresis (px)",
             "How far off the middle the ball can be before it switches, higher means calmer clicking"),
            ("aim_offset", "Aim offset (ball heights)",
             "Aims above the middle if it's negative and below the middle if it's positive"),
            ("zone_hold_s", "Zone memory (sec)",
             "If it loses the bar it keeps using the last spot for this long"),
            ("green_boost", "Green boost",
             "How hard it looks for the green bar, raise it if it loses the green, 1 is normal"),
            ("yellow_boost", "Yellow boost",
             "How hard it looks for the yellow bar (when the ball is outside the green), raise it if it loses the yellow, 0 turns it off"),
            ("white_boost", "White boost",
             "How hard it looks for the white ball, raise it if your ball looks dim or grey and it doesn't see it, 1 is normal, too high and it grabs other bright stuff"),
            ("lost_timeout_s", "Ball lost timeout (sec)",
             "If the ball is gone for this long the minigame is over and it goes to collect"),
            ("start_confirm_frames", "Start confirm (frames)",
             "How many frames in a row it has to see the bar before it starts, higher means less false starts"),
            ("poll_sec", "Error poll (sec)",
             "How long it waits before trying again if the scan errors out"),
        ],
    ),
    (
        "Cast and fail cast",
        [
            ("cast_settle_sec", "Cast click settle (sec)",
             "Tiny pause right after the cast click"),
            ("cast_after_sec", "After cast delay (sec)",
             "How long it waits after casting before it looks for the minigame"),
            ("wait_minigame_start_sec", "Fail cast timeout (sec)",
             "If the minigame doesn't show up in this long it recasts (default 20)"),
            ("wait_minigame_end_sec", "Minigame max (sec)",
             "If the minigame goes on longer than this it just collects anyway (default 20)"),
        ],
    ),
    (
        "Keys",
        [
            ("key_hold_sec", "Key hold (sec)",
             "How long T and the rod key get held down, longer means it misses less"),
        ],
    ),
    (
        "Collect fish",
        [
            ("after_minigame_sec", "Delay before collect (sec)",
             "How long it waits after the minigame ends before collecting, same as Delay on the Main tab"),
            ("collect_hold_sec", "Collect hold (sec)",
             "How long it holds T or click to collect, same as Hold on the Main tab"),
            ("after_collect_sec", "After collect delay (sec)",
             "How long it waits after collecting before the next cast"),
            ("visual_read_sec", "Visual T read every (sec)",
             "Visual T collect; how often it reads the T area, lower reacts faster to a spinning fish"),
            ("visual_miss_sec", "Visual T miss (sec)",
             "Visual T collect; the letters have to be gone this long before it lets go of T, stops one bad read from letting go"),
            ("visual_hold_sec", "Visual T hold (sec)",
             "Visual T collect; while the letters are still there it holds T this long, lets go for a sec and holds again"),
            ("visual_release_sec", "Visual T release (sec)",
             "Visual T collect; how long it lets go of T in between those holds"),
            ("visual_gone_sec", "Visual T gone (sec)",
             "Visual T collect; the letters have to stay gone this long before it counts the fish as collected"),
            ("visual_full_sec", "Visual T full hold (sec)",
             "Visual T collect; if the letters vanish after holding at least this long it counts as collected, shorter means the fish swung out"),
            ("visual_start_sec", "Visual T start wait (sec)",
             "Visual T collect; how long it looks for the letters when the collect starts, if it sees nothing it just does a normal hold"),
            ("visual_swing_sec", "Visual T swing wait (sec)",
             "Visual T collect; after the fish swings out this is how long it waits for it to come back"),
            ("visual_max_sec", "Visual T max (sec)",
             "Visual T collect; gives up after this long even if it still reads letters"),
        ],
    ),
    (
        "Mouse click feel",
        [
            ("mouse_nudge_mid_sec", "Move nudge mid (sec)",
             "Timing for the little cursor nudge so Roblox actually registers the click"),
            ("mouse_nudge_settle_sec", "Move settle (sec)",
             "How long it waits after moving the cursor before clicking"),
            ("mouse_click_hold_sec", "Click hold (sec)",
             "How long a normal click stays down"),
        ],
    ),
    (
        "Webhook",
        [
            ("name_read_delay_sec", "Name read delay (sec)",
             "How long it waits after a catch before reading the fish name, same as Read after on the Webhook tab"),
        ],
    ),
]


def merge_advanced(raw: dict | None) -> dict[str, float]:
    out = dict(DEFAULT_ADVANCED)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in out:
                try:
                    out[k] = float(v)
                except (TypeError, ValueError):
                    pass
    return out

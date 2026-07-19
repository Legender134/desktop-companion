from .models import ActionId, ActionRole, AnimationSpec, PetActionDefinition


CELL_WIDTH, CELL_HEIGHT, COLUMNS, ROWS = 192, 208, 8, 11
LOOK_DEGREES = tuple(index * 22.5 for index in range(16))
ACTION_SPECS = {
    ActionId.IDLE: AnimationSpec(0, 7, 180, None),
    ActionId.RUN_RIGHT: AnimationSpec(1, 8, 90, 1, movement=1),
    ActionId.RUN_LEFT: AnimationSpec(2, 8, 90, 1, movement=-1),
    ActionId.WAVE: AnimationSpec(3, 4, 150, 3),
    ActionId.JUMP: AnimationSpec(4, 5, 120, 1, hold_ms=400),
    ActionId.BELLY_FLOP: AnimationSpec(5, 8, 150, 1, hold_ms=1000),
    ActionId.EXPECT: AnimationSpec(6, 6, 180, 2),
    ActionId.PATROL: AnimationSpec(7, 6, 140, 2),
    ActionId.CURIOUS: AnimationSpec(8, 6, 170, 2),
}
ACTION_MANIFEST_SLOTS = (
    ("idle", ActionId.IDLE, "待机", 0),
    ("moveRight", ActionId.RUN_RIGHT, "向右移动", 0),
    ("moveLeft", ActionId.RUN_LEFT, "向左移动", 0),
    ("greet", ActionId.WAVE, "打招呼", 3),
    ("jump", ActionId.JUMP, "跃起", 1),
    ("special", ActionId.BELLY_FLOP, "特别动作", 2),
    ("wait", ActionId.EXPECT, "等待", 3),
    ("observe", ActionId.PATROL, "环顾四周", 2),
    ("curious", ActionId.CURIOUS, "好奇观察", 3),
)
_LEGACY_ROLES = {
    ActionId.IDLE: (ActionRole.IDLE, 0),
    ActionId.RUN_RIGHT: (ActionRole.MOVE, 1),
    ActionId.RUN_LEFT: (ActionRole.MOVE, -1),
}
DEFAULT_PET_ACTIONS = tuple(
    PetActionDefinition(
        key,
        action_id,
        label,
        autoplay_weight,
        spec=ACTION_SPECS[action_id],
        role=_LEGACY_ROLES.get(action_id, (ActionRole.INTERACTION, 0))[0],
        direction=_LEGACY_ROLES.get(action_id, (ActionRole.INTERACTION, 0))[1],
    )
    for key, action_id, label, autoplay_weight in ACTION_MANIFEST_SLOTS
)
IN_PLACE_ACTIONS = (
    ActionId.WAVE,
    ActionId.JUMP,
    ActionId.BELLY_FLOP,
    ActionId.EXPECT,
    ActionId.PATROL,
    ActionId.CURIOUS,
)
KEY_TO_ACTION = {
    1: ActionId.IDLE,
    2: ActionId.RUN_RIGHT,
    3: ActionId.RUN_LEFT,
    4: ActionId.WAVE,
    5: ActionId.JUMP,
    6: ActionId.BELLY_FLOP,
    7: ActionId.EXPECT,
    8: ActionId.PATROL,
    9: ActionId.CURIOUS,
    0: ActionId.RANDOM,
}

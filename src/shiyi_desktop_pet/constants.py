from .models import ActionId, AnimationSpec


CELL_WIDTH, CELL_HEIGHT, COLUMNS, ROWS = 192, 208, 8, 11
LOOK_DEGREES = tuple(index * 22.5 for index in range(16))
ACTION_SPECS = {
    ActionId.IDLE: AnimationSpec(0, 7, 180, None),
    ActionId.RUN_RIGHT: AnimationSpec(1, 8, 90, 1, movement=1),
    ActionId.RUN_LEFT: AnimationSpec(2, 8, 90, 1, movement=-1),
    ActionId.WAVE: AnimationSpec(3, 4, 150, 2),
    ActionId.JUMP: AnimationSpec(4, 5, 120, 1),
    ActionId.BELLY_FLOP: AnimationSpec(5, 8, 150, 1, hold_ms=1000),
    ActionId.EXPECT: AnimationSpec(6, 6, 180, 1),
    ActionId.PATROL: AnimationSpec(7, 6, 140, 1),
    ActionId.CURIOUS: AnimationSpec(8, 6, 170, 1),
}
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

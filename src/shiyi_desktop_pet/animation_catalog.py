from PySide6.QtGui import QImage

from .constants import ACTION_SPECS, CELL_HEIGHT, CELL_WIDTH, LOOK_DEGREES
from .models import ActionId, FrameAsset
from .resource_locator import resource_path


def _has_visible_pixel(image: QImage) -> bool:
    return any(
        image.pixelColor(x, y).alpha() > 0
        for y in range(image.height())
        for x in range(image.width())
    )


class AnimationCatalog:
    def __init__(self, atlas: QImage):
        if atlas.isNull():
            raise ValueError("spritesheet could not be decoded")
        if (atlas.width(), atlas.height()) != (1536, 2288):
            raise ValueError("spritesheet must be 1536x2288")
        if not atlas.hasAlphaChannel():
            raise ValueError("spritesheet must have alpha")
        self._atlas = atlas.convertToFormat(QImage.Format.Format_RGBA8888)
        self.look_degrees = LOOK_DEGREES
        used_counts = (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)
        for row, used in enumerate(used_counts):
            for column in range(8):
                visible = _has_visible_pixel(self._cell(row, column))
                if visible is not (column < used):
                    raise ValueError(f"unexpected occupancy at row {row} column {column}")
        self._actions = {
            action: tuple(
                FrameAsset(self._cell(spec.row, column), spec.row, column)
                for column in range(spec.frame_count)
            )
            for action, spec in ACTION_SPECS.items()
        }

    @classmethod
    def load_default(cls) -> "AnimationCatalog":
        return cls(QImage(str(resource_path("spritesheet.webp"))))

    def _cell(self, row: int, column: int) -> QImage:
        return self._atlas.copy(column * CELL_WIDTH, row * CELL_HEIGHT, CELL_WIDTH, CELL_HEIGHT)

    def frames(self, action: ActionId) -> tuple[FrameAsset, ...]:
        return self._actions[action]

    def look_frame(self, degrees: float) -> FrameAsset:
        index = round(degrees / 22.5)
        if not 0.0 <= degrees < 360.0 or abs(degrees - index * 22.5) > 1e-6:
            raise ValueError("direction must be a 22.5-degree step from 0 through 337.5")
        row, column = 9 + index // 8, index % 8
        return FrameAsset(self._cell(row, column), row, column)

    def hit_test(self, frame: FrameAsset, x: float, y: float, scale: float) -> bool:
        if scale <= 0:
            return False
        source_x, source_y = int(x / scale), int(y / scale)
        if not 0 <= source_x < CELL_WIDTH or not 0 <= source_y < CELL_HEIGHT:
            return False
        return frame.image.pixelColor(source_x, source_y).alpha() > 0

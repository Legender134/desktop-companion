"""Stable product and bundled-pet identities for Desktop Companion 2.0."""

PRODUCT_NAME = "桌面灵伴"
PRODUCT_VERSION = "2.0"
APP_IDENTIFIER = "DesktopCompanion"
SETTINGS_DIRECTORY = APP_IDENTIFIER
LOG_FILENAME = f"{APP_IDENTIFIER}.log"

PET_CHOICES = (
    ("shiyi", "十一"),
    ("ziling", "紫灵"),
)
PET_IDS = frozenset(pet_id for pet_id, _ in PET_CHOICES)


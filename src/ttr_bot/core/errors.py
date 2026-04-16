"""TTR Bot exception hierarchy.

All bot-specific errors derive from ``TTRBotError`` so callers can
catch the full family with a single ``except TTRBotError`` clause.
"""


class TTRBotError(Exception):
    """Base class for all TTR Bot errors."""


class WindowNotFoundError(TTRBotError):
    """The Toontown Rewritten window could not be located."""


class CalibrationError(TTRBotError):
    """Template scale calibration failed."""


class CaptureError(TTRBotError):
    """Screen capture returned ``None`` or an unusable frame."""


class TemplateNotFoundError(TTRBotError):
    """A required template image is missing from the templates directory."""

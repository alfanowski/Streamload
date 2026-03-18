"""DRM decryption subsystem (Widevine + PlayReady).

Re-exports the public API so callers can import directly from the
package::

    from streamload.core.drm import DRMManager, WidevineCDM, PlayReadyCDM
"""

from streamload.core.drm.manager import DRMManager
from streamload.core.drm.playready import PlayReadyCDM
from streamload.core.drm.widevine import WidevineCDM

__all__ = [
    "DRMManager",
    "PlayReadyCDM",
    "WidevineCDM",
]

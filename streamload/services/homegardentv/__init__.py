"""HomeGardenTV service plugin for Streamload.

HGTV (Home & Garden Television) is an Italian home renovation and
lifestyle channel operated by Warner Bros. Discovery.  It broadcasts
house-hunting, renovation, and interior design programmes.

The service runs on the shared Aurora platform API.  This module
only declares service-specific attributes; all logic lives in
:class:`~streamload.services._aurora_base.AuroraServiceBase`.
"""

from streamload.services import ServiceRegistry
from streamload.services._aurora_base import AuroraServiceBase


@ServiceRegistry.register
class HomeGardenTVService(AuroraServiceBase):
    """HGTV (hgtv.it) service plugin."""

    name = "HomeGardenTV"
    short_name = "hg"
    domains = ["www.hgtv.it", "hgtv.it"]
    environment_id = "hgtvit"

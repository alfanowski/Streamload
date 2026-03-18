"""Real Time service plugin for Streamload.

Real Time is an Italian lifestyle and entertainment channel operated by
Warner Bros. Discovery.  It broadcasts reality shows, cooking
programmes, and factual entertainment.

The service runs on the shared Aurora platform API.  This module
only declares service-specific attributes; all logic lives in
:class:`~streamload.services._aurora_base.AuroraServiceBase`.
"""

from streamload.services import ServiceRegistry
from streamload.services._aurora_base import AuroraServiceBase


@ServiceRegistry.register
class RealTimeService(AuroraServiceBase):
    """Real Time (realtime.it) service plugin."""

    name = "Real Time"
    short_name = "rt"
    domains = ["www.realtime.it", "realtime.it"]
    environment_id = "realtime"

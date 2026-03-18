"""Food Network service plugin for Streamload.

Food Network is an Italian food and cooking channel operated by Warner
Bros. Discovery.  It broadcasts cooking competitions, restaurant shows,
and culinary travel programmes.

The service runs on the shared Aurora platform API.  This module
only declares service-specific attributes; all logic lives in
:class:`~streamload.services._aurora_base.AuroraServiceBase`.
"""

from streamload.services import ServiceRegistry
from streamload.services._aurora_base import AuroraServiceBase


@ServiceRegistry.register
class FoodNetworkService(AuroraServiceBase):
    """Food Network (foodnetwork.it) service plugin."""

    name = "Food Network"
    short_name = "fn"
    domains = ["www.foodnetwork.it", "foodnetwork.it"]
    environment_id = "foodnetwork"

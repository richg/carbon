from zope.interface import implements

from twisted.plugin import IPlugin
from twisted.application.service import IServiceMaker

from carbon import service
from carbon import conf


class CarbonCombinedServiceMaker(object):

    implements(IServiceMaker, IPlugin)
    tapname = "carbon-combined"
    description = "Collect stats for graphite. Cache and Aggregator."
    options = conf.CarbonCombinedOptions

    def makeService(self, options):
        """
        Construct a C{carbon-cache} service.
        """
        return service.createCombinedService(options)


# Now construct an object which *provides* the relevant interfaces
serviceMaker = CarbonCombinedServiceMaker()

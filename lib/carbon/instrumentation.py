import os
import time
import socket
try:
    from resource import getrusage, RUSAGE_SELF
except ImportError:
    RUSAGE_SELF = 0

    class _rusage(object):
        def __init__(self):
            self.ru_utime = 0.0
            self.ru_stime = 0.0

    def getrusage(who=0):
        return _rusage()


from twisted.application.service import Service
from twisted.internet.task import LoopingCall
from carbon.conf import settings


stats = {}
HOSTNAME = socket.gethostname().replace('.','_')
PAGESIZE = os.sysconf('SC_PAGESIZE') if hasattr(os, 'sysconf') else 0
rusage = getrusage(RUSAGE_SELF)
lastUsage = rusage.ru_utime + rusage.ru_stime
lastUsageTime = time.time()

# NOTE: Referencing settings in this *top level scope* will
# give you *defaults* only. Probably not what you wanted.

# TODO(chrismd) refactor the graphite metrics hierarchy to be cleaner,
# more consistent, and make room for frontend metrics.
#metric_prefix = "Graphite.backend.%(program)s.%(instance)s." % settings


def increment(stat, increase=1):
  try:
    stats[stat] += increase
  except KeyError:
    stats[stat] = increase


def append(stat, value):
  try:
    stats[stat].append(value)
  except KeyError:
    stats[stat] = [value]


def getCpuUsage():
  global lastUsage, lastUsageTime

  rusage = getrusage(RUSAGE_SELF)
  currentUsage = rusage.ru_utime + rusage.ru_stime
  currentTime = time.time()

  usageDiff = currentUsage - lastUsage
  timeDiff = currentTime - lastUsageTime

  if timeDiff == 0: #shouldn't be possible, but I've actually seen a ZeroDivisionError from this
    timeDiff = 0.000001

  cpuUsagePercent = (usageDiff / timeDiff) * 100.0

  lastUsage = currentUsage
  lastUsageTime = currentTime

  return cpuUsagePercent


def getMemUsage():
  rss_pages = int( open('/proc/self/statm').read().split()[1] )
  return rss_pages * PAGESIZE


def recordMetrics():
  global lastUsage
  myStats = stats.copy()
  stats.clear()

  # cache metrics
  if settings.program == 'carbon-cache':
    record = cache_record
    updateTimes = myStats.get('updateTimes', [])
    committedPoints = myStats.get('committedPoints', 0)
    creates = myStats.get('creates', 0)
    errors = myStats.get('errors', 0)
    cacheQueries = myStats.get('cacheQueries', 0)
    cacheOverflow = myStats.get('cache.overflow', 0)

    if updateTimes:
      avgUpdateTime = sum(updateTimes) / len(updateTimes)
      record('avgUpdateTime', avgUpdateTime)

    if committedPoints:
      pointsPerUpdate = float(committedPoints) / len(updateTimes)
      record('pointsPerUpdate', pointsPerUpdate)

    record('updateOperations', len(updateTimes))
    record('committedPoints', committedPoints)
    record('creates', creates)
    record('errors', errors)
    record('cache.queries', cacheQueries)
    record('cache.queues', len(cache.MetricCache))
    record('cache.size', cache.MetricCache.size)
    record('cache.overflow', cacheOverflow)

  # aggregator metrics
  elif settings.program == 'carbon-aggregator':
    record = aggregator_record
    record('allocatedBuffers', len(BufferManager))
    record('bufferedDatapoints',
           sum([b.size for b in BufferManager.buffers.values()]))
    record('aggregateDatapointsSent', myStats.get('aggregateDatapointsSent', 0))

  # relay metrics
  else:
    record = relay_record

  # common metrics
  record('metricsReceived', myStats.get('metricsReceived', 0))
  record('cpuUsage', getCpuUsage())
  try: # This only works on Linux
    record('memUsage', getMemUsage())
  except:
    pass


def cache_record(metric, value):
    prefix = settings.CARBON_METRIC_PREFIX
    if settings.instance is None:
      fullMetric = '%s.agents.%s.%s' % (prefix, HOSTNAME, metric)
    else:
      fullMetric = '%s.agents.%s-%s.%s' % (prefix, HOSTNAME, settings.instance, metric)
    datapoint = (time.time(), value)
    cache.MetricCache.store(fullMetric, datapoint)

def relay_record(metric, value):
    prefix = settings.CARBON_METRIC_PREFIX
    if settings.instance is None:
      fullMetric = '%s.relays.%s.%s' % (prefix, HOSTNAME, metric)
    else:
      fullMetric = '%s.relays.%s-%s.%s' % (prefix, HOSTNAME, settings.instance, metric)
    datapoint = (time.time(), value)
    events.metricGenerated(fullMetric, datapoint)

def aggregator_record(metric, value):
    prefix = settings.CARBON_METRIC_PREFIX
    if settings.instance is None:
      fullMetric = '%s.aggregator.%s.%s' % (prefix, HOSTNAME, metric)
    else:
      fullMetric = '%s.aggregator.%s-%s.%s' % (prefix, HOSTNAME, settings.instance, metric)
    datapoint = (time.time(), value)
    events.metricGenerated(fullMetric, datapoint)


class InstrumentationService(Service):
    def __init__(self):
        self.record_task = LoopingCall(recordMetrics)

    def startService(self):
        if settings.CARBON_METRIC_INTERVAL > 0:
          self.record_task.start(settings.CARBON_METRIC_INTERVAL, False)
        Service.startService(self)

    def stopService(self):
        if settings.CARBON_METRIC_INTERVAL > 0:
          self.record_task.stop()
        Service.stopService(self)


# Avoid import circularities
from carbon import state, events, cache
from carbon.aggregator.buffers import BufferManager

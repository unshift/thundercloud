from ..db import dbConnection as db
from thundercloud.util.restApiClient import RestApiClient
from thundercloud.spec.slave import SlaveState

from twisted.internet.defer import inlineCallbacks
from twisted.internet.defer import returnValue

from twisted.internet.task import LoopingCall

import logging

log = logging.getLogger("orchestrator.slave")

# Slave perspective: send vanilla commands to slave servers
class SlavePerspective(object):
    def __init__(self, slaveSpec):
        self.slaveSpec = slaveSpec
    
    def url(self, path=None):
        if path is None:
            return str("%s://%s:%s/%s" % (self.slaveSpec.scheme, self.slaveSpec.host, self.slaveSpec.port, self.slaveSpec.path))
        else:
            if path[0] == "/":
                path = path[1:]
            return str("%s://%s:%s/%s/%s" % (self.slaveSpec.scheme, self.slaveSpec.host, self.slaveSpec.port, self.slaveSpec.path, path))
    
    def createJob(self, jobSpec):
        log.debug("Creating job with spec %s" % jobSpec)
        return RestApiClient.POST(self.url("/job"), postdata=jobSpec.toJson())
           
    def startJob(self, jobId):
        return RestApiClient.POST(self.url("/job/%d/start" % jobId))

    def pauseJob(self, jobId):
        return RestApiClient.POST(self.url("/job/%d/pause" % jobId))
    
    def resumeJob(self, jobId):
        return RestApiClient.POST(self.url("/job/%d/resume" % jobId))
    
    def stopJob(self, jobId):
        return RestApiClient.POST(self.url("/job/%d/stop" % jobId))
    
    def jobState(self, jobId):
        return RestApiClient.GET(self.url("/job/%d/state" % jobId))
    
    def jobResults(self, jobId, shortResults):
        if shortResults == True:
            return RestApiClient.GET(self.url("/job/%d/results?short=true" % jobId))
        else:
            return RestApiClient.GET(self.url("/job/%d/results" % jobId))
    
    def heartbeat(self):
        return RestApiClient.GET(self.url("/status/heartbeat"))

class SlaveNotFound(Exception):
    pass

class SlaveAlreadyConnected(Exception):
    def __init__(self, slaveId=None):
        self.slaveId = slaveId

class SlaveConnectionError(Exception):
    pass

class _SlaveAllocator(object):
    def __init__(self):
        self.slaves = {}

    def _getSlaveNo(self):
        slaveNo = db.execute("SELECT slaveNo FROM slaveno").fetchone()["slaveNo"]
        db.execute("UPDATE slaveno SET slaveNo = ?", (slaveNo + 1,))
        return slaveNo

    def _getSlavesInState(self, state):
        def f((slave, status, task)):
            if status.state == state:
                return True
        return [i for i in self.slaves.itervalues() if f(i)]
    
    def _getSlaveBySlaveSpec(self, slaveSpec):
        def f((slave, status, task)):
            if slave.slaveSpec == slaveSpec:
                return True
        result = [i for i in self.slaves.itervalues() if f(i)]
        # XXX
        assert len(result) == 1
        return result[0]

    def _getSlaveByObject(self, slaveObj):
        def f((slave, status, task)):
            if slave == slaveObj:
                return True
        result = [i for i in self.slaves.itervalues() if f(i)]
        # XXX
        assert len(result) == 1
        return result[0]

    def _getSlaveById(self, slaveId):
        return self.slaves[slaveId]

    @inlineCallbacks
    def addSlave(self, slaveSpec):
        for slaveId, (connectedSlave, status, task) in self.slaves.iteritems():
            if connectedSlave.slaveSpec.host == slaveSpec.host and \
               connectedSlave.slaveSpec.port == slaveSpec.port and \
               connectedSlave.slaveSpec.path == slaveSpec.path:
                raise SlaveAlreadyConnected(slaveId)
        
        slaveNo = self._getSlaveNo()
        slave = SlavePerspective(slaveSpec)
        status = SlaveState()
        #status.state = SlaveState.IDLE

        # check that the slave is up and running
        request = self.checkHealth(slave)
        yield request

        if request.result != True:
            raise SlaveConnectionError
        
        # set up a heartbeat call
        task = LoopingCall(self.checkHealth, slave)
        task.start(60, now=False)
        
        self.slaves[slaveNo] = (slave, status, task)
        returnValue(slaveNo)
    
    def removeSlave(self, slaveId):
        (slaveObj, status, task) = self.slaves[slaveId]
        task.stop()
        self.slaves.pop(slaveId)
    
    @inlineCallbacks
    def checkHealth(self, slave):
        request = slave.heartbeat()
        yield request
        
        if request.result == False:
            self.degrade(slave)
            returnValue(False)
        else:
            returnValue(True)

    def degrade(self, slave):
        (slaveObj, status, task) = self._getSlaveByObject(slave)
        task.stop()
            
    
    @inlineCallbacks
    def allocate(self, jobSpec):
        slaves = []
        
        # this gets the maximum of the results of clientFunction(t), where t happens
        # every 20% of the job duration.  this is to get a rough idea of what the max really
        # will be, though it's really not accurate.
        clientFunction = lambda t: eval(jobSpec.clientFunction)
        maxClientsPerSec = max([clientFunction(t) for t in range(0, jobSpec.duration, int(.2*jobSpec.duration))])
        
        # first try to fit the job onto idle slaves
        idleSlaves = sorted(self._getSlavesInState(SlaveState.IDLE), lambda (i, j, k), (l, m, n): i.slaveSpec.maxRequestsPerSec - l.slaveSpec.maxRequestsPerSec)
        idleCapacity = reduce(lambda x, y: x+y, [i.slaveSpec.maxRequestsPerSec for (i, j, k) in idleSlaves])
        
        # if there's more idle capacity than there are requests, then figure out
        # a subset of idle hosts to use
        if idleCapacity >= maxClientsPerSec:
            i = 0
            for (slave, status, task) in idleSlaves:
                i += slave.slaveSpec.maxRequestsPerSec
                slaves.append((slave, status, task))
                if i >= maxClientsPerSec:
                    break
        
        # otherwise use all the idle capacity and then move on to already
        # allocated slaves
        else:
            slaves = idleCapacity


        # for all the slaves being allocated, do a quick health check. if one fails then
        # retry the allocation recursively and return the result
        for (slave, status, task) in slaves:
            try:
                request = self.checkHealth(slave)
                yield request
            except SlaveConnectionError:
                returnValue(self.allocate(jobSpec))
                
            if request.result == True:
                slave.state = SlaveState.ALLOCATED

        returnValue([slave for (slave, status, task) in slaves])

    def release(self, slaveList):
        for slave in slaveList:
            pass
    
    def markAsRunning(self, slave):
        (slaveObj, status, task) = self._getSlaveByObject(slave)
        status.increment()
    
    def markAsFinished(self, slave):
        (slaveObj, status, task) = self._getSlaveByObject(slave)
        status.decrement()        
    

SlaveAllocator = _SlaveAllocator()
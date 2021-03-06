from thundercloud.spec.job import JobSpec

from twisted.internet.defer import Deferred, DeferredList
from twisted.internet.defer import inlineCallbacks
from twisted.internet.defer import returnValue

from ..db import dbConnection as db
from job import JobPerspective
from slave import SlaveAllocator, SlaveAlreadyConnected, NoSlavesAvailable, InsufficientSlaveCapacity
from user import UserPerspective, UserManager

import simplejson as json

import logging
import datetime

log = logging.getLogger("orchestrator")

class NoSlavesAvailable(Exception):
    pass

# Handle the multitude of jobs and slaves in the system
class _Orchestrator(object):
    def __init__(self):
        self.jobs = {}
         
    def _getJobNo(self):
        jobNo = db.execute("SELECT jobNo FROM jobno").fetchone()["jobNo"]
        db.execute("UPDATE jobno SET jobNo = ?", (jobNo + 1,))
        return jobNo

    def _logToDb(self, jobId, operation):
        db.execute("INSERT INTO orchestrator (job, operation, timestamp) VALUES (?, ?, ?)", 
                    (jobId, operation, datetime.datetime.now()))  

    @inlineCallbacks
    def registerSlave(self, slaveSpec):
        log.debug("Connecting slave.  Spec: %s" % slaveSpec)
        try:
            request = SlaveAllocator.addSlave(slaveSpec)
            yield request
            slaveId = request.result
        except SlaveAlreadyConnected, ex:
            log.warn("Reconnection from slave server at %s://%s:%s/%s" % (slaveSpec.scheme, slaveSpec.host, slaveSpec.port, slaveSpec.path))
            
            # XXX should do some job perspective synchronization
            # and sanitizing here
            slaveId = ex.slaveId

        log.debug("Slave %d connected" % slaveId)
        returnValue(slaveId)
        
    def unregisterSlave(self, slave):
        SlaveAllocator.removeSlave(slave)

    # create a job perspective object locally, and create a job on
    # all remote servers.    
    def _createJobSlaveCallback(self, result, slave):
        return result, slave
    
    def _createJobCallback(self, results, jobId, user, deferred):
        for (success, result) in results:
            if success == True:
                (remoteJobId, slave) = result
                remoteJobId = int(json.loads(remoteJobId))
                self.jobs[jobId].addSlave(slave, remoteJobId)
            else:
                deferred.errback(jobId)
                return
        log.info("Created job %d" % jobId)
            
        self._logToDb(jobId, "create")
        db.execute("INSERT INTO jobs (id, user, spec) VALUES (?, ?, ?)", (jobId, user.userId, self.jobs[jobId].jobSpec))
        deferred.callback(jobId)
    
    @inlineCallbacks
    def createJob(self, username, jobSpec):
        jobNo = self._getJobNo()
        job = JobPerspective(jobNo, jobSpec)
        self.jobs[jobNo] = job
        
        user = yield UserManager.get(username)
        log.debug("Creating job %d for user %s... connecting slave servers" % (jobNo, user.userSpec.username))
        
        # allocate a bunch of slaves here
        slaves = yield SlaveAllocator.allocate(jobSpec)
        log.debug("Using slaves: %s" % slaves)
        
        # divide the client function to spread the load over all slaves in the set
        clientFunctionPerSlave = "(%s)/%s" % (jobSpec.clientFunction, len(slaves))
        transferLimitPerSlave = jobSpec.transferLimit / len(slaves)
        modifiedJobSpec = JobSpec(jobSpec.toJson())
        modifiedJobSpec.clientFunction = clientFunctionPerSlave
        modifiedJobSpec.transferLimit = transferLimitPerSlave
        
        deferred = Deferred()
        slaveRequests = []
        for slave in slaves:
            request = slave.createJob(modifiedJobSpec)
            request.addCallback(self._createJobSlaveCallback, slave)
            slaveRequests.append(request)
        
        deferredList = DeferredList(slaveRequests)
        deferredList.addCallback(self._createJobCallback, jobNo, user, deferred)
        yield deferredList
        returnValue(jobNo)    
    
    def startJob(self, jobId):
        self._logToDb(jobId, "start")
        return self.jobs[jobId].start()
    
    def pauseJob(self, jobId):
        self._logToDb(jobId, "pause")
        return self.jobs[jobId].pause()
    
    def resumeJob(self, jobId):
        self._logToDb(jobId, "resume")
        return self.jobs[jobId].resume()
    
    def stopJob(self, jobId):
        self._logToDb(jobId, "stop")
        return self.jobs[jobId].stop()

    def jobState(self, jobId):
        return self.jobs[jobId].state()
    
    def jobResults(self, jobId, short):
        return self.jobs[jobId].results(short)

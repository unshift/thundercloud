from twisted.internet.defer import Deferred, DeferredList

from restApiClient import RestApiClient

from thundercloud.job import JobResults, JobState
from thundercloud.util import mergeDict

import simplejson as json

class AggregateJobResults(JobResults):
    
    @classmethod
    def _merge(cls, lhs, rhs):
        if type(lhs) == type(rhs) == dict:
            if sorted(lhs.keys()) == sorted(rhs.keys()):
                result = {}
                for k in result.iterkeys():
                    result[k] = lhs[k] + rhs[k]
                return result
            else:
                return mergeDict(lhs, rhs)
        else:
            return lhs + rhs
    
    @classmethod
    def _aggregateState(cls, states):
        # just get unique states
        stateSet = list(set(states))
        
        # if all states are the same, return it. this
        # should be the usual case, since we wait for
        # all jobs to change state before returning a value
        if len(stateSet) == 1:
            return stateSet[0]
    
        # if any slave job is unknown, the whole thing is unknown
        if JobState.UNKNOWN in stateSet:
            return JobState.UNKNOWN
        
        # if any slave job is still running, the entire job is still running
        if JobState.RUNNING in stateSet:
            return JobState.RUNNING
    

    @classmethod
    def _aggregateStatisticsByTime(cls, statsList, statsInterval):
        if statsList == [{"": {}}]:
            return
        
        result = {}        
        for stat in statsList:
            sortedKeys = sorted(stat.keys(), lambda a, b: int(float(a)-float(b)))
            for i in range(0, int(float(sortedKeys[-1]))+1, statsInterval):
                result[i] = {}       
                for k in sortedKeys:
                    if i - statsInterval <= float(k) < i + statsInterval:
                        distance = (statsInterval - abs(float(k) - i))
                        weight = distance / statsInterval
                        for v in ["requestsCompleted", "requestsFailed", "requestsPerSec", "clients", "iterations"]:
                            try:
                                result[i][v] += stat[k][v] * weight
                            except KeyError:
                                result[i][v] = stat[k][v] * weight

                        try:
                            result[i]["averageResponseTime"] += stat[k]["averageResponseTime"]
                        except KeyError:
                            result[i]["averageResponseTime"] = 0

        return result

        
    
    def aggregate(self, jobResults, statsInterval):
        for attr in self._attributes:
            # don't change the job ID, since we want the job ID in the
            # master server and not the slave servers
            if attr == "jobId":
                continue
            
            # job state needs to be aggregated separately
            if attr == "state":
                continue            
            # this too
            if attr == "statisticsByTime":
                continue
            
            for jobResult in jobResults:
                # if we're using a default value and the job result has something
                # legit, just use it
                if getattr(self, attr) == self._attributes[attr]:
                    setattr(self, attr, getattr(jobResult, attr))
                    continue
                
                # otherwise selectively do stuff by type
                elif type(getattr(self, attr)) == dict:
                    setattr(self, attr, mergeDict(getattr(self, attr), getattr(jobResult, attr), AggregateJobResults._merge))
                elif type(getattr(self, attr)) == int:
                    setattr(self, attr, getattr(self, attr) + getattr(jobResult, attr))
                elif type(getattr(self, attr)) == float:
                    setattr(self, attr, getattr(self, attr) + getattr(jobResult, attr))      
        
        # aggregate the job state separately    
        self.state = AggregateJobResults._aggregateState([jobResult.state for jobResult in jobResults])
        
        # statisticsByTime might not exist if the results are short. if it's there, aggregate some results
        self.statisticsByTime = AggregateJobResults._aggregateStatisticsByTime([jobResult.statisticsByTime for jobResult in jobResults], statsInterval)
        
        
# Job perspective: local job ID corresponds to multiple remote job IDs on
# multiple slave servers
class JobPerspective(object):
    def __init__(self, jobId, jobSpec):
        self.jobId = jobId
        self.jobSpec = jobSpec
        self.mapping = {}
    
    def addSlave(self, slave, remoteJobId):
        self.mapping[slave] = remoteJobId
    
    def removeSlave(self, slave):
        self.mapping.pop(slave)
    
    def start(self):
        return self._jobOp("startJob")

    def pause(self):
        return self._jobOp("pauseJob")
    
    def resume(self):
        return self._jobOp("resumeJob")
    
    def stop(self):
        return self._jobOp("stopJob")

    def _jobOpCallback(self, results, deferred):
        deferred.callback(results)
        
    def _jobOp(self, operation):
        deferred = Deferred()
        
        requests = []
        for slave, remoteId in self.mapping.iteritems():
            requests.append(getattr(slave, "%s" % operation)(remoteId))

        deferredList = DeferredList(requests)
        deferredList.addCallback(self._jobOpCallback, deferred)

        return deferred        


    def stateCallback(self, results, deferred):
        states = []
        for (result, state) in results:
            states.append(result)
        deferred.callback(AggregateJobResults._aggregateState(states))
    
    def state(self):
        deferred = self._jobOp("jobState")
        deferred.addCallback(self.stateCallback, deferred)
        return deferred
    
    
    
    def resultsCallback(self, results, deferred, short):
        aggregateResults = AggregateJobResults()
        
        # decode all json
        decodedResults = [(status, JobResults(json.loads(result))) for (status, result) in results]
        
        # set the job ID to the master's job ID
        aggregateResults.jobId = self.jobId
        
        # combine and add results from all the slave servers.  this 
        # aggregates things like bytes transferred, requests completed, etc.
        aggregateResults.aggregate([result for (status, result) in decodedResults], self.jobSpec.statsInterval)
        
        # if we're doing no stats, cut out statisticsByTime complete
        if short == True:
            try:
                del(aggregateResults.statisticsByTime)
            except AttributeError:
                pass     
        
        deferred.callback(aggregateResults)
    
    def results(self, short):
        deferred = Deferred()
        
        requests = []
        for slave in self.mapping.keys():
            requests.append(slave.jobResults(self.mapping[slave], short))

        deferredList = DeferredList(requests)
        deferredList.addCallback(self.resultsCallback, deferred, short)

        return deferred   
        


# Slave perspective: send vanilla commands to slave servers
class SlavePerspective(object):
    def __init__(self, slaveSpec):
        self.slaveSpec = slaveSpec
        self.url = ""
    
    def createJob(self, jobSpec):
        return RestApiClient.POST(self.url+"/job", postdata=jobSpec.toJson())
           
    def startJob(self, jobId):
        return RestApiClient.POST(self.url+"/job/"+str(jobId)+"/start")

    def pauseJob(self, jobId):
        return RestApiClient.POST(self.url+"/job/"+str(jobId)+"/pause")
    
    def resumeJob(self, jobId):
        return RestApiClient.POST(self.url+"/job/"+str(jobId)+"/resume")
    
    def stopJob(self, jobId):
        return RestApiClient.POST(self.url+"/job/"+str(jobId)+"/stop")
    
    def jobState(self, jobId):
        return RestApiClient.GET(self.url+"/job/"+str(jobId)+"/state")
    
    def jobResults(self, jobId, short):
        url = self.url+"/job/"+str(jobId)+"/results"
        if short == True:
            url += "?short=true"
        return RestApiClient.GET(url) 
    

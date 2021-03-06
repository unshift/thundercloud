if (tc == null) { 
	var tc = new Object();
}
if (tc.ui == null) {
	tc.ui = new Object();
}
tc.ui.dashboard = new Object();
tc.ui.dashboard.urls = [];
tc.ui.dashboard.pollInterval = 1000; // milliseconds


$(document).ready(function() {
    
    tc.ui.dashboard.progressbar = $("#dashboard-progress").progressbar({ value: 0 });  
	$("#dashboard-status").html("NEW");
	$("#dashboard-percent-complete").html("0");
	$("#dashboard-time-elapsed").html("00:00:00");
	$("#dashboard-time-remaining").html("00:00:00");
	$("#dashboard-button-start").attr("disabled", false);
	$("#dashboard-button-pause").attr("disabled", true);
	$("#dashboard-button-stop").attr("disabled", true);
	
	$("#dashboard-button-start").click(function() {
		tc.api.startJob(tc.ui.jobId, 
						function() {
							$("#dashboard-button-pause").attr("disabled", false);
							$("#dashboard-button-stop").attr("disabled", false);
							$("#dashboard-button-start").attr("disabled", true);
							tc.api.poll(tc.ui.jobId, tc.ui.dashboard.pollInterval, tc.ui.dashboard.update);
						},
						tc.ui.dashboard.errback
		);
	});
	$("#dashboard-button-pause").click(function() {
		switch ($("#dashboard-button-pause").val()) {
			case "Pause":
				tc.api.pauseJob(tc.ui.jobId, function() {
					$("#dashboard-button-pause").val("Resume");
					tc.api.poll(tc.ui.jobId, Infinity, tc.ui.dashboard.update);
				});
				break;
			case "Resume":
				tc.api.resumeJob(tc.ui.jobId, function() {
					$("#dashboard-button-pause").val("Pause");
					tc.api.poll(tc.ui.jobId, tc.ui.dashboard.pollInterval, tc.ui.dashboard.update);
				});
				break;
		};
	});		
	$("#dashboard-button-stop").click(function() {
		tc.api.stopJob(tc.ui.jobId, 
						function() {
							tc.ui.dashboard.jobComplete();
							tc.api.poll(tc.ui.jobId, Infinity, tc.ui.dashboard.update);
						},
						tc.ui.dashboard.errback
		);
	});
});

tc.ui.dashboard.update = function(response) {
	var percentage = Math.min(100, 100 * (response.time_elapsed / response.limits_duration));
	var timeleft = Math.max(0, response.limits_duration - response.time_elapsed);
	tc.ui.dashboard.progressbar.progressbar("value", percentage);
	$("#dashboard-status").html(tc.api.JobStateToText[response.job_state]);
	$("#dashboard-percent-complete").html(percentage);
	$("#dashboard-time-elapsed").html(response.time_elapsed);
	$("#dashboard-time-remaining").html(timeleft);
	$("#dashboard-stats-current-iterations").html(response.iterations_total);
	$("#dashboard-stats-current-elapsedTime").html(response.time_elapsed);
	$("#dashboard-stats-current-bytesTransferred").html(response.transfer_total);
	
	if (response.job_state == tc.api.JobState.COMPLETE) {
		tc.ui.dashboard.jobComplete();
	}
	
};

tc.ui.dashboard.jobComplete = function() {
	$("#dashboard-button-start").attr("disabled", true);
	$("#dashboard-button-pause").attr("disabled", true);
	$("#dashboard-button-stop").attr("disabled", true);
	
	tc.api.jobResults(tc.ui.jobId, false, function(data, statusText) {
		tc.ui.dashboard.plot(jsonParse(data).results_byTime);
	});	
	tc.ui.wizard.tabs.tabs("enable", 0);
	tc.ui.newtab.reset();
};

tc.ui.dashboard.errback = function(XMLHttpRequest, statusText, error) {
	console.log(XMLHttpRequest);
	console.log(statusText);
	console.log(error);
};


tc.ui.dashboard.plot = function(data) {
	tc.ui.dashboard.plotRequestsPerSec(data);
	tc.ui.dashboard.plotResponseTime(data);
}
tc.ui.dashboard.plotRequestsPerSec = function(data) {
	// construct a graph-able array from the results data
	var requestsPerSec = [];
	var trendLine = [];
	var rollingAverage = 0;
	var xMax = 0;
	var yMax = 0;
	
	// JS can't access object keys like other languages, so
	// this hack is to sort the keys and then add items in order
	var keys = [];
	for (var i in data) {
		keys.push(i);
	}
	keys.sort(function(x, y) { return parseFloat(x) - parseFloat(y) });
	
	// skip 0, because nobody cares about the origin of the graph
	for (var i = 1; i < keys.length; i++) {
		var j = keys[i];
		var x = parseFloat(j);
		var y = parseFloat(data[j]["requestsPerSec"]);
		
		xMax = (x > xMax ? x : xMax);
		yMax = (y > yMax ? y : yMax);
		requestsPerSec.push([x, y]);

		newRollingAverage = ((y + ((i-1)*rollingAverage))/i)
		rollingAverage = newRollingAverage;
		trendLine.push([x, rollingAverage]);		
		
	}
	
	$.plot($("#dashboard-graphs-requestsPerSecond"), 
        [
         { 
        	label: "requests/sec", 
        	points: { show: true }, 
        	lines: { show: true },
        	data: requestsPerSec,
         },
         {
        	label: "average",
        	points: { show: false },
        	lines: { show: true },
        	data: trendLine,
         }
        ],
        { 
        	xaxis: { max: xMax }, 
        	yaxis: { max: yMax },
        	grid: { hoverable: true, clickable: true },
        	legend: {
        		show: true,
        		position: "se",
         },
        }
	);
};
tc.ui.dashboard.plotResponseTime = function(data) {
	var timeToConnect = []
	var timeToFirstByte = []
	var responseTime = [];
	var xMax = 0;
	var yMax = 0;
	
	// JS can't access object keys like other languages, so
	// this hack is to sort the keys and then add items in order
	var keys = [];
	for (var i in data) {
		keys.push(i);
	}
	keys.sort(function(x, y) { return parseFloat(x) - parseFloat(y) });
	
	// skip 0, because nobody cares about the origin of the graph
	for (var i = 1; i < keys.length; i++) {
		var j = keys[i];
		var x = parseFloat(j);
		
		var _ttc = parseFloat(data[j]["timeToConnect"])*1000;
		var _ttfb = parseFloat(data[j]["timeToFirstByte"])*1000;
		var _rt = parseFloat(data[j]["responseTime"])*1000;
		
		timeToConnect.push([x, _ttc]);
		timeToFirstByte.push([x, _ttfb]);
		responseTime.push([x, _rt]);
		
		xMax = (x > xMax ? x : xMax);
		yMax = (Math.max(_ttc, _ttfb, _rt) > yMax ? Math.max(_ttc, _ttfb, _rt) : yMax);
	}

	$.plot($("#dashboard-graphs-responseTime"), 
        [
         { 
        	label: "average time to connect (ms)", 
        	points: { show: true }, 
        	lines: { show: true },
        	data: timeToConnect, 
         },
         { 
        	label: "average time to first byte (ms)", 
        	points: { show: true }, 
        	lines: { show: true },
        	data: timeToFirstByte,
         },
         { 
        	label: "average response time (ms)", 
        	points: { show: true }, 
        	lines: { show: true },
        	data: responseTime, 
         },        
         
        ],
        { 
        	xaxis: { max: xMax }, 
        	yaxis: { max: yMax },
        	grid: { hoverable: true, clickable: true },
        	legend: {
        		show: true,
        		position: "se",
         },
        }
	);
};


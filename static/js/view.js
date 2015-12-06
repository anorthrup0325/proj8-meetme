$(function() {
	$('#btn-clear').on('click', function() {
		// Send to server
		$.ajax({
			url: anorthrup0325.url.set,
			data: {
				'what': 'final',
				'for': 'meeting',
				'who': parseInt(anorthrup0325.data.index),
				'as': false,
				'object': true
			},
			dataType: "json",
			success: function(data) {
				anorthrup0325.refreshPage();
			},
			error: function(data) {
				anorthrup0325.refreshPage();
			}
		});
	});

	$('#btn-open').on('click', function() {
		// Open meeting
		$.ajax({
				url: anorthrup0325.url.set,
				data: {
					'what': 'status',
					'for': 'meeting',
					'who': parseInt(anorthrup0325.data.index),
					'as': 'open'
				},
				dataType: "json",
				success: function(data) {
					anorthrup0325.refreshPage();
				},
				error: function(data) {
					anorthrup0325.refreshPage();
				}
			});
	});
	$('#btn-close').on('click', function() {
		if (confirm("Are you sure you want to close this meeting?")) {
			// Close meeting
			$.ajax({
				url: anorthrup0325.url.set,
				data: {
					'what': 'status',
					'for': 'meeting',
					'who': parseInt(anorthrup0325.data.index),
					'as': 'closed'
				},
				dataType: "json",
				success: function(data) {
					anorthrup0325.refreshPage();
				},
				error: function(data) {
					anorthrup0325.refreshPage();
				}
			});
		}
	});
	$('#btn-delete').on('click', function() {
		if (confirm("Are you sure you want to delete this meeting?")) {
			// Void meeting
			$.ajax({
				url: anorthrup0325.url.del,
				data: {
					'meeting': parseInt(anorthrup0325.data.index),
				},
				dataType: "json",
				success: function(data) {
					if (data.result == true) {
						anorthrup0325.gotoIndex();
					} else {
						$('#error').show();
					}
				},
				error: function(data) {
					$('#error').show();
				}
			});
		}
	});

	$('#btn-change').on('click', function() {
		$('#timing-changes').toggle();
	});
	$('#btn-time-cancel').on('click', function() {
		$('#timing-changes').hide();
	});
	$('#btn-time-update').on('click', function() {
		// Update times from calendars selected
		var calendars = []; // Build from inputs
		$('#timing-boxes input[name="calendars"]').each(function() {
			if (this.checked) {
				calendars.push($(this).val());
			}
		});

		$.ajax({
			url: anorthrup0325.url.update,
			data: {
				'calendars': calendars,
				'meeting': parseInt(anorthrup0325.data.index)
			},
			traditional: true, // Can use request.args.getlist('calendars')
			dataType: "json",
			success: function(data) {
				anorthrup0325.refreshPage();
			},
			error: function(data) {
				anorthrup0325.refreshPage();
			}
		});
	});

	var final_start = "";
	var final_end = "";
	$("#final-time-picker").daterangepicker({
		timePicker: true,
		timePickerIncrement: 15,
		locale: {
			format: 'ddd MM/DD/YYYY HH:mm'
		}
	});
	function updateTimes(ev, picker) {
		final_start = picker.startDate.format();
		final_end = picker.endDate.format();
	}
	updateTimes(null, $('#final-time-picker').data('daterangepicker'));
	$('#final-time-picker').on('apply.daterangepicker', updateTimes);
	$('#btn-final-time').on('click', function() {
		// Send to server
		$.ajax({
			url: anorthrup0325.url.set,
			data: {
				'what': 'final',
				'for': 'meeting',
				'who': parseInt(anorthrup0325.data.index),
				'as': JSON.stringify({
					'start': final_start,
					'end': final_end
				}),
				'object': true
			},
			dataType: "json",
			success: function(data) {
				anorthrup0325.refreshPage();
			},
			error: function(data) {
				anorthrup0325.refreshPage();
			}
		});
	});
});
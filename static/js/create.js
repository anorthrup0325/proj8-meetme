$(function() {
	$("#range").daterangepicker({
		timePicker: true,
		timePickerIncrement: 15,
		locale: {
			format: 'ddd MM/DD/YYYY HH:mm'
		}
	});
	function updateTimes(ev, picker) {
		$('#range-start').val(picker.startDate.format());
		$('#range-end').val(picker.endDate.format());
	}
	updateTimes(null, $('#range').data('daterangepicker'));
	$('#range').on('apply.daterangepicker', updateTimes);
});
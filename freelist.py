import arrow
import math

class FreeList():
	def __init__(self, btl):
		self.btl = FreeList.copyList(btl)
		self.ftl = FreeList.between(self.btl)

	@staticmethod
	def round_down(time, snap):
		return snap * math.floor(1.0 * time / snap)

	@staticmethod
	def round_up(time, snap):
		return snap * math.ceil(1.0 * time / snap)

	@staticmethod
	def copyList(l):
		res = list()
		for item in l:
			res.append( {"start": item["start"], "end": item["end"]} )
		return res

	@staticmethod
	def create(start, end, day_start_time, day_end_time, btl):
		"""
		Creates a FreeList with user values

		:param start: Starting date in ISO format
		:param end: Ending date in ISO format
		:param day_start_time: Daily start time in ISO format (with tz)
		:param day_end_time: Daily end time in ISO format (with tz)
		:param btl: Busy Time List, [ {start: full ISO string, end: full ISO string}, ]

		:returns: A FreeTime list
		"""

		try:
			t_start = arrow.get(start)
			t_end = arrow.get(end)
			t_tstart = arrow.get(day_start_time)
			t_tend = arrow.get(day_end_time)
		except:
			raise ValueError("Dates/Times must be in ISO 8601 format")

		t_tstart = t_tstart.floor("minute")
		t_tstart = t_tstart.replace(minute = FreeList.round_down(t_tstart.minute, 15))

		t_tend = t_tend.floor("minute")
		t_minutes = FreeList.round_up(t_tend.minute, 15)
		if t_minutes < 60:
			t_tend = t_tend.replace(minute = t_minutes)
		else:
			t_tend = t_tend.replace(hours = +1, minute = 0)

		t_day_start = t_start.floor("day")
		t_day_end = t_end.floor("day")
		t_time_start = t_tstart.floor("minute")
		t_time_end = t_tend.floor("minute")

		btl = FreeList.copyList(btl)

		t_day_start_range = t_day_start.replace(days = -1)
		for day in arrow.Arrow.range('day', t_day_start_range, t_day_end):
			nday = day.replace(days = +1)
			# Increment by start and end times per day
			day = day.replace(days = t_time_end.day - 1, hours = t_time_end.hour, minutes = t_time_end.minute)
			nday = nday.replace(days = t_time_start.day - 1, hours = t_time_start.hour, minutes = t_time_start.minute)
			# Add as a busy time
			btl.append({"start": day.isoformat(), "end": nday.isoformat(), "desc":""})

		# Union the times
		btl = FreeList.unionized( sorted( btl, key=lambda range: arrow.get(range["start"]).timestamp ) )

		return FreeList(btl)

	@staticmethod
	def create_from_list(btl):
		btl = FreeList.unionized( sorted( btl, key=lambda range: arrow.get(range["start"]).timestamp ) )
		return FreeList(btl)
	
	def getTimes(self):
		return self.ftl

	def get_busy_times(self):
		return self.btl

	@staticmethod
	def unionized(l):
		res = list()
		if len(l) <= 0:
			return res

		cur = None

		for r in l:
			t_start = arrow.get(r["start"])
			t_end = arrow.get(r["end"])

			if not cur is None:
				if cur["end"] >= t_start:
					if cur["end"] < t_end:
						cur["end"] = t_end
					continue
				else:
					res.append({"start": cur["start"].isoformat(), "end": cur["end"].isoformat()})
			cur = {"start": t_start, "end": t_end}
		res.append({"start": cur["start"].isoformat(), "end": cur["end"].isoformat()})

		return res

	@staticmethod
	def between(l):
		res = list()
		if len(l) <= 0:
			return res

		last = None
		for r in l:
			if not last is None:
				res.append( {"start": last["end"], "end": r["start"]} )
			last = r

		return res

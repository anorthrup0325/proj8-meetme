import flask
from flask import render_template
from flask import request
from flask import url_for
import uuid

import json
import logging

# Date handling 
import arrow # Replacement for datetime, based on moment.js
import datetime # But we still need time
from dateutil import tz  # For interpreting local times


# OAuth2  - Google library implementation for convenience
from oauth2client import client
import httplib2   # used in oauth2 flow

# Google API for services 
from apiclient import discovery

# MongoDB
from pymongo import MongoClient
from bson.objectid import ObjectId

# Calculating free times
from freelist import FreeList

###
# Globals
###
import CONFIG

try:
  dbclient = MongoClient(CONFIG.MONGO_URL)
  db = dbclient.meetings
  collection_settings = db.settings
except:
  print("Could not connect to MongoDB. Is it running? Correct password?")
  sys.exit(1)

app = flask.Flask(__name__)

SCOPES = 'https://www.googleapis.com/auth/calendar.readonly email'
CLIENT_SECRET_FILE = CONFIG.GOOGLE_LICENSE_KEY  ## You'll need this
APPLICATION_NAME = 'MeetMe class project'


#############################
#
#  Pages (routed from URLs)
#
#############################

@app.route("/")
@app.route("/index")
def index():
  app.logger.debug("Entering index")
  success,response = require_credentials()
  if success == False:
    return response
  if "email" not in flask.session:
    service = get_people_service(response)
    flask.session["email"] = get_email(service)
  if "id" not in flask.session:
    flask.session["id"] = mongo_get_my_id(flask.session['email'])
  if "calendars" not in flask.session:
    gcal_service = get_gcal_service(response)
    flask.session['calendars'] = list_calendars(gcal_service)
  if flask.request.args.get('uri'):
    return flask.redirect(flask.request.args.get('uri'))
  meetings = mongo_get_my_meetings(flask.session["id"])
  return render_template('index.html', meetings=meetings)
  
@app.route("/view")
def view():
	success,response = require_credentials()
	if success == False:
		return response
    
	meeting_id = flask.request.args.get('id', type=int)
	request_status, meeting_info = mongo_get_meeting_info(int(flask.session['id']), meeting_id)
	meeting_times = []
	if request_status == 'owner':
		# Compile user data
		btl = []
		for user in meeting_info['users']:
			if ("user_" + str(user)) in meeting_info:
				btl = btl + meeting_info["user_" + str(user)]
		if len(btl) == 0:
			btl = FreeList.create(meeting_info['start'], meeting_info['end'],
				meeting_info['start_time'], meeting_info['end_time'], []).get_busy_times()
		meeting_times = FreeList.create_from_list(btl).getTimes()
	return render_template('view.html', status=request_status, meeting=meeting_info, meeting_times=meeting_times)

@app.route("/create")
def create():
  success,response = require_credentials()
  if success == False:
    return response
  return render_template('create.html')

@app.route("/join")
def join():
  success,response = require_credentials()
  if success == False:
    return response

  t_id = flask.request.args.get('meeting', type=int)
  t_secret = flask.request.args.get('secret')
  state,info = mongo_get_joining_info(flask.session['id'], t_id)
  if state == 'invalid':
    return flask.render_template('join.html', state='invalid')
  if state == 'joined':
    return flask.redirect(flask.url_for('view', id=t_id))

  t_join = False
  if state == 'open':
    # Join the thing
    t_join = True
  elif state == 'info':
    if t_secret == info:
      t_join = True

  if t_join:
    # Join the meeting
    t_res = mongo_join_meeting(flask.session['id'], t_id)
    if t_res:
      return flask.redirect(flask.url_for('view', id=t_id))
  return flask.render_template('join.html', state='failed')


@app.route("/_create", methods=["POST"])
def func_create():
  success,response = require_credentials()
  if success == False:
    return response
  t_title = flask.request.form.get('title')
  t_desc = flask.request.form.get('desc')
  t_start = arrow.get(flask.request.form.get('start'))
  t_end = arrow.get(flask.request.form.get('end'))

  t_start_date = t_start.floor('day').format()
  t_end_date = t_end.floor('day').format()
  t_start_time = arrow.get(t_start.format('HH:mm ZZ'), 'HH:mm ZZ').format()
  t_end_time = arrow.get(t_end.format('HH:mm ZZ'), 'HH:mm ZZ').format()

  success,t_res = mongo_create_meeting(flask.session['id'], t_title, t_desc, t_start_date, t_end_date, t_start_time, t_end_time)

  if success:
    return flask.redirect(flask.url_for('view', id=t_res['id']))

  return flask.redirect(flask.url_for('index'))

@app.route("/_update")
def func_update():
    # Read calendars
    success,response = require_credentials()
    gcal_service = get_gcal_service(response)
    app.logger.debug("Returned from get_gcal_service")
    selected_cals = request.args.getlist('calendars')

    # Get meeting info
    meeting = request.args.get('meeting', type=int)
    status,meeting_info = mongo_get_meeting_info(flask.session['id'], meeting)

    if status == 'invalid' or status == 'private':
    	return flask.jsonify(result=False)

    ftl, btl = get_times(meeting_info, gcal_service, selected_cals)
    user_btl = calc_busy_meeting_times(meeting_info, ftl, btl);

    # Now put in mongo
    res = mongo_set_times(meeting, flask.session['id'], user_btl)

    return flask.jsonify(result=res)

@app.route('/_set')
def func_set():
  t_what = flask.request.args.get('what') # key
  t_for = flask.request.args.get('for') # user, meeting
  t_who = flask.request.args.get('who') # id of who
  t_as = flask.request.args.get('as') # value
  if not (t_who and t_what and t_for):
    return flask.jsonify(result=False)
  t_who = int(t_who)
  t_obj = False
  if 'object' in flask.request.args:
    t_obj = flask.request.args.get('object')
  t_success = mongo_set_data(t_what, t_for, t_who, t_as, flask.session['id'], t_obj)
  return flask.jsonify(result=t_success)

@app.route('/_del')
def func_del():
	t_meeting = flask.request.args.get('meeting', type=int)
	t_success = mongo_set_data('status', 'meeting', t_meeting, 'void', flask.session['id'])
	return flask.jsonify(result=t_success);

####
#
#  Google calendar authorization:
#      Returns us to the main /choose screen after inserting
#      the calendar_service object in the session state.  May
#      redirect to OAuth server first, and may take multiple
#      trips through the oauth2 callback function.
#
#  Protocol for use ON EACH REQUEST: 
#     First, check for valid credentials
#     If we don't have valid credentials
#         Get credentials (jump to the oauth2 protocol)
#         (redirects back to /choose, this time with credentials)
#     If we do have valid credentials
#         Get the service object
#
#  The final result of successful authorization is a 'service'
#  object.  We use a 'service' object to actually retrieve data
#  from the Google services. Service objects are NOT serializable ---
#  we can't stash one in a cookie.  Instead, on each request we
#  get a fresh serivce object from our credentials, which are
#  serializable. 
#
#  Note that after authorization we always redirect to /choose;
#  If this is unsatisfactory, we'll need a session variable to use
#  as a 'continuation' or 'return address' to use instead. 
#
####

def valid_credentials():
    """
    Returns OAuth2 credentials if we have valid
    credentials in the session.  This is a 'truthy' value.
    Return None if we don't have credentials, or if they
    have expired or are otherwise invalid.  This is a 'falsy' value. 
    """
    if 'credentials' not in flask.session:
      return None

    credentials = client.OAuth2Credentials.from_json(
        flask.session['credentials'])

    if (credentials.invalid or
        credentials.access_token_expired):
      return None
    return credentials

def require_credentials():
  app.logger.debug("Checking credentials for Google calendar access")
  credentials = valid_credentials()
  if not credentials:
    app.logger.debug("Redirecting to authorization")
    return (False, flask.redirect(url_for("oauth2callback", uri=request.url)))
  return (True, credentials)


def get_gcal_service(credentials):
  """
  We need a Google calendar 'service' object to obtain
  list of calendars, busy times, etc.  This requires
  authorization. If authorization is already in effect,
  we'll just return with the authorization. Otherwise,
  control flow will be interrupted by authorization, and we'll
  end up redirected back to /choose *without a service object*.
  Then the second call will succeed without additional authorization.
  """
  app.logger.debug("Entering get_gcal_service")
  http_auth = credentials.authorize(httplib2.Http())
  service = discovery.build('calendar', 'v3', http=http_auth)
  app.logger.debug("Returning service")
  return service
  
def get_people_service(credentials):
  http_auth = credentials.authorize(httplib2.Http())
  service = discovery.build('plus', 'v1', http=http_auth)
  return service

@app.route('/oauth2callback')
def oauth2callback():
  """
  The 'flow' has this one place to call back to.  We'll enter here
  more than once as steps in the flow are completed, and need to keep
  track of how far we've gotten. The first time we'll do the first
  step, the second time we'll skip the first step and do the second,
  and so on.
  """
  app.logger.debug("Entering oauth2callback")
  flow =  client.flow_from_clientsecrets(
      CLIENT_SECRET_FILE,
      scope= SCOPES,
      redirect_uri=flask.url_for('oauth2callback', _external=True))
  ## Note we are *not* redirecting above.  We are noting *where*
  ## we will redirect to, which is this function. 
  
  ## The *second* time we enter here, it's a callback 
  ## with 'code' set in the URL parameter.  If we don't
  ## see that, it must be the first time through, so we
  ## need to do step 1. 
  app.logger.debug("Got flow")
  if 'code' not in flask.request.args:
    app.logger.debug("Code not in flask.request.args")
    auth_uri = flow.step1_get_authorize_url() + '&state=' + str(request.args.get('uri') or flask.url_for('index'))
    return flask.redirect(auth_uri)
    ## This will redirect back here, but the second time through
    ## we'll have the 'code' parameter set
  else:
    ## It's the second time through ... we can tell because
    ## we got the 'code' argument in the URL.
    app.logger.debug("Code was in flask.request.args")
    auth_code = flask.request.args.get('code')
    credentials = flow.step2_exchange(auth_code)
    flask.session['credentials'] = credentials.to_json()
    ## Now I can build the service and execute the query,
    ## but for the moment I'll just log it and go back to
    ## the main screen
    app.logger.debug("Got credentials")
    return flask.redirect(flask.url_for('index', uri=flask.request.args.get('state')))

####
#
#   Initialize session variables 
#
####

def init_session_values():
    """
    Start with some reasonable defaults for date and time ranges.
    Note this must be run in app context ... can't call from main. 
    """
    # Default date span = today to 1 week from now
    now = arrow.now('local')
    tomorrow = now.replace(days=+1)
    nextweek = now.replace(days=+7)
    flask.session["begin_date"] = now.floor('day').isoformat()
    flask.session["end_date"] = nextweek.ceil('day').isoformat()
    flask.session["daterange"] = "{} - {}".format(
        now.format("MM/DD/YYYY"),
        nextweek.format("MM/DD/YYYY"))
    # Default time span each day, 9 to 5
    flask.session["begin_time"] = interpret_time("9am")
    flask.session["end_time"] = interpret_time("5pm")

def interpret_time( text ):
    """
    Read time in a human-compatible format and
    interpret as ISO format with local timezone.
    May throw exception if time can't be interpreted. In that
    case it will also flash a message explaining accepted formats.
    """
    app.logger.debug("Decoding time '{}'".format(text))
    time_formats = ["ha", "h:mma",  "h:mm a", "H:mm"]
    try: 
        as_arrow = arrow.get(text, time_formats).replace(tzinfo=tz.tzlocal())
        app.logger.debug("Succeeded interpreting time")
    except:
        app.logger.debug("Failed to interpret time")
        flask.flash("Time '{}' didn't match accepted formats 13:30 or 1:30pm"
              .format(text))
        raise
    return as_arrow.isoformat()

def interpret_date( text ):
    """
    Convert text of date to ISO format used internally,
    with the local time zone.
    """
    try:
      as_arrow = arrow.get(text, "MM/DD/YYYY").replace(
          tzinfo=tz.tzlocal())
    except:
        flask.flash("Date '{}' didn't fit expected format 12/31/2001")
        raise
    return as_arrow.isoformat()

def next_day(isotext):
    """
    ISO date + 1 day (used in query to Google calendar)
    """
    as_arrow = arrow.get(isotext)
    return as_arrow.replace(days=+1).isoformat()

####
#
#  Functions (NOT pages) that return some information
#
####
  
def list_calendars(service):
    """
    Given a google 'service' object, return a list of
    calendars.  Each calendar is represented by a dict, so that
    it can be stored in the session object and converted to
    json for cookies. The returned list is sorted to have
    the primary calendar first, and selected (that is, displayed in
    Google Calendars web app) calendars before unselected calendars.
    """
    app.logger.debug("Entering list_calendars")  
    calendar_list = service.calendarList().list().execute()["items"]
    result = [ ]
    for cal in calendar_list:
        kind = cal["kind"]
        id = cal["id"]
        if "description" in cal: 
            desc = cal["description"]
        else:
            desc = "(no description)"
        summary = cal["summary"]
        # Optional binary attributes with False as default
        selected = ("selected" in cal) and cal["selected"]
        primary = ("primary" in cal) and cal["primary"]
        

        result.append(
          { "kind": kind,
            "id": id,
            "summary": summary,
            "selected": selected,
            "primary": primary
            })
    return sorted(result, key=cal_sort_key)


def cal_sort_key( cal ):
    """
    Sort key for the list of calendars:  primary calendar first,
    then other selected calendars, then unselected calendars.
    (" " sorts before "X", and tuples are compared piecewise)
    """
    if cal["selected"]:
       selected_key = " "
    else:
       selected_key = "X"
    if cal["primary"]:
       primary_key = " "
    else:
       primary_key = "X"
    return (primary_key, selected_key, cal["summary"])

def get_email(service):
  peoples = service.people()
  emails = peoples.get(userId='me').execute()
  return emails["emails"][0]["value"]
    
def get_times(meeting, service, cals):
	ftl = [] # Free Time List
	btl = [] # Busy Time List
	
	time_min = arrow.get(meeting['start']).isoformat()
	time_max = arrow.get(meeting['end']).replace(hours=+24, seconds=-1).isoformat()
	
	# Iterate through selected calendars
	for cal in cals:
		# Get the items from google
		cal_items = service.events().list(calendarId=cal, timeMin=time_min, timeMax=time_max, singleEvents=True).execute()['items']
		for item in cal_items:
			try:
				t_start = item["start"]["dateTime"]
			except:
				t_start = arrow.get(item["start"]["date"], "YYYY-MM-DD").replace(
          tzinfo=tz.tzlocal()).isoformat()
			try:
				t_end = item["end"]["dateTime"]
			except:
				t_end = arrow.get(item["end"]["date"], "YYYY-MM-DD").replace(
          tzinfo=tz.tzlocal()).isoformat()
			item_range = {"start": t_start, "end": t_end, "desc": item["summary"]}
			if "transparency" in item and item["transparency"] == "transparent":
				ftl.append(item_range)
			else:
				btl.append(item_range)
	
	return ftl,btl

def calc_busy_meeting_times(meeting, ftl, btl):
  btl = sorted(btl, key=lambda range: range["start"])
  btl = FreeList.unionized(btl)
  
  fl = FreeList.create(meeting['start'], meeting['end'], meeting['start_time'], meeting['end_time'], btl)

  return fl.get_busy_times()


#################
#
# Functions used within the templates
#
#################

@app.template_filter( 'fmtdate' )
def format_arrow_date( date ):
    try: 
        normal = arrow.get( date )
        return normal.format("ddd MM/DD/YYYY")
    except:
        return "(bad date)"

@app.template_filter( 'fmttime' )
def format_arrow_time( time ):
    try:
        normal = arrow.get( time )
        return normal.format("HH:mm")
    except:
        return "(bad time)"

@app.template_filter( 'fmtdatetime' )
def format_arrow_datetime( datetime ):
    try:
        normal = arrow.get( datetime )
        return normal.format("ddd MM/DD/YYYY HH:mm")
    except:
        return "(bad time)"

@app.template_filter( 'fmtdatetimesmall' )
def format_arrow_datetime_small( datetime ):
    try:
        normal = arrow.get( datetime )
        return normal.format("MM/DD/YYYY HH:mm")
    except:
        return "(bad time)"

@app.template_filter( 'alerttype' )
def format_alert_type( type ):
	if type == 'success' or type == 'info' or type == 'warning' or type == 'danger':
		return type
	return 'info'

def get_meeting_type(status):
	if status == 'open':
		return 'success'
	elif status == 'closed':
		return 'warning'
	elif status == 'void':
		return 'danger'
	return 'info'


##############
#
# Functions used with mongo
#
##############

def mongo_get_my_id(email):
  resp = db.users.find_one({ "email": email })
  if resp != None:
  	return int(resp['id'])
  n = db.settings.find_one({ "type": "user" })
  nextid = int(n['next'])
  db.settings.update({ "type": "user" }, {"$set": { "next": nextid + 1 } })
  new_user = {
    "id": nextid,
    "email": email,
    "meetings": []
  }
  db.users.insert(new_user)
  return nextid

def mongo_get_my_meetings_ids(user_id):
  resp = db.users.find_one({ "id": user_id })
  if resp == None:
    return []
  return resp["meetings"]

def mongo_get_my_meetings(user_id):
  meetings = mongo_get_my_meetings_ids(user_id)
  res = []
  voided = [] # Showing voided meetings at the bottom
  for id in meetings:
    meeting = db.meetings.find_one({ "id": id })
    if meeting != None:
      meeting_info = {
        "title": meeting["title"],
        "desc": meeting["desc"],
        "id": int(meeting["id"]),
		    "type": get_meeting_type(meeting["status"]),
		    "my_time": ("user_" + str(user_id)) in meeting,
      }
      if meeting["final"] != False:
        meeting_info["final"] = meeting["final"]
      if meeting["owner"] == user_id:
        # Add in other stuffs
        meeting_info["users"] = meeting["users"]
      if meeting['status'] == 'void':
        voided.append(meeting_info)
      else:
        res.append(meeting_info)
  return res + voided

def mongo_get_meeting_info(user_id, meeting_id):
  user = db.users.find_one({ "id": user_id })
  meeting = db.meetings.find_one({ "id": meeting_id })
  if meeting == None:
    return ('invalid', meeting_id)
  if meeting_id not in user["meetings"]:
    return ('private', meeting_id)
  meeting['id'] = meeting_id
  if meeting['owner'] == user_id:
    meeting['my_time'] = ("user_" + str(user_id)) in meeting
    return ('owner', meeting)
  return ('participant', {
    'title': meeting['title'],
    'desc': meeting['desc'],
    'start': meeting['start'],
    'end': meeting['end'],
    'start_time': meeting['start_time'],
    'end_time': meeting['end_time'],
    'status': meeting['status'],
    "my_time": ("user_" + str(user_id)) in meeting,
    'id': meeting_id,
    'final': meeting['final']
  })

def mongo_get_joining_info(user_id,meeting_id):
  user = db.users.find_one({ "id": user_id })
  meeting = db.meetings.find_one({ "id": meeting_id })
  if meeting == None:
    return ('invalid', meeting_id)
  if meeting['id'] in user['meetings']:
    return ('joined', meeting_id)
  if 'secret' not in meeting:
    return ('open', meeting_id)
  print(meeting['secret'])
  meeting_info = meeting['secret']
  return ('info', meeting_info)


def mongo_set_data(t_what, t_for, t_who, t_as, t_by, t_obj=False):
  changes = {}
  changes[t_what] = t_as
  print(changes)
  if t_obj:
    changes[t_what] = json.loads(t_as)
  if t_for == 'meeting':
    meeting = db.meetings.find_one({ "id": t_who })
    if meeting == None:
      return False
    if meeting["owner"] != t_by:
      return False
    t_res = db.meetings.update_one({ "id": t_who }, {"$set": changes});
    print(str(t_res.modified_count))
    return t_res.modified_count != False
  else:
 		user = db.meetings.find_one({ "id": t_who })
 		if user == None:
 			return False
 		if user["id"] != t_by:
 			return False
 		t_res = db.users.update_one({ "id": t_who }, {"$set": changes})
 		return t_res.modified_count != False

def mongo_set_times(meeting_id, user_id, mtl):
	meeting = db.meetings.find_one({"id": meeting_id})
	if meeting == None:
		return False
	if user_id not in meeting["users"]:
		return False
	changes = {}
	changes["user_" + str(user_id)] = mtl
	res = db.meetings.update_one({"id": meeting_id}, {"$set": changes})
	return res.modified_count != False

def mongo_next_meeting():
  n = db.settings.find_one({ "type": "meeting" })
  nextid = int(n['next'])
  db.settings.update({ "type": "meeting" }, {"$set": { "next": nextid + 1 } })
  return nextid

def mongo_create_meeting(user_id, title, desc, start, end, start_time, end_time):
  meeting = {
    'owner': user_id,
    'title': title,
    'desc': desc,
    'start': start,
    'end': end,
    'start_time': start_time,
    'end_time': end_time,
    'final': False,
    'status': 'open',
    'users': [user_id],
    'id': mongo_next_meeting(),
    'secret': str(uuid.uuid4())
  }
  # Add to user's meetings
  user = db.users.find_one({"id": user_id})
  if user == None:
    return (False, None)
  user_meetings = user['meetings']
  user_meetings.append(meeting['id'])
  db.users.update_one({"id": user_id}, {"$set": {'meetings': user_meetings}})
  # Add to meetings
  db.meetings.insert_one(meeting)
  return (True, meeting)

def mongo_join_meeting(user_id, meeting_id):
  # Add to user's meetings
  user = db.users.find_one({"id": user_id})
  if user == None:
    return False
  user_meetings = user['meetings']
  user_meetings.append(meeting_id)
  db.users.update_one({"id": user_id}, {"$set": {'meetings': user_meetings}})

  # Add to meetings's users
  meeting = db.meetings.find_one({"id": meeting_id})
  if meeting == None:
    return False
  meeting_users = meeting['users']
  meeting_users.append(user_id)
  db.meetings.update_one({"id": meeting_id}, {"$set": {'users': meeting_users}})
  return True

##############


if __name__ == "__main__":
  # App is created above so that it will
  # exist whether this is 'main' or not
  # (e.g., if we are running in a CGI script)

  app.secret_key = str(uuid.uuid4())  
  app.debug=CONFIG.DEBUG
  app.logger.setLevel(logging.DEBUG)
  # We run on localhost only if debugging,
  # otherwise accessible to world
  if CONFIG.DEBUG:
    # Reachable only from the same computer
    app.run(port=CONFIG.PORT,host="0.0.0.0")
  else:
    # Reachable from anywhere 
    app.run(port=CONFIG.PORT,host="0.0.0.0")
    

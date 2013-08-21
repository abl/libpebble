#!/usr/bin/env python

import logging

log = logging.getLogger()
logging.basicConfig(format='[%(levelname)-8s] %(message)s')
log.setLevel(logging.DEBUG)

import bridge, uuid, json, urllib2, collections, time

from struct import pack, unpack
from base64 import b64decode

from pebble import AppMessage

HTTP_URL_KEY = 0xFFFF
HTTP_STATUS_KEY = 0xFFFE
HTTP_COOKIE_KEY = 0xFFFC
HTTP_CONNECT_KEY = 0xFFFB
HTTP_USE_GET_KEY = 0xFFFA
    
HTTP_APP_ID_KEY = 0xFFF2
HTTP_COOKIE_STORE_KEY = 0xFFF0
HTTP_COOKIE_LOAD_KEY = 0xFFF1
HTTP_COOKIE_FSYNC_KEY = 0xFFF3
HTTP_COOKIE_DELETE_KEY = 0xFFF4
    
HTTP_TIME_KEY = 0xFFF5
HTTP_UTC_OFFSET_KEY = 0xFFF6
HTTP_IS_DST_KEY = 0xFFF7
HTTP_TZ_NAME_KEY = 0xFFF8

HTTP_LOCATION_KEY = 0xFFE0
HTTP_LATITUDE_KEY = 0xFFE1
HTTP_LONGITUDE_KEY = 0xFFE2
HTTP_ALTITUDE_KEY = 0xFFE3

#Not yet standard.
HTTP_FRAMEBUFFER_SLICE = 0xFFF9

class HTTPebble(bridge.PebbleBridge):
	UUID = uuid.UUID(bytes="\x91\x41\xB6\x28\xBC\x89\x49\x8E\xB1\x47\x04\x9F\x49\xC0\x99\xAD")

	type_conversion = {
		'b': ('INT', 'b'),
		'B': ('UINT', 'B'),
		's': ('INT', 'h'),
		'S': ('UINT', 'H'),
		'i': ('INT', 'i'),
		'I': ('UINT', 'I')
	}

	def request_screenshot(self):
		vals = [
			(HTTP_FRAMEBUFFER_SLICE, "UINT", pack("<B", 1))
		]

		tuples = [AppMessage.construct_tuple(*x) for x in vals]
		#TODO: Global transaction counter?
		msg = AppMessage.construct_message(AppMessage.construct_dict(tuples), "PUSH", self.UUID.bytes, "\x10")
		self._pebble._send_message("APPLICATION_MESSAGE", msg)

	def http_url_key(self, uri, parameters):
		#Strip type information
		parameters = {x:parameters[x][0] for x in parameters}
		uri = uri[0]

		cookie = parameters[HTTP_COOKIE_KEY]
		app_id = parameters[HTTP_APP_ID_KEY]
		del parameters[HTTP_COOKIE_KEY]
		del parameters[HTTP_APP_ID_KEY]

		log.info("URI: %s" % repr(uri))
		log.info(json.dumps(parameters))

		req = urllib2.Request(uri)
		req.add_header('Content-Type', 'application/json')
		req.add_header('X-Pebble-ID', self._id)
		
		try:
			response = urllib2.urlopen(req, json.dumps(parameters))

			code = response.getcode()
			success = 1 if code is 200 else 0

			data = json.load(response)
			if type(data) is not dict:
				log.warn("Received invalid (non-dictionary) JSON from server.")
				success = 0
		except urllib2.URLError as e:
			log.warn("URLError: %s" % e.reason)
			success = 0
		except:
			exctype, value = sys.exc_info()[:2]
			log.warn("%s: %s" % (exctype, value))
			success = 0
		

		vals = [
			(HTTP_STATUS_KEY, "UINT", pack("<H", code)),
			(HTTP_URL_KEY, "UINT", pack("<B", success)),
			(HTTP_COOKIE_KEY, "UINT", pack("<I", cookie)),
			(HTTP_APP_ID_KEY, "UINT", pack("<I", app_id))
		]

		if success:
			log.info("%d: %s" % (code, data))

			for k in data:
				v = data[k]
				k = int(k)
				if type(v) is list:
					assert len(v) == 2
					t = v[0]
					v = v[1]

					if t == 'd':
						vals.append((k, "BYTE_ARRAY", b64decode(v)))
					else:
						assert t in self.type_conversion
						t = self.type_conversion[t]
						vals.append((k, t[0], pack('<%s' % t[1], v)))
				elif type(v) is int:
					vals.append((k, "INT", pack('<i', v)))
				else:
					vals.append((k, "CSTRING", v))

		tuples = [AppMessage.construct_tuple(*x) for x in vals]
		return AppMessage.construct_dict(tuples)


	def http_location_key(self, code, parameters):
		assert code[0] == 1, "Expected 1, got %s" % repr(code)
		assert len(parameters) == 0
		vals = [
			(HTTP_LOCATION_KEY, 5.0),
			(HTTP_LATITUDE_KEY, 47.62052),
			(HTTP_LONGITUDE_KEY, -122.32408),
			(HTTP_ALTITUDE_KEY, 31.337),
		]
		tuples = [AppMessage.construct_tuple(x[0], "UINT", pack("<f", x[1])) for x in vals]
		return AppMessage.construct_dict(tuples)


	def http_time_key(self, code, parameters):
		assert code[0] == 1, "Expected 1, got %s" % repr(code)
		assert len(parameters) == 0
		if time.daylight:
			vals = [
				(HTTP_TIME_KEY, 'UINT', pack("<I", int(time.time()))),
				(HTTP_UTC_OFFSET_KEY, 'INT', pack("<i", time.altzone)),
				(HTTP_IS_DST_KEY, 'UINT', pack("<B", time.daylight)),
				(HTTP_TZ_NAME_KEY, 'CSTRING', time.tzname[1]),
			]
		else:
			vals = [
				(HTTP_TIME_KEY, 'UINT', pack("<I", int(time.time()))),
				(HTTP_UTC_OFFSET_KEY, 'INT', pack("<i", time.timezone)),
				(HTTP_IS_DST_KEY, 'UINT', pack("<B", time.daylight)),
				(HTTP_TZ_NAME_KEY, 'CSTRING', time.tzname[0]),
			]

		tuples = [AppMessage.construct_tuple(*x) for x in vals]
		return AppMessage.construct_dict(tuples)

	def http_cookie_store(self, request_id, parameters):
		request_id = request_id[0]
		app_id = parameters[HTTP_APP_ID_KEY][0]
		del parameters[HTTP_APP_ID_KEY]
		
		for key in parameters:
			self._cookies[app_id][key] = parameters[key]

		vals = [
			(HTTP_COOKIE_STORE_KEY, 'INT', pack("<i", request_id)),
			(HTTP_APP_ID_KEY, 'INT', pack("<i", app_id)),
		]

		tuples = [AppMessage.construct_tuple(*x) for x in vals]
		return AppMessage.construct_dict(tuples)


	def http_cookie_load(self, request_id, parameters):
		request_id = request_id[0]
		app_id = parameters[HTTP_APP_ID_KEY][0]
		del parameters[HTTP_APP_ID_KEY]

		vals = [
			(HTTP_COOKIE_LOAD_KEY, 'INT', pack("<i", request_id)),
			(HTTP_APP_ID_KEY, 'INT', pack("<i", app_id)),
		]


		for key in parameters:
			assert parameters[key][0] == 1
			try:
				(v,t) = self._cookies[app_id][key]
				vals.append((key,AppMessage.struct_to_tuple_type[t[-1]],pack("<%s" % t, v)))
			except KeyError:
				#Spec says to ignore missing keys.
				log.debug("App %x tried to retrieve non-existent key %x in request %x" % (app_id, key, request_id))

		tuples = [AppMessage.construct_tuple(*x) for x in vals]
		return AppMessage.construct_dict(tuples)


	def http_cookie_fsync(self, code, parameters):
		assert code[0] == 1, "Expected 1, got %s" % repr(code)
		app_id = parameters[HTTP_APP_ID_KEY]
		del parameters[HTTP_APP_ID_KEY]
		assert len(parameters) == 0

		#TODO: Currently a no-op until persistent data store is set up.
		#NOTE: This is within spec.

		vals = [
			(HTTP_COOKIE_FSYNC_KEY, 'UINT', pack("<B", 1)),
			(HTTP_APP_ID_KEY, 'INT', pack("<i", app_id)),
		]

		tuples = [AppMessage.construct_tuple(*x) for x in vals]
		return AppMessage.construct_dict(tuples)

	def http_cookie_delete(self, request_id, parameters):
		request_id = request_id[0]
		app_id = parameters[HTTP_APP_ID_KEY][0]
		del parameters[HTTP_APP_ID_KEY]
		
		#NOTE: The spec does not define what to do if a deletion fails unlike with load - so we warn.

		for key in parameters:
			assert parameters[key][0] == 1
			try:
				del self._cookies[app_id][key]
			except KeyError:
				log.warn("App %x tried to delete non-existent key %x in request %x" % (app_id, key, request_id))

		vals = [
			(HTTP_COOKIE_DELETE_KEY, 'INT', pack("<i", request_id)),
			(HTTP_APP_ID_KEY, 'INT', pack("<i", app_id)),
		]

		tuples = [AppMessage.construct_tuple(*x) for x in vals]
		return AppMessage.construct_dict(tuples)


	commands = {
		HTTP_URL_KEY: http_url_key,
		HTTP_LOCATION_KEY: http_location_key,
		HTTP_TIME_KEY: http_time_key,
		HTTP_COOKIE_STORE_KEY: http_cookie_store,
		HTTP_COOKIE_LOAD_KEY: http_cookie_load,
		HTTP_COOKIE_FSYNC_KEY: http_cookie_fsync,
		HTTP_COOKIE_DELETE_KEY: http_cookie_delete,
	}

	def __init__(self, pebble):
		self._pebble = pebble
		self._id = pebble.id
		self._cookies = collections.defaultdict(dict) #TODO: Serialize/deserialize to disk
		if len(self._id) > 4:
			self._id = self._id[-5:-3] + self._id[-2:] #TODO: Verify this doesn't break non-lightblue folks.

		vals = [(HTTP_CONNECT_KEY, 'INT', pack("<B", 1))]
		tuples = [AppMessage.construct_tuple(*x) for x in vals]
		msg = AppMessage.construct_message(AppMessage.construct_dict(tuples), "PUSH", self.UUID.bytes, '\x01') #TODO: Transaction handling.
		pebble._send_message("APPLICATION_MESSAGE", msg)


	def process(self, msg_dict):
		parameters = {}
		command = None
		code = None
		for k in msg_dict:
			if k in self.commands:
				c = self.commands[k]
				if command is not None:
					log.error("Got more than one command; %s" % c)
				else:
					log.info("HTTP command: %s" % c)
					command = c
					code = msg_dict[k]
			else:
				parameters[k] = msg_dict[k]

		if command is None:
			log.error("Command could not be identified, is one of: %s" % ", ".join([hex(x) for x in parameters.keys()]))
			return

		for p in parameters:
			log.info("    %s: %s" % (p, repr(parameters[p])))

		return command(self, code, parameters)


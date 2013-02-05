# coding=utf-8
import type_pb2
import json
import dict2xml
import copy
import re
from protobuf_to_dict import protobuf_to_dict
from werkzeug.wrappers import Request, Response
from werkzeug.wsgi import responder
from werkzeug.routing import Map, Rule
from wsgiref.simple_server import make_server

from validate import *
from swagger import api_doc
import instance_manager

instances = instance_manager.NavitiaManager('Jörmungandr.ini')

def render(dico, format, callback):
    if format == 'json':
        json_str = json.dumps(dico, ensure_ascii=False)
        if callback == '' or callback == None:
            result = Response(json_str, mimetype='application/json')
        else:
            result = Response(callback + '(' + json_str + ')', mimetype='application/json')
    elif format == 'txt':
        result = Response(json.dumps(dico, ensure_ascii=False, indent=4), mimetype='text/plain')
    elif format == 'xml':
        result = Response('<?xml version="1.0" encoding="UTF-8"?>\n'+ dict2xml.dict2xml(dico, wrap="Response"), mimetype='application/xml')
    elif format == 'pb':
        result = Response('Protocol buffer not supported for this request', status=404)
    else:
        result = Response("Unknown file format format. Please choose .json, .txt, .xml or .pb", mimetype='text/plain', status=404)
    result.headers.add('Access-Control-Allow-Origin', '*')
    return result


def render_from_protobuf(pb_resp, format, callback):
    if format == 'pb':
        return Response(pb_resp.SerializeToString(), mimetype='application/octet-stream')
    else:
        return render(protobuf_to_dict(pb_resp, use_enum_labels=True), format, callback)


def send_and_receive(request, region = None):
    socket = instances.socket_of_key(region)
    socket.send(request.SerializeToString())
    pb = socket.recv()
    resp = type_pb2.Response()
    resp.ParseFromString(pb)
    return resp

def on_index(request, version = None, region = None ):
    return Response('Hello from the index')

def on_regions(request, version, format):
    return render(instances.regions(), format,  request.args.get('callback'))

def on_status(request, region, format):
    req = type_pb2.Request()
    req.requested_api = type_pb2.STATUS
    resp = send_and_receive(req, region)
    return render_from_protobuf(resp, format, request.args.get('callback'))

def on_load(request, region, format):
    req = type_pb2.Request()
    req.requested_api = type_pb2.LOAD
    resp = send_and_receive(req, region)
    return render_from_protobuf(resp, format, request.args.get('callback'))

pb_type = {
        'stop_area': type_pb2.STOPAREA,
        'stop_point': type_pb2.STOPPOINT,
        'city': type_pb2.CITY,
        'address': type_pb2.ADDRESS
        }

def on_first_letter(request_args, version, region, format, callback):
    req = type_pb2.Request()
    req.requested_api = type_pb2.FIRSTLETTER
    req.first_letter.name = request_args['name']
    req.first_letter.types = request_args['object_type']
    resp = send_and_receive(req, region)
    return render_from_protobuf(resp, format, callback)


def stop_times(request_args, version, region, format, departure_filter, arrival_filter, api, callback):
    req = type_pb2.Request()
    req.requested_api = api
    req.next_stop_times.departure_filter = departure_filter
    req.next_stop_times.arrival_filter = arrival_filter

    req.next_stop_times.from_datetime = request_args["from_datetime"]
    req.next_stop_times.duration = request_args["duration"]
    req.next_stop_times.depth = request_args["depth"]
    req.next_stop_times.nb_stoptimes = request_args["nb_stoptimes"]
    req.next_stop_times.wheelchair = request_args["wheelchair"]
    resp = send_and_receive(req, region)
    return render_from_protobuf(resp, format, request.args.get('callback'))

def on_line_schedule(request_args, version, region, format, callback):
    return stop_times(request_args, version, region, format, request_args["filter"], "", type_pb2.LINE_SCHEDUL, callbackE)

def on_next_arrivals(request_args, version, region, format, callback):
    return stop_times(request_args, version, region, format, request_args["filter"], "", type_pb2.NEXT_DEPARTURES, callback)

def on_next_departures(request_args, version, region, format, callback):
    return stop_times(request_args, version, region, format, "", request_args["filter"], type_pb2.NEXT_ARRIVALS, callback)

def on_stops_schedule(request_args, version, region, format, callback):
    return stop_times(request_args, version, region, format, request_args["departure_filter"], request_args["arrival_filter"],type_pb2.STOPS_SCHEDULE, callback)

def on_departure_board(request_args, version, region, format, callback):
    return stop_times(request_args, version, region, format, request_args["filter"], "", type_pb2.DEPARTURE_BOARD, callback)

def on_proximity_list(request_args, version, region, format, callback):
    req = type_pb2.Request()
    req.requested_api = type_pb2.PROXIMITYLIST
    req.proximity_list.coord.lon = request_args["lon"]
    req.proximity_list.coord.lat = request_args["lat"]
    req.proximity_list.distance = request_args["distance"]
    req.proximity_list.types = request_args["object_type"]
    resp = send_and_receive(req, region)
    return render_from_protobuf(resp, format, callback)

def journeys(requested_type, request_args, version, region, format, callback):
#    req.params = "origin=coord:2.1301409667968625:48.802045523752106&destination=coord:2.3818232910156234:48.86202003509158&datetime=20120615T143200&format=pb" 
    req = type_pb2.Request()
    req.requested_api = requested_type

    req.journeys.origin = request_args["origin"]
    req.journeys.destination = request_args["destination"] if "destination" in request_args else ""
    req.journeys.datetime.append(request_args["datetime"])
    req.journeys.clockwise = request_args["clockwise"]
    #req.journeys.forbiddenline += request.args.getlist('forbiddenline[]')
    #req.journeys.forbiddenmode += request.args.getlist('forbiddenmode[]')
    #req.journeys.forbiddenroute += request.args.getlist('forbiddenroute[]')
    req.journeys.walking_speed = request_args["walking_speed"]
    req.journeys.walking_distance = request_args["walking_distance"]
    req.journeys.wheelchair = request_args["wheelchair"]
    resp = send_and_receive(req, region)
    return render_from_protobuf(resp, format, callback)

def on_journeys(requested_type):
    return lambda request, version, region, format, callback: journeys(requested_type, request, version, region, format, callback)

def ptref(requested_type, request_args, version, region, format, callback):
    req = type_pb2.Request()
    req.requested_api = type_pb2.PTREFERENTIAL

    req.ptref.requested_type = requested_type
    req.ptref.filter = request_args["filter"]
    req.ptref.depth = request_args["depth"]
    resp = send_and_receive(req, region)
    return render_from_protobuf(resp, format, callback)

def on_ptref(requested_type):
    return lambda request_args, version, region, format, callback: ptref(requested_type, request_args, version, region, format, callback)


scheduleArguments = {
        "filter" : Argument("Filter to have the times you want", filter, True,
                            False, order=0),
        "from_datetime" : Argument("The date from which you want the times",
                              datetime, True, False, order=10),
        "duration" : Argument("Maximum duration between the datetime and the last  retrieved stop time",
                                  int, False, False, defaultValue=86400, order=20 ),        
        "wheelchair" : Argument("true if you want the times to have accessibility", boolean, False, False, defaultValue=False, order=50)
        }
stopsScheduleArguments = copy.copy(scheduleArguments)
del stopsScheduleArguments["filter"]
stopsScheduleArguments["departure_filter"] = Argument("The filter of your departure point", filter,
                                                      True, False,order=0)
stopsScheduleArguments["arrival_filter"] = Argument("The filter of your arrival point", filter,
                                                      True, False,order=1)

nextTimesArguments = copy.copy(scheduleArguments)
nextTimesArguments["nb_stoptimes"] = Argument("The maximum number of stop_times", int , False, False, 20, order=30)

ptrefArguments = {
        "filter" : Argument("Conditions to filter the returned objects", filter,
                            False, False, "", order=0),
        "depth" : Argument("Maximum depth on objects", int, False, False, 1,
                           order = 50)
        }
journeyArguments = {
        "origin" : Argument("Departure Point", entrypoint, True, False, order = 0),
        "destination" : Argument("Destination Point" , entrypoint, True, False, order = 1),
        "datetime" : Argument("The time from which you want to arrive (or arrive before depending on the value of clockwise", datetime, True, False, order = 2),
        "clockwise" : Argument("1 if you want to have a journey that starts after datetime, 0 if you a journey that arrives before datetime", boolean, False, False, True, order = 3),
        #"forbiddenline" : Argument("Forbidden lines identified by their external codes",  str, False, True, ""),
        #"forbiddenmode" : Argument("Forbidden modes identified by their external codes", str, False, True, ""),
        #"forbiddenroute" : Argument("Forbidden routes identified by their external codes", str, False, True, ""),
        "walking_speed" : Argument("Walking speed in m/s", float, False, False, 1.38),
        "walking_distance" : Argument("Maximum walking distance in meters", int,
                                      False, False, 1000),
        "wheelchair" : Argument("Does the journey has to be accessible ?",
                                boolean, False, False, 0)
        }
isochroneArguments = copy.copy(journeyArguments)
del isochroneArguments["destination"]

apis = {
        "first_letter" : {"endpoint" : on_first_letter, "arguments" : {"name" : Argument("The data to search", str, True, False, order = 1),
                                                                       "object_type[]" : Argument("The type of datas you want in return", str, False, False, "")},
                          "description" : "Retrieves the objects which contains in their name the \"name\"",
                          "order":2},
        "next_departures" : {"endpoint" : on_next_departures, "arguments" :
                             nextTimesArguments, 
                             "description" : "Retrieves the departures after datetime at the stop points filtered with filter",
                          "order":3},
        "next_arrivals" : {"endpoint" : on_next_arrivals, "arguments" :
                            nextTimesArguments,
                           "description" : "Retrieves the departures after datetime at the stop points filtered with filter",
                          "order":3},
        "line_schedule" : {"endpoint" : on_line_schedule, "arguments" :
                           scheduleArguments,
                           "description" : "Retrieves the schedule of line at the day datetime",
                          "order":4},
        "stops_schedule" : {"endpoint" : on_stops_schedule, "arguments" :
                            stopsScheduleArguments,
                            "description" : "Retrieves the schedule for 2 stops points",
                          "order":4},
        "departure_board" : {"endpoint" : on_departure_board,
                             "arguments":scheduleArguments,
                             "description" : "Give all the departures of filter at datetime",
                          "order":4},
        "stop_areas" : {"endpoint" : on_ptref(type_pb2.STOPAREA), "arguments" :
                        ptrefArguments,
                        "description" : "Retrieves all the stop areas filtered with filter",
                          "order":5},
        "stop_points" : {"endpoint" : on_ptref(type_pb2.STOPPOINT), "arguments" :
                        ptrefArguments,
                        "description" : "Retrieves all the stop points filtered with filter",
                          "order":5},
        "lines" : {"endpoint" : on_ptref(type_pb2.LINE), "arguments" :
                        ptrefArguments,
                        "description" : "Retrieves all the stop_areas filtered with filter",
                          "order":5},
        "routes" : {"endpoint" : on_ptref(type_pb2.ROUTE), "arguments" :
                        ptrefArguments,
                        "description" : "Retrieves all the routes filtered with filter",
                          "order":5},
        "networks" : {"endpoint" : on_ptref(type_pb2.NETWORK), "arguments" :
                        ptrefArguments,
                        "description" : "Retrieves all the networks filtered with filter",
                          "order":5},
        "modes" : {"endpoint" : on_ptref(type_pb2.MODE), "arguments" :
                        ptrefArguments,
                        "description" : "Retrieves all the modes filtered with filter",
                          "order":5},
        "mode_types" : {"endpoint" : on_ptref(type_pb2.MODETYPE), "arguments" :
                        ptrefArguments,
                        "description" : "Retrieves all the mode types filtered with filter",
                          "order":5},
        "connections" : {"endpoint" : on_ptref(type_pb2.CONNECTION), "arguments" :
                        ptrefArguments,
                        "description" : "Retrieves all the connections points filtered with filter",
                          "order":5},
        "route_points" : {"endpoint" : on_ptref(type_pb2.ROUTEPOINT), "arguments" :
                        ptrefArguments,
                        "description" : "Retrieves all the route points filtered with filter",
                          "order":5},
        "companies" : {"endpoint" : on_ptref(type_pb2.COMPANY), "arguments" :
                        ptrefArguments,
                        "description" : "Retrieves all the companies filtered with filter",
                          "order":5},
        "vehicle_journeys" : {"endpoint" : on_ptref(type_pb2.VEHICLEJOURNEY),
                              "arguments" : ptrefArguments,
                              "description" :"Retrieves all the vehicle journeys filtered with filter" ,
                              "order" : 5},
        "journeys" : {"endpoint" :  on_journeys(type_pb2.PLANNER), "arguments" :
                      journeyArguments,
                      "description" : "Computes and retrieves a journey",
                          "order":1},
        "isochrone" : {"endpoint" : on_journeys(type_pb2.ISOCHRONE), "arguments" : isochroneArguments,
                       "description" : "Computes and retrieves an isochrone",
                          "order":1},
        "proximity_list" : {"endpoint" : on_proximity_list, "arguments" : {
                "lon" : Argument("Longitude of the point from where you want objects", float, True, False, order=0),
                "lat" : Argument("Latitude of the point from where you want objects", float, True, False, order=1),
                "dist" : Argument("Distance range of the query", int, False, False, 1000, order=3),
                "object_type[]" : Argument("Type of the objects you want to have in return", str, False, False, "", order=4)
                },
            "description" : "Retrieves all the objects around a point within the given distance",
            "order" : 1.1}
        
        }
apis_all = copy.copy(apis)
apis_all["regions"] = {"arguments" : {}, "description" : "Retrieves the list of available regions", "regions" : False,
                          "order":0}


def on_api(request, version, region, api, format):
    if version != "v0":
        return Response("Unknown version: " + version, status=404)
    if api in apis:
        v = validate_arguments(request, apis[api]["arguments"])
        if v.valid:
            return apis[api]["endpoint"](v.arguments, version, region, format, request.args.get("callback"))
        else:
            return Response("Invalid arguments: " + str(v.details), status=400)
    else:
        return Response("Unknown api: " + api, status=404)


def universal_journeys(api, request, version, format):
    origin = request.args.get("origin", "")
    origin_re = re.match('^coord:(.+):(.+)$', origin)
    region = None
    if origin_re:
        try:
            lon = float(origin_re.group(1))
            lat = float(origin_re.group(2))
            region = instances.key_of_coord(lon, lat)
        except:
            return Response("Unable to parse coordinates", status=400)
        if region:
            return on_api(request, version, region, api, format)
        else:
            return Response("No region found at given coordinates", status=404)
    else:
        return Response("Journeys without specifying a region only accept coordinates as origin or destination", status=400)

def on_universal_journeys(api):
    return lambda request, version, format: universal_journeys(api, request, version, format)

def on_universal_proximity_list(request, version, format):
    try:
        region = instances.key_of_coord(float(request.args.get("lon")), float(request.args.get("lat")))
        if region:
            return on_api(request, version, region, "proximity_list", format)
        else:
            return Response("No region found at given coordinates", status=404)
    except:
        return Response("Invalid coordianates", status=400)
   

def on_summary_doc(request) :
    return render(api_doc(apis_all, instances), 'json',  request.args.get('callback'))

def on_doc(request, api):
    return render(api_doc(apis_all, instances, api), 'json', request.args.get('callback'))

url_map = Map([
    Rule('/', endpoint=on_index),
    Rule('/<version>/', endpoint=on_index),
    Rule('/<version>/regions.<format>', endpoint = on_regions),
    Rule('/<version>/journeys.<format>', endpoint = on_universal_journeys("journeys")),
    Rule('/<version>/isochrone.<format>', endpoint = on_universal_journeys("isochrone")),
    Rule('/<version>/proximity_list.<format>', endpoint = on_universal_proximity_list),
    Rule('/<region>/load.<format>', endpoint = on_load),
    Rule('/<region>/status.<format>', endpoint = on_status),
    Rule('/<version>/<region>/', endpoint = on_index),
    Rule('/<version>/<region>/<api>.<format>', endpoint = on_api),
    Rule('/doc.json', endpoint = on_summary_doc),
    Rule('/doc.json/<api>', endpoint = on_doc)
    ])



@responder
def application(environ, start_response):
    request = Request(environ)
    urls = url_map.bind_to_environ(environ)
    return urls.dispatch(lambda fun, v: fun(request, **v),
            catch_http_exceptions=True)

if __name__ == '__main__':
    v = validate_apis(apis_all)
    if not(v.valid):
        for apiname, details in v.details.iteritems():
            if len(details) > 0:
                print "Error in api : " + apiname
                for error in details : 
                    print "\t"+error

    httpd = make_server('', 8088, application)
    print "Serving on port 8088..."
    httpd.serve_forever()

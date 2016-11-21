# Copyright (c) 2001-2015, Canal TP and/or its affiliates. All rights reserved.
#
# This file is part of Navitia,
#     the software to build cool stuff with public transport.
#
# Hope you'll enjoy and contribute to this project,
#     powered by Canal TP (www.canaltp.fr).
# Help us simplify mobility and open public transport:
#     a non ending quest to the responsive locomotion way of traveling!
#
# LICENCE: This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
# Stay tuned using
# twitter @navitia
# IRC #navitia on freenode
# https://groups.google.com/d/forum/navitia
# www.navitia.io

from __future__ import absolute_import, print_function, unicode_literals, division
import logging
from jormungandr.scenarios import new_default
from navitiacommon import type_pb2, response_pb2
import uuid
from jormungandr.scenarios.utils import fill_uris
from jormungandr.planner import JourneyParameters
from flask import g
from jormungandr.utils import get_uri_pt_object, generate_id
from jormungandr import app
import gevent
import gevent.pool
import collections


def create_crowfly(_from, to, begin, end, mode='walking'):
    section = response_pb2.Section()
    section.type = response_pb2.CROW_FLY
    section.origin.CopyFrom(_from)
    section.destination.CopyFrom(to)
    section.duration = end-begin
    section.begin_date_time = begin
    section.end_date_time = end
    section.street_network.mode = response_pb2.Walking
    section.id = unicode(uuid.uuid4())
    return section


class SectionSorter(object):
    def __call__(self, a, b):
        if a.begin_date_time != b.begin_date_time:
            return -1 if a.begin_date_time < b.begin_date_time else 1
        else:
            return -1 if a.end_date_time < b.end_date_time else 1


def get_max_fallback_duration(request, mode):
    if mode == 'walking':
        return request['max_walking_duration_to_pt']
    if mode == 'bss':
        return request['max_bss_duration_to_pt']
    if mode == 'bike':
        return request['max_bike_duration_to_pt']
    if mode == 'car':
        return request['max_car_duration_to_pt']
    raise ValueError('unknown mode: {}'.format(mode))


#TODO: make this work, it's dynamically imported, so the function is register too late
#@app.before_request
def _init_g():
    g.origins_places_crowfly = {}
    g.destinations_places_crowfly = {}
    g.origins_fallback = {}
    g.destinations_fallback = {}
    g.fallback_direct_path = {}
    g.requested_origin = None
    g.requested_destination = None


def create_parameters(request):
    return JourneyParameters(max_duration=request['max_duration'],
                             max_transfers=request['max_transfers'],
                             wheelchair=request['wheelchair'] or False,
                             realtime_level=request['data_freshness'],
                             max_extra_second_pass=request['max_extra_second_pass'],
                             walking_transfer_penalty=request['_walking_transfer_penalty'],
                             forbidden_uris=request['forbidden_uris[]'])


def _update_crowfly_duration(instance, mode, stop_area_uri, requested_point):
    stop_points = instance.georef.get_stop_points_for_stop_area(stop_area_uri)
    crowfly_sps = set()
    odt_stop_points = set()
    fallback_list = collections.defaultdict(dict)
    for stop_point in stop_points:
        fallback_list[mode][stop_point.uri] = 0
        crowfly_sps.add(stop_point.uri)
 
    if requested_point.uri in fallback_list[mode]:
        fallback_list[mode][requested_point.uri] = 0

    map_coord = {
        type_pb2.STOP_POINT: requested_point.stop_point.coord,
        type_pb2.STOP_AREA: requested_point.stop_area.coord,
        type_pb2.ADDRESS: requested_point.address.coord,
        type_pb2.ADMINISTRATIVE_REGION: requested_point.administrative_region.coord
    }
    coord = map_coord.get(requested_point.embedded_type, None)
    if coord:
        odt_sps = instance.georef.get_odt_stop_points(coord)
        for stop_point in odt_sps:
            fallback_list[mode][stop_point.uri] = 0
            odt_stop_points.add(stop_point.uri)
    
    return crowfly_sps, odt_stop_points, fallback_list


def _rename_journey_sections_ids(start_idx, sections):
    for s in sections:
        s.id = "dp_section_{}".format(start_idx)
        start_idx += 1


def _extend_pt_sections_with_direct_path(pt_journey, dp_journey):
    if getattr(dp_journey, 'journeys', []) and hasattr(dp_journey.journeys[0], 'sections'):
        _rename_journey_sections_ids(len(pt_journey.sections), dp_journey.journeys[0].sections)
        pt_journey.sections.extend(dp_journey.journeys[0].sections)


def _reverse_journeys(res):
    if not getattr(res, "journeys"):
        return res
    for j in res.journeys:
        if not getattr(j, "sections"):
            continue
        previous_section_begin = j.arrival_date_time
        for s in j.sections:
            from copy import deepcopy
            o = deepcopy(s.origin)
            d = deepcopy(s.destination)
            s.origin.CopyFrom(d)
            s.destination.CopyFrom(o)
            s.end_date_time = previous_section_begin
            previous_section_begin = s.begin_date_time = s.end_date_time - s.duration
    return res


def _get_places_crowfly(instance, mode, place, max_duration, max_nb_crowfly=5000, **kwargs):
    # When max_duration is 0, there is no need to compute the fallback to pt, except if place is a stop_point or a
    # stop_area
    if max_duration == 0:
        if instance.georef.get_stop_points_from_uri(place.uri):
            return {mode: place}
        else:
            return {mode: []}
    return {mode: instance.georef.get_crow_fly(get_uri_pt_object(place), mode, max_duration,
                                               max_nb_crowfly, **kwargs)}


def _sn_routing_matrix(instance, place, places_crowfly, mode, max_duration, request, **kwargs):
    # When max_duration is 0, there is no need to compute the fallback to pt, except if place is a stop_point or a
    # stop_area
    if max_duration == 0:
        if place:
            return {mode: {place.uri: 0}}
        else:
            return {mode: {}}
    places = places_crowfly[mode]
    sn_routing_matrix = instance.street_network_service.get_street_network_routing_matrix([place],
                                                                                           places,
                                                                                           mode,
                                                                                           max_duration,
                                                                                           request,
                                                                                           **kwargs)
    if not sn_routing_matrix.rows[0].duration:
        return {mode: {}}
    import numpy as np
    durations = np.array(sn_routing_matrix.rows[0].duration)
    valid_duration_idx = np.argwhere((durations > -1) & (durations < max_duration)).flatten()
    return {mode: dict(zip([places[i].uri for i in valid_duration_idx],
                       durations[(durations > -1) & (durations < max_duration)].flatten()))}


class AsyncWorker(object):
    def __init__(self, instance, krakens_call, request, size=app.config.get('GREENLET_POOL_SIZE', 3)):
        self.pool = gevent.pool.Pool(size)
        self.instance = instance
        self.krakens_call = krakens_call
        self.request = request
        self.speed_switcher = {
            "walking": instance.walking_speed,
            "bike": instance.bike_speed,
            "car": instance.car_speed,
            "bss": instance.bss_speed,
        }

    def get_routing_matrix_futures(self, origin, destination,
                                   origins_places_crowfly,
                                   destinations_places_crowfly):
        origin_futures = []
        destination_futures = []

        called_dep_modes = set()
        called_arr_modes = set()
        for dep_mode, arr_mode in self.krakens_call:
            if dep_mode not in called_dep_modes:
                origin_futures.append(self.pool.spawn(_sn_routing_matrix,
                                                      self.instance,
                                                      origin,
                                                      origins_places_crowfly,
                                                      dep_mode,
                                                      get_max_fallback_duration(self.request, dep_mode),
                                                      self.request,
                                                      **self.speed_switcher))
                called_dep_modes.add(dep_mode)
            if arr_mode not in called_arr_modes:
                destination_futures.append(self.pool.spawn(_sn_routing_matrix,
                                                           self.instance,
                                                           destination,
                                                           destinations_places_crowfly,
                                                           arr_mode,
                                                           get_max_fallback_duration(self.request, arr_mode),
                                                           self.request,
                                                           **self.speed_switcher))
                called_arr_modes.add(arr_mode)

            return origin_futures, destination_futures

    def get_crowfly_futures(self, origin, destination):
        origin_futures = []
        destination_futures = []

        called_dep_modes = set()
        called_arr_modes = set()
        for dep_mode, arr_mode in self.krakens_call:
            if dep_mode not in called_dep_modes:
                origin_futures.append(self.pool.spawn(_get_places_crowfly,
                                                      self.instance,
                                                      dep_mode,
                                                      origin,
                                                      get_max_fallback_duration(self.request, dep_mode),
                                                      **self.speed_switcher))
                called_dep_modes.add(dep_mode)
            if arr_mode not in called_arr_modes:
                destination_futures.append(self.pool.spawn(_get_places_crowfly,
                                                           self.instance,
                                                           arr_mode,
                                                           destination,
                                                           get_max_fallback_duration(self.request, arr_mode),
                                                           **self.speed_switcher))
                called_arr_modes.add(arr_mode)
        return origin_futures, destination_futures

    def get_update_crowfly_duration_futures(self):
        origin_futures = []
        destination_futures = []
        origin = self.request['origin']
        destination = self.request['destination']
        called_dep_modes = set()
        called_arr_modes = set()
        for dep_mode, arr_mode in self.krakens_call:
            if dep_mode not in called_dep_modes:
                origin_futures.append(self.pool.spawn(_update_crowfly_duration, self.instance, dep_mode,
                                                      origin, g.requested_origin))
                called_dep_modes.add(dep_mode)
            if arr_mode not in called_arr_modes:
                destination_futures.append(self.pool.spawn(_update_crowfly_duration, self.instance, arr_mode,
                                                           destination, g.requested_destination))
                called_arr_modes.add(arr_mode)
        return origin_futures, destination_futures

    def get_direct_path_futures(self, func, fallback_direct_path, origin, destination):
        futures_direct_path = []
        for dep_mode, _ in self.krakens_call:
            futures_direct_path.append(self.pool.spawn(func, self.instance,
                                                       dep_mode,
                                                       origin, destination,
                                                       self.request['datetime'],
                                                       self.request['clockwise'],
                                                       self.request,
                                                       fallback_direct_path))
        return futures_direct_path

    def get_pt_journey_futures(self, origin, destination, fallback_direct_path, origins_fallback,
                            destinations_fallback, journey_parameters):
        futures_jourenys = []
        reverse_sections = False
        instance = self.instance
        datetime = self.request['datetime']
        clockwise = self.request['clockwise']
        for dep_mode, arr_mode in self.krakens_call:
            dp_key = (dep_mode, origin.uri, destination.uri, datetime, clockwise, reverse_sections)
            dp = fallback_direct_path.get(dp_key)
            if dp.journeys:
                journey_parameters.direct_path_duration = dp.journeys[0].durations.total
            else:
                journey_parameters.direct_path_duration = None

            origins = origins_fallback.get(dep_mode)
            destinations = destinations_fallback.get(arr_mode)

            def worker_journey():
                if not origins_fallback or not destinations_fallback or not self.request.get('max_duration', 0):
                    return dep_mode, arr_mode, None
                return dep_mode, arr_mode, instance.planner.journeys(origins, destinations,
                                                                     datetime, clockwise,
                                                                     journey_parameters)
            futures_jourenys.append(self.pool.spawn(worker_journey))
            return futures_jourenys

    @staticmethod
    def _build_from(journey, instance, first_section, func_extend_journey, _from, crow_fly_stop_points, odt_stop_points,
                    request, dep_mode, fallback_direct_path, origins_fallback):

        departure = first_section.origin
        journey.departure_date_time = journey.departure_date_time - origins_fallback[departure.uri]
        if _from.uri != departure.uri:
            if departure.uri in odt_stop_points:
                journey.sections[0].origin.CopyFrom(_from)
            elif departure.uri in crow_fly_stop_points:
                journey.sections.extend([create_crowfly(_from, departure, journey.departure_date_time,
                                         journey.sections[0].begin_date_time)])
            else:
                func_extend_journey(instance, journey, dep_mode, _from, departure, journey.departure_date_time,
                                    origins_fallback, True, request, fallback_direct_path)
        journey.sections.sort(SectionSorter()) 
        return journey

    @staticmethod
    def _build_to(journey, instance, last_section, func_extend_journey, to, crow_fly_stop_points, odt_stop_points,
                  request, arr_mode, fallback_direct_path, destinations_fallback):

        arrival = last_section.destination
        journey.arrival_date_time = journey.arrival_date_time + destinations_fallback[arrival.uri]
        last_section_end = last_section.end_date_time

        if to.uri != arrival.uri:
            if arrival.uri in odt_stop_points:
                journey.sections[-1].destination.CopyFrom(to)
            elif arrival.uri in crow_fly_stop_points:
                journey.sections.extend([create_crowfly(arrival, to, last_section_end,
                                                        journey.arrival_date_time)])
            else:
                o = arrival
                d = to
                reverse_sections = False
                if arr_mode == 'car':
                    o, d, reverse_sections = d, o, True
                func_extend_journey(instance, journey, arr_mode, o, d, journey.arrival_date_time,
                                    destinations_fallback, False, request, fallback_direct_path, reverse_sections)
        journey.sections.sort(SectionSorter())
        return journey

    def build_journeys(self, func_extend_journey, map_response, crow_fly_stop_points, odt_stop_points):
        futures = []
        for values in map_response:
            dep_mode = values[0]
            arr_mode = values[1]
            journey = values[2]
            # from
            futures.append(self.pool.spawn(self._build_from, journey, self.instance,
                                           journey.sections[0], func_extend_journey, g.requested_origin,
                                           crow_fly_stop_points, odt_stop_points, self.request,
                                           dep_mode, g.fallback_direct_path, g.origins_fallback[dep_mode]))
            # to
            futures.append(self.pool.spawn(self._build_to, journey, self.instance,
                                           journey.sections[-1], func_extend_journey, g.requested_destination,
                                           crow_fly_stop_points, odt_stop_points, self.request,
                                           arr_mode, g.fallback_direct_path, g.destinations_fallback[arr_mode]))
        return futures


class Scenario(new_default.Scenario):

    def __init__(self):
        super(Scenario, self).__init__()

    def _get_direct_path(self, instance, mode, pt_object_origin, pt_object_destination, datetime, clockwise,
                         request, fallback_direct_path, reverse_sections=False):
        dp_key = (mode, pt_object_origin.uri, pt_object_destination.uri, datetime, clockwise, reverse_sections)
        dp = fallback_direct_path.get(dp_key)
        if not dp:
            dp = fallback_direct_path[dp_key] = instance.street_network_service.direct_path(mode,
                                                                                            pt_object_origin,
                                                                                            pt_object_destination,
                                                                                            datetime,
                                                                                            clockwise,
                                                                                            request)
            if reverse_sections:
                _reverse_journeys(dp)
        return dp

    def _get_stop_points(self, instance, place, mode, max_duration, request, reverse=False, max_nb_crowfly=5000):
        # we use place_nearby of kraken at the first place to get stop_points around the place, then call the
        # one_to_many(or many_to_one according to the arg "reverse") service to take street network into consideration
        # TODO: reverse is not handled as so far

        # When max_duration is 0, there is no need to compute the fallback to pt, except if place is a stop_point or a
        # stop_area
        if max_duration == 0:
            if instance.georef.get_stop_points_from_uri(place.uri):
                return {place.uri: 0}
            else:
                return {}
        places_crowfly = instance.georef.get_crow_fly(get_uri_pt_object(place), mode, max_duration, max_nb_crowfly)

        sn_routing_matrix = instance.street_network_service.get_street_network_routing_matrix([place],
                                                                                              places_crowfly,
                                                                                              mode,
                                                                                              max_duration,
                                                                                              request)
        if not sn_routing_matrix.rows[0].duration:
            return {}
        import numpy as np
        durations = np.array(sn_routing_matrix.rows[0].duration)
        valid_duration_idx = np.argwhere((durations > -1) & (durations < max_duration)).flatten()
        return dict(zip([places_crowfly[i].uri for i in valid_duration_idx],
                        durations[(durations > -1) & (durations < max_duration)].flatten()))

    def _extend_journey(self, instance, pt_journey, mode, pb_from, pb_to, departure_date_time, nm, clockwise,
                        request, fallback_direct_path, reverse_sections=False):
        import copy

        departure_dp = self._get_direct_path(instance, mode, pb_from, pb_to, departure_date_time, clockwise, request,
                                             fallback_direct_path, reverse_sections)
        if clockwise:
            pt_journey.duration += nm[pb_to.uri]
        elif not reverse_sections:
            pt_journey.duration += nm[pb_from.uri]
        elif reverse_sections:
            pt_journey.duration += nm[pb_to.uri]

        departure_direct_path = copy.deepcopy(departure_dp)
        pt_journey.durations.walking += departure_direct_path.journeys[0].durations.walking
        _extend_pt_sections_with_direct_path(pt_journey, departure_direct_path)

    def call_kraken(self, request_type, request, instance, krakens_call):
        """
        For all krakens_call, call the kraken and aggregate the responses

        return the list of all responses
        """
        logger = logging.getLogger(__name__)
        logger.debug('datetime: %s', request['datetime'])
        #odt_stop_points is a set of stop_point.uri with is_zonal = true used to manage tad_zonal
        odt_stop_points = set()
        #crow_fly_stop_points is a set of stop_point.uri used to create a crowfly section.
        crow_fly_stop_points = set()

        if not g.requested_origin:
            g.requested_origin = instance.georef.place(request['origin'])

        if not g.requested_destination:
            g.requested_destination = instance.georef.place(request['destination'])

        worker = AsyncWorker(instance, krakens_call, request)

        if request.get('max_duration', 0):
            # Get all stop_points around the requested origin within a crowfly range
            # Calls on origins and destinations are asynchronous
            orig_futures, dest_futures = worker.get_crowfly_futures(g.requested_origin, g.requested_destination)
            gevent.joinall(orig_futures + dest_futures)
            for future in gevent.iwait(orig_futures):
                g.origins_places_crowfly.update(future.get())
            for future in gevent.iwait(dest_futures):
                g.destinations_places_crowfly.update(future.get())

            # Once we get crow fly stop points with origins and destinations, we start
            # the computation NM: the fallback matrix which contains the arrival duration for crowfly stop_points
            # from origin/destination
            # Ex:
            #                  stop_point1   stop_point2  stop_point3
            # request_origin     86400(s)      43200(s)     21600(s)
            # As a side note this won't work the day when our ETA will be impacted by the datetime of the journey,
            # at least for the arrival when doing a "departure after" request.
            orig_futures, dest_futures = worker.get_routing_matrix_futures(g.requested_origin,
                                                                           g.requested_destination,
                                                                           g.origins_places_crowfly,
                                                                           g.destinations_places_crowfly)
            gevent.joinall(orig_futures + dest_futures)
            for future in gevent.iwait(orig_futures):
                g.origins_fallback.update(future.get())
            for future in gevent.iwait(dest_futures):
                g.destinations_fallback.update(future.get())

            # In Some special cases, like "odt" or "departure(arrive) from(to) a stop_area",
            # the first(last) section should be treated differently
            orig_futures, dest_futures = worker.get_update_crowfly_duration_futures()
            gevent.joinall(orig_futures + dest_futures)

            def _updater(_futures, fb, crow_fly_stop_points, odt_stop_points):
                for f in gevent.iwait(_futures):
                    crow_fly_res, odt_res, fb_res = f.get()
                    crow_fly_stop_points |= crow_fly_res
                    odt_stop_points |= odt_res
                    for mode in (mode for mode in fb_res if mode in fb):
                        fb[mode].update(fb_res[mode])

            _updater(orig_futures, g.origins_fallback, crow_fly_stop_points, odt_stop_points)
            _updater(dest_futures, g.destinations_fallback, crow_fly_stop_points, odt_stop_points)

        resp = []
        journey_parameters = create_parameters(request)

        # Now we compute the direct path with all requested departure mode
        # their time will be used to initialized our PT calls
        futures = worker.get_direct_path_futures(self._get_direct_path,
                                                 g.fallback_direct_path,
                                                 g.requested_origin,
                                                 g.requested_destination)
        for future in gevent.iwait(futures):
            self.nb_kraken_calls += 1
            resp_direct_path = future.get()
            if resp_direct_path.journeys:
                if resp_direct_path not in resp:
                    resp_direct_path.journeys[0].internal_id = str(generate_id())
                    resp.append(resp_direct_path)

        # Here starts the computation for pt journey
        futures = worker.get_pt_journey_futures(g.requested_origin, g.requested_destination,
                                                g.fallback_direct_path, g.origins_fallback,
                                                g.destinations_fallback, journey_parameters)

        map_response = []
        for future in gevent.iwait(futures):
            dep_mode, arr_mode, local_resp = future.get()
            if local_resp is None:
                continue
            dp_key = (dep_mode, g.requested_origin.uri, g.requested_destination.uri, request['datetime'],
                      request['clockwise'], False)
            direct_path = g.fallback_direct_path.get(dp_key)

            if local_resp.HasField(b"error") and local_resp.error.id == response_pb2.Error.error_id.Value('no_solution') \
                    and direct_path.journeys:
                local_resp.ClearField(b"error")
            if local_resp.HasField(b"error"):
                return [local_resp]

            # for log purpose we put and id in each journeys
            for j in local_resp.journeys:
                j.internal_id = str(generate_id())
                map_response.append((dep_mode, arr_mode, j))
            resp.append(local_resp)

        futures = worker.build_journeys(self._extend_journey, map_response, crow_fly_stop_points, odt_stop_points)
        for future in gevent.iwait(futures):
            journey = future.get()
            journey.durations.total = journey.duration
            journey.sections.sort(SectionSorter())

        for r in resp:
            fill_uris(r)
        return resp

    def isochrone(self, request, instance):
        return self.__on_journeys(type_pb2.ISOCHRONE, request, instance)

    def journeys(self, request, instance):
        logger = logging.getLogger(__name__)
        logger.warn('using experimental scenario!!!')
        _init_g()
        return self.__on_journeys(type_pb2.PLANNER, request, instance)

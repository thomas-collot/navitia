# Copyright (c) 2001-2014, Canal TP and/or its affiliates. All rights reserved.
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

from .tests_mechanism import AbstractTestFixture, dataset
from .check_utils import *
from jormungandr import app
from shapely.geometry import asShape, Point


@dataset({"main_routing_test": {}})
class TestGraphicalIsochron(AbstractTestFixture):
    """
    Test the structure of the isochrons response
    """

    def test_from_graphical_isochron_coord(self):
        query = "v1/coverage/main_routing_test/isochrons?from={}&datetime={}&duration={}"
        query = query.format(s_coord, "20120614T080000", "3600")
        response = self.query(query)
        origin = Point(0.0000898312, 0.0000898312)
        d = response['isochrons'][0]['geojson']
        multi_poly = asShape(d)

        assert (multi_poly.contains(origin))
        is_valid_graphical_isochron(response, self.tester, query)

    def test_to_graphical_isochron_coord(self):
        query = "v1/coverage/main_routing_test/isochrons?to={}&datetime={}&duration={}&datetime_represents=arrival"
        query = query.format(s_coord, "20120614T080000", "3600")
        response = self.query(query)
        destination = Point(0.0000898312, 0.0000898312)
        d = response['isochrons'][0]['geojson']
        multi_poly = asShape(d)

        assert (multi_poly.contains(destination))
        is_valid_graphical_isochron(response, self.tester, query)

    def test_reverse_graphical_isochrons_coord_clockwise(self):
        q = "v1/coverage/main_routing_test/isochrons?datetime={}&to={}&duration={}"
        q = q.format('20120614T080000', s_coord, '3600')
        normal_response, error_code = self.query_no_assert(q)

        assert error_code == 404
        assert normal_response['error']['message'] == 'reverse isochrone works only for anti-clockwise request'

    def test_graphical_isochrons_coord_clockwise(self):
        q = "v1/coverage/main_routing_test/isochrons?datetime={}&from={}&duration={}&datetime_represents=arrival"
        q = q.format('20120614T080000', s_coord, '3600')
        normal_response, error_code = self.query_no_assert(q)

        assert error_code == 404
        assert normal_response['error']['message'] == 'isochrone works only for clockwise request'

    def test_graphical_isochrons_no_arguments(self):
        q = "v1/coverage/main_routing_test/isochrons"
        normal_response, error_code = self.query_no_assert(q)
        assert error_code == 400
        assert normal_response['message'] == 'you should provide a \'from\' or a \'to\' argument'

    def test_graphical_isochrons_no_region(self):
        q = "v1/coverage/isochrons"
        normal_response, error_code = self.query_no_assert(q)
        assert error_code == 404
        assert normal_response['error']['message'] == 'The region isochrons doesn\'t exists'

    def testgrapical_isochrons_invald_duration(self):
        q = "v1/coverage/main_routing_test/isochrons?datetime={}&from={}&duration={}"
        q = q.format('20120614T080000', s_coord, '-3600')
        normal_response, error_code = self.query_no_assert(q)
        assert error_code == 400
        assert normal_response['message'] == 'Unable to evaluate, invalid positive int'
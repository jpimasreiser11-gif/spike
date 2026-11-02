"""Spike Geo (A16): GeoJSON and CSV in, a deterministic SVG map out, distances and areas on a sphere, a choropleth.
Everything is offline: the checks are closed-form values on the sphere the module uses, and a few published figures
within a stated tolerance (a sphere is not WGS 84: distances differ by up to about 0.5 %, areas by about 1 %)."""

import json
import math
import re

import pytest

from spike.geo import data as geodata
from spike.geo import measure
from spike.geo.project import Equirectangular
from spike.geo.render import choropleth_classes, render_map
from spike.geo.tools import GeoMap, GeoMeasure
from spike.tools.base import PermissionBroker
from spike.tools.builtin import Workspace

R_KM = measure.EARTH_RADIUS_M / 1000


# ---------------------------------------------------------------- distance (haversine)
def test_haversine_matches_closed_forms_on_the_sphere():
    assert measure.EARTH_RADIUS_M == 6_371_008.8  # the IUGG mean radius, stated in the docs
    assert measure.haversine((0, 0), (0, 0)) == 0
    quarter = math.pi * measure.EARTH_RADIUS_M / 2
    assert measure.haversine((0, 0), (90, 0)) == pytest.approx(quarter, rel=1e-12)  # equator to the pole
    assert measure.haversine((0, 0), (0, 90)) == pytest.approx(quarter, rel=1e-12)
    assert measure.haversine((0, 10), (0, 11)) == pytest.approx(math.radians(1) * measure.EARTH_RADIUS_M, rel=1e-12)
    assert measure.haversine((90, 0), (-90, 123)) == pytest.approx(math.pi * measure.EARTH_RADIUS_M, rel=1e-12)
    assert measure.haversine((12.5, 40.2), (-33, 151)) == measure.haversine((-33, 151), (12.5, 40.2))
    # across the antimeridian the short way is 2 degrees, not 358
    assert measure.haversine((0, 179), (0, -179)) == pytest.approx(math.radians(2) * measure.EARTH_RADIUS_M, rel=1e-12)


@pytest.mark.parametrize("a,b,published_km", [
    ((51.5074, -0.1278), (48.8566, 2.3522), 343.5),  # London - Paris, city centres: published as about 343-344 km
    ((40.7128, -74.0060), (51.5074, -0.1278), 5570),  # New York - London: published as about 5,570 km
    ((40.4168, -3.7038), (41.3851, 2.1734), 505),  # Madrid - Barcelona: published as about 505 km
])
def test_haversine_agrees_with_published_city_distances_within_half_a_percent(a, b, published_km):
    # the published figures are rounded and use slightly different city points; 0.5 % also covers sphere vs ellipsoid
    assert measure.haversine(a, b) / 1000 == pytest.approx(published_km, rel=0.005)


def test_path_length_sums_the_legs():
    legs = [(0, 0), (0, 1), (1, 1)]
    assert measure.path_length(legs) == pytest.approx(2 * math.radians(1) * measure.EARTH_RADIUS_M, rel=1e-4)
    assert measure.path_length([(5, 5)]) == 0


# ---------------------------------------------------------------- area (spherical polygon)
def box(lat1, lat2, lon1, lon2):
    return [(lat1, lon1), (lat1, lon2), (lat2, lon2), (lat2, lon1), (lat1, lon1)]


def test_area_of_an_octant_is_an_eighth_of_the_sphere():
    octant = [(0, 0), (90, 0), (0, 90)]
    expected = 4 * math.pi * measure.EARTH_RADIUS_M**2 / 8
    assert measure.ring_area(octant) == pytest.approx(expected, rel=1e-9)
    assert measure.ring_area(octant[::-1]) == pytest.approx(expected, rel=1e-9)  # orientation does not matter
    assert measure.ring_area(octant + [octant[0]]) == pytest.approx(expected, rel=1e-9)  # closed or not


def test_area_of_a_lat_lon_box_is_r_squared_times_dlon_times_dsin():
    for lat1, lat2, lon1, lon2 in ((0, 1, 0, 1), (41, 45, -111.05, -104.05), (-30, -20, 100, 110)):
        expected = measure.EARTH_RADIUS_M**2 * math.radians(lon2 - lon1) * (
            math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)))
        # the box's top and bottom edges are parallels; the module draws great circles between the corners
        assert measure.ring_area(box(lat1, lat2, lon1, lon2)) == pytest.approx(expected, rel=2e-3)
    one_degree = measure.ring_area(box(0, 1, 0, 1)) / 1e6
    assert one_degree == pytest.approx(12_364, rel=1e-3)  # the 1 degree cell at the equator, about 12,364 km2


def test_area_of_wyoming_agrees_with_the_published_figure_within_half_a_percent():
    wyoming = box(41, 45, -111.05, -104.05)  # the state is bounded by two parallels and two meridians
    assert measure.ring_area(wyoming) / 1e6 == pytest.approx(253_335, rel=0.005)  # 97,813 sq mi


def test_polygon_area_subtracts_holes_and_the_far_side_is_not_used():
    outer, hole = box(0, 10, 0, 10), box(2, 4, 2, 4)
    assert measure.polygon_area([outer, hole]) == pytest.approx(
        measure.ring_area(outer) - measure.ring_area(hole), rel=1e-12)
    assert measure.polygon_area([outer]) == measure.ring_area(outer)
    # a ring wound the other way round is the same polygon, never the other side of the globe
    assert measure.ring_area(outer[::-1]) == pytest.approx(measure.ring_area(outer), rel=1e-12)
    assert measure.ring_area([(0, 0), (1, 1)]) == 0  # fewer than three corners: nothing to measure


def test_perimeter_closes_the_ring():
    ring = box(0, 1, 0, 1)
    assert measure.perimeter(ring) == pytest.approx(4 * math.radians(1) * measure.EARTH_RADIUS_M, rel=1e-4)


# ---------------------------------------------------------------- reading GeoJSON
FEATURES = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"name": "Madrid", "pop": 3.3},
     "geometry": {"type": "Point", "coordinates": [-3.7038, 40.4168]}},
    {"type": "Feature", "properties": {"name": "AVE"},
     "geometry": {"type": "LineString", "coordinates": [[-3.7038, 40.4168], [2.1734, 41.3851]]}},
    {"type": "Feature", "properties": {"name": "Zona", "valor": 7},
     "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}},
    {"type": "Feature", "properties": {"name": "Islas"},
     "geometry": {"type": "MultiPolygon", "coordinates": [[[[5, 5], [5, 6], [6, 6], [6, 5], [5, 5]]],
                                                           [[[8, 8], [8, 9], [9, 9], [9, 8], [8, 8]]]]}},
    {"type": "Feature", "properties": {"name": "Paradas"},
     "geometry": {"type": "MultiPoint", "coordinates": [[1, 2], [3, 4]]}},
    {"type": "Feature", "properties": {"name": "Rutas"},
     "geometry": {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]], [[2, 2], [3, 3]]]}},
    {"type": "Feature", "properties": {"name": "Sin forma"}, "geometry": None},
]}


def test_geojson_geometries_are_read_as_lat_lon_in_the_documented_order():
    dataset = geodata.parse_geojson(json.dumps(FEATURES))
    names = [f.props.get("name") for f in dataset.features]
    assert names == ["Madrid", "AVE", "Zona", "Islas", "Paradas", "Rutas"]  # the null geometry is skipped, and said
    madrid, ave, zona, islas, paradas, rutas = dataset.features
    assert madrid.points == [(40.4168, -3.7038)]  # GeoJSON is [lon, lat]; the module keeps (lat, lon)
    assert ave.lines == [[(40.4168, -3.7038), (41.3851, 2.1734)]]
    assert len(zona.polygons) == 1 and len(zona.polygons[0]) == 1
    assert len(islas.polygons) == 2 and len(paradas.points) == 2 and len(rutas.lines) == 2
    assert dataset.skipped == ["feature 7: no geometry"]


def test_geojson_accepts_a_bare_geometry_a_single_feature_and_a_geometry_collection():
    point = geodata.parse_geojson('{"type": "Point", "coordinates": [10, 20, 300]}')  # a height is ignored
    assert point.features[0].points == [(20, 10)]
    one = geodata.parse_geojson(json.dumps(FEATURES["features"][0]))
    assert one.features[0].props["name"] == "Madrid"
    collection = geodata.parse_geojson(json.dumps({"type": "GeometryCollection", "geometries": [
        {"type": "Point", "coordinates": [1, 2]}, {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}]}))
    assert collection.features[0].points == [(2, 1)] and len(collection.features[0].lines) == 1


@pytest.mark.parametrize("text,fragment", [
    ("not json", "not valid JSON"),
    ('{"type": "Feature", "geometry": {"type": "Circle", "coordinates": [1, 2]}}', "Circle"),
    ('{"type": "Point", "coordinates": [10, 95]}', "latitude"),
    ('{"type": "Point", "coordinates": [200, 10]}', "longitude"),
    ('{"type": "Point", "coordinates": [500000, 4500000]}', "projected"),
    ('{"type": "Point", "coordinates": ["a", 1]}', "number"),
    ('{"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]}', "at least 4"),
    ('{"type": "Topology"}', "GeoJSON"),
    ('[1, 2]', "GeoJSON"),
])
def test_bad_geojson_is_refused_with_a_reason(text, fragment):
    with pytest.raises(geodata.GeoError) as err:
        geodata.parse_geojson(text)
    assert fragment in str(err.value)


def test_size_limits_say_what_was_left_out(monkeypatch):
    monkeypatch.setattr(geodata, "MAX_FEATURES", 3)
    many = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"i": i}, "geometry": {"type": "Point", "coordinates": [i, i]}}
        for i in range(10)]}
    dataset = geodata.parse_geojson(json.dumps(many))
    assert len(dataset.features) == 3 and dataset.truncated == {"features": 10}
    monkeypatch.setattr(geodata, "MAX_VERTICES", 25)
    line = {"type": "LineString", "coordinates": [[i, 0] for i in range(10)]}
    dataset = geodata.parse_geojson(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": line}] * 3}))
    assert dataset.truncated == {"vertices": 30, "features": 3} and len(dataset.features) == 2
    with pytest.raises(geodata.GeoError):  # one feature alone over the budget: nothing useful is left
        monkeypatch.setattr(geodata, "MAX_VERTICES", 5)
        geodata.parse_geojson(json.dumps({"type": "Feature", "properties": {}, "geometry": line}))


# ---------------------------------------------------------------- reading CSV
def test_csv_latitude_and_longitude_columns_are_detected_in_spanish_and_english():
    es = "ciudad;Latitud;Longitud;habitantes\nMadrid;40,4168;-3,7038;3300000\nBarcelona;41,3851;2,1734;1600000\n"
    dataset = geodata.parse_csv(es)
    assert [f.points for f in dataset.features] == [[(40.4168, -3.7038)], [(41.3851, 2.1734)]]
    assert dataset.features[0].props == {"ciudad": "Madrid", "habitantes": 3300000.0}
    en = "﻿name,lat,lng,pop\nOslo,59.91,10.75,700000\n"  # a BOM from a spreadsheet export
    assert geodata.parse_csv(en).features[0].points == [(59.91, 10.75)]
    for header in ("LATITUDE,LONGITUDE", "y,x", "Lat,Lon", "latitud,longitud", "lat,long"):
        text = f"{header}\n10,20\n"
        assert geodata.parse_csv(text).features[0].points == [(10, 20)], header
    tabs = "name\tlat\tlon\nA\t1\t2\n"
    assert geodata.parse_csv(tabs).features[0].points == [(1, 2)]


def test_csv_column_override_bad_rows_and_missing_columns():
    text = "id,a,b\n1,10,20\n2,abc,5\n3,100,5\n4,,\n"
    dataset = geodata.parse_csv(text, lat_column="a", lon_column="b")
    assert [f.points for f in dataset.features] == [[(10, 20)]]
    assert len(dataset.skipped) == 3 and "row 3" in dataset.skipped[0]  # the header is row 1
    with pytest.raises(geodata.GeoError) as err:
        geodata.parse_csv("id,value\n1,2\n")
    assert "latitude" in str(err.value) and "id, value" in str(err.value)
    with pytest.raises(geodata.GeoError):
        geodata.parse_csv("lat,lon\n")
    with pytest.raises(geodata.GeoError):
        geodata.parse_csv("lat,lon\n1,2\n", lat_column="nope")


def test_load_uses_the_extension_and_the_content(tmp_path):
    (tmp_path / "a.geojson").write_text(json.dumps(FEATURES), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(FEATURES), encoding="utf-8")
    (tmp_path / "c.csv").write_text("lat,lon\n1,2\n", encoding="utf-8")
    (tmp_path / "d.txt").write_text("lat,lon\n1,2\n", encoding="utf-8")
    assert len(geodata.load(tmp_path / "a.geojson").features) == 6
    assert len(geodata.load(tmp_path / "b.json").features) == 6
    assert len(geodata.load(tmp_path / "c.csv").features) == 1
    with pytest.raises(geodata.GeoError):
        geodata.load(tmp_path / "d.txt")
    with pytest.raises(geodata.GeoError):
        geodata.load(tmp_path / "missing.geojson")
    (tmp_path / "big.csv").write_text("lat,lon\n" + "1,2\n" * 10, encoding="utf-8")
    geodata.MAX_BYTES, old = 20, geodata.MAX_BYTES
    try:
        with pytest.raises(geodata.GeoError):
            geodata.load(tmp_path / "big.csv")
    finally:
        geodata.MAX_BYTES = old


# ---------------------------------------------------------------- the map
def test_the_projection_keeps_the_scale_true_on_its_standard_parallel():
    proj = Equirectangular.fit([(40, -4), (42, 3)])
    assert proj.lat_ts == pytest.approx(41)
    (x0, y0), (x1, y1) = proj.xy(41, 0), proj.xy(41, 1)
    assert (x1 - x0) == pytest.approx(math.radians(1) * measure.EARTH_RADIUS_M * math.cos(math.radians(41)))
    assert proj.xy(42, 0)[1] - proj.xy(41, 0)[1] == pytest.approx(math.radians(1) * measure.EARTH_RADIUS_M)
    assert y1 == y0  # y follows latitude only; north is up in the picture (the page flips it)


def test_data_across_the_antimeridian_is_centred_on_it():
    proj = Equirectangular.fit([(-17, 178), (-18, -179), (-16, 179.5)])
    assert abs(abs(proj.lon0) - 180) < 3
    xs = [proj.xy(lat, lon)[0] for lat, lon in [(-17, 178), (-18, -179), (-16, 179.5)]]
    assert max(xs) - min(xs) < 4 * math.radians(1) * measure.EARTH_RADIUS_M  # about 3 degrees, not 357


def dataset_of(features):
    return geodata.parse_geojson(json.dumps({"type": "FeatureCollection", "features": features}))


def test_the_map_is_deterministic_and_carries_a_scale_note():
    dataset = geodata.parse_geojson(json.dumps(FEATURES))
    first = render_map(dataset, title="Prueba", lang="es")
    assert first == render_map(dataset, title="Prueba", lang="es")
    assert first.startswith("<svg") and first.rstrip().endswith("</svg>")
    assert "Proyección equirrectangular" in first and "km" in first
    assert "Equirectangular projection" in render_map(dataset, lang="en")
    assert first.count("<circle") >= 3 and "<path" in first
    assert "prefers-color-scheme:dark" in first.replace(" ", "")  # readable in light and dark
    assert "<script" not in first and "http://" not in first.replace("http://www.w3.org/2000/svg", "")
    from xml.dom import minidom

    minidom.parseString(first)  # well-formed XML


def test_names_in_the_data_cannot_break_out_of_the_picture():
    hostile = '<script>alert(1)</script>"&'
    dataset = dataset_of([{"type": "Feature", "properties": {"name": hostile},
                           "geometry": {"type": "Point", "coordinates": [1, 2]}}])
    svg = render_map(dataset, title=hostile, labels="name")
    assert "<script" not in svg and "&lt;script&gt;" in svg
    from xml.dom import minidom

    minidom.parseString(svg)


def test_a_single_point_and_an_empty_dataset_still_draw():
    one = dataset_of([{"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [1, 2]}}])
    assert render_map(one).startswith("<svg")
    empty = geodata.Dataset(features=[], source="x")
    assert "<svg" in render_map(empty)


def polygons_with(values):
    return dataset_of([
        {"type": "Feature", "properties": {"name": f"z{i}", "valor": v},
         "geometry": {"type": "Polygon", "coordinates": [[[i, 0], [i, 1], [i + 1, 1], [i + 1, 0], [i, 0]]]}}
        for i, v in enumerate(values)])


def test_choropleth_classes_are_equal_intervals_with_a_class_for_missing_values():
    dataset = polygons_with([0, 10, 20, 30, 40, None, "n/a"])
    classes = choropleth_classes(dataset, "valor", bins=4)
    assert classes.breaks == [0, 10, 20, 30, 40]
    assert [classes.bin_of(v) for v in (0, 9.99, 10, 25, 40)] == [0, 0, 1, 2, 3]  # the top value is in the last class
    assert classes.counts == [1, 1, 1, 2] and classes.missing == 2
    same = choropleth_classes(polygons_with([5, 5, 5]), "valor", bins=5)
    assert same.breaks == [5, 5] and same.counts == [3]


def test_choropleth_draws_a_legend_and_one_class_per_polygon():
    dataset = polygons_with([1, 2, 3, 4, 5, None])
    svg = render_map(dataset, value="valor", bins=5, lang="en")
    assert svg.count('class="poly c') == 5 and 'class="poly nodata"' in svg
    assert "valor" in svg and "No data" in svg and "1 – 1.8" in svg
    es = render_map(dataset, value="valor", bins=5, lang="es")
    assert "Sin datos" in es and "1 – 1,8" in es  # decimal comma in Spanish
    assert svg == render_map(dataset, value="valor", bins=5, lang="en")
    # light and dark ramps are both defined, from the lowest to the highest class
    assert svg.count("--c0:") == 2 and svg.count("--c4:") == 2


def test_a_choropleth_needs_polygons_and_a_numeric_property():
    points = geodata.parse_csv("lat,lon,n\n1,2,3\n")
    with pytest.raises(geodata.GeoError) as err:
        render_map(points, value="n")
    assert "polygon" in str(err.value)
    with pytest.raises(geodata.GeoError) as err:
        render_map(polygons_with([1, 2]), value="nombre")
    assert "numeric property" in str(err.value) and "valor" in str(err.value)


# ---------------------------------------------------------------- the tools
@pytest.fixture
def ws(tmp_path):
    (tmp_path / "ciudades.geojson").write_text(json.dumps(FEATURES), encoding="utf-8")
    (tmp_path / "ciudades.csv").write_text("nombre;latitud;longitud\nMadrid;40,4168;-3,7038\n"
                                           "Barcelona;41,3851;2,1734\n", encoding="utf-8")
    (tmp_path / "zonas.geojson").write_text(json.dumps(polygons_features([3, 6, 9])), encoding="utf-8")
    return Workspace(tmp_path)


def polygons_features(values):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": f"z{i}", "valor": v},
         "geometry": {"type": "Polygon", "coordinates": [[[i, 0], [i, 1], [i + 1, 1], [i + 1, 0], [i, 0]]]}}
        for i, v in enumerate(values)]}


async def test_geo_map_reads_a_workspace_file_and_hands_the_picture_to_the_app(ws):
    result = await GeoMap(ws).run({"path": "ciudades.csv", "label": "nombre", "lang": "en", "title": "Cities"})
    assert result.ok and result.content and result.private  # the user's data: kept from providers not allowed it
    ui = result.data["ui"]
    assert ui["kind"] == "geo_map" and ui["title"] == "Cities" and ui["svg"].startswith("<svg")
    assert ui["stats"]["features"] == 2 and ui["stats"]["points"] == 2
    assert ui["projection"] == "equirectangular" and ui["lat_ts"] == pytest.approx(40.9, abs=0.01)
    assert ui["radius_km"] == pytest.approx(6371.0088)
    assert "<svg" not in result.content  # the model reads numbers, not markup
    assert [r["name"] for r in ui["rows"]] == ["Madrid", "Barcelona"]


async def test_geo_map_choropleth_reports_the_classes(ws):
    result = await GeoMap(ws).run({"path": "zonas.geojson", "value": "valor", "bins": 3, "lang": "en"})
    ui = result.data["ui"]
    assert [leg["count"] for leg in ui["legend"]] == [1, 1, 1] and ui["value"] == "valor"
    assert ui["rows"][0]["area_km2"] == pytest.approx(12_364, rel=5e-3)
    assert "valor" in result.content and "equal-interval" in result.content


async def test_geo_map_errors_are_results_not_crashes(ws):
    tool = GeoMap(ws)
    for args in ({"path": "../outside.geojson"}, {"path": "nope.geojson"}, {"path": "ciudades.csv", "value": "x"},
                 {"path": "zonas.geojson", "value": "name"}, {"path": "zonas.geojson", "bins": 99},
                 {"path": "ciudades.csv", "lang": "fr"}, {}):
        result = await tool.run(args)
        assert not result.ok and result.content.startswith("error:"), args


async def test_geo_map_and_measure_read_without_asking(ws):
    for tool in (GeoMap(ws), GeoMeasure(ws)):
        assert tool.risk == "read" and tool.default_policy == "allow"
        policy, _ = PermissionBroker({}).policy_for_call(tool, {"path": "ciudades.csv"})
        assert policy == "allow"


async def test_geo_measure_between_two_points_and_over_a_file(ws):
    tool = GeoMeasure(ws)
    result = await tool.run({"a": [40.4168, -3.7038], "b": [41.3851, 2.1734]})
    assert result.ok and re.search(r"50\d(\.\d+)? km", result.content)
    assert "6371.0088" in result.content and "0.5 %" in result.content  # the radius and the accuracy limit
    result = await tool.run({"path": "ciudades.geojson"})
    assert result.ok and "AVE" in result.content and "Zona" in result.content
    assert "length" in result.content and "area" in result.content
    for bad in ({}, {"a": [1, 2]}, {"a": [100, 2], "b": [1, 2]}, {"a": "x", "b": [1, 2]}, {"path": "nope.csv"}):
        failed = await tool.run(bad)
        assert not failed.ok and failed.content.startswith("error:"), bad

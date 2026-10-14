import asyncio

import httpx
import pytest
import respx

from app.agents.researcher import NoSource, WikipediaClient, name_similarity, research_landmark, split_facts
from tests.agent_fakes import landmark

API = "https://en.wikipedia.org/w/api.php"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"

LM = landmark("lm1", name="Krannert Art Museum")


def geo(*hits):
    return {"query": {"geosearch": [dict(pageid=i, title=t, lat=lat, lon=lon) for i, (t, lat, lon) in enumerate(hits)]}}


def summary(title, extract, type_="standard"):
    return {
        "type": type_,
        "title": title,
        "extract": extract,
        "content_urls": {"desktop": {"page": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"}},
    }


EXTRACT = (
    "Krannert Art Museum is an art museum in Champaign, Illinois. It is on the U.S. campus of the university. "
    "It opened in 1961. The collection holds over 10,000 works."
)


def run(lm=LM):
    async def go():
        async with httpx.AsyncClient() as http:
            return await research_landmark(WikipediaClient(http, user_agent="DriverTour-test"), lm)

    return asyncio.run(go())


@respx.mock
def test_match_by_coordinates_and_name():
    respx.get(API).respond(json=geo(("Some Street", LM.lat, LM.lng), ("Krannert Art Museum", LM.lat + 0.0005, LM.lng)))
    route = respx.get(f"{SUMMARY}Krannert_Art_Museum").respond(json=summary("Krannert Art Museum", EXTRACT))

    research, detail = run()

    assert research.title == "Krannert Art Museum"
    assert research.source_url == "https://en.wikipedia.org/wiki/Krannert_Art_Museum"
    assert research.facts[1] == "It is on the U.S. campus of the university."
    assert len(research.facts) == 4
    assert detail["name_similarity"] >= 0.9
    assert route.calls.last.request.headers["User-Agent"] == "DriverTour-test"


@respx.mock
def test_no_name_match_is_no_source():
    respx.get(API).respond(json=geo(("Starbucks", LM.lat, LM.lng)))
    with pytest.raises(NoSource, match="no_name_match"):
        run()


@respx.mock
def test_right_name_but_too_far_is_no_source():
    respx.get(API).respond(json=geo(("Krannert Art Museum", LM.lat + 0.004, LM.lng)))  # 约 440 m
    with pytest.raises(NoSource, match="no_name_match"):
        run()


@respx.mock
def test_disambiguation_page_is_no_source():
    respx.get(API).respond(json=geo(("Krannert Art Museum", LM.lat, LM.lng)))
    respx.get(f"{SUMMARY}Krannert_Art_Museum").respond(json=summary("Krannert Art Museum", EXTRACT, "disambiguation"))
    with pytest.raises(NoSource, match="not_standard_page"):
        run()


@respx.mock
def test_too_few_facts_is_no_source():
    respx.get(API).respond(json=geo(("Krannert Art Museum", LM.lat, LM.lng)))
    respx.get(f"{SUMMARY}Krannert_Art_Museum").respond(json=summary("Krannert Art Museum", "A museum in Illinois."))
    with pytest.raises(NoSource, match="too_few_facts"):
        run()


@respx.mock
def test_http_error_is_no_source():
    respx.get(API).respond(status_code=503)
    with pytest.raises(NoSource, match="http_error"):
        run()


@pytest.mark.parametrize(
    "a, b, ok",
    [
        ("Champaign County Courthouse", "Champaign County Courthouse (Illinois)", True),
        ("Krannert Center", "Krannert Center for the Performing Arts", True),
        ("Starbucks", "Starbucks Reserve Roastery", False),  # 单个词不算包含
        ("West Side Park", "Urbana Free Library", False),
    ],
)
def test_name_similarity(a, b, ok):
    assert (name_similarity(a, b) >= 0.6) is ok


def test_split_facts_keeps_abbreviations():
    assert split_facts("It is on St. Mary's Road. It opened in 1961.") == ["It is on St. Mary's Road.", "It opened in 1961."]

"""Starter catalog of planetary image collections; users can add any mission.

Portal references checked on 2026-09-07. A catalog entry is not a claim of
current operational status or of automatic-download support.
"""

import re
import unicodedata

PDS = "https://pds.nasa.gov/datasearch/data-search/"
PSA = "https://archives.esac.esa.int/psa/"
ISRO = "https://pradan.issdc.gov.in/"
DARTS = "https://darts.isas.jaxa.jp/"


def entry(body, name, grouping="date", archive_url=PDS, identifier=None, backend="local"):
    slug = unicodedata.normalize("NFKD", body + "_" + name).encode("ascii", "ignore").decode()
    return {"id": identifier or re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_"), "body": body,
            "name": name, "grouping": grouping, "archive_url": archive_url, "backend": backend}


MISSION_CATALOG = [
    entry("Marte", "Curiosity", "sol", "https://mars.nasa.gov/msl/multimedia/raw-images/", "curiosity", "curiosity"),
    entry("Marte", "Perseverance", "sol", "https://mars.nasa.gov/mars2020/multimedia/raw-images/", "perseverance"),
    *[entry("Marte", name, "sol") for name in ("Spirit", "Opportunity", "Pathfinder - Sojourner", "Phoenix", "InSight", "Viking 1", "Viking 2")],
    *[entry("Marte", name, "orbit") for name in ("Mars Reconnaissance Orbiter", "Mars Odyssey", "Mars Global Surveyor", "MAVEN", "Mariner 9")],
    entry("Marte", "Mars Express", "orbit", "https://www.cosmos.esa.int/web/psa/mars-express"),
    entry("Marte", "ExoMars Trace Gas Orbiter", "orbit", PSA),
    entry("Marte", "Mars Orbiter Mission", "orbit", "https://mrbrowse.issdc.gov.in/MOMLTA/"),
    entry("Marte", "Tianwen-1 - Zhurong", "sol", "https://www.cnsa.gov.cn/english/"),
    entry("Marte", "Hope", "orbit", "https://www.emiratesmarsmission.ae/"),
    entry("Lua", "Lunar Reconnaissance Orbiter", "orbit", "https://wms.lroc.asu.edu/lroc/thumbnails"),
    *[entry("Lua", f"Apollo {number}") for number in (8, 10, 11, 12, 13, 14, 15, 16, 17)],
    *[entry("Lua", name, "orbit") for name in ("Clementine", "Lunar Orbiter 1", "Lunar Orbiter 2", "Lunar Orbiter 3", "Lunar Orbiter 4", "Lunar Orbiter 5")],
    *[entry("Lua", f"Surveyor {number}") for number in (1, 3, 5, 6, 7)],
    entry("Lua", "Kaguya - SELENE", "orbit", "https://legacy.darts.isas.jaxa.jp/app/pdap/selene/"),
    entry("Lua", "SLIM", "date", "https://www.isas.jaxa.jp/home/slim/SLIM/index.html"),
    entry("Lua", "SMART-1", "orbit", PSA),
    *[entry("Lua", name, "date", ISRO) for name in ("Chandrayaan-1", "Chandrayaan-2", "Chandrayaan-3")],
    *[entry("Lua", f"Chang'e-{number}", "date", "https://www.cnsa.gov.cn/english/") for number in range(1, 7)],
    entry("Lua", "Danuri - KPLO", "orbit", "https://www.kari.re.kr/eng/"),
    entry("Lua", "Artemis I - Orion", "date", "https://www.nasa.gov/artemis/"),
    entry("Lua", "Artemis II - Orion", "date", "https://www.nasa.gov/artemis/"),
    entry("Lua", "Blue Ghost Mission 1", "date", "https://fireflyspace.com/missions/blue-ghost-mission-1/"),
    entry("Lua", "IM-1 - Odysseus", "date", "https://www.intuitivemachines.com/"),
    entry("Lua", "IM-2 - Athena", "date", "https://www.intuitivemachines.com/"),
    entry("Mercúrio", "BepiColombo", "date", "https://www.cosmos.esa.int/web/bepicolombo/mainpage"),
    entry("Mercúrio", "MESSENGER", "orbit"),
    entry("Mercúrio", "Mariner 10"),
    entry("Vênus", "Akatsuki", "orbit", "https://darts.isas.jaxa.jp/en/missions/akatsuki"),
    entry("Vênus", "Venus Express", "orbit", PSA),
    entry("Vênus", "Magellan", "orbit"),
    entry("Vênus", "Mariner 10"),
    entry("Júpiter", "Juno", "orbit", "https://www.missionjuno.swri.edu/junocam/processing"),
    entry("Júpiter", "Galileo", "orbit"),
    entry("Júpiter", "Juice", "date", "https://www.cosmos.esa.int/web/juice"),
    entry("Júpiter", "Europa Clipper", "date", "https://science.nasa.gov/mission/europa-clipper/"),
    entry("Saturno", "Cassini - Huygens", "orbit"),
    *[entry(body, name) for body, name in (("Júpiter", "Voyager 1"), ("Júpiter", "Voyager 2"), ("Saturno", "Voyager 1"), ("Saturno", "Voyager 2"), ("Urano", "Voyager 2"), ("Netuno", "Voyager 2"))],
    entry("Plutão", "New Horizons", "date", "https://pluto.jhuapl.edu/soc/Pluto-Encounter/index.php"),
    *[entry("Asteroides", name) for name in ("Dawn", "NEAR Shoemaker", "OSIRIS-REx", "DART", "Lucy", "Psyche")],
    *[entry("Asteroides", name, "date", DARTS) for name in ("Hayabusa", "Hayabusa2")],
    entry("Cometas", "Rosetta", "date", PSA),
    *[entry("Cometas", name) for name in ("Deep Impact - EPOXI", "Stardust")],
    entry("Outros", "Coleção local", "folders", "", "local"),
]

# Only tested connectors are enabled. Registration alone never enables downloads.
DOWNLOAD_BACKENDS = {
    "perseverance": "perseverance",
    "marte_mars_reconnaissance_orbiter": "hirise",
    "marte_mars_express": "esa_hrsc",
    "lua_lunar_reconnaissance_orbiter": "lroc",
    "lua_kaguya_selene": "kaguya",
}
for profile in MISSION_CATALOG:
    if profile["id"] in DOWNLOAD_BACKENDS:
        profile["backend"] = DOWNLOAD_BACKENDS[profile["id"]]
        if profile["backend"] != "perseverance":
            profile["grouping"] = "observation"

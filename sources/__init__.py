"""Source registry. Add future missions here without changing drawing tools."""

from .curiosity import CuriositySource
from .local import LocalImageSource
from .perseverance import PerseveranceSource
from .archives import HiriseSource, LrocSource, EsaHrscSource, KaguyaSource

SOURCES = {source.id: source for source in (CuriositySource, LocalImageSource, PerseveranceSource, HiriseSource, LrocSource, EsaHrscSource, KaguyaSource)}


def get_source(source_id="curiosity"):
    return SOURCES.get(source_id, CuriositySource)()

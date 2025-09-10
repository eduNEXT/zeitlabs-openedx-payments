"""Processors registry"""
from typing import Dict, Type

import pkg_resources

from .base import BaseProcessor

PROCESSORS: Dict[str, Type[BaseProcessor]] = {}


def load_entrypoint_processors() -> None:
    """
    Discover and register processors defined via entry_points.
    """
    for ep in pkg_resources.iter_entry_points(group='zeitlabs_payments.v1'):
        cls = ep.load()
        slug = getattr(cls, 'SLUG', None)
        if not slug:
            raise ValueError(f"Processor {cls.__name__} from entry point '{ep.name}' must define a SLUG")
        if slug in PROCESSORS:
            raise ValueError(f"Duplicate processor slug '{slug}' found in {cls.__name__}")
        PROCESSORS[slug] = cls


def get_processor(slug: str) -> BaseProcessor:
    """
    Return an *instance* of the processor that matches `slug`
    or raise ValueError if unknown.
    """
    try:
        return PROCESSORS[slug]()
    except KeyError as exc:
        raise ValueError(f'Unsupported payment provider: {slug}') from exc

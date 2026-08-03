"""Streamlit session helpers for shared DB/service instances."""
from __future__ import annotations

import streamlit as st

from src.services.objects_service import ObjectsService
from src.services.parking_db import ParkingDatabase


def get_parking_db() -> ParkingDatabase:
    if "parking_db" not in st.session_state:
        st.session_state.parking_db = ParkingDatabase()
    return st.session_state.parking_db


def get_objects_service(service, *, cache_key: str = "objects_service") -> ObjectsService:
    """Build/cache ObjectsService from CompaniesService or return ObjectsService as-is."""
    if isinstance(service, ObjectsService):
        return service
    tender_db = getattr(service, "tender_db", None)
    repo = getattr(service, "repo", None)
    if not tender_db and repo is not None and getattr(repo, "tender_repo", None):
        tender_db = repo.tender_repo.tender_db
    if cache_key not in st.session_state:
        st.session_state[cache_key] = ObjectsService(
            radar_db=getattr(service, "radar_db", None),
            tender_db=tender_db,
            crm_db=getattr(service, "crm_db", None),
        )
    return st.session_state[cache_key]

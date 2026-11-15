"""Sous-ensemble validé du format JSON (inspiré d'OCDS) des données ouvertes du SEAO.

Validation stricte des champs dont RadarAO dépend; les autres champs sont tolérés (le format
peut évoluer) et conservés tels quels dans `raw`.
"""

from datetime import datetime
from typing import Any

from dateutil import parser as dateparser
from pydantic import BaseModel, ConfigDict, Field, field_validator

from worker.ingestion.regions import region_from_postal_code

_QC_TZ_DEFAULT = "-05:00"


def parse_seao_date(value: str | None) -> datetime | None:
    """Accepte « aaaa-mm-jj hh:MM » (spécification 2021) et l'ISO 8601 observé dans les fichiers."""
    if not value:
        return None
    try:
        dt = dateparser.isoparse(value) if "T" in value else dateparser.parse(value)
    except (ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        dt = dateparser.isoparse(dt.strftime("%Y-%m-%dT%H:%M:%S") + _QC_TZ_DEFAULT)
    return dt


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class Address(_Loose):
    locality: str | None = None
    region: str | None = None
    postalCode: str | None = None
    countryName: str | None = None


class PartyIn(_Loose):
    id: str
    name: str
    address: Address | None = None
    roles: list[str] = Field(default_factory=list)
    details: dict[str, Any] | None = None

    @property
    def neq(self) -> str | None:
        return (self.details or {}).get("neq")

    @property
    def region_code(self) -> str | None:
        return region_from_postal_code(self.address.postalCode if self.address else None)


class Classification(_Loose):
    scheme: str | None = None
    id: str
    description: str | None = None


class Item(_Loose):
    id: str | None = None
    description: str | None = None
    classification: Classification | None = None
    additionalClassifications: list[Classification] = Field(default_factory=list)


class Period(_Loose):
    startDate: str | None = None
    endDate: str | None = None


class Value(_Loose):
    amount: float | None = None
    currency: str | None = None


class OrgRef(_Loose):
    id: str | None = None
    name: str | None = None


class DocumentRef(_Loose):
    url: str | None = None


class TenderIn(_Loose):
    id: str | None = None
    title: str = ""
    status: str
    procuringEntity: OrgRef | None = None
    items: list[Item] = Field(default_factory=list)
    procurementMethod: str | None = None
    procurementMethodDetails: str | None = None
    mainProcurementCategory: str | None = None
    tenderPeriod: Period | None = None
    numberOfTenderers: int | None = None
    documents: list[DocumentRef] = Field(default_factory=list)
    value: Value | None = None
    minValue: Value | None = None


class AwardIn(_Loose):
    id: str
    date: str | None = None
    value: Value | None = None
    suppliers: list[OrgRef] = Field(default_factory=list)


class ContractIn(_Loose):
    id: str
    awardID: str | None = None
    value: Value | None = None
    dateSigned: str | None = None


class ReleaseIn(_Loose):
    ocid: str
    id: str
    date: str | None = None
    tag: list[str]
    parties: list[PartyIn] = Field(default_factory=list)
    buyer: OrgRef | None = None
    tender: TenderIn | None = None
    awards: list[AwardIn] = Field(default_factory=list)
    contracts: list[ContractIn] = Field(default_factory=list)

    @field_validator("tag")
    @classmethod
    def _non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("tag vide")
        return v

    @property
    def sort_key(self) -> str:
        # L'identifiant de publication (aaaammjjhhmmss) reflète l'ordre de publication; `date`
        # est parfois la date d'origine de l'avis (observé sur les tenderUpdate).
        return self.id.rjust(20, "0")

    def buyer_party(self) -> PartyIn | None:
        buyer_id = (self.tender.procuringEntity.id if self.tender and self.tender.procuringEntity else None) or (
            self.buyer.id if self.buyer else None
        )
        for p in self.parties:
            if p.id == buyer_id or (buyer_id is None and "buyer" in p.roles):
                return p
        return None

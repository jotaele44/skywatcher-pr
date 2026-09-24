"""Source and controller contracts for Space-Track Integration v1.

The values in this module are operational policy, not inferred identity facts.
They encode the public API guidance current at the v1 baseline and make rate,
retention, and idempotency rules executable.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import DistributionClass


@dataclass(frozen=True)
class ControllerContract:
    controller: str
    capability_scoped: bool
    description: str


@dataclass(frozen=True)
class SourceContract:
    source_id: str
    controller: str
    api_class: str
    priority: str
    role: str
    max_requests_per_hour: float | None
    retain_locally: bool
    incremental_predicate: str | None
    canonical_role: str
    distribution_class: DistributionClass
    notes: tuple[str, ...] = ()
    query_once: bool = False
    window_limit_count: int | None = None
    window_seconds: int | None = None


CONTROLLER_CONTRACTS: tuple[ControllerContract, ...] = (
    ControllerContract("basicspacedata", False, "Member-accessible public SDA data."),
    ControllerContract("publicfiles", False, "Public-file inventory and downloads."),
    ControllerContract(
        "expandedspacedata",
        True,
        "ODR/SSA-sharing and other expanded data; exact access is account-dependent.",
    ),
    ControllerContract("fileshare", True, "Permission-controlled file-share resources."),
    ControllerContract("eventsdata", True, "Permission-controlled event resources."),
)


SOURCE_CONTRACTS: tuple[SourceContract, ...] = (
    SourceContract(
        "satcat",
        "basicspacedata",
        "satcat",
        "P0",
        "Authoritative public catalog identity/lifecycle assertions.",
        1 / 24,
        True,
        "FILE",
        "catalog_identity",
        DistributionClass.ACCOUNT_ONLY,
        (
            "Use FILE watermark deltas after an initial full baseline.",
            "NAME_ONLY is never sufficient identity evidence.",
            "RCSVALUE semantics changed on 2026-05-28 and requires semantic versioning.",
        ),
    ),
    SourceContract(
        "satcat_change",
        "basicspacedata",
        "satcat_change",
        "P0",
        "Recent changes to INTLDES/NORAD/SATNAME/COUNTRY/LAUNCH/DECAY.",
        1 / 24,
        True,
        None,
        "catalog_event",
        DistributionClass.ACCOUNT_ONLY,
    ),
    SourceContract(
        "satcat_debut",
        "basicspacedata",
        "satcat_debut",
        "P0",
        "New records added to the public Satellite Catalog.",
        1 / 24,
        True,
        "DEBUT",
        "catalog_event",
        DistributionClass.ACCOUNT_ONLY,
    ),
    SourceContract(
        "gp",
        "basicspacedata",
        "gp",
        "P0",
        "Newest SGP4-compatible element set for tracked Earth-orbiting objects.",
        1.0,
        True,
        "CREATION_DATE",
        "current_orbit",
        DistributionClass.ACCOUNT_ONLY,
        (
            "Initial baseline uses all propagable recent-epoch objects.",
            "Subsequent acquisition advances by CREATION_DATE watermark.",
            "OMM logical fields are canonical; TLE/3LE are compatibility manifestations.",
            "Do not poll one object at a time.",
        ),
    ),
    SourceContract(
        "decay",
        "basicspacedata",
        "decay",
        "P0",
        "Predicted and historical decay lifecycle assertions.",
        1 / 24,
        True,
        "MSG_EPOCH",
        "reentry_event",
        DistributionClass.ACCOUNT_ONLY,
        ("Preserve every row and PRECEDENCE stage; never latest-row-collapse.",),
    ),
    SourceContract(
        "decay_60day",
        "basicspacedata",
        "decay",
        "P0",
        "Weekly 60-day decay prediction denominator.",
        1 / (24 * 7),
        True,
        "MSG_EPOCH",
        "reentry_prediction",
        DistributionClass.ACCOUNT_ONLY,
        ("Acquire no more than weekly, preferably Wednesday after 17:00 UTC.",),
    ),
    SourceContract(
        "tip",
        "basicspacedata",
        "tip",
        "P0",
        "Tracking and Impact Prediction messages for terminal reentry prediction.",
        1.0,
        True,
        "INSERT_EPOCH",
        "reentry_event",
        DistributionClass.ACCOUNT_ONLY,
        (
            "LAT/LON are predicted 10-km crossing coordinates, not impact coordinates.",
            "A separate final-12-hour watch may use the source-authorized 10-minute cadence.",
        ),
    ),
    SourceContract(
        "publicfiles",
        "publicfiles",
        "loadpublicdata",
        "P0",
        "Public-file inventory including owner/operator products such as NASA-JSC ephemerides.",
        3 / 24,
        True,
        None,
        "operator_ephemeris_or_public_product",
        DistributionClass.ACCOUNT_ONLY,
        ("Inventory at most once every eight hours.",),
    ),
    SourceContract(
        "publicfile_download",
        "publicfiles",
        "download",
        "P0",
        "One named public-file payload.",
        None,
        True,
        None,
        "operator_ephemeris_or_public_product",
        DistributionClass.ACCOUNT_ONLY,
        (
            "Persist each named file locally and do not fetch the same download query twice.",
            "Do not download more than 10 public files per 15 minutes.",
        ),
        True,
        10,
        15 * 60,
    ),
    SourceContract(
        "gp_history",
        "basicspacedata",
        "gp_history",
        "P1",
        "Historical SGP4 element sets.",
        None,
        True,
        None,
        "historical_orbit",
        DistributionClass.ACCOUNT_ONLY,
        (
            "Each bounded historical query is acquired once and retained locally.",
            "Use bulk yearly archives for large date/object ranges.",
            "Never use GP_HISTORY as a current ephemeris feed.",
        ),
        True,
    ),
    SourceContract(
        "cdm_public",
        "basicspacedata",
        "cdm_public",
        "P1",
        "Public conjunction data messages.",
        3 / 24,
        True,
        "CREATED",
        "conjunction_event",
        DistributionClass.ACCOUNT_ONLY,
        ("Upstream history is bounded; local append-only retention is required.",),
    ),
    SourceContract(
        "organization",
        "expandedspacedata",
        "organization",
        "P1",
        "Public owner/operator directory relationships when authorized/available.",
        None,
        True,
        None,
        "operator_relationship",
        DistributionClass.UNKNOWN,
        ("Absence of a public assignment is not evidence that no operator exists.",),
    ),
    SourceContract(
        "boxscore",
        "basicspacedata",
        "boxscore",
        "P2",
        "Aggregate object counts; part of Space Situation Report presentation.",
        1 / 24,
        True,
        None,
        "aggregate_context",
        DistributionClass.ACCOUNT_ONLY,
    ),
    SourceContract(
        "launch_site",
        "basicspacedata",
        "launch_site",
        "P2",
        "Launch-site reference vocabulary.",
        None,
        True,
        None,
        "reference",
        DistributionClass.ACCOUNT_ONLY,
    ),
    SourceContract(
        "announcement",
        "basicspacedata",
        "announcement",
        "P2",
        "Service/source operational announcements.",
        None,
        True,
        None,
        "source_service_event",
        DistributionClass.ACCOUNT_ONLY,
    ),
    SourceContract(
        "curated_favorites",
        "basicspacedata",
        "gp",
        "P2",
        "Administrator-curated Navigation/Special_Interest/Visible/Weather collections.",
        1.0,
        True,
        None,
        "collection_membership",
        DistributionClass.ACCOUNT_ONLY,
        ("Membership is metadata/discovery context, never identity proof.",),
    ),
)


_SOURCE_BY_ID = {contract.source_id: contract for contract in SOURCE_CONTRACTS}


def get_source_contract(source_id: str) -> SourceContract:
    try:
        return _SOURCE_BY_ID[source_id]
    except KeyError as exc:
        raise KeyError(f"unknown Space-Track source_id: {source_id}") from exc

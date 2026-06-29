"""L2 lineage tests — ``record_lineage()`` on Job success (PROV write).

These exercise the W3C-PROV lineage append (§3.3): on a successful Job we write
one ``activity`` row + its ``agent`` + ``entity`` rows for outputs + ``edge`` rows
(``generated_by`` / ``derived_from`` / ``used`` / ``associated_with``) in ONE
transaction, recording the resolved RoutingPolicy from M3 as the agent's route.

The security keystone (GATE-2 / §WU-keys): every ``params_json`` and ``agent``
value is run through deep secret redaction (reusing ``models.secrets.redact`` /
``redact_keys``) BEFORE the write, so NO raw key ever lands in any lineage row.
The pure builders are unit-tested in isolation; ``record_lineage`` is exercised
end-to-end against a REAL temp-file SQLite DB (never an in-memory shim).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from media_studio import lineage
from media_studio.jobs import JobStatus
from media_studio.library import Library


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _db_for(index: Path) -> Path:
    return index.with_suffix(".db")


def _rows(db: Path, table: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(db))
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608 - fixed table name
    finally:
        conn.close()


def _fresh_library(tmp_path: Path) -> Library:
    """A Library over a not-yet-existing index (migration creates an empty DB)."""
    return Library(tmp_path / "library.json", probe_duration=lambda _p: 0.0)


def _job(*, method: str | None = "shorts.select", params: object = None, status: object = JobStatus.DONE) -> object:
    request = None if method is None else {"method": method, "params": params}
    return SimpleNamespace(id="job-1", status=status, request=request)


# --------------------------------------------------------------------------- #
# redact_secrets — deep secret redaction
# --------------------------------------------------------------------------- #
def test_redact_secrets_apikey_scalar():
    out = lineage.redact_secrets({"apiKey": "sk-SECRET12345"})
    assert out["apiKey"] == "…2345"
    assert "sk-SECRET12345" not in str(out)


def test_redact_secrets_apikeys_list():
    out = lineage.redact_secrets({"apiKeys": ["sk-RAWKEYABCD", "tok-9999"]})
    assert out["apiKeys"] == ["…ABCD", "…9999"]


def test_redact_secrets_providers_list_uses_redact_keys():
    out = lineage.redact_secrets({"providers": [{"id": "openrouter", "apiKeys": ["sk-RAWKEYWXYZ"]}]})
    assert out["providers"] == [{"id": "openrouter", "apiKeys": ["…WXYZ"]}]


def test_redact_secrets_nested_dict_recurses():
    out = lineage.redact_secrets({"outer": {"token": "tok-INNERSECRET"}})
    assert out["outer"]["token"] == "…CRET"


def test_redact_secrets_list_recurses():
    out = lineage.redact_secrets([{"secret": "pw-ABCDEFGH"}, "plain"])
    assert out == [{"secret": "…EFGH"}, "plain"]


def test_redact_secrets_scalar_passthrough():
    assert lineage.redact_secrets("hello") == "hello"
    assert lineage.redact_secrets(42) == 42
    assert lineage.redact_secrets(None) is None


def test_redact_secrets_non_string_key_passthrough():
    # A non-string dict key cannot be a known secret name -> the value still
    # recurses through the generic else-branch unchanged.
    out = lineage.redact_secrets({1: "x", 2: {"apiKey": "sk-DEEPKEY99"}})
    assert out[1] == "x"
    assert out[2]["apiKey"] == "…EY99"


def test_redact_secrets_secret_key_with_nested_value_recurses():
    # A secret-named key whose value is neither str nor list (a nested dict)
    # falls through to a recursive redact (still scrubbing any inner secret).
    out = lineage.redact_secrets({"secret": {"apiKey": "sk-NESTEDABCD"}})
    assert out["secret"]["apiKey"] == "…ABCD"


# --------------------------------------------------------------------------- #
# job field extractors
# --------------------------------------------------------------------------- #
def test_job_op_from_request_method():
    assert lineage.job_op(_job(method="shorts.select")) == "shorts.select"


def test_job_op_missing_request():
    assert lineage.job_op(_job(method=None)) == ""


def test_job_op_method_not_a_string():
    assert lineage.job_op(SimpleNamespace(request={"method": 123})) == ""


def test_job_status_enum_to_wire_value():
    assert lineage.job_status(_job(status=JobStatus.DONE)) == "done"


def test_job_status_plain_string():
    assert lineage.job_status(SimpleNamespace(status="done")) == "done"


def test_job_params_present():
    assert lineage.job_params(_job(params={"a": 1})) == {"a": 1}


def test_job_params_missing_request():
    assert lineage.job_params(_job(method=None)) is None


# --------------------------------------------------------------------------- #
# entity_id + normalize_output_entity + normalize_agent
# --------------------------------------------------------------------------- #
def test_entity_id_uses_provided_id():
    assert lineage.entity_id({"id": "abc123"}) == "abc123"


def test_entity_id_generated_when_missing():
    eid = lineage.entity_id({})
    assert isinstance(eid, str) and len(eid) == 12


def test_entity_id_non_dict_generates():
    eid = lineage.entity_id(None)
    assert isinstance(eid, str) and len(eid) == 12


def test_normalize_output_entity_full():
    e = lineage.normalize_output_entity(
        {
            "id": "out1",
            "kind": "short",
            "path": "/x/clip.mp4",
            "title": "Clip",
            "addedAt": "2026-01-01T00:00:00Z",
            "durationSec": 12.5,
            "contentHash": "blake3:deadbeef",
            "hasTranscript": True,
            "thumbnailPath": "/x/clip.jpg",
        }
    )
    assert e == {
        "id": "out1",
        "kind": "short",
        "path": "/x/clip.mp4",
        "role": "output",
        "title": "Clip",
        "addedAt": "2026-01-01T00:00:00Z",
        "durationSec": 12.5,
        "contentHash": "blake3:deadbeef",
        "hasTranscript": True,
        "thumbnailPath": "/x/clip.jpg",
    }


def test_normalize_output_entity_defaults_for_non_dict():
    e = lineage.normalize_output_entity(None)
    assert e["role"] == "output"
    assert e["kind"] == "output"
    assert e["path"] == ""
    assert e["durationSec"] == 0.0
    assert e["contentHash"] is None
    assert e["hasTranscript"] is False
    assert isinstance(e["id"], str) and len(e["id"]) == 12


def test_normalize_agent_full_with_route():
    aid, app_version, route_json, preset = lineage.normalize_agent(
        {"appVersion": "1.1.0", "route": {"mode": "local"}, "preset": "Punchy"}
    )
    assert isinstance(aid, str) and len(aid) == 12
    assert app_version == "1.1.0"
    assert route_json == '{"mode": "local"}'
    assert preset == "Punchy"


def test_normalize_agent_non_dict_yields_empty():
    aid, app_version, route_json, preset = lineage.normalize_agent(None)
    assert isinstance(aid, str)
    assert app_version == ""
    assert route_json is None
    assert preset == ""


def test_normalize_agent_redacts_secret_in_route():
    _aid, _app, route_json, _preset = lineage.normalize_agent({"route": {"mode": "cloud", "apiKey": "sk-ROUTESECRET"}})
    assert route_json is not None
    assert "sk-ROUTESECRET" not in route_json
    assert "…CRET" in route_json


# --------------------------------------------------------------------------- #
# build_edges
# --------------------------------------------------------------------------- #
def test_build_edges_full():
    edges = lineage.build_edges("act1", "ag1", ["o1", "o2"], ["i1"])
    assert ("act1", "ag1", "associated_with") in edges
    assert ("act1", "i1", "used") in edges
    assert ("o1", "act1", "generated_by") in edges
    assert ("o2", "act1", "generated_by") in edges
    assert ("o1", "i1", "derived_from") in edges
    assert ("o2", "i1", "derived_from") in edges


def test_build_edges_no_inputs():
    edges = lineage.build_edges("act1", "ag1", ["o1"], [])
    assert edges == [("act1", "ag1", "associated_with"), ("o1", "act1", "generated_by")]


def test_build_edges_no_outputs():
    edges = lineage.build_edges("act1", "ag1", [], ["i1"])
    assert edges == [("act1", "ag1", "associated_with"), ("act1", "i1", "used")]


# --------------------------------------------------------------------------- #
# record_lineage — end-to-end against a REAL temp-file SQLite DB
# --------------------------------------------------------------------------- #
def test_record_lineage_writes_all_rows(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    activity_id = lineage.record_lineage(
        lib,
        _job(method="shorts.select", params={"videoId": "src1"}),
        inputs=[{"id": "src1"}],
        outputs=[{"id": "out1", "kind": "short", "path": "/x/clip.mp4"}],
        agent={"appVersion": "1.1.0", "route": {"mode": "local"}, "preset": "Punchy"},
    )
    db = _db_for(lib.index_path)

    agents = _rows(db, "agent")
    assert len(agents) == 1
    assert agents[0]["app_version"] == "1.1.0"
    assert agents[0]["route_json"] == '{"mode": "local"}'
    assert agents[0]["preset"] == "Punchy"

    acts = _rows(db, "activity")
    assert len(acts) == 1
    assert acts[0]["id"] == activity_id
    assert acts[0]["op"] == "shorts.select"
    assert acts[0]["status"] == "done"
    assert acts[0]["agent_id"] == agents[0]["id"]
    assert acts[0]["params_json"] == '{"videoId": "src1"}'
    assert acts[0]["started_at"] and acts[0]["ended_at"]

    outputs = _rows(db, "entity")
    assert [o["id"] for o in outputs] == ["out1"]
    assert outputs[0]["role"] == "output"
    assert outputs[0]["kind"] == "short"

    rels = {(e["src"], e["dst"], e["rel"]) for e in _rows(db, "edge")}
    assert (activity_id, agents[0]["id"], "associated_with") in rels
    assert (activity_id, "src1", "used") in rels
    assert ("out1", activity_id, "generated_by") in rels
    assert ("out1", "src1", "derived_from") in rels


def test_record_lineage_no_raw_key_in_any_row(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    raw_params = "sk-PARAMSECRET01"
    raw_provider = "sk-PROVIDERSEC02"
    raw_nested = "tok-NESTEDSEC03"
    raw_route = "sk-ROUTESEC04"
    lineage.record_lineage(
        lib,
        _job(
            params={
                "apiKey": raw_params,
                "providers": [{"id": "openrouter", "apiKeys": [raw_provider]}],
                "opts": {"token": raw_nested},
            }
        ),
        inputs=[{"id": "src1"}],
        outputs=[{"id": "out1", "path": "/x/clip.mp4"}],
        agent={"appVersion": "1.1.0", "route": {"mode": "cloud", "apiKey": raw_route}},
    )
    db = _db_for(lib.index_path)
    blob = "".join(
        str(value)
        for table in ("agent", "activity", "entity", "edge")
        for row in _rows(db, table)
        for value in tuple(row)
    )
    for raw in (raw_params, raw_provider, raw_nested, raw_route):
        assert raw not in blob, f"raw secret leaked into lineage rows: {raw}"
    # The redacted last-4 form is still present (proves redaction ran, not deletion).
    assert "…ET01" in blob and "…EC02" in blob


def test_record_lineage_handles_none_params_and_agent(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    activity_id = lineage.record_lineage(lib, _job(method=None), inputs=[], outputs=[], agent=None)
    db = _db_for(lib.index_path)
    acts = _rows(db, "activity")
    assert acts[0]["id"] == activity_id
    assert acts[0]["op"] == ""
    assert acts[0]["params_json"] is None
    agents = _rows(db, "agent")
    assert agents[0]["route_json"] is None
    assert _rows(db, "entity") == []
    # Only the agent-association edge exists (no inputs / outputs).
    assert [(e["rel"]) for e in _rows(db, "edge")] == ["associated_with"]


def test_record_lineage_rolls_back_on_write_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lib = _fresh_library(tmp_path)

    def _boom(_conn: object, _e: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(lineage, "_insert_entity_row", _boom)
    with pytest.raises(RuntimeError, match="disk full"):
        lineage.record_lineage(
            lib,
            _job(params={"a": 1}),
            inputs=[{"id": "src1"}],
            outputs=[{"id": "out1"}],
            agent={"appVersion": "1.1.0"},
        )
    db = _db_for(lib.index_path)
    # The whole append rolled back: no agent / activity / output / edge rows.
    assert _rows(db, "agent") == []
    assert _rows(db, "activity") == []
    assert _rows(db, "entity") == []
    assert _rows(db, "edge") == []


def test_library_record_lineage_facade(tmp_path: Path):
    # The Library method delegates to lineage.record_lineage (lazy import seam).
    lib = _fresh_library(tmp_path)
    activity_id = lib.record_lineage(
        _job(params={"videoId": "src1"}),
        inputs=[{"id": "src1"}],
        outputs=[{"id": "out1", "path": "/x/clip.mp4"}],
        agent={"appVersion": "1.1.0", "route": {"mode": "local"}},
    )
    acts = _rows(_db_for(lib.index_path), "activity")
    assert acts[0]["id"] == activity_id


# --------------------------------------------------------------------------- #
# L3 — lineage_of() ancestors / descendants query (recursive edge walk)
# --------------------------------------------------------------------------- #
def _add_source(lib: Library, tmp_path: Path, name: str) -> str:
    """Add a real (empty) media file to the library and return its source id."""
    media = tmp_path / name
    media.write_bytes(b"\x00")
    return lib.add(str(media))["id"]


def _record(lib: Library, *, inputs: list[object], outputs: list[object]) -> str:
    return lib.record_lineage(
        _job(method="shorts.select"),
        inputs=inputs,
        outputs=outputs,
        agent={"appVersion": "1.1.0", "route": {"mode": "local"}},
    )


def test_lineage_of_unknown_id_returns_empty_structure(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    out = lineage.lineage_of(lib, "nope")
    assert out == {
        "id": "nope",
        "entity": None,
        "ancestors": [],
        "descendants": [],
        "provenance": None,
    }


def test_lineage_of_root_entity_shape_for_source(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src = _add_source(lib, tmp_path, "talk.mp4")
    out = lineage.lineage_of(lib, src)
    entity = out["entity"]
    assert entity is not None
    assert entity["id"] == src
    assert entity["kind"] == "video"
    assert entity["role"] == "source"
    assert entity["title"] == "talk"
    assert entity["contentHash"] is None
    assert entity["hasTranscript"] is False
    assert "missing" not in entity


def test_lineage_of_ancestors_single_hop(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src = _add_source(lib, tmp_path, "talk.mp4")
    _record(lib, inputs=[{"id": src}], outputs=[{"id": "clip1", "kind": "short", "path": "/x/c.mp4"}])
    out = lineage.lineage_of(lib, "clip1")
    assert [a["id"] for a in out["ancestors"]] == [src]
    assert out["ancestors"][0]["role"] == "source"
    assert out["descendants"] == []


def test_lineage_of_descendants_single_hop(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src = _add_source(lib, tmp_path, "talk.mp4")
    _record(lib, inputs=[{"id": src}], outputs=[{"id": "clip1", "kind": "short", "path": "/x/c.mp4"}])
    out = lineage.lineage_of(lib, src)
    assert [d["id"] for d in out["descendants"]] == ["clip1"]
    assert out["descendants"][0]["role"] == "output"
    assert out["ancestors"] == []


def test_lineage_of_multi_hop_ancestors_and_descendants(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src = _add_source(lib, tmp_path, "talk.mp4")
    _record(lib, inputs=[{"id": src}], outputs=[{"id": "clip1", "path": "/x/c1.mp4"}])
    _record(lib, inputs=[{"id": "clip1"}], outputs=[{"id": "final", "path": "/x/f.mp4"}])

    anc = lineage.lineage_of(lib, "final")
    assert [a["id"] for a in anc["ancestors"]] == ["clip1", src]  # BFS order

    desc = lineage.lineage_of(lib, src)
    assert [d["id"] for d in desc["descendants"]] == ["clip1", "final"]


def test_lineage_of_diamond_dedups_shared_ancestor(tmp_path: Path):
    # merged <- clipA <- src ;  merged <- clipB <- src  (src reached twice).
    lib = _fresh_library(tmp_path)
    src = _add_source(lib, tmp_path, "talk.mp4")
    _record(lib, inputs=[{"id": src}], outputs=[{"id": "clipA", "path": "/x/a.mp4"}])
    _record(lib, inputs=[{"id": src}], outputs=[{"id": "clipB", "path": "/x/b.mp4"}])
    _record(lib, inputs=[{"id": "clipA"}, {"id": "clipB"}], outputs=[{"id": "merged", "path": "/x/m.mp4"}])

    anc = lineage.lineage_of(lib, "merged")
    ids = [a["id"] for a in anc["ancestors"]]
    assert ids == ["clipA", "clipB", src]  # src appears exactly once (seen-guard)


def test_lineage_of_missing_source_yields_stub(tmp_path: Path):
    # An input that was never added to the library has no entity row -> a loud
    # `missing` stub (never silently dropped from the derivation).
    lib = _fresh_library(tmp_path)
    _record(lib, inputs=[{"id": "ghost"}], outputs=[{"id": "out1", "path": "/x/o.mp4"}])
    out = lineage.lineage_of(lib, "out1")
    assert out["ancestors"] == [{"id": "ghost", "missing": True}]


# --------------------------------------------------------------------------- #
# L4 — provenance card data (producing activity + agent of the queried node)
# --------------------------------------------------------------------------- #
def test_provenance_for_produced_output_carries_op_route_and_params(tmp_path: Path):
    # A produced clip exposes the op that made it, the agent's app version +
    # resolved route (M3 RoutingPolicy), and the redacted params -> the L4 card.
    lib = _fresh_library(tmp_path)
    src = _add_source(lib, tmp_path, "talk.mp4")
    lib.record_lineage(
        _job(method="shortmaker.select", params={"prompt": "punchy", "template": "bold"}),
        inputs=[{"id": src}],
        outputs=[{"id": "clip1", "kind": "short", "path": "/x/c.mp4"}],
        agent={"appVersion": "1.1.0", "preset": "Punchy", "route": {"mode": "local", "model": "qwen2.5:7b"}},
    )
    prov = lineage.lineage_of(lib, "clip1")["provenance"]
    assert prov is not None
    assert prov["op"] == "shortmaker.select"
    assert prov["status"] == "done"
    assert prov["appVersion"] == "1.1.0"
    assert prov["preset"] == "Punchy"
    assert prov["route"] == {"mode": "local", "model": "qwen2.5:7b"}
    assert prov["params"] == {"prompt": "punchy", "template": "bold"}
    assert prov["startedAt"] == prov["endedAt"]  # one timestamp at append time


def test_provenance_is_none_for_a_raw_source(tmp_path: Path):
    # A library source was imported, not produced by an activity -> no card data.
    lib = _fresh_library(tmp_path)
    src = _add_source(lib, tmp_path, "talk.mp4")
    assert lineage.lineage_of(lib, src)["provenance"] is None


def test_provenance_null_route_and_params_round_trip_to_none(tmp_path: Path):
    # An agent with no route + a job with no params store SQL NULL, which
    # `_parse_json` decodes back to None (not "" / not a crash).
    lib = _fresh_library(tmp_path)
    src = _add_source(lib, tmp_path, "talk.mp4")
    lib.record_lineage(
        _job(method="shortmaker.export", params=None),
        inputs=[{"id": src}],
        outputs=[{"id": "clip2", "path": "/x/c2.mp4"}],
        agent={"appVersion": "1.1.0"},
    )
    prov = lineage.lineage_of(lib, "clip2")["provenance"]
    assert prov is not None
    assert prov["route"] is None
    assert prov["params"] is None
    assert prov["preset"] == ""  # normalize_agent default for a missing preset


def test_provenance_dangling_generated_by_edge_is_not_guessed(tmp_path: Path):
    # Defensive: a generated_by edge whose activity row is absent yields None
    # (the INNER JOIN drops it) rather than a half-built / guessed card.
    lib = _fresh_library(tmp_path)
    with lib._open() as conn:
        conn.execute(
            "INSERT INTO edge (src, dst, rel) VALUES (?, ?, ?)",
            ("orphan", "no-such-activity", lineage.REL_GENERATED_BY),
        )
    assert lineage.lineage_of(lib, "orphan")["provenance"] is None


def test_library_lineage_facade(tmp_path: Path):
    # The Library.lineage method delegates to lineage.lineage_of (lazy import).
    lib = _fresh_library(tmp_path)
    src = _add_source(lib, tmp_path, "talk.mp4")
    _record(lib, inputs=[{"id": src}], outputs=[{"id": "clip1", "path": "/x/c.mp4"}])
    out = lib.lineage("clip1")
    assert [a["id"] for a in out["ancestors"]] == [src]

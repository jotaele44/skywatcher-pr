"""Equivalence test for the Core module reorg: pipeline/rlsm_ontology_gate.py is
now a backward-compat shim over skywatcher.core.ontology_gate. See
docs/ADR_SKYWATCHER_MODULE_BOUNDARIES.md."""

from pathlib import Path

from pipeline.rlsm_ontology_gate import run_gate as old_run_gate
from skywatcher.core.ontology_gate import run_gate as new_run_gate

CONFIG_DIR = Path("configs")


def test_shim_reexports_identical_function():
    assert old_run_gate is new_run_gate


def test_shim_functional_equivalence():
    assert old_run_gate(CONFIG_DIR) == new_run_gate(CONFIG_DIR)

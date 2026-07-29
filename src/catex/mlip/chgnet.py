"""Bounded CHGNet pre-relaxation for a VASP POSCAR.

CHGNet is an optional dependency. Importing CatEx never imports torch, ASE, or
CHGNet; the heavyweight stack is loaded only when a user explicitly starts a
pre-relaxation.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import time
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from typing import Any

import numpy as np
from pymatgen.core import Structure
from pymatgen.io.vasp.inputs import Poscar


class ChgnetPreRelaxationError(ValueError):
    """Raised when CHGNet input or output violates the CatEx contract."""


class ChgnetUnavailableError(ChgnetPreRelaxationError):
    """Raised when the optional local CHGNet runtime is unavailable."""


@dataclass(frozen=True, slots=True)
class ChgnetPreRelaxationConfig:
    """Scientific and numerical settings for one CHGNet pre-relaxation."""

    model_name: str = "0.3.0"
    optimizer: str = "FIRE"
    fmax_eV_per_angstrom: float = 0.05
    max_steps: int = 500
    relax_cell: bool = False
    device: str = "auto"

    def __post_init__(self) -> None:
        if self.model_name not in {"0.3.0", "r2scan"}:
            raise ChgnetPreRelaxationError("model_name must be 0.3.0 or r2scan")
        if self.optimizer not in {"FIRE", "BFGS", "LBFGS"}:
            raise ChgnetPreRelaxationError("optimizer must be FIRE, BFGS, or LBFGS")
        if not math.isfinite(self.fmax_eV_per_angstrom) or not (
            0.005 <= self.fmax_eV_per_angstrom <= 1.0
        ):
            raise ChgnetPreRelaxationError("fmax must be between 0.005 and 1.0 eV/angstrom")
        if not 1 <= self.max_steps <= 5000:
            raise ChgnetPreRelaxationError("max_steps must be between 1 and 5000")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ChgnetPreRelaxationError("device must be auto, cpu, or cuda")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "catex.chgnet-pre-relaxation-config.v1",
            "model_name": self.model_name,
            "optimizer": self.optimizer,
            "fmax_eV_per_angstrom": self.fmax_eV_per_angstrom,
            "max_steps": self.max_steps,
            "relax_cell": self.relax_cell,
            "device": self.device,
        }


@dataclass(frozen=True, slots=True)
class ChgnetPreRelaxationResult:
    """One completed CHGNet relaxation before project persistence."""

    poscar_text: str
    summary: dict[str, Any]
    warnings: tuple[str, ...]


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


@lru_cache(maxsize=1)
def chgnet_capabilities() -> dict[str, Any]:
    """Describe the optional runtime without importing torch or loading a model."""

    packages = {
        name: {
            "installed": importlib.util.find_spec(name) is not None,
            "version": _package_version(name),
        }
        for name in ("chgnet", "ase", "torch")
    }
    missing = [name for name, item in packages.items() if not item["installed"]]
    cuda_available = False
    if packages["torch"]["installed"]:
        try:
            import torch

            cuda_available = bool(torch.cuda.is_available())
        except (ImportError, RuntimeError):
            cuda_available = False
    return {
        "schema_version": "catex.chgnet-capabilities.v1",
        "available": not missing,
        "packages": packages,
        "missing_packages": missing,
        "models": ["0.3.0", "r2scan"],
        "optimizers": ["FIRE", "BFGS", "LBFGS"],
        "devices": ["auto", "cpu", *(["cuda"] if cuda_available else [])],
        "cuda_available": cuda_available,
        "defaults": ChgnetPreRelaxationConfig().to_dict(),
        "execution_location": "local",
        "contacts_hpc": False,
    }


def _maximum_displacement(initial: Structure, final: Structure) -> tuple[float, float]:
    if len(initial) != len(final):
        raise ChgnetPreRelaxationError("CHGNet changed the number of sites")
    delta_fractional = final.frac_coords - initial.frac_coords
    delta_fractional -= np.round(delta_fractional)
    displacement = np.linalg.norm(initial.lattice.get_cartesian_coords(delta_fractional), axis=1)
    if not len(displacement):
        return 0.0, 0.0
    return float(np.max(displacement)), float(np.sqrt(np.mean(np.square(displacement))))


def _selective_dynamics(poscar: Poscar) -> list[list[bool]] | None:
    if poscar.selective_dynamics is None:
        return None
    flags = [[bool(value) for value in row] for row in poscar.selective_dynamics]
    if any(any(row) and not all(row) for row in flags):
        raise ChgnetPreRelaxationError(
            "CHGNet pre-relaxation currently supports only F F F or T T T selective-dynamics rows"
        )
    return flags


def run_chgnet_pre_relaxation(
    poscar_text: str,
    config: ChgnetPreRelaxationConfig,
) -> ChgnetPreRelaxationResult:
    """Run one local, bounded CHGNet relaxation and return a new POSCAR.

    The original POSCAR is never modified. Fully fixed VASP selective-dynamics
    rows are translated into ASE ``FixAtoms`` constraints. A fixed lattice is
    the default and is restored exactly after relaxation.
    """

    capabilities = chgnet_capabilities()
    if not capabilities["available"]:
        missing = ", ".join(capabilities["missing_packages"])
        raise ChgnetUnavailableError(f"CHGNet runtime is not installed; missing: {missing}")
    if config.device == "cuda" and not capabilities["cuda_available"]:
        raise ChgnetPreRelaxationError("CUDA was requested, but torch cannot access a CUDA device")
    try:
        from ase.constraints import FixAtoms
        from chgnet.model import CHGNet, StructOptimizer
        from pymatgen.io.ase import AseAtomsAdaptor
    except ImportError as exc:  # pragma: no cover - guarded by capability response
        raise ChgnetUnavailableError("CHGNet, ASE, or torch could not be imported") from exc

    try:
        source = Poscar.from_str(poscar_text)
    except (OSError, ValueError) as exc:
        raise ChgnetPreRelaxationError("The source POSCAR could not be parsed") from exc
    reference = source.structure
    if not len(reference):
        raise ChgnetPreRelaxationError("The source POSCAR contains no atoms")
    flags = _selective_dynamics(source)
    fixed_indices = [index for index, row in enumerate(flags or []) if not any(row)]
    if len(fixed_indices) == len(reference):
        raise ChgnetPreRelaxationError("CHGNet cannot relax a POSCAR in which every atom is fixed")
    if config.relax_cell and fixed_indices:
        raise ChgnetPreRelaxationError(
            "Cell relaxation cannot be combined with fixed atoms in the bounded CatEx mode"
        )

    adaptor = AseAtomsAdaptor()
    atoms = adaptor.get_atoms(reference)
    if fixed_indices:
        atoms.set_constraint(FixAtoms(indices=fixed_indices))

    requested_device = None if config.device == "auto" else config.device
    started = time.perf_counter()
    try:
        if config.model_name == "0.3.0":
            model = CHGNet.load(verbose=False)
        else:
            model = CHGNet.load(model_name=config.model_name, verbose=False)
        relaxer = StructOptimizer(
            model=model,
            optimizer_class=config.optimizer,
            use_device=requested_device,
            on_isolated_atoms="warn",
        )
        relaxation = relaxer.relax(
            atoms,
            fmax=config.fmax_eV_per_angstrom,
            steps=config.max_steps,
            relax_cell=config.relax_cell,
            verbose=False,
            assign_magmoms=True,
        )
    except (RuntimeError, ValueError, TypeError) as exc:
        raise ChgnetPreRelaxationError(f"CHGNet relaxation failed: {exc}") from exc
    elapsed = time.perf_counter() - started

    final_raw = relaxation.get("final_structure")
    trajectory = relaxation.get("trajectory")
    if not isinstance(final_raw, Structure) or trajectory is None:
        raise ChgnetPreRelaxationError("CHGNet returned an incomplete relaxation result")
    final = final_raw
    if not config.relax_cell:
        final = Structure(
            lattice=reference.lattice,
            species=[site.specie for site in final_raw],
            coords=final_raw.frac_coords,
            coords_are_cartesian=False,
            site_properties=final_raw.site_properties,
        )

    energies = [float(value) for value in getattr(trajectory, "energies", [])]
    force_frames = getattr(trajectory, "forces", [])
    if not energies or not force_frames:
        raise ChgnetPreRelaxationError("CHGNet returned no energy/force trajectory")
    final_forces = np.asarray(force_frames[-1], dtype=float)
    if final_forces.shape != (len(reference), 3):
        raise ChgnetPreRelaxationError("CHGNet returned an invalid final force array")
    mobile_indices = [index for index in range(len(reference)) if index not in fixed_indices]
    final_fmax = float(np.max(np.linalg.norm(final_forces[mobile_indices], axis=1)))
    converged = final_fmax <= config.fmax_eV_per_angstrom * (1 + 1e-6)
    # StructOptimizer observes the initial geometry, every optimizer step, and
    # then explicitly appends the final geometry once more.
    n_steps = max(len(energies) - 2, 0)
    max_displacement, rms_displacement = _maximum_displacement(reference, final)
    input_sha256 = hashlib.sha256(poscar_text.encode("utf-8")).hexdigest()
    comment = f"CatEx CHGNet {config.model_name} pre-relaxed from {input_sha256[:12]}"
    output_text = Poscar(
        final,
        comment=comment,
        selective_dynamics=flags,
    ).get_str()

    warnings = [
        "CHGNet is a pre-relaxation aid, not a substitute for a converged VASP calculation.",
        (
            "Universal-potential predictions may be out of domain for surfaces, adsorbates, "
            "defects, or unusual charge states."
        ),
    ]
    if not flags:
        warnings.append("No Selective dynamics flags were present; all atoms were allowed to move.")
    if config.relax_cell:
        warnings.append(
            "The unit cell was allowed to relax; verify slab vacuum and lattice parameters "
            "before VASP."
        )
    if not converged:
        warnings.append(
            "The requested force threshold was not reached before the relaxation stopped."
        )

    calculator = getattr(relaxer, "calculator", None)
    actual_device = str(getattr(calculator, "device", requested_device or "auto"))
    summary = {
        "schema_version": "catex.chgnet-pre-relaxation-result.v1",
        "status": "converged" if converged else "max_steps_or_optimizer_stop",
        "converged": converged,
        "n_steps": n_steps,
        "final_fmax_eV_per_angstrom": final_fmax,
        "target_fmax_eV_per_angstrom": config.fmax_eV_per_angstrom,
        "initial_energy_eV": energies[0],
        "final_energy_eV": energies[-1],
        "energy_change_eV": energies[-1] - energies[0],
        "maximum_displacement_angstrom": max_displacement,
        "rms_displacement_angstrom": rms_displacement,
        "fixed_atom_count": len(fixed_indices),
        "mobile_atom_count": len(mobile_indices),
        "fixed_indices_1based": [index + 1 for index in fixed_indices],
        "model_name": config.model_name,
        "model_version": str(getattr(model, "version", config.model_name)),
        "optimizer": config.optimizer,
        "device": actual_device,
        "relax_cell": config.relax_cell,
        "elapsed_seconds": elapsed,
        "input_sha256": input_sha256,
        "output_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
        "scientific_role": "geometry_pre_relaxation_only",
    }
    return ChgnetPreRelaxationResult(output_text, summary, tuple(warnings))

# HPC shell modes

Some Slurm sites initialize the environment-modules `module` function only for a
login shell. CatEx models this as an execution-site property instead of injecting
an arbitrary `source` command into a generated job script.

## Contract

`catex.slurm-execution-profile.v1` accepts an optional `shell_mode`:

- `nonlogin` (default) renders `#!/bin/bash`;
- `login` renders `#!/bin/bash -l`.

`catex.slurm-cluster-policy.v1` accepts optional `allowed_shell_modes`. Omitting
the field permits only `nonlogin`, preserving the original behavior. A login
script is valid only when the profile selects `login` and the policy contains
`login`.

```json
{
  "shell_mode": "login"
}
```

```json
{
  "allowed_shell_modes": ["nonlogin", "login"]
}
```

These fragments belong inside their corresponding full profile and policy
documents.

## Security boundary

A login shell may execute site and user initialization files. Enabling it is a
site-specific trust decision and must be established by a read-only capability
probe plus policy review. CatEx does not accept custom shebang flags, `source`
paths, initialization commands, shell control operators, or arbitrary command
strings.

Shell mode, modules, MPI layout, partition, walltime, and executable identity are
execution provenance. They do not enter the scientific `energy_family_id`, but
they remain in the Slurm plan and its hash for auditability.

## Failure interpretation

Exit status 127 at `module purge` before `srun` means the execution environment
was not initialized; it is not evidence that VASP or VASPsol is absent. Preserve
the failed run, verify login-shell module behavior read-only, update the explicit
site policy, and create a new run directory. Do not overwrite or delete the
failed evidence.

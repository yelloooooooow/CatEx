import { describe, expect, it } from 'vitest'

import { parseIncarFile, parseKpointsFile, parsePotcarMetadataFile, parseSlurmScriptFile } from './vaspInputFiles'

describe('VASP input file imports', () => {
  it('parses commented INCAR assignments and rejects duplicate tags', () => {
    expect(parseIncarFile('ENCUT = 520 ! eV\nISPIN=2; LWAVE = F\n')).toEqual({
      ENCUT: '520',
      ISPIN: '2',
      LWAVE: 'F',
    })
    expect(() => parseIncarFile('ENCUT=400\nencut=500\n')).toThrow(/Duplicate INCAR tag/)
  })

  it('parses only automatic Gamma or Monkhorst-Pack KPOINTS', () => {
    expect(parseKpointsFile('Imported mesh\n0\nGamma\n3 3 1\n0 0 0\n')).toEqual({
      comment: 'Imported mesh',
      generation_mode: 'gamma',
      subdivisions: [3, 3, 1],
      shift: [0, 0, 0],
    })
    expect(() => parseKpointsFile('Explicit\n4\nReciprocal\n0 0 0\n')).toThrow(/automatic-mesh/)
  })

  it('accepts sanitized POTCAR metadata and never raw POTCAR content', () => {
    const metadata = {
      schema_version: 'catex.potcar-metadata.v1',
      potential_family: 'PAW_PBE_54',
      datasets: [
        {
          element: 'Na',
          potential_label: 'Na_pv',
          titel: 'PAW_PBE Na_pv',
          lexch: 'PE',
          zval: 9,
          enmax_eV: 260,
          sha256: 'a'.repeat(64),
        },
      ],
    }
    expect(parsePotcarMetadataFile(JSON.stringify(metadata))).toEqual(metadata)
    expect(() => parsePotcarMetadataFile('TITEL = PAW_PBE Na_pv')).toThrow(/not valid JSON/)
  })

  it('imports supported Slurm resources while ignoring mail and arbitrary shell', () => {
    const imported = parseSlurmScriptFile(`#!/bin/bash
#SBATCH --job-name=NiZn_bare_relax
#SBATCH --partition=deimos
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --time=7-00:00:00
#SBATCH --mail-user=private@example.invalid
module purge
module load intel/oneapi2023.2_impi
export OMP_NUM_THREADS=1
srun --mpi=pmi2 \\
/HOME/user/VASP/bin/vasp_std
echo custom
`)
    expect(imported).toMatchObject({
      job_name: 'NiZn_bare_relax',
      partition: 'deimos',
      nodes: 1,
      tasks_per_node: 32,
      walltime: '7-00:00:00',
      module_loads: ['intel/oneapi2023.2_impi'],
      executable: '/HOME/user/VASP/bin/vasp_std',
      mpi_plugin: 'pmi2',
    })
    expect(imported.ignored_lines).toEqual([
      '#SBATCH --mail-user=private@example.invalid',
      'echo custom',
    ])
  })
})

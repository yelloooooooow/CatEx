import { useEffect, useRef, useState } from 'react'
import type { WEAS as WeasViewer } from 'weas'

import { useI18n } from '../i18n'
import type { ViewerPayload } from '../types'

interface StructureViewerProps {
  structure: ViewerPayload | null
  fixedAtomIndices1Based?: number[]
  mobileAtomIndices1Based?: number[]
  focusedAtomIndex1Based?: number | null
  showAtomIndices?: boolean
  onAtomClick?: (index1Based: number) => void
}

interface ExtendedHighlightManager {
  applySettings: (settings: Record<string, unknown>) => void
  drawHighlightAtoms: () => void
}

const EMPTY_ATOM_INDICES: number[] = []

function zeroBased(indices: number[], siteCount: number): number[] {
  return [...new Set(indices)]
    .filter((index) => Number.isInteger(index) && index >= 1 && index <= siteCount)
    .map((index) => index - 1)
}

function synchronizeConstraintVisualization(
  viewer: WeasViewer,
  structure: ViewerPayload,
  fixedAtomIndices1Based: number[],
  mobileAtomIndices1Based: number[],
  focusedAtomIndex1Based: number | null,
  showAtomIndices: boolean,
) {
  const siteCount = structure.species.length
  const highlightManager = viewer.avr.highlightManager as unknown as ExtendedHighlightManager
  highlightManager.applySettings({
    selection: { indices: [], scale: 1.16, type: 'sphere', color: '#ffe082', opacity: 0.9 },
    fixed: {
      indices: zeroBased(fixedAtomIndices1Based, siteCount),
      scale: 1.08,
      type: 'sphere',
      color: '#ff7168',
      opacity: 0.62,
    },
    mobile: {
      indices: zeroBased(mobileAtomIndices1Based, siteCount),
      scale: 1.15,
      type: 'sphere',
      color: '#5de0b3',
      opacity: 0.64,
    },
    focused: {
      indices: focusedAtomIndex1Based ? zeroBased([focusedAtomIndex1Based], siteCount) : [],
      scale: 1.34,
      type: 'sphere',
      color: '#ffd166',
      opacity: 0.98,
    },
  })
  highlightManager.drawHighlightAtoms()

  const indices = showAtomIndices
    ? Array.from({ length: siteCount }, (_, index) => index + 1)
    : focusedAtomIndex1Based && focusedAtomIndex1Based <= siteCount
      ? [focusedAtomIndex1Based]
      : []
  viewer.avr.ALManager.setOverlaySettings(indices.length ? [{
    origins: indices.map((index) => structure.cartesian_coordinates[index - 1]),
    texts: indices.map((index) => `#${index} ${structure.species[index - 1]}`),
    color: '#f7fffbd9',
    fontSize: showAtomIndices ? '12px' : '15px',
    shift: [0, 0, 0.18],
  }] : [])
  viewer.render()
}

export function StructureViewer({
  structure,
  fixedAtomIndices1Based = EMPTY_ATOM_INDICES,
  mobileAtomIndices1Based = EMPTY_ATOM_INDICES,
  focusedAtomIndex1Based = null,
  showAtomIndices = false,
  onAtomClick,
}: StructureViewerProps) {
  const { tr } = useI18n()
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<WeasViewer | null>(null)
  const onAtomClickRef = useRef(onAtomClick)
  const [viewerError, setViewerError] = useState<string | null>(null)

  useEffect(() => {
    onAtomClickRef.current = onAtomClick
  }, [onAtomClick])

  useEffect(() => {
    if (!structure || !containerRef.current) return
    const container = containerRef.current
    setViewerError(null)
    let viewer: WeasViewer | null = null
    let disposed = false
    const pendingClickTimers = new Set<number>()
    void import('weas')
      .then(({ Atoms, WEAS }) => {
        if (disposed) return
        const atoms = new Atoms({
          symbols: structure.species,
          positions: structure.cartesian_coordinates,
          cell: structure.lattice,
          pbc: structure.periodic,
        })
        viewer = new WEAS({
          domElement: container,
          atoms: [atoms],
          viewerConfig: {
            backgroundColor: '#081713',
            modelStyle: 1,
            atomScale: 0.48,
            showBondedAtoms: true,
            bondSettings: {
              hideLongBonds: true,
              showHydrogenBonds: true,
              showOutBoundaryBonds: true,
            },
          },
          guiConfig: {
            controls: { enabled: false },
            buttons: { enabled: false },
          },
        })
        viewer.initialize()
        viewerRef.current = viewer
        viewer.avr.applyState(
          {
            backgroundColor: '#081713',
            modelStyle: 1,
            atomScale: 0.48,
            showBondedAtoms: true,
          },
          { redraw: 'full' },
        )
        synchronizeConstraintVisualization(
          viewer,
          structure,
          fixedAtomIndices1Based,
          mobileAtomIndices1Based,
          focusedAtomIndex1Based,
          showAtomIndices,
        )
      })
      .catch((error: unknown) => {
        if (!disposed) {
          setViewerError(
            error instanceof Error
              ? error.message
              : tr('结构查看器初始化失败', 'Failed to initialize the structure viewer'),
          )
        }
      })
    const handleViewerClick = () => {
      if (!onAtomClickRef.current) return
      const timer = window.setTimeout(() => {
        pendingClickTimers.delete(timer)
        const selected = viewer?.avr.selectedAtomsIndices ?? []
        const selectedIndex = selected.at(-1)
        if (selectedIndex === undefined) return
        viewer!.avr.selectedAtomsIndices = []
        onAtomClickRef.current?.(selectedIndex + 1)
      }, 0)
      pendingClickTimers.add(timer)
    }
    container.addEventListener('click', handleViewerClick)
    return () => {
      disposed = true
      container.removeEventListener('click', handleViewerClick)
      pendingClickTimers.forEach((timer) => window.clearTimeout(timer))
      if (viewerRef.current === viewer) viewerRef.current = null
      viewer?.avr.destroy?.()
      viewer?.clear()
      container.replaceChildren()
    }
  // Visual constraint props are synchronized by the effect below without rebuilding WebGL.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [structure, tr])

  useEffect(() => {
    if (!structure || !viewerRef.current) return
    synchronizeConstraintVisualization(
      viewerRef.current,
      structure,
      fixedAtomIndices1Based,
      mobileAtomIndices1Based,
      focusedAtomIndex1Based,
      showAtomIndices,
    )
  }, [fixedAtomIndices1Based, focusedAtomIndex1Based, mobileAtomIndices1Based, showAtomIndices, structure])

  if (!structure) {
    return (
      <div className="viewer-empty">
        <div className="viewer-orbit" />
        <strong>{tr('尚未载入结构', 'No structure loaded')}</strong>
        <span>{tr('上传 POSCAR/CIF 或载入合成示例', 'Upload POSCAR/CIF or load the synthetic example')}</span>
      </div>
    )
  }

  return (
    <div className="viewer-shell">
      <div
        aria-label={tr('三维周期结构查看器', '3D periodic structure viewer')}
        className={`structure-viewer ${onAtomClick ? 'interactive' : ''}`}
        ref={containerRef}
      />
      <div className="viewer-overlay">
        <span>WEAS · {tr('球棍模型', 'ball-and-stick')}</span>
        <span>{structure.species.length} atoms</span>
      </div>
      {viewerError && <div className="viewer-error">{viewerError}</div>}
    </div>
  )
}

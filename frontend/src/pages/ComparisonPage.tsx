import { useState, useEffect } from 'react'
import { simulationApi } from '../api/client'
import { useI18n } from '../i18n'
import './Page.css'

interface ParamSet {
  id: string
  name: string
  description?: string
}

interface SimulationStatus {
  running: boolean
  run_id?: string
  elapsed_seconds?: number
  remaining_seconds?: number
}

function ComparisonPage() {
  const { t } = useI18n()
  const [paramSets, setParamSets] = useState<ParamSet[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [duration, setDuration] = useState(30)
  const [simStatus, setSimStatus] = useState<SimulationStatus | null>(null)
  const [comparison, setComparison] = useState<Record<string, unknown>[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const loadParamSets = async () => {
    try {
      const response = await simulationApi.getParamSets()
      setParamSets(response.data.param_sets || [])
    } catch (error) {
      console.error('Failed to load param sets:', error)
    }
  }

  const loadSimStatus = async () => {
    try {
      const response = await simulationApi.status()
      setSimStatus(response.data)

      if (response.data.running) {
        const compResponse = await simulationApi.comparison()
        setComparison(compResponse.data || [])
      }
    } catch (error) {
      console.error('Failed to load status:', error)
    }
  }

  useEffect(() => {
    loadParamSets()
    loadSimStatus()

    const interval = setInterval(loadSimStatus, 2000)
    return () => clearInterval(interval)
  }, [])

  const handleToggleSelect = (id: string) => {
    setSelectedIds(prev =>
      prev.includes(id)
        ? prev.filter(x => x !== id)
        : [...prev, id]
    )
  }

  const handleStart = async () => {
    if (selectedIds.length === 0) {
      setMessage({ type: 'error', text: t.comparison.selectAtLeastOne })
      return
    }

    setIsLoading(true)
    setMessage(null)
    try {
      const response = await simulationApi.start({
        param_set_ids: selectedIds,
        duration_minutes: duration,
      })
      if (response.data.success) {
        setMessage({ type: 'success', text: t.comparison.started })
        loadSimStatus()
      } else {
        setMessage({ type: 'error', text: t.comparison.startFailed })
      }
    } catch (error) {
      setMessage({ type: 'error', text: t.comparison.startFailed })
    } finally {
      setIsLoading(false)
    }
  }

  const handleStop = async () => {
    setIsLoading(true)
    try {
      await simulationApi.stop()
      setMessage({ type: 'success', text: t.comparison.simStopped })
      loadSimStatus()
    } catch (error) {
      setMessage({ type: 'error', text: t.comparison.stopFailed })
    } finally {
      setIsLoading(false)
    }
  }

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  return (
    <div className="page">
      <h2 className="page-title">{t.comparison.title}</h2>

      {message && (
        <div className={`alert ${message.type === 'success' ? 'alert-success' : 'alert-error'}`}>
          {message.text}
        </div>
      )}

      <div className="content-grid">
        {/* Simulation Control */}
        <div className="panel">
          <h3>{t.comparison.simControl}</h3>

          {simStatus?.running ? (
            <div className="sim-running">
              <div className="sim-status text-positive">{t.common.running}</div>
              <div className="sim-info">
                <div className="metric-row">
                  <span className="metric-label">{t.comparison.elapsed}</span>
                  <span className="metric-value">
                    {formatTime(simStatus.elapsed_seconds || 0)}
                  </span>
                </div>
                <div className="metric-row">
                  <span className="metric-label">{t.comparison.remaining}</span>
                  <span className="metric-value">
                    {formatTime(simStatus.remaining_seconds || 0)}
                  </span>
                </div>
              </div>
              <button
                className="btn btn-danger"
                onClick={handleStop}
                disabled={isLoading}
              >
                {t.comparison.stopSim}
              </button>
            </div>
          ) : (
            <div className="sim-setup">
              <div className="form-group">
                <label>{t.comparison.duration} ({t.comparison.minutes})</label>
                <input
                  type="number"
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value))}
                  min={1}
                  max={1440}
                />
              </div>
              <button
                className="btn btn-primary"
                onClick={handleStart}
                disabled={isLoading || selectedIds.length === 0}
              >
                {t.comparison.startSim} ({selectedIds.length} {t.comparison.selected})
              </button>
            </div>
          )}
        </div>

        {/* Parameter Sets */}
        <div className="panel">
          <h3>{t.comparison.paramSets}</h3>
          <div className="param-set-list">
            {paramSets.length > 0 ? (
              paramSets.map(ps => (
                <div
                  key={ps.id}
                  className={`param-set-item ${selectedIds.includes(ps.id) ? 'selected' : ''}`}
                  onClick={() => handleToggleSelect(ps.id)}
                >
                  <div className="param-set-checkbox">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(ps.id)}
                      onChange={() => handleToggleSelect(ps.id)}
                    />
                  </div>
                  <div className="param-set-info">
                    <div className="param-set-name">{ps.name}</div>
                    {ps.description && (
                      <div className="param-set-desc">{ps.description}</div>
                    )}
                  </div>
                </div>
              ))
            ) : (
              <div className="text-muted">{t.comparison.noParamSets}</div>
            )}
          </div>
        </div>

        {/* Live Comparison */}
        {simStatus?.running && comparison.length > 0 && (
          <div className="panel full-width">
            <h3>{t.comparison.liveComparison}</h3>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t.comparison.paramSetName}</th>
                  <th>{t.comparison.uptimePercent}</th>
                  <th>{t.mm.totalPnl}</th>
                  <th>{t.comparison.fillCount}</th>
                  <th>{t.mm.effectivePoints}</th>
                </tr>
              </thead>
              <tbody>
                {comparison.map((row, idx) => (
                  <tr key={idx}>
                    <td>{row.param_set_name as string}</td>
                    <td>{((row.uptime_percentage as number) || 0).toFixed(1)}%</td>
                    <td className={(row.total_pnl as number) >= 0 ? 'text-positive' : 'text-negative'}>
                      ${((row.total_pnl as number) || 0).toFixed(2)}
                    </td>
                    <td>{(row.fill_count as number) || 0}</td>
                    <td>{((row.effective_points as number) || 0).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default ComparisonPage

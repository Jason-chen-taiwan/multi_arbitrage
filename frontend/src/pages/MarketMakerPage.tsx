import { useState, useEffect, useCallback } from 'react'
import { useOutletContext } from 'react-router-dom'
import type { WebSocketData } from '../hooks/useWebSocket'
import { mmApi } from '../api/client'
import { useI18n } from '../i18n'
import './Page.css'

interface OutletContext {
  isConnected: boolean
  lastMessage: WebSocketData | null
}

interface MMConfig {
  quote: {
    order_distance_bps: number
    cancel_distance_bps: number
    rebalance_distance_bps: number
    queue_position_limit: number
  }
  position: {
    order_size_btc: number
    max_position_btc: number
  }
  volatility: {
    window_sec: number
    threshold_bps: number
    resume_threshold_bps: number
    stable_seconds: number
  }
}

interface HedgeStats {
  total_attempts: number
  total_success: number
  total_failed: number
  total_fallback: number
  success_rate: number
  avg_latency_ms: number | null
}

const defaultConfig: MMConfig = {
  quote: {
    order_distance_bps: 8,
    cancel_distance_bps: 3,
    rebalance_distance_bps: 10,
    queue_position_limit: 3,
  },
  position: {
    order_size_btc: 0.01,
    max_position_btc: 0.05,
  },
  volatility: {
    window_sec: 2,
    threshold_bps: 4,
    resume_threshold_bps: 3,
    stable_seconds: 2,
  },
}

function MarketMakerPage() {
  const { lastMessage } = useOutletContext<OutletContext>()
  const { t } = useI18n()
  const [isLoading, setIsLoading] = useState(false)
  const [config, setConfig] = useState<MMConfig>(defaultConfig)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [isConfigCollapsed, setIsConfigCollapsed] = useState(false)

  // Runtime controls state (預設皆為 OFF)
  const [runtimeHedgeEnabled, setRuntimeHedgeEnabled] = useState(false)
  const [runtimeInstantCloseEnabled, setRuntimeInstantCloseEnabled] = useState(false)
  const [runtimeLiquidationProtection, setRuntimeLiquidationProtection] = useState(false)
  const [liqMarginThreshold, setLiqMarginThreshold] = useState(80)  // 預設 80%
  const [liqDistanceThreshold, setLiqDistanceThreshold] = useState(5)  // 預設 5%
  const [isTogglingHedge, setIsTogglingHedge] = useState(false)
  const [isTogglingInstantClose, setIsTogglingInstantClose] = useState(false)
  const [isTogglingLiquidationProtection, setIsTogglingLiquidationProtection] = useState(false)

  const mmStatus = lastMessage?.mm_status
  const mmExecutor = lastMessage?.mm_executor as Record<string, unknown> | undefined
  const mmPositions = lastMessage?.mm_positions
  const fillHistory = lastMessage?.fill_history || []
  const orderbooks = lastMessage?.orderbooks

  // Load config on mount
  useEffect(() => {
    loadConfig()
  }, [])

  // Sync runtime controls from mm_status (WebSocket provides this directly)
  useEffect(() => {
    if (mmStatus) {
      // 從 WebSocket 推送的 mm_status 同步運行時控制狀態
      if (typeof mmStatus.hedge_enabled === 'boolean') {
        setRuntimeHedgeEnabled(mmStatus.hedge_enabled)
      }
      if (typeof mmStatus.instant_close_enabled === 'boolean') {
        setRuntimeInstantCloseEnabled(mmStatus.instant_close_enabled)
      }
      if (typeof mmStatus.liquidation_protection_enabled === 'boolean') {
        setRuntimeLiquidationProtection(mmStatus.liquidation_protection_enabled)
      }
    }
  }, [mmStatus])

  // Toggle hedge enabled (與即時平倉互斥)
  const handleToggleHedge = useCallback(async () => {
    if (!mmStatus?.running) return
    setIsTogglingHedge(true)
    try {
      const newValue = !runtimeHedgeEnabled
      const response = await mmApi.setHedgeEnabled(newValue)
      // 從 API 回應中獲取狀態（包含互斥處理結果）
      const data = response.data as { hedge_enabled: boolean; instant_close_enabled: boolean }
      setRuntimeHedgeEnabled(data.hedge_enabled)
      setRuntimeInstantCloseEnabled(data.instant_close_enabled)
      const msg = newValue ? '對沖已開啟（即時平倉已自動關閉）' : '對沖已關閉'
      setMessage({ type: 'success', text: msg })
      setTimeout(() => setMessage(null), 2000)
    } catch (error) {
      console.error('Failed to toggle hedge:', error)
      setMessage({ type: 'error', text: '切換對沖失敗' })
    } finally {
      setIsTogglingHedge(false)
    }
  }, [runtimeHedgeEnabled, mmStatus?.running])

  // Toggle instant close enabled (與對沖互斥)
  const handleToggleInstantClose = useCallback(async () => {
    if (!mmStatus?.running) return
    setIsTogglingInstantClose(true)
    try {
      const newValue = !runtimeInstantCloseEnabled
      const response = await mmApi.setInstantCloseEnabled(newValue)
      // 從 API 回應中獲取狀態（包含互斥處理結果）
      const data = response.data as { hedge_enabled: boolean; instant_close_enabled: boolean }
      setRuntimeInstantCloseEnabled(data.instant_close_enabled)
      setRuntimeHedgeEnabled(data.hedge_enabled)
      const msg = newValue ? '即時平倉已開啟（對沖已自動關閉）' : '即時平倉已關閉'
      setMessage({ type: 'success', text: msg })
      setTimeout(() => setMessage(null), 2000)
    } catch (error) {
      console.error('Failed to toggle instant close:', error)
      setMessage({ type: 'error', text: '切換即時平倉失敗' })
    } finally {
      setIsTogglingInstantClose(false)
    }
  }, [runtimeInstantCloseEnabled, mmStatus?.running])

  // Toggle liquidation protection enabled
  const handleToggleLiquidationProtection = useCallback(async () => {
    setIsTogglingLiquidationProtection(true)
    try {
      const newValue = !runtimeLiquidationProtection
      await mmApi.setLiquidationProtection({ enabled: newValue })
      setRuntimeLiquidationProtection(newValue)
      setMessage({ type: 'success', text: `爆倉保護已${newValue ? '開啟' : '關閉'}` })
      setTimeout(() => setMessage(null), 2000)
    } catch (error) {
      console.error('Failed to toggle liquidation protection:', error)
      setMessage({ type: 'error', text: '切換爆倉保護失敗' })
    } finally {
      setIsTogglingLiquidationProtection(false)
    }
  }, [runtimeLiquidationProtection])

  // Save liquidation protection thresholds
  const handleSaveLiquidationThresholds = useCallback(async () => {
    try {
      await mmApi.setLiquidationProtection({
        margin_ratio_threshold: liqMarginThreshold,
        liq_distance_threshold: liqDistanceThreshold,
      })
      setMessage({ type: 'success', text: '爆倉保護閾值已儲存' })
      setTimeout(() => setMessage(null), 2000)
    } catch (error) {
      console.error('Failed to save liquidation thresholds:', error)
      setMessage({ type: 'error', text: '儲存閾值失敗' })
    }
  }, [liqMarginThreshold, liqDistanceThreshold])

  const loadConfig = async () => {
    try {
      const response = await mmApi.getConfig()
      if (response.data) {
        setConfig({
          quote: {
            order_distance_bps: response.data.quote?.order_distance_bps ?? defaultConfig.quote.order_distance_bps,
            cancel_distance_bps: response.data.quote?.cancel_distance_bps ?? defaultConfig.quote.cancel_distance_bps,
            rebalance_distance_bps: response.data.quote?.rebalance_distance_bps ?? defaultConfig.quote.rebalance_distance_bps,
            queue_position_limit: response.data.quote?.queue_position_limit ?? defaultConfig.quote.queue_position_limit,
          },
          position: {
            order_size_btc: response.data.position?.order_size_btc ?? defaultConfig.position.order_size_btc,
            max_position_btc: response.data.position?.max_position_btc ?? defaultConfig.position.max_position_btc,
          },
          volatility: {
            window_sec: response.data.volatility?.window_sec ?? defaultConfig.volatility.window_sec,
            threshold_bps: response.data.volatility?.threshold_bps ?? defaultConfig.volatility.threshold_bps,
            resume_threshold_bps: response.data.volatility?.resume_threshold_bps ?? defaultConfig.volatility.resume_threshold_bps,
            stable_seconds: response.data.volatility?.stable_seconds ?? defaultConfig.volatility.stable_seconds,
          },
        })
      }

      // 載入爆倉保護配置
      const liqResponse = await mmApi.getLiquidationProtection()
      if (liqResponse.data) {
        setRuntimeLiquidationProtection(liqResponse.data.enabled ?? false)
        setLiqMarginThreshold(liqResponse.data.margin_ratio_threshold ?? 80)
        setLiqDistanceThreshold(liqResponse.data.liq_distance_threshold ?? 5)
      }
    } catch (error) {
      console.error('Failed to load config:', error)
    }
  }

  const handleSaveConfig = async () => {
    setIsLoading(true)
    setMessage(null)
    try {
      await mmApi.updateConfig(config as unknown as Record<string, unknown>)
      setMessage({ type: 'success', text: t.mm.configSaved })
      setTimeout(() => setMessage(null), 3000)
    } catch (error) {
      setMessage({ type: 'error', text: t.mm.configSaveFailed })
    } finally {
      setIsLoading(false)
    }
  }

  const handleReloadConfig = async () => {
    setIsLoading(true)
    setMessage(null)
    try {
      await mmApi.reloadConfig()
      await loadConfig()
      setMessage({ type: 'success', text: t.mm.configReloaded })
      setTimeout(() => setMessage(null), 3000)
    } catch (error) {
      setMessage({ type: 'error', text: t.mm.configReloadFailed })
    } finally {
      setIsLoading(false)
    }
  }

  const handleStart = async () => {
    setIsLoading(true)
    try {
      await mmApi.start({})
    } catch (error) {
      console.error('Failed to start MM:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleStop = async () => {
    setIsLoading(true)
    try {
      await mmApi.stop()
    } catch (error) {
      console.error('Failed to stop MM:', error)
    } finally {
      setIsLoading(false)
    }
  }

  // Extract executor data safely (use backend field names)
  // state.to_dict() has: volatility_bps, fill_count, pnl_usd at top level
  // stats object contains: uptime_pct, boosted_pct, total_time_ms, bid_cancels, etc.
  const state = mmExecutor?.state as Record<string, unknown> | undefined
  const stats = state?.stats as Record<string, unknown> | undefined

  // Operation history from executor state
  const operationHistory = (state?.operation_history as Array<{
    time: string
    action: string
    side: string
    order_price?: number
    reason?: string
  }>) || []

  // Top-level fields from state
  const totalPnl = (state?.pnl_usd as number) || 0
  const fillCount = (state?.fill_count as number) || 0
  const volatilityBps = (state?.volatility_bps as number) || 0

  // Stats object fields
  const uptimePercentage = (stats?.uptime_pct as number) || 0
  const effectivePoints = (stats?.effective_pts_pct as number) || 0
  const totalTimeMs = (stats?.total_time_ms as number) || 0
  const runningSeconds = totalTimeMs / 1000
  const pauseCount = (stats?.volatility_pause_count as number) || 0

  // Check if paused based on executor status
  const executorStats = mmExecutor?.stats as Record<string, unknown> | undefined
  const executorStatus = executorStats?.status as string | undefined
  const isPaused = executorStatus === 'paused'

  // Tier distribution (backend uses boosted/standard/basic/out_of_range naming)
  const tier100Pct = (stats?.boosted_pct as number) || 0
  const tier50Pct = (stats?.standard_pct as number) || 0
  const tier10Pct = (stats?.basic_pct as number) || 0
  const tierOverPct = (stats?.out_of_range_pct as number) || 0

  // Order stats (backend uses bid/ask naming, in stats object)
  const bidCancels = (stats?.bid_cancels as number) || 0
  const bidQueueCancels = (stats?.bid_queue_cancels as number) || 0
  const bidRebalances = (stats?.bid_rebalances as number) || 0
  const askCancels = (stats?.ask_cancels as number) || 0
  const askQueueCancels = (stats?.ask_queue_cancels as number) || 0
  const askRebalances = (stats?.ask_rebalances as number) || 0

  // Current orders (bid/ask) - distance_bps 由後端計算（基於 best_bid/best_ask）
  const bidOrder = state?.bid_order as { price: number; qty: number; status: string; distance_bps?: number } | null
  const askOrder = state?.ask_order as { price: number; qty: number; status: string; distance_bps?: number } | null

  // Calculate distance from mid price
  const getMidPrice = () => {
    const ob = orderbooks?.STANDX?.['BTC-USD']
    if (!ob?.bids?.[0] || !ob?.asks?.[0]) return null
    return (ob.bids[0][0] + ob.asks[0][0]) / 2
  }
  const midPrice = getMidPrice()

  // 後端會計算 distance_bps（基於 best_bid/best_ask），此函數作為 fallback
  const calcDistanceBps = (orderPrice: number) => {
    if (!midPrice || !orderPrice) return null
    return Math.abs((midPrice - orderPrice) / midPrice * 10000)
  }

  // Format running time
  const formatRunningTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}分${secs}秒`
  }

  // Maker Hours calculation
  // Formula: Maker Hours = (order_size / 2) × multiplier
  // multiplier: 1.0x (≥70% uptime) or 0.5x (≥50% uptime)
  const orderSize = config.position.order_size_btc
  const MM1_TARGET = 360
  const MM2_TARGET = 504

  const getUptimeTier = () => {
    if (uptimePercentage >= 70) return { tier: 'boosted', multiplier: 1.0 }
    if (uptimePercentage >= 50) return { tier: 'standard', multiplier: 0.5 }
    return { tier: 'inactive', multiplier: 0 }
  }

  const { tier: uptimeTier, multiplier } = getUptimeTier()
  const makerHoursPerHour = (orderSize / 2) * multiplier
  const makerHoursPerMonth = makerHoursPerHour * 24 * 30
  const mm1Progress = Math.min((makerHoursPerMonth / MM1_TARGET) * 100, 100)
  const mm2Progress = Math.min((makerHoursPerMonth / MM2_TARGET) * 100, 100)

  // Update config helper
  const updateQuote = (key: keyof MMConfig['quote'], value: number) => {
    setConfig(prev => ({ ...prev, quote: { ...prev.quote, [key]: value } }))
  }
  const updatePosition = (key: keyof MMConfig['position'], value: number) => {
    setConfig(prev => ({ ...prev, position: { ...prev.position, [key]: value } }))
  }
  const updateVolatility = (key: keyof MMConfig['volatility'], value: number) => {
    setConfig(prev => ({ ...prev, volatility: { ...prev.volatility, [key]: value } }))
  }

  // Extract hedge stats from executor
  const hedgeStats = (state?.hedge_stats as HedgeStats) || null
  const hedgeTarget = mmStatus?.hedge_target as string || 'none'
  const hedgeConfigured = hedgeTarget !== 'none'

  return (
    <div className="page">
      <div className="page-header">
        <h2 className="page-title">{t.mm.title}</h2>
        <div className="page-actions">
          {mmStatus?.running ? (
            <button
              className="btn btn-danger"
              onClick={handleStop}
              disabled={isLoading}
            >
              {isLoading ? t.mm.stopping : t.mm.stopMM}
            </button>
          ) : (
            <button
              className="btn btn-primary"
              onClick={handleStart}
              disabled={isLoading}
            >
              {isLoading ? t.mm.starting : t.mm.startMM}
            </button>
          )}
        </div>
      </div>

      {message && (
        <div className={`alert ${message.type === 'success' ? 'alert-success' : 'alert-error'}`}>
          {message.text}
        </div>
      )}

      {/* Strategy Configuration - Collapsible */}
      <div className={`panel config-panel ${isConfigCollapsed ? 'collapsed' : ''}`}>
        <div className="panel-header-collapsible" onClick={() => setIsConfigCollapsed(!isConfigCollapsed)}>
          <h3>{t.mm.strategyConfig}</h3>
          <span className={`collapse-icon ${isConfigCollapsed ? 'collapsed' : ''}`}>▼</span>
        </div>
        <div className={`config-content ${isConfigCollapsed ? 'hidden' : ''}`}>
        <div className="config-grid">
          {/* Quote Parameters */}
          <div className="config-section">
            <h4>{t.mm.quoteParams}</h4>
            <div className="config-row">
              <label>{t.mm.orderDistance}</label>
              <div className="input-with-unit">
                <input
                  type="number"
                  value={config.quote.order_distance_bps}
                  onChange={(e) => updateQuote('order_distance_bps', Number(e.target.value))}
                  min={0}
                  step={1}
                />
                <span className="unit">{t.mm.bps}</span>
              </div>
            </div>
            <div className="config-row">
              <label>{t.mm.cancelDistance}</label>
              <div className="input-with-unit">
                <input
                  type="number"
                  value={config.quote.cancel_distance_bps}
                  onChange={(e) => updateQuote('cancel_distance_bps', Number(e.target.value))}
                  min={0}
                  step={1}
                />
                <span className="unit">{t.mm.bps}</span>
              </div>
            </div>
            <div className="config-row">
              <label>{t.mm.rebalanceDistance}</label>
              <div className="input-with-unit">
                <input
                  type="number"
                  value={config.quote.rebalance_distance_bps}
                  onChange={(e) => updateQuote('rebalance_distance_bps', Number(e.target.value))}
                  min={0}
                  step={1}
                />
                <span className="unit">{t.mm.bps}</span>
              </div>
            </div>
            <div className="config-row">
              <label>{t.mm.queueLimit}</label>
              <div className="input-with-unit">
                <input
                  type="number"
                  value={config.quote.queue_position_limit}
                  onChange={(e) => updateQuote('queue_position_limit', Number(e.target.value))}
                  min={0}
                  step={1}
                />
                <span className="unit">{t.mm.levels}</span>
              </div>
            </div>
          </div>

          {/* Position Parameters */}
          <div className="config-section">
            <h4>{t.mm.positionParams}</h4>
            <div className="config-row">
              <label>{t.mm.orderSize}</label>
              <div className="input-with-unit">
                <input
                  type="number"
                  value={config.position.order_size_btc}
                  onChange={(e) => updatePosition('order_size_btc', Number(e.target.value))}
                  min={0}
                  step={0.001}
                />
                <span className="unit">BTC</span>
              </div>
            </div>
            <div className="config-row">
              <label>{t.mm.maxPosition}</label>
              <div className="input-with-unit">
                <input
                  type="number"
                  value={config.position.max_position_btc}
                  onChange={(e) => updatePosition('max_position_btc', Number(e.target.value))}
                  min={0}
                  step={0.01}
                />
                <span className="unit">BTC</span>
              </div>
            </div>
          </div>

          {/* Volatility Control */}
          <div className="config-section">
            <h4>{t.mm.volatilityControl}</h4>
            <div className="config-row">
              <label>{t.mm.observeWindow}</label>
              <div className="input-with-unit">
                <input
                  type="number"
                  value={config.volatility.window_sec}
                  onChange={(e) => updateVolatility('window_sec', Number(e.target.value))}
                  min={1}
                  step={1}
                />
                <span className="unit">{t.mm.sec}</span>
              </div>
            </div>
            <div className="config-row">
              <label>{t.mm.pauseThreshold}</label>
              <div className="input-with-unit">
                <input
                  type="number"
                  value={config.volatility.threshold_bps}
                  onChange={(e) => updateVolatility('threshold_bps', Number(e.target.value))}
                  min={0}
                  step={0.5}
                />
                <span className="unit">{t.mm.bps}</span>
              </div>
            </div>
            <div className="config-row">
              <label>{t.mm.resumeThreshold}</label>
              <div className="input-with-unit">
                <input
                  type="number"
                  value={config.volatility.resume_threshold_bps}
                  onChange={(e) => updateVolatility('resume_threshold_bps', Number(e.target.value))}
                  min={0}
                  step={0.5}
                />
                <span className="unit">{t.mm.bps}</span>
              </div>
            </div>
          </div>

          {/* Config Actions */}
          <div className="config-section">
            <h4>配置操作</h4>
            <div className="config-buttons">
              <button
                className="btn btn-primary"
                onClick={handleSaveConfig}
                disabled={isLoading}
              >
                {t.common.save}
              </button>
              <button
                className="btn btn-secondary"
                onClick={handleReloadConfig}
                disabled={isLoading}
              >
                {t.common.reload}
              </button>
            </div>
          </div>
        </div>
        </div>
      </div>

      {/* Runtime Controls - 運行時控制 */}
      <div className="runtime-controls-bar">
        <div className="runtime-control">
          <span className="control-label">對沖開關</span>
          <button
            className={`toggle-btn ${runtimeHedgeEnabled && mmStatus?.running ? 'active' : ''}`}
            onClick={handleToggleHedge}
            disabled={!mmStatus?.running || isTogglingHedge || hedgeTarget === 'none'}
            title={!mmStatus?.running ? '請先啟動做市商' : (hedgeTarget === 'none' ? '未配置對沖帳戶' : (runtimeHedgeEnabled ? '點擊關閉對沖' : '點擊開啟對沖'))}
          >
            {isTogglingHedge ? '...' : (runtimeHedgeEnabled ? 'ON' : 'OFF')}
          </button>
          <span className="control-hint">
            {hedgeTarget === 'none'
              ? '未配置對沖帳戶'
              : `StandX 對沖帳戶 - ${!mmStatus?.running ? '啟動後可用' : (runtimeHedgeEnabled ? '已啟用' : '已停用')}`
            }
          </span>
        </div>
        <div className="runtime-control">
          <span className="control-label">即時平倉</span>
          <button
            className={`toggle-btn ${runtimeInstantCloseEnabled && mmStatus?.running ? 'active warning' : ''}`}
            onClick={handleToggleInstantClose}
            disabled={!mmStatus?.running || isTogglingInstantClose}
            title={!mmStatus?.running ? '請先啟動做市商' : (runtimeInstantCloseEnabled ? '點擊關閉即時平倉' : '點擊開啟即時平倉')}
          >
            {isTogglingInstantClose ? '...' : (runtimeInstantCloseEnabled ? 'ON' : 'OFF')}
          </button>
          <span className="control-hint">
            {!mmStatus?.running ? '啟動後可用' : (runtimeInstantCloseEnabled ? '成交後立即市價平倉' : '正常模式')}
          </span>
        </div>
        <div className={`liquidation-protection-box ${runtimeLiquidationProtection ? 'active' : ''}`}>
          <div className="liq-header">
            <span className="liq-title">🛡️ 爆倉保護</span>
            <button
              className={`toggle-btn ${runtimeLiquidationProtection ? 'active danger' : ''}`}
              onClick={handleToggleLiquidationProtection}
              disabled={isTogglingLiquidationProtection}
              title={runtimeLiquidationProtection ? '點擊關閉爆倉保護' : '點擊開啟爆倉保護'}
            >
              {isTogglingLiquidationProtection ? '...' : (runtimeLiquidationProtection ? 'ON' : 'OFF')}
            </button>
          </div>
          <div className="liq-thresholds">
            <div className="liq-threshold-item">
              <span className="liq-threshold-label">Margin 閾值</span>
              <div className="liq-threshold-input">
                <input
                  type="number"
                  value={liqMarginThreshold}
                  onChange={(e) => setLiqMarginThreshold(Number(e.target.value))}
                  min={50}
                  max={100}
                />
                <span className="liq-unit">%</span>
              </div>
            </div>
            <div className="liq-threshold-item">
              <span className="liq-threshold-label">清算距離</span>
              <div className="liq-threshold-input">
                <input
                  type="number"
                  value={liqDistanceThreshold}
                  onChange={(e) => setLiqDistanceThreshold(Number(e.target.value))}
                  min={1}
                  max={20}
                />
                <span className="liq-unit">%</span>
              </div>
            </div>
            <button className="liq-save-btn" onClick={handleSaveLiquidationThresholds}>
              儲存
            </button>
          </div>
          {runtimeLiquidationProtection && (
            <div className="liq-status">
              ⚡ 當 Margin &gt; {liqMarginThreshold}% 或 清算距離 &lt; {liqDistanceThreshold}% 時自動平倉
            </div>
          )}
        </div>
      </div>

      {/* Summary Cards */}
      <div className="summary-cards">
        <div className="card">
          <div className="card-title">{t.common.status}</div>
          <div className={`card-value ${mmStatus?.running ? 'text-positive' : 'text-negative'}`}>
            {mmStatus?.running ? t.common.running : t.common.stopped}
          </div>
          <div className="card-subtitle">實盤交易</div>
        </div>

        <div className="card">
          <div className="card-title">{t.mm.totalPnl}</div>
          <div className={`card-value ${totalPnl >= 0 ? 'text-positive' : 'text-negative'}`}>
            ${totalPnl.toFixed(2)}
          </div>
          <div className="card-subtitle">USD</div>
        </div>

        <div className="card">
          <div className="card-title">{t.mm.uptime}</div>
          <div className="card-value">{uptimePercentage.toFixed(1)}%</div>
          <div className="card-subtitle">{effectivePoints.toFixed(2)} {t.mm.effectivePoints}</div>
        </div>

        <div className="card">
          <div className="card-title">{t.mm.position}</div>
          <div className={`card-value ${(mmPositions?.net_btc || 0) >= 0 ? 'text-positive' : 'text-negative'}`}>
            {mmPositions?.net_btc?.toFixed(6) || '0.000000'} BTC
          </div>
          <div className="card-subtitle">
            {mmPositions?.is_hedged ? t.mm.hedged : t.mm.notHedged}
          </div>
        </div>

        <div className="card">
          <div className="card-title">{t.mm.fills}</div>
          <div className="card-value">{fillCount}</div>
          <div className="card-subtitle">{t.mm.totalFills}</div>
        </div>

        <div className="card">
          <div className="card-title">對沖狀態</div>
          <div className={`card-value ${runtimeHedgeEnabled && hedgeTarget !== 'none' ? 'text-positive' : 'text-muted'}`}>
            {runtimeHedgeEnabled && hedgeTarget !== 'none' ? '已啟用' : '未啟用'}
          </div>
          <div className="card-subtitle">
            {hedgeTarget === 'standx_hedge' ? 'StandX 對沖帳戶' : '不對沖'}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="content-grid">
        {/* Order Book + Depth Analysis */}
        <div className="panel orderbook-panel">
          <h3>{t.mm.orderBook} (StandX BTC-USD)</h3>
          {orderbooks?.STANDX?.['BTC-USD'] ? (
            <>
              <div className="orderbook">
                {(() => {
                  const asks = orderbooks.STANDX['BTC-USD'].asks.slice(0, 10)
                  const bids = orderbooks.STANDX['BTC-USD'].bids.slice(0, 10)

                  // 計算最大 size 用於正規化深度條寬度
                  const allSizes = [...asks.map(a => a[1]), ...bids.map(b => b[1])]
                  const maxSize = Math.max(...allSizes, 0.001)

                  // Asks 累積量（從最遠到最近）
                  const asksCumulative: number[] = []
                  let askTotal = 0
                  for (let i = asks.length - 1; i >= 0; i--) {
                    askTotal += asks[i][1]
                    asksCumulative[i] = askTotal
                  }

                  // Bids 累積量（從最近到最遠）
                  const bidsCumulative: number[] = []
                  let bidTotal = 0
                  for (let i = 0; i < bids.length; i++) {
                    bidTotal += bids[i][1]
                    bidsCumulative[i] = bidTotal
                  }

                  return (
                    <>
                      <div className="orderbook-header">
                        <span>{t.mm.price}</span>
                        <span>{t.mm.size}</span>
                        <span>{t.mm.volume}</span>
                      </div>

                      {/* Asks (賣單) - 從高到低顯示 */}
                      <div className="orderbook-side asks">
                        {asks.slice().reverse().map(([price, size], idx) => {
                          const originalIdx = asks.length - 1 - idx
                          const depthPct = (size / maxSize) * 100
                          return (
                            <div key={idx} className="orderbook-row ask">
                              <div className="depth-bar-bg ask" style={{ width: `${depthPct}%` }} />
                              <span className="text-negative">{price.toFixed(2)}</span>
                              <span>{size.toFixed(4)}</span>
                              <span className="text-muted">{asksCumulative[originalIdx].toFixed(4)}</span>
                            </div>
                          )
                        })}
                      </div>

                      {/* Spread */}
                      <div className="orderbook-spread">
                        <span className="spread-price">{midPrice?.toFixed(2) || '--'}</span>
                        <span className="spread-label">
                          {t.mm.spread}: {(asks[0]?.[0] - bids[0]?.[0]).toFixed(2)} ({((asks[0]?.[0] - bids[0]?.[0]) / midPrice! * 10000).toFixed(1)} bps)
                        </span>
                      </div>

                      {/* Bids (買單) - 從高到低顯示 */}
                      <div className="orderbook-side bids">
                        {bids.map(([price, size], idx) => {
                          const depthPct = (size / maxSize) * 100
                          return (
                            <div key={idx} className="orderbook-row bid">
                              <div className="depth-bar-bg bid" style={{ width: `${depthPct}%` }} />
                              <span className="text-positive">{price.toFixed(2)}</span>
                              <span>{size.toFixed(4)}</span>
                              <span className="text-muted">{bidsCumulative[idx].toFixed(4)}</span>
                            </div>
                          )
                        })}
                      </div>
                    </>
                  )
                })()}
              </div>

              {/* Depth Analysis */}
              <div className="depth-analysis">
                <h4 className="panel-title-accent">{t.mm.depthAnalysis}</h4>
                {(() => {
                  const bidDepth = orderbooks.STANDX['BTC-USD'].bids.slice(0, 10).reduce((sum, [, size]) => sum + size, 0)
                  const askDepth = orderbooks.STANDX['BTC-USD'].asks.slice(0, 10).reduce((sum, [, size]) => sum + size, 0)
                  const totalDepth = bidDepth + askDepth
                  const bidPct = totalDepth > 0 ? (bidDepth / totalDepth) * 100 : 50
                  const askPct = totalDepth > 0 ? (askDepth / totalDepth) * 100 : 50
                  const imbalance = bidPct - 50

                  return (
                    <>
                      <div className="depth-bar-container">
                        <div className="depth-bar">
                          <div className="depth-segment bid" style={{ width: `${bidPct}%` }}>
                            <span className="depth-value">{bidDepth.toFixed(2)} BTC</span>
                          </div>
                          <div className="depth-segment ask" style={{ width: `${askPct}%` }}>
                            <span className="depth-value">{askDepth.toFixed(2)} BTC</span>
                          </div>
                        </div>
                      </div>
                      <div className="depth-labels">
                        <span>{t.mm.bidDepth}</span>
                        <span className={imbalance >= 0 ? 'text-positive' : 'text-negative'}>
                          {t.mm.imbalance}: {imbalance >= 0 ? '+' : ''}{imbalance.toFixed(1)}%
                        </span>
                        <span>{t.mm.askDepth}</span>
                      </div>
                    </>
                  )
                })()}
              </div>

            </>
          ) : (
            <div className="text-muted">{t.mm.noOrderBookData}</div>
          )}
        </div>

        {/* Execution Stats */}
        <div className="panel execution-stats-panel">
          <h3>{t.mm.executionStats}</h3>

          {/* Current Orders - Compact Row */}
          <div className="current-orders-compact">
            <div className="order-compact bid">
              <span className="order-side">{t.mm.bidOrder}:</span>
              {bidOrder ? (
                <>
                  <span className="order-price text-positive">${bidOrder.price.toFixed(2)}</span>
                  <span className="order-qty">{bidOrder.qty} BTC</span>
                  {/* 優先使用後端計算的 distance_bps（基於 best_bid），fallback 到本地計算 */}
                  <span className={`order-bps ${(bidOrder.distance_bps ?? calcDistanceBps(bidOrder.price) ?? 0) <= 10 ? 'in-range' : 'out-range'}`}>
                    {(bidOrder.distance_bps ?? calcDistanceBps(bidOrder.price))?.toFixed(1)} bps
                  </span>
                </>
              ) : (
                <span className="order-none">--</span>
              )}
            </div>
            <div className="order-compact ask">
              <span className="order-side">{t.mm.askOrder}:</span>
              {askOrder ? (
                <>
                  <span className="order-price text-negative">${askOrder.price.toFixed(2)}</span>
                  <span className="order-qty">{askOrder.qty} BTC</span>
                  {/* 優先使用後端計算的 distance_bps（基於 best_ask），fallback 到本地計算 */}
                  <span className={`order-bps ${(askOrder.distance_bps ?? calcDistanceBps(askOrder.price) ?? 0) <= 10 ? 'in-range' : 'out-range'}`}>
                    {(askOrder.distance_bps ?? calcDistanceBps(askOrder.price))?.toFixed(1)} bps
                  </span>
                </>
              ) : (
                <span className="order-none">--</span>
              )}
            </div>
          </div>

          {/* Queue Position - below current orders */}
          {orderbooks?.STANDX?.['BTC-USD'] && (
            <div className="queue-position-inline">
              {(() => {
                const bids = orderbooks.STANDX!['BTC-USD'].bids
                const asks = orderbooks.STANDX!['BTC-USD'].asks

                // 計算買單位置：我的 bid 在 bids 中排第幾檔
                let bidQueuePos = '-'
                if (bidOrder?.price) {
                  const bidIdx = bids.findIndex(([price]) => price <= bidOrder.price)
                  if (bidIdx === -1) {
                    bidQueuePos = `>${bids.length}`
                  } else if (bids[bidIdx][0] === bidOrder.price) {
                    bidQueuePos = String(bidIdx + 1)
                  } else {
                    bidQueuePos = String(bidIdx + 1)
                  }
                }

                // 計算賣單位置：我的 ask 在 asks 中排第幾檔
                let askQueuePos = '-'
                if (askOrder?.price) {
                  const askIdx = asks.findIndex(([price]) => price >= askOrder.price)
                  if (askIdx === -1) {
                    askQueuePos = `>${asks.length}`
                  } else if (asks[askIdx][0] === askOrder.price) {
                    askQueuePos = String(askIdx + 1)
                  } else {
                    askQueuePos = String(askIdx + 1)
                  }
                }

                return (
                  <div className="queue-inline-row">
                    <span className="queue-item">
                      <span className="queue-label-sm">{t.mm.buyOrderPosition}:</span>
                      <span className={`queue-value-sm ${bidQueuePos !== '-' && parseInt(bidQueuePos) <= 3 ? 'text-warning' : 'text-positive'}`}>
                        {bidQueuePos !== '-' ? `第 ${bidQueuePos} 檔` : '--'}
                      </span>
                    </span>
                    <span className="queue-item">
                      <span className="queue-label-sm">{t.mm.sellOrderPosition}:</span>
                      <span className={`queue-value-sm ${askQueuePos !== '-' && parseInt(askQueuePos) <= 3 ? 'text-warning' : 'text-negative'}`}>
                        {askQueuePos !== '-' ? `第 ${askQueuePos} 檔` : '--'}
                      </span>
                    </span>
                  </div>
                )
              })()}
            </div>
          )}

          {/* Top Stats Grid - 2x2 */}
          <div className="stats-grid-2x2">
            <div className="stat-card">
              <div className="stat-value-large">{formatRunningTime(runningSeconds)}</div>
              <div className="stat-label">{t.mm.runningTime}</div>
            </div>
            <div className="stat-card">
              <div className="stat-value-large">{uptimePercentage.toFixed(1)}%</div>
              <div className="stat-label">{t.mm.effectiveScore}</div>
            </div>
            <div className="stat-card">
              <div className="stat-value-large">{fillCount}</div>
              <div className="stat-label">{t.mm.fillCount}</div>
            </div>
            <div className="stat-card">
              <div className={`stat-value-large ${totalPnl >= 0 ? 'text-positive' : 'text-negative'}`}>
                {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}
              </div>
              <div className="stat-label">{t.mm.livePnl}</div>
            </div>
          </div>

          {/* Tier Distribution */}
          <div className="tier-section">
            <div className="tier-label">{t.mm.tierDistribution} (StandX)</div>
            <div className="tier-bar">
              <div className="tier-segment tier-100" style={{ width: `${tier100Pct}%` }} />
              <div className="tier-segment tier-50" style={{ width: `${tier50Pct}%` }} />
              <div className="tier-segment tier-10" style={{ width: `${tier10Pct}%` }} />
              <div className="tier-segment tier-over" style={{ width: `${tierOverPct}%` }} />
            </div>
            <div className="tier-legend">
              <span><span className="tier-dot tier-100" /> {t.mm.tier100}: {tier100Pct.toFixed(1)}%</span>
              <span><span className="tier-dot tier-50" /> {t.mm.tier50}: {tier50Pct.toFixed(1)}%</span>
              <span><span className="tier-dot tier-10" /> {t.mm.tier10}: {tier10Pct.toFixed(1)}%</span>
              <span><span className="tier-dot tier-over" /> {t.mm.tierOver}: {tierOverPct.toFixed(1)}%</span>
            </div>
          </div>

          {/* Cancel/Queue/Rebalance Stats */}
          <div className="stats-grid-2">
            <div className="stat-card">
              <div className="stat-value text-positive">{bidCancels}/{bidQueueCancels}/{bidRebalances}</div>
              <div className="stat-label">{t.mm.bidStats}</div>
            </div>
            <div className="stat-card">
              <div className="stat-value text-negative">{askCancels}/{askQueueCancels}/{askRebalances}</div>
              <div className="stat-label">{t.mm.askStats}</div>
            </div>
          </div>

          {/* Volatility Status */}
          <div className="volatility-row">
            <div className="volatility-info">
              <span className="volatility-label">{t.mm.volatility}</span>
              <span className="volatility-value">{volatilityBps.toFixed(1)} bps</span>
              <span className={`volatility-status ${isPaused ? 'paused' : 'normal'}`}>
                {isPaused ? t.mm.paused : t.mm.normal}
              </span>
            </div>
            <div className="pause-info">
              {t.mm.pauseCount}: {pauseCount}次
            </div>
          </div>
        </div>

        {/* Maker Hours Estimate */}
        <div className="panel maker-hours-panel">
          <h3 className="panel-title-accent">{t.mm.makerHoursEstimate}</h3>

          {/* MM1 Progress */}
          <div className="progress-section">
            <div className="progress-label">{t.mm.mm1Target}</div>
            <div className="progress-bar-container">
              <div className="progress-bar-fill mm1" style={{ width: `${mm1Progress}%` }} />
              <span className="progress-text">{mm1Progress.toFixed(0)}%</span>
            </div>
          </div>

          {/* MM2 Progress */}
          <div className="progress-section">
            <div className="progress-label">{t.mm.mm2Target}</div>
            <div className="progress-bar-container">
              <div className="progress-bar-fill mm2" style={{ width: `${mm2Progress}%` }} />
              <span className="progress-text">{mm2Progress.toFixed(0)}%</span>
            </div>
          </div>

          {/* Hours Stats */}
          <div className="hours-stats">
            <div className="hours-row">
              <span className="hours-label">{t.mm.perHour}</span>
              <span className="hours-value">{makerHoursPerHour.toFixed(4)}</span>
            </div>
            <div className="hours-row">
              <span className="hours-label">{t.mm.perMonth}</span>
              <span className="hours-value">{makerHoursPerMonth.toFixed(2)}</span>
            </div>
          </div>
        </div>

        {/* Uptime Program Status */}
        <div className="panel uptime-program-panel">
          <h3 className="panel-title-accent">{t.mm.uptimeProgram}</h3>

          {/* Uptime Circle */}
          <div className="uptime-circle-container">
            <svg className="uptime-circle" viewBox="0 0 100 100">
              <circle
                className="uptime-circle-bg"
                cx="50"
                cy="50"
                r="45"
                fill="none"
                strokeWidth="8"
              />
              <circle
                className={`uptime-circle-progress ${uptimeTier}`}
                cx="50"
                cy="50"
                r="45"
                fill="none"
                strokeWidth="8"
                strokeDasharray={`${uptimePercentage * 2.83} 283`}
                strokeLinecap="round"
                transform="rotate(-90 50 50)"
              />
            </svg>
            <div className="uptime-circle-text">
              <div className="uptime-pct">{uptimePercentage.toFixed(1)}%</div>
              <div className={`uptime-tier-label ${uptimeTier}`}>
                {uptimeTier === 'boosted' ? 'BOOSTED' : uptimeTier === 'standard' ? 'STANDARD' : t.mm.inactive}
              </div>
            </div>
          </div>

          {/* Tier Info */}
          <div className="uptime-tiers">
            <div className="uptime-tier-row">
              <span>{t.mm.boosted}</span>
              <span className="tier-multiplier">1.0x</span>
            </div>
            <div className="uptime-tier-row">
              <span>{t.mm.standard}</span>
              <span className="tier-multiplier">0.5x</span>
            </div>
            <div className="uptime-tier-row highlight">
              <span>{t.mm.currentMultiplier}</span>
              <span className="tier-multiplier current">{multiplier}x</span>
            </div>
          </div>
        </div>

        {/* Positions */}
        <div className="panel full-width">
          <h3>{t.mm.positions}</h3>
          <div className="positions-grid">
            <div className="metric-row">
              <span className="metric-label">StandX BTC</span>
              <span className="metric-value">
                {mmPositions?.standx?.btc?.toFixed(6) || '0.000000'}
              </span>
            </div>
            <div className="metric-row">
              <span className="metric-label">StandX 對沖帳戶 BTC</span>
              <span className="metric-value">
                {mmPositions?.grvt?.btc?.toFixed(6) || '0.000000'}
              </span>
            </div>
            <div className="metric-row">
              <span className="metric-label">{t.mm.netPosition}</span>
              <span className={`metric-value ${(mmPositions?.net_btc || 0) >= 0 ? 'text-positive' : 'text-negative'}`}>
                {mmPositions?.net_btc?.toFixed(6) || '0.000000'} BTC
              </span>
            </div>
            <div className="metric-row">
              <span className="metric-label">{t.mm.lastSync}</span>
              <span className="metric-value">
                {mmPositions?.seconds_ago
                  ? `${mmPositions.seconds_ago.toFixed(1)}${t.common.syncAgo}`
                  : 'N/A'}
              </span>
            </div>
          </div>
        </div>

        {/* Hedge Stats */}
        {hedgeConfigured && (
          <div className="panel full-width">
            <h3>對沖統計</h3>

            {/* 基本資訊 */}
            <div className="positions-grid" style={{ marginBottom: '16px' }}>
              <div className="metric-row">
                <span className="metric-label">對沖目標</span>
                <span className="metric-value">StandX 對沖帳戶</span>
              </div>
              <div className="metric-row">
                <span className="metric-label">淨敞口</span>
                <span className={`metric-value ${Math.abs(mmPositions?.net_btc || 0) < 0.0001 ? 'text-positive' : 'text-warning'}`}>
                  {(mmPositions?.net_btc || 0).toFixed(6)} BTC
                  {Math.abs(mmPositions?.net_btc || 0) < 0.0001 ? ' (已對沖)' : ' (待對沖)'}
                </span>
              </div>
              <div className="metric-row">
                <span className="metric-label">成功 / 失敗</span>
                <span className="metric-value">
                  <span className="text-positive">{hedgeStats?.total_success || 0}</span>
                  {' / '}
                  <span className="text-negative">{hedgeStats?.total_failed || 0}</span>
                </span>
              </div>
              <div className="metric-row">
                <span className="metric-label">平均延遲</span>
                <span className="metric-value">
                  {hedgeStats?.avg_latency_ms ? `${hedgeStats.avg_latency_ms.toFixed(0)} ms` : 'N/A'}
                </span>
              </div>
            </div>

            {/* 帳戶對比表格 */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
              {/* 主帳戶 */}
              <div style={{ backgroundColor: 'var(--bg-secondary)', borderRadius: '8px', padding: '12px' }}>
                <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '12px', color: 'var(--text-primary)', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px' }}>
                  主帳戶
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>PnL</span>
                    <span className={`${(mmPositions?.standx?.pnl || 0) >= 0 ? 'text-positive' : 'text-negative'}`} style={{ fontWeight: 'bold' }}>
                      ${(mmPositions?.standx?.pnl || 0).toFixed(2)}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>Margin Ratio</span>
                    <span className={`${
                      mmPositions?.standx?.risk_level === 'danger' ? 'text-negative' :
                      mmPositions?.standx?.risk_level === 'warning' ? 'text-warning' : 'text-positive'
                    }`}>
                      {((mmPositions?.standx?.margin_ratio || 0) * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>清算距離</span>
                    <span className={`${
                      (mmPositions?.standx?.liq_distance_pct || 100) < 5 ? 'text-negative' :
                      (mmPositions?.standx?.liq_distance_pct || 100) < 10 ? 'text-warning' : 'text-positive'
                    }`}>
                      {mmPositions?.standx?.liq_distance_pct != null ? `${mmPositions.standx.liq_distance_pct.toFixed(1)}%` : 'N/A'}
                    </span>
                  </div>
                </div>
              </div>

              {/* 對沖帳戶 */}
              <div style={{ backgroundColor: 'var(--bg-secondary)', borderRadius: '8px', padding: '12px' }}>
                <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '12px', color: 'var(--text-primary)', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px' }}>
                  對沖帳戶
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>PnL</span>
                    <span className={`${(mmPositions?.hedge?.pnl || 0) >= 0 ? 'text-positive' : 'text-negative'}`} style={{ fontWeight: 'bold' }}>
                      ${(mmPositions?.hedge?.pnl || 0).toFixed(2)}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>Margin Ratio</span>
                    <span className={`${
                      mmPositions?.hedge?.risk_level === 'danger' ? 'text-negative' :
                      mmPositions?.hedge?.risk_level === 'warning' ? 'text-warning' : 'text-positive'
                    }`}>
                      {((mmPositions?.hedge?.margin_ratio || 0) * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>清算距離</span>
                    <span className={`${
                      (mmPositions?.hedge?.liq_distance_pct || 100) < 5 ? 'text-negative' :
                      (mmPositions?.hedge?.liq_distance_pct || 100) < 10 ? 'text-warning' : 'text-positive'
                    }`}>
                      {mmPositions?.hedge?.liq_distance_pct != null ? `${mmPositions.hedge.liq_distance_pct.toFixed(1)}%` : 'N/A'}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* 合計淨利潤 */}
            <div style={{ backgroundColor: 'var(--bg-tertiary)', borderRadius: '8px', padding: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '14px', fontWeight: 'bold' }}>合計淨利潤</span>
              <span className={`${(mmPositions?.total_pnl || 0) >= 0 ? 'text-positive' : 'text-negative'}`} style={{ fontSize: '18px', fontWeight: 'bold' }}>
                ${(mmPositions?.total_pnl || 0).toFixed(2)}
              </span>
            </div>

            {/* 危險警告 */}
            {/* 危險警告 */}
            {(mmPositions?.standx?.risk_level === 'danger' || mmPositions?.hedge?.risk_level === 'danger') && (
              <div style={{ marginTop: '12px', padding: '12px', backgroundColor: 'rgba(239, 68, 68, 0.15)', border: '1px solid var(--negative-color)', borderRadius: '8px', color: 'var(--negative-color)', fontWeight: 'bold', textAlign: 'center' }}>
                ⚠️ 爆倉風險警告！請立即減倉或補充保證金
              </div>
            )}
          </div>
        )}

        {/* Fill History */}
        <div className="panel full-width">
          <h3>{t.mm.recentFills} ({fillHistory.length})</h3>
          <div className="fill-history">
            {fillHistory.length > 0 ? (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t.mm.time}</th>
                    <th>{t.mm.side}</th>
                    <th>{t.mm.price}</th>
                    <th>{t.mm.qty}</th>
                    <th>{t.mm.value}</th>
                  </tr>
                </thead>
                <tbody>
                  {fillHistory.slice(0, 10).map((fill, idx) => (
                    <tr key={idx}>
                      <td>{new Date(fill.time).toLocaleTimeString()}</td>
                      <td className={fill.side === 'buy' ? 'text-positive' : 'text-negative'}>
                        {fill.side.toUpperCase()}
                      </td>
                      <td>${fill.price.toFixed(2)}</td>
                      <td>{fill.qty.toFixed(6)}</td>
                      <td>${fill.value.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="text-muted">{t.mm.noFills}</div>
            )}
          </div>
        </div>

        {/* Operation History */}
        <div className="panel full-width">
          <h3>{t.mm.operationHistory} ({operationHistory.length})</h3>
          <div className="operation-history">
            {operationHistory.length > 0 ? (
              <table className="data-table operation-table">
                <thead>
                  <tr>
                    <th>{t.mm.opTime}</th>
                    <th>{t.mm.opAction}</th>
                    <th>{t.mm.opOrderPrice}</th>
                    <th>{t.mm.opReason}</th>
                  </tr>
                </thead>
                <tbody>
                  {operationHistory.slice(0, 20).map((op, idx) => {
                    const actionLabels: Record<string, string> = {
                      place: t.mm.actionPlace,
                      cancel: t.mm.actionCancel,
                      rebalance: t.mm.actionRebalance,
                      fill: t.mm.actionFill,
                      exposure_hedge: '敞口對沖',
                      instant_close: '即時平倉',
                    }
                    const actionColors: Record<string, string> = {
                      place: 'text-positive',
                      cancel: 'text-negative',
                      rebalance: 'text-warning',
                      fill: 'text-info',
                      exposure_hedge: 'text-info',
                      instant_close: 'text-warning',
                    }
                    const sideLabel = op.side === 'buy' ? t.mm.sideBuy : t.mm.sideSell
                    const sideColor = op.side === 'buy' ? 'text-positive' : 'text-negative'
                    const actionLabel = actionLabels[op.action] || op.action
                    const actionColor = actionColors[op.action] || ''

                    // Format time - extract HH:MM:SS
                    let timeStr = op.time || ''
                    if (timeStr.includes('T')) {
                      timeStr = timeStr.split('T')[1]?.split('.')[0] || timeStr
                    }

                    return (
                      <tr key={idx}>
                        <td className="text-muted mono">{timeStr}</td>
                        <td>
                          <span className={sideColor}>{sideLabel}</span>
                          <span className={actionColor}>{actionLabel}</span>
                        </td>
                        <td className="mono">${op.order_price?.toFixed(2) || '--'}</td>
                        <td className="text-muted op-reason">{op.reason || ''}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            ) : (
              <div className="text-muted">{t.mm.noOperations}</div>
            )}
          </div>
        </div>
      </div>

      {/* Footer Status Bar */}
      <div className="status-bar">
        <span>StandX: {mmPositions?.standx?.btc?.toFixed(4) || '0.0000'} BTC</span>
        <span>對沖帳戶: {mmPositions?.grvt?.btc?.toFixed(4) || '0.0000'} BTC</span>
        <span>{t.mm.netExposure}: {mmPositions?.net_btc?.toFixed(4) || '0.0000'}</span>
        <span>對沖: {hedgeConfigured ? 'StandX' : '關閉'}</span>
        <span className="sync-status">
          {t.mm.sync}: {mmPositions?.seconds_ago ? `${mmPositions.seconds_ago.toFixed(1)}${t.common.syncAgo}` : 'N/A'}
        </span>
      </div>
    </div>
  )
}

export default MarketMakerPage

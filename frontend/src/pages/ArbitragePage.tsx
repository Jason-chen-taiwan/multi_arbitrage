import { useOutletContext } from 'react-router-dom'
import type { WebSocketData } from '../hooks/useWebSocket'
import { useI18n } from '../i18n'
import './Page.css'

interface OutletContext {
  isConnected: boolean
  lastMessage: WebSocketData | null
}

function ArbitragePage() {
  const { lastMessage } = useOutletContext<OutletContext>()
  const { t } = useI18n()

  const systemStatus = lastMessage?.system_status
  const marketData = lastMessage?.market_data
  const opportunities = lastMessage?.opportunities || []
  const stats = lastMessage?.stats
  const executorStats = lastMessage?.executor_stats

  return (
    <div className="page">
      <h2 className="page-title">{t.arbitrage.title}</h2>

      {/* Summary Cards */}
      <div className="summary-cards">
        <div className="card">
          <div className="card-title">{t.common.status}</div>
          <div className={`card-value ${systemStatus?.running ? 'text-positive' : 'text-negative'}`}>
            {systemStatus?.running ? t.common.running : t.common.stopped}
          </div>
          <div className="card-subtitle">
            {systemStatus?.dry_run ? t.mm.dryRunMode : t.arbitrage.liveTrading}
          </div>
        </div>

        <div className="card">
          <div className="card-title">Total Updates</div>
          <div className="card-value">{stats?.total_updates?.toLocaleString() || 0}</div>
          <div className="card-subtitle">Market data updates</div>
        </div>

        <div className="card">
          <div className="card-title">{t.arbitrage.opportunities}</div>
          <div className="card-value">{stats?.total_opportunities || 0}</div>
          <div className="card-subtitle">Total detected</div>
        </div>

        <div className="card">
          <div className="card-title">Successful Executions</div>
          <div className="card-value text-positive">
            {executorStats?.successful_executions || 0}
          </div>
          <div className="card-subtitle">
            of {executorStats?.total_attempts || 0} attempts
          </div>
        </div>

        <div className="card">
          <div className="card-title">{t.mm.totalPnl}</div>
          <div className={`card-value ${(executorStats?.total_profit || 0) >= 0 ? 'text-positive' : 'text-negative'}`}>
            ${executorStats?.total_profit?.toFixed(2) || '0.00'}
          </div>
          <div className="card-subtitle">USD</div>
        </div>
      </div>

      {/* Market Data */}
      <div className="content-grid">
        <div className="panel">
          <h3>{t.arbitrage.priceTable}</h3>
          <div className="metrics-list">
            {marketData && Object.entries(marketData).map(([exchange, symbols]) => (
              <div key={exchange}>
                <div className="metric-label" style={{ marginBottom: '8px', fontWeight: 600 }}>
                  {exchange}
                </div>
                {Object.entries(symbols).map(([symbol, data]) => (
                  <div className="metric-row" key={`${exchange}-${symbol}`}>
                    <span className="metric-label">{symbol}</span>
                    <span className="metric-value">
                      ${data.best_bid?.toFixed(2)} / ${data.best_ask?.toFixed(2)}
                    </span>
                  </div>
                ))}
              </div>
            ))}
            {!marketData && (
              <div className="text-muted">{t.arbitrage.noData}</div>
            )}
          </div>
        </div>

        <div className="panel">
          <h3>{t.arbitrage.opportunities} ({opportunities.length})</h3>
          <div className="metrics-list">
            {opportunities.length > 0 ? (
              opportunities.slice(0, 10).map((opp, idx) => (
                <div className="metric-row" key={idx}>
                  <div>
                    <div className="metric-label">
                      Buy {opp.buy_exchange} → Sell {opp.sell_exchange}
                    </div>
                    <div className="text-muted" style={{ fontSize: '12px' }}>
                      {opp.symbol} | Max: {opp.max_quantity} BTC
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="metric-value text-positive">
                      +{opp.profit_pct.toFixed(3)}%
                    </div>
                    <div className="text-muted" style={{ fontSize: '12px' }}>
                      ${opp.profit.toFixed(2)}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-muted">{t.arbitrage.noData}</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default ArbitragePage

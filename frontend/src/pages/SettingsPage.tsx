import { useState, useEffect } from 'react'
import { configApi, controlApi } from '../api/client'
import { useI18n } from '../i18n'
import './Page.css'

interface ExchangeConfig {
  api_key?: string
  api_secret?: string
  private_key?: string
  trading_account_id?: string
  address?: string
  auth_mode?: 'token' | 'wallet'
}

interface ConfigList {
  cex: Record<string, ExchangeConfig>
  dex: Record<string, ExchangeConfig>
  hedge?: {
    target: string
    configured: boolean
    standx?: { configured: boolean }
    grvt?: { configured: boolean }
  }
}

// Predefined exchange options
const EXCHANGE_OPTIONS = {
  dex: ['GRVT', 'STANDX'],
  cex: ['BITGET', 'BINANCE', 'OKX'],
}

function SettingsPage() {
  const { t } = useI18n()
  const [configs, setConfigs] = useState<ConfigList>({ cex: {}, dex: {} })
  const [isLoading, setIsLoading] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Form state
  const [exchangeType, setExchangeType] = useState<'cex' | 'dex'>('dex')
  const [exchangeName, setExchangeName] = useState(EXCHANGE_OPTIONS.dex[0])
  const [authMode, setAuthMode] = useState<'token' | 'wallet'>('wallet')
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [privateKey, setPrivateKey] = useState('')
  const [walletAddress, setWalletAddress] = useState('')
  const [tradingAccountId, setTradingAccountId] = useState('')

  // Hedge config state
  const [hedgeTarget, setHedgeTarget] = useState<'grvt' | 'standx_hedge' | 'none'>('grvt')
  const [hedgeApiToken, setHedgeApiToken] = useState('')
  const [hedgePrivateKey, setHedgePrivateKey] = useState('')
  const [hedgeConfigured, setHedgeConfigured] = useState(false)
  const [hedgeMaskedToken, setHedgeMaskedToken] = useState('')
  const [hedgeMaskedKey, setHedgeMaskedKey] = useState('')

  const loadConfigs = async () => {
    try {
      const response = await configApi.list()
      setConfigs(response.data)

      // Load hedge config
      if (response.data.hedge) {
        setHedgeTarget(response.data.hedge.target as 'grvt' | 'standx_hedge' | 'none')
        setHedgeConfigured(
          response.data.hedge.target === 'none' ||
          (response.data.hedge.target === 'grvt' && response.data.hedge.grvt?.configured) ||
          (response.data.hedge.target === 'standx_hedge' && response.data.hedge.standx?.configured) ||
          false
        )
      }
    } catch (error) {
      console.error('Failed to load configs:', error)
    }
  }

  const loadHedgeConfig = async () => {
    try {
      const response = await configApi.getHedgeConfig()
      if (response.data) {
        setHedgeTarget(response.data.hedge_target || 'grvt')
        setHedgeConfigured(response.data.configured || false)
        setHedgeMaskedToken(response.data.api_token_masked || '')
        setHedgeMaskedKey(response.data.ed25519_key_masked || '')
      }
    } catch (error) {
      console.error('Failed to load hedge config:', error)
    }
  }

  useEffect(() => {
    loadConfigs()
    loadHedgeConfig()
  }, [])

  const handleSaveConfig = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setMessage(null)

    try {
      const config: ExchangeConfig = {}

      if (exchangeType === 'cex') {
        // CEX: API Key + API Secret
        config.api_key = apiKey
        config.api_secret = apiSecret
      } else if (exchangeName === 'GRVT') {
        // GRVT: API Key + API Secret (Private Key) + Trading Account ID
        config.api_key = apiKey
        config.api_secret = apiSecret
        config.trading_account_id = tradingAccountId
      } else if (exchangeName === 'STANDX') {
        // STANDX: Two modes - Token or Wallet
        config.auth_mode = authMode
        if (authMode === 'token') {
          config.api_key = apiKey
          config.private_key = privateKey
        } else {
          // Wallet signature mode
          config.private_key = privateKey
          config.address = walletAddress
        }
      } else {
        // Other DEX: API Key + Private Key
        config.api_key = apiKey
        config.private_key = privateKey
      }

      await configApi.save({
        exchange_name: exchangeName.toUpperCase(),
        exchange_type: exchangeType,
        config: config as Record<string, unknown>,
      })

      setMessage({ type: 'success', text: t.settings.savedConfig })
      loadConfigs()

      // Reset form
      setExchangeName(EXCHANGE_OPTIONS[exchangeType][0])
      setAuthMode('wallet')
      setApiKey('')
      setApiSecret('')
      setPrivateKey('')
      setWalletAddress('')
      setTradingAccountId('')
    } catch (error) {
      setMessage({ type: 'error', text: t.settings.failedSave })
    } finally {
      setIsLoading(false)
    }
  }

  const handleDeleteConfig = async (name: string, type: 'cex' | 'dex') => {
    if (!confirm(`Delete ${name} configuration?`)) return

    setIsLoading(true)
    try {
      await configApi.delete({ exchange_name: name, exchange_type: type })
      setMessage({ type: 'success', text: t.settings.deletedConfig })
      loadConfigs()
    } catch (error) {
      setMessage({ type: 'error', text: t.settings.failedDelete })
    } finally {
      setIsLoading(false)
    }
  }

  const handleReinit = async () => {
    setIsLoading(true)
    setMessage(null)
    try {
      const response = await controlApi.reinit()
      if (response.data.success) {
        setMessage({ type: 'success', text: t.settings.reinitialized })
      } else {
        setMessage({ type: 'error', text: t.settings.reinitFailed })
      }
    } catch (error) {
      setMessage({ type: 'error', text: t.settings.reinitFailed })
    } finally {
      setIsLoading(false)
    }
  }

  const handleReconnect = async () => {
    setIsLoading(true)
    setMessage(null)
    try {
      const response = await configApi.reconnect()
      if (response.data.success) {
        setMessage({ type: 'success', text: t.settings.reconnected })
      } else {
        setMessage({ type: 'error', text: t.settings.reconnectFailed })
      }
    } catch (error) {
      setMessage({ type: 'error', text: t.settings.reconnectFailed })
    } finally {
      setIsLoading(false)
    }
  }

  const handleSaveHedgeConfig = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setMessage(null)

    try {
      const hedgeConfig: Record<string, string> = {
        hedge_target: hedgeTarget,
      }

      if (hedgeTarget === 'standx_hedge') {
        if (hedgeApiToken) hedgeConfig.api_token = hedgeApiToken
        if (hedgePrivateKey) hedgeConfig.ed25519_private_key = hedgePrivateKey
      }

      await configApi.saveHedgeConfig(hedgeConfig)
      setMessage({ type: 'success', text: '對沖配置已保存。請重新連接交易所以啟用新配置。' })

      // Reset form and reload config
      setHedgeApiToken('')
      setHedgePrivateKey('')
      loadHedgeConfig()
    } catch (error) {
      setMessage({ type: 'error', text: '保存對沖配置失敗' })
    } finally {
      setIsLoading(false)
    }
  }

  const allConfigs = [
    ...Object.entries(configs.cex).map(([name, config]) => ({ name, type: 'cex' as const, config })),
    ...Object.entries(configs.dex).map(([name, config]) => ({ name, type: 'dex' as const, config })),
  ]

  return (
    <div className="page">
      <h2 className="page-title">{t.settings.title}</h2>

      {message && (
        <div className={`alert ${message.type === 'success' ? 'alert-success' : 'alert-error'}`}>
          {message.text}
        </div>
      )}

      <div className="content-grid">
        {/* Add Exchange Form */}
        <div className="panel">
          <h3>{t.settings.addExchange}</h3>
          <form onSubmit={handleSaveConfig} className="form">
            {/* Two-column layout for Type and Exchange */}
            <div className="form-row">
              <div className="form-group">
                <label>{t.settings.exchangeType}</label>
                <select
                  value={exchangeType}
                  onChange={(e) => {
                    const newType = e.target.value as 'cex' | 'dex'
                    setExchangeType(newType)
                    setExchangeName(EXCHANGE_OPTIONS[newType][0])
                  }}
                >
                  <option value="dex">DEX (去中心化)</option>
                  <option value="cex">CEX (中心化)</option>
                </select>
              </div>

              <div className="form-group">
                <label>{t.settings.selectExchange}</label>
                <select
                  value={exchangeName}
                  onChange={(e) => setExchangeName(e.target.value)}
                >
                  {EXCHANGE_OPTIONS[exchangeType].map((exchange) => (
                    <option key={exchange} value={exchange}>
                      {exchange}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* STANDX Auth Mode Selection */}
            {exchangeName === 'STANDX' && (
              <div className="form-group">
                <label>{t.settings.authMode}</label>
                <select
                  value={authMode}
                  onChange={(e) => setAuthMode(e.target.value as 'token' | 'wallet')}
                >
                  <option value="wallet">錢包簽名模式</option>
                  <option value="token">Token 模式</option>
                </select>
              </div>
            )}

            {/* CEX fields */}
            {exchangeType === 'cex' && (
              <>
                <div className="form-group">
                  <label>API Key</label>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={`${exchangeName} API Key`}
                    required
                  />
                </div>
                <div className="form-group">
                  <label>API Secret</label>
                  <input
                    type="password"
                    value={apiSecret}
                    onChange={(e) => setApiSecret(e.target.value)}
                    placeholder={`${exchangeName} API Secret`}
                    required
                  />
                </div>
              </>
            )}

            {/* GRVT fields */}
            {exchangeName === 'GRVT' && (
              <>
                <div className="form-group">
                  <label>API Key</label>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="GRVT API Key"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>API Secret</label>
                  <input
                    type="password"
                    value={apiSecret}
                    onChange={(e) => setApiSecret(e.target.value)}
                    placeholder="GRVT API Secret (Private Key)"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Trading Account ID</label>
                  <input
                    type="text"
                    value={tradingAccountId}
                    onChange={(e) => setTradingAccountId(e.target.value)}
                    placeholder="子帳戶 ID (從 GRVT API 管理頁面獲取)"
                    required
                  />
                </div>
              </>
            )}

            {/* STANDX Token mode fields */}
            {exchangeName === 'STANDX' && authMode === 'token' && (
              <>
                <div className="form-group">
                  <label>API Key</label>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="StandX API Key"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>{t.settings.privateKey}</label>
                  <input
                    type="password"
                    value={privateKey}
                    onChange={(e) => setPrivateKey(e.target.value)}
                    placeholder="StandX Private Key"
                    required
                  />
                </div>
              </>
            )}

            {/* STANDX Wallet mode fields */}
            {exchangeName === 'STANDX' && authMode === 'wallet' && (
              <>
                <div className="form-group">
                  <label>Private Key</label>
                  <input
                    type="password"
                    value={privateKey}
                    onChange={(e) => setPrivateKey(e.target.value)}
                    placeholder="錢包私鑰"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Wallet Address</label>
                  <input
                    type="text"
                    value={walletAddress}
                    onChange={(e) => setWalletAddress(e.target.value)}
                    placeholder="錢包地址"
                    required
                  />
                </div>
              </>
            )}

            <button type="submit" className="btn btn-primary" disabled={isLoading}>
              {isLoading ? t.common.loading : t.settings.saveAndStart}
            </button>
          </form>
        </div>

        {/* Configured Exchanges */}
        <div className="panel">
          <h3>{t.settings.configuredExchanges}</h3>
          <div className="exchange-list">
            {allConfigs.length > 0 ? (
              allConfigs.map(({ name, type }) => (
                <div key={`${type}-${name}`} className="exchange-item">
                  <div className="exchange-info">
                    <span className="exchange-name">{name}</span>
                    <span className={`exchange-type ${type}`}>{type.toUpperCase()}</span>
                  </div>
                  <button
                    className="btn btn-sm btn-danger"
                    onClick={() => handleDeleteConfig(name, type)}
                    disabled={isLoading}
                  >
                    {t.common.delete}
                  </button>
                </div>
              ))
            ) : (
              <div className="text-muted">{t.settings.noExchanges}</div>
            )}
          </div>
        </div>

        {/* Hedge Account Configuration */}
        <div className="panel">
          <h3>對沖帳戶配置</h3>
          <form onSubmit={handleSaveHedgeConfig} className="form">
            <div className="form-group">
              <label>對沖目標</label>
              <select
                value={hedgeTarget}
                onChange={(e) => setHedgeTarget(e.target.value as 'grvt' | 'standx_hedge' | 'none')}
              >
                <option value="grvt">GRVT (DEX)</option>
                <option value="standx_hedge">StandX 對沖帳戶</option>
                <option value="none">不對沖</option>
              </select>
              <small className="form-hint">
                {hedgeTarget === 'grvt' && '使用 GRVT 交易所對沖（需先配置 GRVT）'}
                {hedgeTarget === 'standx_hedge' && '使用另一個 StandX 帳戶對沖'}
                {hedgeTarget === 'none' && '做市商成交後不執行對沖操作'}
              </small>
            </div>

            {hedgeTarget === 'standx_hedge' && (
              <>
                {/* 顯示已配置的帳戶資訊 */}
                {hedgeConfigured && hedgeMaskedToken && (
                  <div className="form-group">
                    <label>目前配置</label>
                    <div className="configured-info">
                      <div><strong>API Token:</strong> <code>{hedgeMaskedToken}</code></div>
                      <div><strong>Ed25519 Key:</strong> <code>{hedgeMaskedKey}</code></div>
                    </div>
                  </div>
                )}
                <div className="form-group">
                  <label>API Token (對沖帳戶) {hedgeConfigured && '(留空保留現有)'}</label>
                  <input
                    type="password"
                    value={hedgeApiToken}
                    onChange={(e) => setHedgeApiToken(e.target.value)}
                    placeholder={hedgeConfigured ? '留空保留現有 Token' : 'StandX 對沖帳戶的 API Token'}
                  />
                </div>
                <div className="form-group">
                  <label>Ed25519 Private Key (對沖帳戶) {hedgeConfigured && '(留空保留現有)'}</label>
                  <input
                    type="password"
                    value={hedgePrivateKey}
                    onChange={(e) => setHedgePrivateKey(e.target.value)}
                    placeholder={hedgeConfigured ? '留空保留現有 Key' : 'StandX 對沖帳戶的 Ed25519 Private Key'}
                  />
                </div>
              </>
            )}

            <div className="form-group">
              <span className={`status-badge ${hedgeConfigured ? 'status-success' : 'status-warning'}`}>
                {hedgeConfigured ? '已配置' : '未配置'}
              </span>
            </div>

            <button type="submit" className="btn btn-primary" disabled={isLoading}>
              {isLoading ? t.common.loading : '保存對沖配置'}
            </button>
          </form>
        </div>

        {/* System Controls */}
        <div className="panel">
          <h3>{t.settings.systemControls}</h3>
          <div className="button-group">
            <button
              className="btn btn-secondary"
              onClick={handleReconnect}
              disabled={isLoading}
            >
              {t.settings.reconnectAll}
            </button>
            <button
              className="btn btn-warning"
              onClick={handleReinit}
              disabled={isLoading}
            >
              {t.settings.reinitSystem}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default SettingsPage

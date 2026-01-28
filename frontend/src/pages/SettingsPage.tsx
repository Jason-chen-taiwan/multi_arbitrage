import { useState, useEffect } from 'react'
import { configApi, controlApi, mmApi, accountsApi, strategiesApi, CreateAccountData, CreateStrategyData, AccountInfo, StrategyInfo } from '../api/client'
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

  // ==================== 帳號池狀態 ====================
  const [accounts, setAccounts] = useState<AccountInfo[]>([])
  const [showAddAccountForm, setShowAddAccountForm] = useState(false)
  const [newAccount, setNewAccount] = useState<CreateAccountData>({
    id: '',
    name: '',
    exchange: 'standx',
    api_token: '',
    ed25519_private_key: '',
    proxy: { url: '', username: '', password: '' }
  })

  // ==================== 策略狀態 ====================
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [showAddStrategyForm, setShowAddStrategyForm] = useState(false)
  const [newStrategy, setNewStrategy] = useState<CreateStrategyData>({
    id: '',
    name: '',
    enabled: true,
    main_account_id: '',
    hedge_account_id: '',
    trading: { symbol: 'BTC-USD', order_size_btc: '0.01', max_position_btc: '0.05', order_distance_bps: 8 }
  })

  // ==================== 載入函數 ====================

  const loadAccounts = async () => {
    try {
      const response = await accountsApi.list()
      setAccounts(response.data.accounts || [])
    } catch (error) {
      console.error('Failed to load accounts:', error)
    }
  }

  const loadStrategies = async () => {
    try {
      const response = await strategiesApi.list()
      setStrategies(response.data.strategies || [])
    } catch (error) {
      console.error('Failed to load strategies:', error)
    }
  }

  const loadConfigs = async () => {
    try {
      const response = await configApi.list()
      setConfigs(response.data)
    } catch (error) {
      console.error('Failed to load configs:', error)
    }
  }

  useEffect(() => {
    loadConfigs()
    loadAccounts()
    loadStrategies()
  }, [])

  // ==================== 帳號操作 ====================

  const handleCreateAccount = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setMessage(null)

    try {
      const response = await accountsApi.create(newAccount)
      if (response.data.success) {
        setMessage({ type: 'success', text: response.data.message || '帳號已新增' })
        setShowAddAccountForm(false)
        setNewAccount({
          id: '',
          name: '',
          exchange: 'standx',
          api_token: '',
          ed25519_private_key: '',
          proxy: { url: '', username: '', password: '' }
        })
        loadAccounts()
      } else {
        setMessage({ type: 'error', text: response.data.error || '新增失敗' })
      }
    } catch (error) {
      setMessage({ type: 'error', text: '新增帳號失敗' })
    } finally {
      setIsLoading(false)
    }
  }

  const handleDeleteAccount = async (accountId: string) => {
    if (!confirm(`確定要刪除帳號 "${accountId}"？`)) return

    setIsLoading(true)
    try {
      const response = await accountsApi.delete(accountId)
      if (response.data.success) {
        setMessage({ type: 'success', text: '帳號已刪除' })
        loadAccounts()
      } else {
        setMessage({ type: 'error', text: response.data.error || '刪除失敗' })
      }
    } catch (error) {
      setMessage({ type: 'error', text: '刪除帳號失敗' })
    } finally {
      setIsLoading(false)
    }
  }

  // ==================== 策略操作 ====================

  const handleCreateStrategy = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setMessage(null)

    try {
      const response = await strategiesApi.create(newStrategy)
      if (response.data.success) {
        setMessage({ type: 'success', text: response.data.message || '策略已新增' })
        setShowAddStrategyForm(false)
        setNewStrategy({
          id: '',
          name: '',
          enabled: true,
          main_account_id: '',
          hedge_account_id: '',
          trading: { symbol: 'BTC-USD', order_size_btc: '0.01', max_position_btc: '0.05', order_distance_bps: 8 }
        })
        loadStrategies()
      } else {
        setMessage({ type: 'error', text: response.data.error || '新增失敗' })
      }
    } catch (error) {
      setMessage({ type: 'error', text: '新增策略失敗' })
    } finally {
      setIsLoading(false)
    }
  }

  const handleDeleteStrategy = async (strategyId: string) => {
    if (!confirm(`確定要刪除策略 "${strategyId}"？`)) return

    setIsLoading(true)
    try {
      const response = await strategiesApi.delete(strategyId)
      if (response.data.success) {
        setMessage({ type: 'success', text: '策略已刪除' })
        loadStrategies()
      } else {
        setMessage({ type: 'error', text: response.data.error || '刪除失敗' })
      }
    } catch (error) {
      setMessage({ type: 'error', text: '刪除策略失敗' })
    } finally {
      setIsLoading(false)
    }
  }

  const handleToggleStrategy = async (strategyId: string, currentEnabled: boolean) => {
    setIsLoading(true)
    try {
      const response = await strategiesApi.update(strategyId, { enabled: !currentEnabled })
      if (response.data.success) {
        setMessage({ type: 'success', text: `策略已${!currentEnabled ? '啟用' : '停用'}` })
        loadStrategies()
      } else {
        setMessage({ type: 'error', text: response.data.error || '更新失敗' })
      }
    } catch (error) {
      setMessage({ type: 'error', text: '更新策略失敗' })
    } finally {
      setIsLoading(false)
    }
  }

  // ==================== 其他操作 ====================

  const handleSaveConfig = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setMessage(null)

    try {
      const config: ExchangeConfig = {}

      if (exchangeType === 'cex') {
        config.api_key = apiKey
        config.api_secret = apiSecret
      } else if (exchangeName === 'GRVT') {
        config.api_key = apiKey
        config.api_secret = apiSecret
        config.trading_account_id = tradingAccountId
      } else if (exchangeName === 'STANDX') {
        config.auth_mode = authMode
        if (authMode === 'token') {
          config.api_key = apiKey
          config.private_key = privateKey
        } else {
          config.private_key = privateKey
          config.address = walletAddress
        }
      } else {
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
        const results = response.data.results || {}
        const successList = Object.entries(results)
          .filter(([, r]) => (r as { success: boolean }).success)
          .map(([name]) => name)
        const failList = Object.entries(results)
          .filter(([, r]) => !(r as { success: boolean }).success)
          .map(([name, r]) => `${name}: ${(r as { error?: string }).error || '失敗'}`)

        let msg = `重新連接完成: ${successList.join(', ') || '無'}`
        if (failList.length > 0) {
          msg += `\n失敗: ${failList.join(', ')}`
        }
        if (response.data.message) {
          msg += `\n${response.data.message}`
        }
        setMessage({ type: 'success', text: msg })
      } else {
        setMessage({ type: 'error', text: response.data.error || t.settings.reconnectFailed })
      }
    } catch (error) {
      setMessage({ type: 'error', text: t.settings.reconnectFailed })
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
        {/* ==================== 帳號池管理 ==================== */}
        <div className="panel">
          <h3>帳號池管理</h3>
          <p className="form-hint" style={{ marginBottom: 'var(--spacing-md)' }}>
            管理交易所帳號。每個帳號可設定代理（女巫防護），並可在多個策略中重複使用。
          </p>

          {/* Account List */}
          <div className="exchange-list" style={{ marginBottom: 'var(--spacing-lg)' }}>
            {accounts.length > 0 ? (
              accounts.map((account) => (
                <div key={account.id} className="exchange-item">
                  <div className="exchange-info">
                    <span className="exchange-name">{account.name}</span>
                    <span className="exchange-type dex">{account.exchange.toUpperCase()}</span>
                    {account.has_proxy && (
                      <span style={{ marginLeft: '8px', fontSize: '0.75em', color: 'var(--color-success)' }}>
                        有代理
                      </span>
                    )}
                    {account.used_by_strategies.length > 0 && (
                      <span style={{ marginLeft: '8px', fontSize: '0.75em', color: 'var(--text-muted)' }}>
                        用於 {account.used_by_strategies.length} 個策略
                      </span>
                    )}
                  </div>
                  <button
                    className="btn btn-sm btn-danger"
                    onClick={() => handleDeleteAccount(account.id)}
                    disabled={isLoading || account.used_by_strategies.length > 0}
                    title={account.used_by_strategies.length > 0 ? '帳號正被策略使用，無法刪除' : ''}
                  >
                    刪除
                  </button>
                </div>
              ))
            ) : (
              <div className="text-muted">尚未配置帳號。點擊下方按鈕新增帳號。</div>
            )}
          </div>

          {/* Add Account Form */}
          {!showAddAccountForm ? (
            <button
              className="btn btn-secondary"
              onClick={() => setShowAddAccountForm(true)}
            >
              新增帳號
            </button>
          ) : (
            <form onSubmit={handleCreateAccount} className="form">
              <h4 style={{ marginBottom: 'var(--spacing-md)' }}>新增帳號</h4>

              <div className="form-row">
                <div className="form-group">
                  <label>帳號 ID</label>
                  <input
                    type="text"
                    value={newAccount.id}
                    onChange={(e) => setNewAccount({ ...newAccount, id: e.target.value })}
                    placeholder="acc_main_1"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>帳號名稱</label>
                  <input
                    type="text"
                    value={newAccount.name}
                    onChange={(e) => setNewAccount({ ...newAccount, name: e.target.value })}
                    placeholder="我的主帳號"
                    required
                  />
                </div>
              </div>

              <div className="form-group">
                <label>交易所</label>
                <select
                  value={newAccount.exchange}
                  onChange={(e) => setNewAccount({ ...newAccount, exchange: e.target.value })}
                >
                  <option value="standx">StandX</option>
                </select>
              </div>

              <div className="form-group">
                <label>API Token</label>
                <input
                  type="password"
                  value={newAccount.api_token}
                  onChange={(e) => setNewAccount({ ...newAccount, api_token: e.target.value })}
                  placeholder="StandX API Token"
                  required
                />
              </div>
              <div className="form-group">
                <label>Ed25519 Private Key</label>
                <input
                  type="password"
                  value={newAccount.ed25519_private_key}
                  onChange={(e) => setNewAccount({ ...newAccount, ed25519_private_key: e.target.value })}
                  placeholder="StandX Ed25519 Private Key"
                  required
                />
              </div>

              <div className="form-group" style={{ marginTop: 'var(--spacing-md)', borderTop: '1px solid var(--border-color)', paddingTop: 'var(--spacing-md)' }}>
                <label style={{ fontWeight: 'bold' }}>代理設定（選填）</label>
                <small className="form-hint">讓此帳號走不同 IP，用於女巫防護</small>
              </div>

              <div className="form-group">
                <label>Proxy URL</label>
                <input
                  type="text"
                  value={newAccount.proxy?.url || ''}
                  onChange={(e) => setNewAccount({
                    ...newAccount,
                    proxy: { ...newAccount.proxy, url: e.target.value }
                  })}
                  placeholder="socks5://host:port"
                />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Proxy Username (可選)</label>
                  <input
                    type="text"
                    value={newAccount.proxy?.username || ''}
                    onChange={(e) => setNewAccount({
                      ...newAccount,
                      proxy: { ...newAccount.proxy, username: e.target.value }
                    })}
                    placeholder="用戶名"
                  />
                </div>
                <div className="form-group">
                  <label>Proxy Password (可選)</label>
                  <input
                    type="password"
                    value={newAccount.proxy?.password || ''}
                    onChange={(e) => setNewAccount({
                      ...newAccount,
                      proxy: { ...newAccount.proxy, password: e.target.value }
                    })}
                    placeholder="密碼"
                  />
                </div>
              </div>

              <div className="button-group" style={{ marginTop: 'var(--spacing-md)' }}>
                <button type="submit" className="btn btn-primary" disabled={isLoading}>
                  {isLoading ? '處理中...' : '新增帳號'}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowAddAccountForm(false)}
                >
                  取消
                </button>
              </div>
            </form>
          )}
        </div>

        {/* ==================== 策略配置 ==================== */}
        <div className="panel">
          <h3>策略配置</h3>
          <p className="form-hint" style={{ marginBottom: 'var(--spacing-md)' }}>
            配置做市策略。從帳號池選擇主帳號和對沖帳號，設定交易參數。
          </p>

          {/* Strategy List */}
          <div className="exchange-list" style={{ marginBottom: 'var(--spacing-lg)' }}>
            {strategies.length > 0 ? (
              strategies.map((strategy) => (
                <div key={strategy.id} className="exchange-item">
                  <div className="exchange-info" style={{ flex: 1 }}>
                    <span className="exchange-name">{strategy.name}</span>
                    <span
                      className={`exchange-type ${strategy.enabled ? 'dex' : 'cex'}`}
                      style={{ cursor: 'pointer' }}
                      onClick={() => handleToggleStrategy(strategy.id, strategy.enabled)}
                      title="點擊切換啟用狀態"
                    >
                      {strategy.enabled ? '已啟用' : '已停用'}
                    </span>
                    <div style={{ fontSize: '0.8em', color: 'var(--text-muted)', marginTop: '4px' }}>
                      主帳號: {strategy.main_account_name} | 對沖: {strategy.hedge_account_name}
                    </div>
                    <div style={{ fontSize: '0.75em', color: 'var(--text-muted)' }}>
                      {strategy.trading.symbol} | {strategy.trading.order_size_btc} BTC | {strategy.trading.order_distance_bps} bps
                    </div>
                  </div>
                  <button
                    className="btn btn-sm btn-danger"
                    onClick={() => handleDeleteStrategy(strategy.id)}
                    disabled={isLoading}
                  >
                    刪除
                  </button>
                </div>
              ))
            ) : (
              <div className="text-muted">尚未配置策略。請先新增帳號，然後配置策略。</div>
            )}
          </div>

          {/* Add Strategy Form */}
          {!showAddStrategyForm ? (
            <button
              className="btn btn-secondary"
              onClick={() => setShowAddStrategyForm(true)}
              disabled={accounts.length < 2}
              title={accounts.length < 2 ? '請先新增至少 2 個帳號' : ''}
            >
              新增策略
            </button>
          ) : (
            <form onSubmit={handleCreateStrategy} className="form">
              <h4 style={{ marginBottom: 'var(--spacing-md)' }}>新增策略</h4>

              <div className="form-row">
                <div className="form-group">
                  <label>策略 ID</label>
                  <input
                    type="text"
                    value={newStrategy.id}
                    onChange={(e) => setNewStrategy({ ...newStrategy, id: e.target.value })}
                    placeholder="strategy_1"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>策略名稱</label>
                  <input
                    type="text"
                    value={newStrategy.name}
                    onChange={(e) => setNewStrategy({ ...newStrategy, name: e.target.value })}
                    placeholder="主策略"
                    required
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>主帳號（做市）</label>
                  <select
                    value={newStrategy.main_account_id}
                    onChange={(e) => setNewStrategy({ ...newStrategy, main_account_id: e.target.value })}
                    required
                  >
                    <option value="">選擇帳號...</option>
                    {accounts.map((acc) => (
                      <option key={acc.id} value={acc.id}>{acc.name}</option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label>對沖帳號</label>
                  <select
                    value={newStrategy.hedge_account_id}
                    onChange={(e) => setNewStrategy({ ...newStrategy, hedge_account_id: e.target.value })}
                    required
                  >
                    <option value="">選擇帳號...</option>
                    {accounts.map((acc) => (
                      <option key={acc.id} value={acc.id}>{acc.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <h5 style={{ marginTop: 'var(--spacing-md)', marginBottom: 'var(--spacing-sm)' }}>交易參數</h5>
              <div className="form-row">
                <div className="form-group">
                  <label>訂單大小 (BTC)</label>
                  <input
                    type="text"
                    value={newStrategy.trading.order_size_btc}
                    onChange={(e) => setNewStrategy({
                      ...newStrategy,
                      trading: { ...newStrategy.trading, order_size_btc: e.target.value }
                    })}
                    placeholder="0.01"
                  />
                </div>
                <div className="form-group">
                  <label>最大倉位 (BTC)</label>
                  <input
                    type="text"
                    value={newStrategy.trading.max_position_btc}
                    onChange={(e) => setNewStrategy({
                      ...newStrategy,
                      trading: { ...newStrategy.trading, max_position_btc: e.target.value }
                    })}
                    placeholder="0.05"
                  />
                </div>
                <div className="form-group">
                  <label>掛單距離 (bps)</label>
                  <input
                    type="number"
                    value={newStrategy.trading.order_distance_bps}
                    onChange={(e) => setNewStrategy({
                      ...newStrategy,
                      trading: { ...newStrategy.trading, order_distance_bps: parseInt(e.target.value) || 8 }
                    })}
                    placeholder="8"
                  />
                </div>
              </div>

              <div className="button-group" style={{ marginTop: 'var(--spacing-md)' }}>
                <button type="submit" className="btn btn-primary" disabled={isLoading}>
                  {isLoading ? '處理中...' : '新增策略'}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowAddStrategyForm(false)}
                >
                  取消
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Add Exchange Form (Legacy - for single account mode) */}
        <div className="panel">
          <h3>{t.settings.addExchange}</h3>
          <p className="form-hint" style={{ marginBottom: 'var(--spacing-md)' }}>
            單帳號模式交易所配置（向後兼容）
          </p>
          <form onSubmit={handleSaveConfig} className="form">
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
                    placeholder="子帳戶 ID"
                    required
                  />
                </div>
              </>
            )}

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

        {/* Emergency Close Position */}
        <div className="panel">
          <h3>緊急平倉</h3>
          <p className="form-hint" style={{ marginBottom: 'var(--spacing-md)' }}>
            手動使用市價單平掉指定帳戶的倉位。此操作不可逆，請謹慎使用。
          </p>
          <div className="button-group">
            <button
              className="btn btn-warning"
              onClick={async () => {
                if (!confirm('確定要平掉主帳戶所有倉位嗎？')) return
                setIsLoading(true)
                try {
                  const response = await mmApi.closeAllPositions('main')
                  if (response.data.success) {
                    setMessage({ type: 'success', text: '主帳戶平倉成功' })
                  } else {
                    setMessage({ type: 'error', text: response.data.error || '平倉失敗' })
                  }
                } catch {
                  setMessage({ type: 'error', text: '平倉請求失敗' })
                } finally {
                  setIsLoading(false)
                }
              }}
              disabled={isLoading}
            >
              平倉主帳戶
            </button>
            <button
              className="btn btn-warning"
              onClick={async () => {
                if (!confirm('確定要平掉對沖帳戶所有倉位嗎？')) return
                setIsLoading(true)
                try {
                  const response = await mmApi.closeAllPositions('hedge')
                  if (response.data.success) {
                    setMessage({ type: 'success', text: '對沖帳戶平倉成功' })
                  } else {
                    setMessage({ type: 'error', text: response.data.error || '平倉失敗' })
                  }
                } catch {
                  setMessage({ type: 'error', text: '平倉請求失敗' })
                } finally {
                  setIsLoading(false)
                }
              }}
              disabled={isLoading}
            >
              平倉對沖帳戶
            </button>
            <button
              className="btn btn-danger"
              onClick={async () => {
                if (!confirm('確定要平掉所有帳戶的倉位嗎？')) return
                setIsLoading(true)
                try {
                  const response = await mmApi.closeAllPositions('both')
                  if (response.data.success) {
                    setMessage({ type: 'success', text: '所有帳戶平倉成功' })
                  } else {
                    setMessage({ type: 'error', text: response.data.error || '平倉失敗' })
                  }
                } catch {
                  setMessage({ type: 'error', text: '平倉請求失敗' })
                } finally {
                  setIsLoading(false)
                }
              }}
              disabled={isLoading}
            >
              平倉所有帳戶
            </button>
          </div>
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

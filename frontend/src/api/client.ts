import axios, { AxiosInstance, AxiosError } from 'axios'

// API base URL - in development, Vite proxy handles this
const API_BASE_URL = '/api'

// Create axios instance with default config
const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response) {
      // Server responded with error status
      console.error('API Error:', error.response.status, error.response.data)
    } else if (error.request) {
      // Request made but no response
      console.error('Network Error:', error.message)
    } else {
      // Error in request setup
      console.error('Request Error:', error.message)
    }
    return Promise.reject(error)
  }
)

// API functions

// Config endpoints
export const configApi = {
  list: () => apiClient.get('/config/list'),
  save: (data: { exchange_name: string; exchange_type: string; config: Record<string, unknown> }) =>
    apiClient.post('/config/save', data),
  delete: (data: { exchange_name: string; exchange_type: string }) =>
    apiClient.post('/config/delete', data),
  health: () => apiClient.get('/config/health'),
  healthExchange: (exchange: string) => apiClient.get(`/config/health/${exchange}`),
  reconnect: () => apiClient.post('/config/reconnect'),
  // Hedge config endpoints
  getHedgeConfig: () => apiClient.get('/config/hedge'),
  saveHedgeConfig: (data: Record<string, string>) => apiClient.post('/config/hedge', data),
}

// Control endpoints
export const controlApi = {
  reinit: () => apiClient.post('/system/reinit'),
  autoExecute: (enabled: boolean) => apiClient.post('/control/auto-execute', { enabled }),
  liveTrade: (enabled: boolean) => apiClient.post('/control/live-trade', { enabled }),
}

// Market Maker endpoints
export const mmApi = {
  start: (data: { order_size?: number; order_distance?: number }) =>
    apiClient.post('/mm/start', data),
  stop: () => apiClient.post('/mm/stop'),
  status: () => apiClient.get('/mm/status'),
  positions: () => apiClient.get('/mm/positions'),
  getConfig: () => apiClient.get('/mm/config'),
  updateConfig: (data: Record<string, unknown>) => apiClient.post('/mm/config', data),
  reloadConfig: () => apiClient.post('/mm/config/reload'),
  // Close all positions with market orders
  closeAllPositions: (account: 'main' | 'hedge' | 'both') =>
    apiClient.post('/mm/close-positions', { account }),
  // Runtime controls
  getRuntimeControls: () => apiClient.get('/mm/runtime/controls'),
  setHedgeEnabled: (enabled: boolean) =>
    apiClient.post('/mm/runtime/hedge', { enabled }),
  setInstantCloseEnabled: (enabled: boolean) =>
    apiClient.post('/mm/runtime/instant-close', { enabled }),
  // Liquidation protection
  getLiquidationProtection: () => apiClient.get('/mm/liquidation-protection'),
  setLiquidationProtection: (config: {
    enabled?: boolean
    margin_ratio_threshold?: number
    liq_distance_threshold?: number
  }) => apiClient.post('/mm/liquidation-protection', config),
}

// Simulation endpoints
export const simulationApi = {
  getParamSets: () => apiClient.get('/simulation/param-sets'),
  createParamSet: (data: { name: string; description?: string; overrides?: Record<string, unknown> }) =>
    apiClient.post('/simulation/param-sets', data),
  updateParamSet: (id: string, data: Record<string, unknown>) =>
    apiClient.put(`/simulation/param-sets/${id}`, data),
  deleteParamSet: (id: string) => apiClient.delete(`/simulation/param-sets/${id}`),
  start: (data: { param_set_ids: string[]; duration_minutes: number }) =>
    apiClient.post('/simulation/start', data),
  stop: () => apiClient.post('/simulation/stop'),
  forceStop: () => apiClient.post('/simulation/force-stop'),
  status: () => apiClient.get('/simulation/status'),
  comparison: () => apiClient.get('/simulation/comparison'),
  getRuns: () => apiClient.get('/simulation/runs'),
  getRunDetail: (runId: string) => apiClient.get(`/simulation/runs/${runId}`),
  getRunComparison: (runId: string, sortBy?: string) =>
    apiClient.get(`/simulation/runs/${runId}/comparison`, { params: { sort_by: sortBy } }),
  deleteRun: (runId: string) => apiClient.delete(`/simulation/runs/${runId}`),
}

// Referral endpoints
export const referralApi = {
  info: () => apiClient.get('/referral/info'),
  status: () => apiClient.get('/referral/status'),
  apply: (code?: string) => apiClient.post('/referral/apply', code ? { code } : {}),
  skip: () => apiClient.post('/referral/skip'),
}

// ==================== 帳號池 API (v2) ====================

export interface ProxyConfig {
  url?: string
  username?: string
  password?: string
}

export interface TradingConfig {
  symbol: string
  order_size_btc: string
  max_position_btc: string
  order_distance_bps: number
  hard_stop_position_btc?: string
}

// ----- 帳號 API 類型 -----

export interface CreateAccountData {
  id: string
  name: string
  exchange: string
  api_token: string
  ed25519_private_key: string
  proxy?: ProxyConfig
}

export interface UpdateAccountData {
  name?: string
  exchange?: string
  api_token?: string
  ed25519_private_key?: string
  proxy?: ProxyConfig
}

export interface AccountInfo {
  id: string
  name: string
  exchange: string
  has_credentials: boolean
  has_proxy: boolean
  used_by_strategies: string[]
}

// ----- 策略 API 類型 -----

export interface CreateStrategyData {
  id: string
  name: string
  enabled: boolean
  main_account_id: string
  hedge_account_id: string
  trading: TradingConfig
}

export interface UpdateStrategyData {
  name?: string
  enabled?: boolean
  main_account_id?: string
  hedge_account_id?: string
  trading?: TradingConfig
}

export interface StrategyInfo {
  id: string
  name: string
  enabled: boolean
  main_account_id: string
  main_account_name: string
  hedge_account_id: string
  hedge_account_name: string
  trading: TradingConfig
  status?: {
    running: boolean
    connected?: boolean
    main_healthy?: boolean
    hedge_healthy?: boolean
    error?: string
  }
}

// 帳號池 API
export const accountsApi = {
  // 列出所有帳號
  list: () => apiClient.get<{ accounts: AccountInfo[]; total: number }>('/accounts'),
  // 取得特定帳號
  get: (accountId: string) => apiClient.get<AccountInfo>(`/accounts/${accountId}`),
  // 新增帳號
  create: (data: CreateAccountData) => apiClient.post('/accounts', data),
  // 更新帳號
  update: (accountId: string, data: UpdateAccountData) => apiClient.put(`/accounts/${accountId}`, data),
  // 刪除帳號
  delete: (accountId: string) => apiClient.delete(`/accounts/${accountId}`),
}

// 策略 API
export const strategiesApi = {
  // 列出所有策略
  list: () => apiClient.get<{ strategies: StrategyInfo[]; total: number }>('/strategies'),
  // 取得特定策略
  get: (strategyId: string) => apiClient.get<StrategyInfo>(`/strategies/${strategyId}`),
  // 新增策略
  create: (data: CreateStrategyData) => apiClient.post('/strategies', data),
  // 更新策略
  update: (strategyId: string, data: UpdateStrategyData) => apiClient.put(`/strategies/${strategyId}`, data),
  // 刪除策略
  delete: (strategyId: string) => apiClient.delete(`/strategies/${strategyId}`),
  // 啟動策略
  start: (strategyId: string) => apiClient.post(`/strategies/${strategyId}/start`),
  // 停止策略
  stop: (strategyId: string) => apiClient.post(`/strategies/${strategyId}/stop`),
  // 啟動所有策略
  startAll: () => apiClient.post('/strategies/start-all'),
  // 停止所有策略
  stopAll: () => apiClient.post('/strategies/stop-all'),
  // 取得彙總狀態
  getSummary: () => apiClient.get('/strategies/summary'),
  // 取得策略狀態
  getStatus: (strategyId: string) => apiClient.get(`/strategies/${strategyId}/status`),
}

// ==================== 向後兼容 (舊版 account pairs API) ====================

export interface AccountPairTradingConfig {
  symbol: string
  order_size_btc: string
  max_position_btc: string
  order_distance_bps: number
  hard_stop_position_btc?: string
}

export interface AccountCredentialsConfig {
  api_token: string
  ed25519_private_key: string
  proxy?: {
    url?: string
    username?: string
    password?: string
  }
}

export interface CreateAccountPairData {
  id: string
  name: string
  enabled: boolean
  main_account: AccountCredentialsConfig
  hedge_account: AccountCredentialsConfig
  trading: AccountPairTradingConfig
}

export interface UpdateAccountPairData {
  name?: string
  enabled?: boolean
  main_account?: AccountCredentialsConfig
  hedge_account?: AccountCredentialsConfig
  trading?: AccountPairTradingConfig
}

// 向後兼容：舊版 account pairs API（映射到新的策略 API）
// 注意：建議使用新的 accountsApi 和 strategiesApi
export const accountPairsApi = {
  // 列出所有（等同於列出所有策略）
  list: () => strategiesApi.list(),
  // 啟動（等同於啟動策略）
  startPair: (pairId: string) => strategiesApi.start(pairId),
  // 停止（等同於停止策略）
  stopPair: (pairId: string) => strategiesApi.stop(pairId),
  // 啟動所有
  startAll: () => strategiesApi.startAll(),
  // 停止所有
  stopAll: () => strategiesApi.stopAll(),
  // 取得彙總狀態
  getSummary: () => strategiesApi.getSummary(),
}

export default apiClient

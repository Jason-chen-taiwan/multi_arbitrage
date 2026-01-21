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

export default apiClient

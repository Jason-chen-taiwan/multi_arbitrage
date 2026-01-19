import { useEffect, useState, useCallback, useRef } from 'react'

export interface WebSocketData {
  timestamp: string
  system_status: {
    running: boolean
    dry_run: boolean
    started_at?: string
  }
  market_data: Record<string, Record<string, {
    best_bid: number
    best_ask: number
    bid_size?: number
    ask_size?: number
    spread_pct?: number
  }>>
  orderbooks: Record<string, Record<string, {
    bids: [number, number][]
    asks: [number, number][]
  }>>
  opportunities: Array<{
    buy_exchange: string
    sell_exchange: string
    symbol: string
    buy_price: number
    sell_price: number
    profit: number
    profit_pct: number
    max_quantity: number
  }>
  stats: {
    total_updates: number
    total_opportunities: number
  }
  executor_stats: {
    total_attempts: number
    successful_executions: number
    total_profit: number
  }
  mm_status: {
    running: boolean
    status: string
    dry_run: boolean
    order_size_btc: number
    order_distance_bps: number
  }
  mm_executor?: Record<string, unknown>
  mm_positions?: {
    status: string
    standx?: { btc: number; equity?: number }
    grvt?: { btc: number; usdt?: number }
    net_btc: number
    is_hedged: boolean
    seconds_ago?: number
  }
  fill_history: Array<{
    time: string
    side: string
    price: number
    qty: number
    value: number
  }>
}

interface UseWebSocketOptions {
  reconnectInterval?: number
  onMessage?: (data: WebSocketData) => void
  onConnect?: () => void
  onDisconnect?: () => void
  onError?: (error: Event) => void
}

interface UseWebSocketReturn {
  isConnected: boolean
  lastMessage: WebSocketData | null
  reconnect: () => void
}

export function useWebSocket(
  url: string = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`,
  options: UseWebSocketOptions = {}
): UseWebSocketReturn {
  const {
    reconnectInterval = 3000,
    onMessage,
    onConnect,
    onDisconnect,
    onError,
  } = options

  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<WebSocketData | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    // Clear any existing reconnect timeout
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }

    // Close existing connection if any
    if (wsRef.current) {
      wsRef.current.close()
    }

    try {
      const ws = new WebSocket(url)

      ws.onopen = () => {
        console.log('[WebSocket] Connected')
        setIsConnected(true)
        onConnect?.()
      }

      ws.onclose = (event) => {
        console.log('[WebSocket] Disconnected', event.code, event.reason)
        setIsConnected(false)
        onDisconnect?.()

        // Auto reconnect
        reconnectTimeoutRef.current = setTimeout(() => {
          console.log('[WebSocket] Attempting reconnect...')
          connect()
        }, reconnectInterval)
      }

      ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error)
        onError?.(error)
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as WebSocketData
          setLastMessage(data)
          onMessage?.(data)
        } catch (e) {
          console.error('[WebSocket] Failed to parse message:', e)
        }
      }

      wsRef.current = ws
    } catch (error) {
      console.error('[WebSocket] Failed to connect:', error)
      // Retry connection
      reconnectTimeoutRef.current = setTimeout(connect, reconnectInterval)
    }
  }, [url, reconnectInterval, onMessage, onConnect, onDisconnect, onError])

  const reconnect = useCallback(() => {
    connect()
  }, [connect])

  useEffect(() => {
    connect()

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [connect])

  return {
    isConnected,
    lastMessage,
    reconnect,
  }
}

export default useWebSocket

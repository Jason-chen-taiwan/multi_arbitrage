import { Outlet, NavLink } from 'react-router-dom'
import { useWebSocket } from '../hooks/useWebSocket'
import { useI18n } from '../i18n'
import LanguageSwitcher from './LanguageSwitcher'
import './Layout.css'

function Layout() {
  const { isConnected, lastMessage } = useWebSocket()
  const { t } = useI18n()

  const mmStatus = lastMessage?.mm_status

  return (
    <div className="layout">
      <header className="header">
        <div className="header-left">
          <h1>StandX Market Maker</h1>
          <div className="status-indicator">
            <span className={`status-dot ${isConnected ? 'connected' : ''}`} />
            <span className="status-text">
              {isConnected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
        </div>
        <nav className="nav">
          <NavLink to="/mm" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            {t.nav.marketMaker}
          </NavLink>
          <NavLink to="/arbitrage" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            {t.nav.arbitrage}
          </NavLink>
          <NavLink to="/comparison" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            {t.nav.comparison}
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            {t.nav.settings}
          </NavLink>
        </nav>
        <div className="header-right">
          <LanguageSwitcher />
          {mmStatus && (
            <span className={`mm-status-badge ${mmStatus.running ? 'running' : 'stopped'}`}>
              MM: {mmStatus.running ? t.common.running : t.common.stopped}
            </span>
          )}
        </div>
      </header>
      <main className="main-content">
        <Outlet context={{ isConnected, lastMessage }} />
      </main>
      <footer className="footer">
        <p>StandX Market Maker Dashboard v1.0.0</p>
      </footer>
    </div>
  )
}

export default Layout

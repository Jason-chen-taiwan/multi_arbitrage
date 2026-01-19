import { useState, useCallback } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { I18nContext, getTranslations, getInitialLanguage, LANG_STORAGE_KEY } from './i18n'
import type { Language } from './i18n'
import Layout from './components/Layout'
import ArbitragePage from './pages/ArbitragePage'
import MarketMakerPage from './pages/MarketMakerPage'
import SettingsPage from './pages/SettingsPage'
import ComparisonPage from './pages/ComparisonPage'

function App() {
  const [lang, setLangState] = useState<Language>(getInitialLanguage)

  const setLang = useCallback((newLang: Language) => {
    setLangState(newLang)
    localStorage.setItem(LANG_STORAGE_KEY, newLang)
  }, [])

  const t = getTranslations(lang)

  return (
    <I18nContext.Provider value={{ lang, t, setLang }}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Navigate to="/mm" replace />} />
            <Route path="arbitrage" element={<ArbitragePage />} />
            <Route path="mm" element={<MarketMakerPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="comparison" element={<ComparisonPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </I18nContext.Provider>
  )
}

export default App

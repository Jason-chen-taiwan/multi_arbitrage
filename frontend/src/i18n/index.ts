import { createContext, useContext } from 'react'
import type { Language, Translations } from './types'
import { zh } from './zh'
import { en } from './en'

export type { Language, Translations }
export { zh, en }

const translations: Record<Language, Translations> = { zh, en }

export const getTranslations = (lang: Language): Translations => translations[lang]

export interface I18nContextType {
  lang: Language
  t: Translations
  setLang: (lang: Language) => void
}

export const I18nContext = createContext<I18nContextType | null>(null)

export const useI18n = (): I18nContextType => {
  const context = useContext(I18nContext)
  if (!context) {
    throw new Error('useI18n must be used within I18nProvider')
  }
  return context
}

// Storage key for persisting language preference
export const LANG_STORAGE_KEY = 'app-language'

// Get initial language from localStorage or browser preference
export const getInitialLanguage = (): Language => {
  const stored = localStorage.getItem(LANG_STORAGE_KEY)
  if (stored === 'zh' || stored === 'en') {
    return stored
  }
  // Check browser language
  const browserLang = navigator.language.toLowerCase()
  if (browserLang.startsWith('zh')) {
    return 'zh'
  }
  return 'en'
}

import { useI18n } from '../i18n'
import type { Language } from '../i18n'

function LanguageSwitcher() {
  const { lang, setLang } = useI18n()

  const handleChange = (newLang: Language) => {
    setLang(newLang)
  }

  return (
    <div className="language-switcher">
      <button
        className={`lang-btn ${lang === 'zh' ? 'active' : ''}`}
        onClick={() => handleChange('zh')}
      >
        中文
      </button>
      <button
        className={`lang-btn ${lang === 'en' ? 'active' : ''}`}
        onClick={() => handleChange('en')}
      >
        EN
      </button>
    </div>
  )
}

export default LanguageSwitcher

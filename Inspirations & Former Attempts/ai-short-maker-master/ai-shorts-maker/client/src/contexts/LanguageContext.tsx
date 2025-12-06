import { createContext, useContext, useState, useEffect, ReactNode } from "react"

type Language = "en" | "ro"

type LanguageContextType = {
  language: Language
  setLanguage: (lang: Language) => void
}

const LanguageContext = createContext<LanguageContextType | null>(null)

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(() => {
    const storedLang = localStorage.getItem("ui-language")
    return (storedLang === "en" || storedLang === "ro") ? storedLang : "en"
  })

  useEffect(() => {
    localStorage.setItem("ui-language", language)
  }, [language])

  return (
    <LanguageContext.Provider value={{ language, setLanguage }}>
      {children}
    </LanguageContext.Provider>
  )
}

export function useLanguage() {
  const context = useContext(LanguageContext)
  if (!context) {
    throw new Error("useLanguage must be used within a LanguageProvider")
  }
  return context
}
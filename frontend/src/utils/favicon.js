// Shared favicon helpers.
//
// We used to hit `google.com/s2/favicons` but that service 404s noisily for
// unknown domains and occasionally gets blocked by CORS. DuckDuckGo's ip3
// endpoint returns a transparent 1x1 for unknown hosts, which is perfect for
// our "small icon next to a company name" use case.
const DEFAULT_HOST = 'icons.duckduckgo.com'

export function extractDomain(website) {
  if (!website) return null
  try {
    const url = website.startsWith('http') ? website : `https://${website}`
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return null
  }
}

export function faviconUrl(website) {
  const domain = extractDomain(website)
  if (!domain) return null
  return `https://${DEFAULT_HOST}/ip3/${domain}.ico`
}

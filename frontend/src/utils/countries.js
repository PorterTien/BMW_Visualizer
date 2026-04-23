// Shared country alias table for filtering companies by HQ country. Used by
// both CompanyTable (filter input) and CompanyMap (geo filter sidebar) — keep
// these in sync by importing from one place.
export const COUNTRY_ALIASES = {
  'United States': ['united states', 'us'],
  'United Kingdom': ['united kingdom', 'uk'],
  'South Korea': ['south korea', 'republic of korea'],
}

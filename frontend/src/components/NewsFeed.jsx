import React, { useEffect, useRef, useState } from 'react'
import { getNews } from '../api/client'

const CATEGORIES = [
  { key: '', label: 'All News' },
  { key: 'funding', label: 'Funding' },
  { key: 'partnership', label: 'Partnerships' },
  { key: 'product launch', label: 'Product Launch' },
  { key: 'facility', label: 'Facilities' },
  { key: 'regulatory', label: 'Regulatory' },
  { key: 'research', label: 'Research' },
  { key: 'market', label: 'Market' },
  { key: 'other', label: 'Other' },
]

const CATEGORY_CONFIG = {
  funding:         { hex: '#10B981', bg: 'bg-emerald-100 text-emerald-800', grad: 'from-emerald-600 to-emerald-900' },
  partnership:     { hex: '#4599FE', bg: 'bg-blue-100 text-blue-800',       grad: 'from-blue-600 to-blue-900' },
  'product launch':{ hex: '#8B5CF6', bg: 'bg-purple-100 text-purple-800',   grad: 'from-purple-600 to-purple-900' },
  facility:        { hex: '#F97316', bg: 'bg-orange-100 text-orange-800',   grad: 'from-orange-600 to-orange-900' },
  regulatory:      { hex: '#EF4444', bg: 'bg-red-100 text-red-800',         grad: 'from-red-600 to-red-900' },
  research:        { hex: '#0EA5E9', bg: 'bg-sky-100 text-sky-800',         grad: 'from-sky-600 to-sky-900' },
  market:          { hex: '#6366F1', bg: 'bg-indigo-100 text-indigo-800',   grad: 'from-indigo-600 to-indigo-900' },
  other:           { hex: '#9CA3AF', bg: 'bg-gray-100 text-gray-700',       grad: 'from-gray-500 to-gray-800' },
}
const DEFAULT_CONFIG = CATEGORY_CONFIG.other

function categoryColor(cat) { return (CATEGORY_CONFIG[cat] || DEFAULT_CONFIG).hex }
function categoryBg(cat)    { return (CATEGORY_CONFIG[cat] || DEFAULT_CONFIG).bg }
function categoryGrad(cat)  { return (CATEGORY_CONFIG[cat] || DEFAULT_CONFIG).grad }

function timeAgo(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  if (isNaN(d)) return dateStr
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function ArticleImage({ category, size = 'full', className = '' }) {
  return (
    <div className={`bg-gradient-to-br ${categoryGrad(category)} flex items-end p-2 ${className}`}>
      <span className={`text-white/70 uppercase tracking-widest font-semibold ${size === 'sm' ? 'text-[9px]' : 'text-xs'}`}>
        {category || 'news'}
      </span>
    </div>
  )
}

export default function NewsFeed() {
  const [news, setNews] = useState([])
  const [loading, setLoading] = useState(true)
  const [activeCategory, setActiveCategory] = useState('')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [selectedArticle, setSelectedArticle] = useState(null)
  const debounceRef = useRef(null)

  function handleSearchChange(val) {
    setSearch(val)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setDebouncedSearch(val), 300)
  }

  useEffect(() => {
    setLoading(true)
    const params = {}
    if (activeCategory) params.category = activeCategory
    if (debouncedSearch) params.search = debouncedSearch
    getNews(params)
      .then(({ data }) => setNews(data))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [activeCategory, debouncedSearch])

  const featured = news[0] || null
  const grid = news.slice(1, 7)
  const sidebarPicks = news.slice(7, 15)

  return (
    <div className="flex h-full overflow-hidden bg-[#F0F4F8]">

      {/* Left sidebar — categories */}
      <div className="w-48 bg-white border-r border-[#B8CAD1] flex flex-col shrink-0">
        <div className="px-4 py-4 border-b border-[#B8CAD1]">
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Filter</div>
          <input
            type="text"
            placeholder="Search..."
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="mt-2 w-full border border-[#B8CAD1] rounded px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#4599FE]"
          />
        </div>
        <nav className="flex-1 overflow-y-auto py-2">
          {CATEGORIES.map((cat) => (
            <button
              key={cat.key}
              onClick={() => setActiveCategory(cat.key)}
              className={`w-full text-left px-4 py-2.5 text-sm transition-colors flex items-center gap-2 ${
                activeCategory === cat.key
                  ? 'bg-[#E8F1FF] text-[#4599FE] font-semibold border-r-2 border-[#4599FE]'
                  : 'text-gray-600 hover:bg-[#F0F4F8]'
              }`}
            >
              {cat.key && (
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: categoryColor(cat.key) }}
                />
              )}
              {cat.label}
            </button>
          ))}
        </nav>
        <div className="px-4 py-3 border-t border-[#B8CAD1] text-xs text-gray-400">
          {news.length} articles
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-y-auto min-w-0">
        <div className="p-6 max-w-4xl">
          <h2 className="text-xl font-bold text-[#031E49] mb-5">Battery Industry Intelligence</h2>

          {loading ? (
            <div className="flex items-center justify-center h-64 text-gray-400">Loading...</div>
          ) : news.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
              <div className="text-base font-medium">No articles found</div>
              <div className="text-sm">Use the AI Research tab to fetch news for a company</div>
            </div>
          ) : (
            <>
              {/* Featured article */}
              {featured && (
                <div
                  className="bg-white rounded-xl border border-[#B8CAD1] overflow-hidden mb-6 cursor-pointer hover:shadow-lg transition-shadow"
                  onClick={() => setSelectedArticle(featured)}
                >
                  <div className="flex">
                    <ArticleImage category={featured.category} className="w-72 h-48 shrink-0" />
                    <div className="flex-1 p-5 flex flex-col justify-between">
                      <div>
                        <div className="flex items-center gap-2 mb-2">
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium capitalize ${categoryBg(featured.category)}`}>
                            {featured.category || 'news'}
                          </span>
                          {featured.company_name && (
                            <span className="text-xs font-semibold text-[#4599FE]">{featured.company_name}</span>
                          )}
                        </div>
                        <h3 className="text-lg font-bold text-[#031E49] leading-snug mb-2">
                          {featured.news_headline}
                        </h3>
                        {featured.summary && (
                          <p className="text-sm text-gray-600 leading-relaxed line-clamp-3">
                            {featured.summary}
                          </p>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-3 text-xs text-gray-400">
                        <span>{timeAgo(featured.date_of_article)}</span>
                        {featured.news_source && <span>· {featured.news_source}</span>}
                        {featured.url && (
                          <a href={featured.url} target="_blank" rel="noreferrer"
                            className="ml-auto text-[#4599FE] hover:underline"
                            onClick={e => e.stopPropagation()}>
                            Read source
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* 3-column grid */}
              {grid.length > 0 && (
                <div className="grid grid-cols-3 gap-4 mb-6">
                  {grid.map((article) => (
                    <div
                      key={article.id}
                      onClick={() => setSelectedArticle(article)}
                      className="bg-white rounded-xl border border-[#B8CAD1] overflow-hidden cursor-pointer hover:shadow-md transition-shadow"
                    >
                      <ArticleImage category={article.category} className="w-full h-28" size="sm" />
                      <div className="p-3">
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium capitalize ${categoryBg(article.category)}`}>
                            {article.category || 'news'}
                          </span>
                        </div>
                        <h4 className="text-sm font-semibold text-[#031E49] leading-snug line-clamp-3">
                          {article.news_headline}
                        </h4>
                        <div className="flex items-center gap-1.5 mt-2 text-[11px] text-gray-400">
                          <span>{timeAgo(article.date_of_article)}</span>
                          {article.news_source && <span>· {article.news_source}</span>}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Remaining articles — compact list */}
              {news.slice(7).length > 0 && (
                <div className="space-y-2">
                  {news.slice(7).map((article) => (
                    <div
                      key={article.id}
                      onClick={() => setSelectedArticle(article)}
                      className="bg-white rounded-lg border border-[#B8CAD1] px-4 py-3 flex items-start gap-4 cursor-pointer hover:shadow-sm transition-shadow"
                    >
                      <ArticleImage category={article.category} className="w-16 h-16 rounded shrink-0" size="sm" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium capitalize ${categoryBg(article.category)}`}>
                            {article.category}
                          </span>
                          {article.company_name && (
                            <span className="text-xs text-[#4599FE] font-medium truncate">{article.company_name}</span>
                          )}
                        </div>
                        <h4 className="text-sm font-semibold text-[#031E49] leading-snug line-clamp-2">
                          {article.news_headline}
                        </h4>
                        <div className="text-xs text-gray-400 mt-1">
                          {timeAgo(article.date_of_article)}{article.news_source ? ` · ${article.news_source}` : ''}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Right sidebar — Latest Highlights */}
      <div className="w-64 bg-white border-l border-[#B8CAD1] flex flex-col shrink-0">
        <div className="px-4 py-4 border-b border-[#B8CAD1]">
          <h3 className="font-bold text-sm text-[#031E49]">Latest Highlights</h3>
        </div>
        <div className="flex-1 overflow-y-auto divide-y divide-[#F0F4F8]">
          {sidebarPicks.map((article) => (
            <button
              key={article.id}
              onClick={() => setSelectedArticle(article)}
              className="w-full text-left px-4 py-3 hover:bg-[#F0F4F8] transition-colors"
            >
              <div className="flex items-start gap-2">
                <span
                  className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0"
                  style={{ backgroundColor: categoryColor(article.category) }}
                />
                <div className="min-w-0">
                  <p className="text-xs font-medium text-[#031E49] leading-snug line-clamp-2">
                    {article.news_headline}
                  </p>
                  <p className="text-[11px] text-gray-400 mt-1">
                    {timeAgo(article.date_of_article)}{article.news_source ? ` · ${article.news_source}` : ''}
                  </p>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Article detail modal */}
      {selectedArticle && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setSelectedArticle(null)}>
          <div
            className="bg-white rounded-2xl shadow-2xl w-[620px] max-h-[80vh] overflow-y-auto"
            onClick={e => e.stopPropagation()}
          >
            <ArticleImage category={selectedArticle.category} className="w-full h-40 rounded-t-2xl" />
            <div className="p-6">
              <div className="flex items-center gap-2 mb-3">
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium capitalize ${categoryBg(selectedArticle.category)}`}>
                  {selectedArticle.category}
                </span>
                {selectedArticle.company_name && (
                  <span className="text-sm font-semibold text-[#4599FE]">{selectedArticle.company_name}</span>
                )}
                <span className="text-xs text-gray-400 ml-auto">
                  {timeAgo(selectedArticle.date_of_article)}{selectedArticle.news_source ? ` · ${selectedArticle.news_source}` : ''}
                </span>
              </div>
              <h2 className="text-xl font-bold text-[#031E49] leading-snug mb-4">
                {selectedArticle.news_headline}
              </h2>
              {selectedArticle.summary && (
                <p className="text-sm text-gray-700 leading-relaxed">{selectedArticle.summary}</p>
              )}
              {selectedArticle.topics?.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-4">
                  {selectedArticle.topics.map((t) => (
                    <span key={t} className="text-xs bg-[#F0F4F8] text-gray-600 px-2 py-1 rounded-full">{t}</span>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-3 mt-5 pt-4 border-t border-[#B8CAD1]">
                {selectedArticle.url && (
                  <a href={selectedArticle.url} target="_blank" rel="noreferrer"
                    className="text-sm text-[#4599FE] hover:underline font-medium">
                    Read full article
                  </a>
                )}
                <button
                  onClick={() => setSelectedArticle(null)}
                  className="ml-auto text-sm text-gray-500 hover:text-gray-800"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

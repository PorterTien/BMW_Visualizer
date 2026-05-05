import React, { useState, useRef, useEffect } from 'react'
import { uploadCSV } from '../api/client'

function useUploadProgress(uploading) {
  const [progress, setProgress] = useState({ pct: 0, label: 'Preparing…' })
  const timerRef = useRef(null)

  useEffect(() => {
    if (!uploading) {
      setProgress({ pct: 0, label: 'Preparing…' })
      clearInterval(timerRef.current)
      return
    }
    const steps = [
      { pct: 10, label: 'Reading file…' },
      { pct: 30, label: 'Loading existing data…' },
      { pct: 55, label: 'Importing companies…' },
      { pct: 80, label: 'Saving to database…' },
      { pct: 96, label: 'Almost done…' },
    ]
    let i = 0
    setProgress(steps[0])
    timerRef.current = setInterval(() => {
      i = Math.min(i + 1, steps.length - 1)
      setProgress(steps[i])
    }, 800)
    return () => clearInterval(timerRef.current)
  }, [uploading])

  return progress
}

function DropZone({ label, accept, onUpload, uploading, progress }) {
  const inputRef = useRef()
  const [dragging, setDragging] = useState(false)

  function handleFile(file) {
    if (file) onUpload(file)
  }

  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          handleFile(e.dataTransfer.files[0])
        }}
        onClick={() => !uploading && inputRef.current?.click()}
        className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
          uploading ? 'border-bmw-blue bg-blue-50 cursor-not-allowed' :
          dragging ? 'border-bmw-blue bg-blue-50 cursor-pointer' : 'border-bmw-border hover:border-bmw-blue cursor-pointer'
        }`}
      >
        <input ref={inputRef} type="file" accept={accept} className="hidden"
          onChange={(e) => handleFile(e.target.files[0])} />
        <div className="text-2xl mb-2">{uploading ? '⏳' : '↑'}</div>
        <div className="text-sm font-medium text-gray-700">{label}</div>
        <div className="text-xs text-gray-400 mt-1">
          {uploading ? progress?.label || 'Uploading…' : 'Click or drag & drop'}
        </div>
      </div>
      {/* Progress bar */}
      {uploading && (
        <div className="mt-2 h-1.5 bg-gray-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-bmw-blue rounded-full transition-all duration-300"
            style={{ width: `${progress?.pct ?? 0}%` }}
          />
        </div>
      )}
      {uploading && (
        <p className="text-xs text-bmw-blue text-center mt-1 animate-pulse">
          {progress?.label || 'Uploading…'}
        </p>
      )}
    </div>
  )
}

function ResultBanner({ result, onDismiss }) {
  if (!result) return null
  const isError = !!result.error
  return (
    <div className={`mt-3 text-xs rounded-lg p-3 border flex items-start justify-between gap-2 ${
      isError ? 'border-red-200 bg-red-50 text-red-600' : 'border-green-200 bg-green-50 text-green-700'
    }`}>
      <span>
        {isError ? result.error : (
          result.added !== undefined
            ? `Added ${result.added}, updated ${result.updated} companies`
            : result.companies_added !== undefined && result.news_added !== undefined
            ? `Added ${result.companies_added} companies, ${result.news_added} news, ${result.proceedings_added} proceedings`
            : result.source
            ? `${result.source} — ${result.companies_added} added · ${result.companies_updated} updated${result.partnerships_added > 0 ? ` · ${result.partnerships_added} partnerships` : ''}`
            : JSON.stringify(result)
        )}
      </span>
      <button onClick={onDismiss} className="opacity-50 hover:opacity-100 flex-shrink-0">✕</button>
    </div>
  )
}

export default function ResearchPanel() {
  const [csvUploading, setCsvUploading] = useState(false)
  const [csvResult, setCsvResult] = useState(null)
  const csvProgress = useUploadProgress(csvUploading)

  async function handleCsvUpload(file) {
    setCsvUploading(true)
    setCsvResult(null)
    try {
      const { data } = await uploadCSV(file)
      setCsvResult(data)
    } catch (e) {
      setCsvResult({ error: e.response?.data?.detail || e.message })
    }
    setCsvUploading(false)
  }

  return (
    <div className="flex-1 px-8 pt-6 pb-4 bg-bmw-gray-light overflow-hidden">
      <div className="max-w-3xl mx-auto space-y-6">

        <div className="bg-white rounded-xl border border-[#DDE4EA] p-6">
          <h3 className="font-semibold text-[text-bmw-text-primary] mb-1">Companies Spreadsheet</h3>
          <p className="text-xs text-gray-500 mb-4">Import a CSV or XLSX with company names. New companies are added; existing ones are updated. AI will automatically classify any companies missing a type.</p>
          <DropZone label="CSV or XLSX file" accept=".csv,.xlsx" onUpload={handleCsvUpload} uploading={csvUploading} progress={csvProgress} />
          <ResultBanner result={csvResult} onDismiss={() => setCsvResult(null)} />
        </div>

      </div>
    </div>
  )
}

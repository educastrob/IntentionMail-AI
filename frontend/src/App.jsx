import React, { useMemo, useRef, useState } from 'react'

function splitTexts(raw) {
  return raw
    .split(/\n\s*\n|^---$|^\s*---\s*$/m)
    .map(t => t.trim())
    .filter(Boolean)
}

export default function App(){
  const [rawText, setRawText] = useState('')
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState([])
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const dropRef = useRef(null)

  const texts = useMemo(() => splitTexts(rawText), [rawText])
  const hasContent = texts.length > 0 || files.length > 0

  const showMessage = (type, message) => {
    if (type === 'error') {
      setError(message)
      setSuccess('')
      setTimeout(() => setError(''), 5000)
    } else {
      setSuccess(message)
      setError('')
      setTimeout(() => setSuccess(''), 3000)
    }
  }

  const onPick = () => document.getElementById('fileInput').click()
  
  const onFiles = (list) => {
    const arr = Array.from(list || [])
    if (!arr.length) return
    
    const valid = arr.filter(f => /\.(pdf|txt)$/i.test(f.name))
    const invalid = arr.filter(f => !/\.(pdf|txt)$/i.test(f.name))
    
    if (invalid.length > 0) {
      showMessage('error', `Formato não suportado: ${invalid.map(f => f.name).join(', ')}`)
    }
    
    if (valid.length > 0) {
      setFiles(prev => [...prev, ...valid])
      showMessage('success', `${valid.length} arquivo(s) adicionado(s)`)
    }
  }

  const onDrop = (e) => {
    e.preventDefault()
    dropRef.current.classList.remove('dragover')
    onFiles(e.dataTransfer.files)
  }

  const removeFile = (name) => {
    setFiles(prev => prev.filter(f => f.name !== name))
    showMessage('success', 'Arquivo removido')
  }

  const analyze = async () => {
    if (!hasContent) {
      showMessage('error', 'Adicione textos ou arquivos (.txt/.pdf) para analisar.')
      return
    }
    
    setLoading(true)
    setResults([])
    setError('')
    
    try {
      let results = []
      
      // Processar textos em lote via JSON
      if (texts.length) {
        
        const resp = await fetch('/api/analyze_batch', { 
          method: 'POST', 
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            texts: texts
          })
        })
        
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({detail: 'Erro desconhecido'}))
          throw new Error(err.detail || `Erro ${resp.status}: ${resp.statusText}`)
        }
        
        const data = await resp.json()
        results = results.concat(data.results || [])
      }
      
      // Processar arquivos individualmente
      if (files.length > 0) {
        for (const file of files) {
          try {            
            const fd = new FormData()
            fd.append('file', file)
            
            const resp = await fetch('/api/analyze', { 
              method: 'POST', 
              body: fd 
            })
            
            if (resp.ok) {
              const result = await resp.json()
              result.id = file.name
              results.push(result)
            } else {
              const err = await resp.json().catch(() => ({detail: 'Erro desconhecido'}))
              console.error(`Erro ao processar ${file.name}:`, err)
              results.push({
                id: file.name,
                category: 'Improdutivo',
                confidence: 0.0,
                suggested_reply: `Erro ao processar arquivo: ${err.detail || 'Erro desconhecido'}`,
                metadata: { intent: 'outros' }
              })
            }
          } catch (e) {
            console.error(`Exceção ao processar ${file.name}:`, e)
            results.push({
              id: file.name,
              category: 'Improdutivo',
              confidence: 0.0,
              suggested_reply: `Erro no processamento: ${e.message}`,
              metadata: { intent: 'outros' }
            })
          }
        }
      }
      
      if (results.length > 0) {
        setResults(results)
        showMessage('success', `${results.length} item(s) analisado(s) com IA com sucesso!`)
      } else {
        showMessage('error', 'Nenhum item foi processado com sucesso.')
      }
      
    } catch (e) {
      console.error('Erro na análise:', e)
      showMessage('error', e.message)
    } finally {
      setLoading(false)
    }
  }

  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text)
      showMessage('success', 'Texto copiado para a área de transferência!')
    } catch (e) {
      showMessage('error', 'Não foi possível copiar o texto.')
    }
  }

  const clearAll = () => {
    setRawText('')
    setFiles([])
    setResults([])
    setError('')
    setSuccess('')
    showMessage('success', 'Todos os dados foram limpos')
  }

  const downloadResults = () => {
    if (!results.length) return
    
    const csv = [
      ['Item', 'Categoria', 'Confiança', 'Intenção', 'Resposta Sugerida'],
      ...results.map(r => [
        r.id || '—',
        r.category || '—',
        `${((r.confidence || 0) * 100).toFixed(1)}%`,
        r.metadata?.intent || '—',
        r.suggested_reply || '—'
      ])
    ].map(row => row.map(cell => `"${cell}"`).join(',')).join('\n')
    
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = `analise-emails-${new Date().toISOString().split('T')[0]}.csv`
    link.click()
  }

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="container">
          <div className="header-content">
            <div className="header-left">
              <h1>🚀 IntentionMail.AI</h1>
            </div>
            <div className="header-right">
              <p>Análise Inteligente de E-Mails   |   <a href="https://github.com/educastrob/IntentionMail-AI" target="_blank" rel="noopener noreferrer" className="github-link">GitHub</a></p>
            </div>
          </div>
        </div>
      </header>

      {/* Messages */}
      {(error || success) && (
        <div className={`message ${error ? 'error' : 'success'}`}>
          <div className="container">
            <span>{error || success}</span>
            <button onClick={() => error ? setError('') : setSuccess('')} className="message-close">×</button>
          </div>
        </div>
      )}

      <main className="container">
        {/* Input Section */}
        <section className="card input-section">
          <div className="input-grid">
            {/* Text Input */}
            <div className="input-field">
              <textarea
                id="textInput"
                value={rawText}
                onChange={e => setRawText(e.target.value)}
                placeholder="Cole aqui os e-mails separados por linhas..."
                className="text-input"
              />
              {texts.length > 0 && (
                <button onClick={() => setRawText('')} className="clear-btn">Limpar</button>
              )}
            </div>

            {/* File Input */}
            <div className="input-field">
              <div
                ref={dropRef}
                className="dropzone"
                onDragOver={e => {e.preventDefault(); dropRef.current.classList.add('dragover')}}
                onDragLeave={() => dropRef.current.classList.remove('dragover')}
                onDrop={onDrop}
              >
                <div className="dropzone-content">
                  <span className="dropzone-icon">📁</span>
                  <p>Arraste arquivos .pdf/.txt aqui</p>
                  <button className="select-files-btn" onClick={onPick} type="button">
                    Selecionar
                  </button>
                </div>
              </div>
              
              <input 
                id="fileInput" 
                type="file" 
                accept=".txt,.pdf" 
                multiple 
                hidden 
                onChange={(e) => onFiles(e.target.files)} 
              />
              
              {files.length > 0 && (
                <div className="file-list">
                  <ul>
                    {files.map(f => (
                      <li key={f.name} className="file-item">
                        <span className="file-name">{f.name}</span>
                        <button 
                          className="remove-file-btn" 
                          type="button" 
                          onClick={() => removeFile(f.name)}
                          title="Remover arquivo"
                        >
                          ×
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>

          {/* Action Buttons */}
          <div className="action-buttons">
            <button 
              className="btn-primary" 
              onClick={analyze} 
              disabled={loading || !hasContent}
            >
              {loading ? (
                <>
                  <span className="spinner"></span>
                  Processando com IA...
                </>
              ) : (
                <>
                  <span className="btn-icon">🚀</span>
                  Analisar com IA
                </>
              )}
            </button>
            
            <button 
              className="btn-secondary" 
              onClick={clearAll}
              disabled={loading}
            >
              <span className="btn-icon">🗑️</span>
              Limpar Tudo
            </button>
          </div>
        </section>

        {/* Results Section */}
        {results.length > 0 && (
          <section className="card results-section">
            <div className="card-header">
              <h2>🎯 Resultados da Análise IA</h2>
              <div className="results-actions">
                <button onClick={downloadResults} className="btn-outline">
                  <span className="btn-icon">📥</span>
                  Exportar CSV
                </button>
                <span className="results-count">{results.length} resultado(s)</span>
              </div>
            </div>
            
            <div className="results-table-container">
              <table className="results-table">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Categoria</th>
                    <th>Confiança</th>
                    <th>Intenção</th>
                    <th>Resposta Sugerida</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r, i) => (
                    <tr key={r.id || i} className="result-row">
                      <td className="item-id">{r.id || `Item ${i + 1}`}</td>
                      <td>
                        <span className={`category-badge ${r.category?.toLowerCase()}`}>
                          {r.category || '—'}
                        </span>
                      </td>
                      <td className="confidence">
                        <div className="confidence-bar">
                          <div 
                            className="confidence-fill" 
                            style={{width: `${(r.confidence || 0) * 100}%`}}
                          ></div>
                          <span className="confidence-text">
                            {((r.confidence || 0) * 100).toFixed(1)}%
                          </span>
                        </div>
                      </td>
                      <td className="intent">
                        <span className="intent-tag">{r.metadata?.intent || '—'}</span>
                      </td>
                      <td className="suggested-reply">
                        <div className="reply-container">
                          <textarea 
                            className="reply-textarea" 
                            readOnly 
                            value={r.suggested_reply || '—'}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Empty State */}
        {!results.length && !loading && (
          <section className="card empty-state">
            <div className="empty-content">
              <span className="empty-icon">🚀</span>
              <h3>Bem-vindo ao IntentionMail.AI</h3>
              <p>Adicione textos ou arquivos e clique em "Analisar com IA" para começar a classificação inteligente</p>
            </div>
          </section>
        )}
      </main>
      
      <footer className="footer">
        <div className="container">
          <p>&copy;2025 | Desenvolvido por Eduardo Castro</p>
        </div>
      </footer>
    </div>
  )
}
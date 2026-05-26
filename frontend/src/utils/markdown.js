import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import { Marked, Renderer } from 'marked'

const languages = {
  bash,
  css,
  html: xml,
  javascript,
  js: javascript,
  json,
  markdown,
  md: markdown,
  py: python,
  python,
  sh: bash,
  sql,
  ts: typescript,
  typescript,
  vue: xml,
  xml,
}

for (const [name, language] of Object.entries(languages)) {
  if (!hljs.getLanguage(name)) hljs.registerLanguage(name, language)
}

const renderer = new Renderer()

renderer.code = (code, infostring = '') => {
  const lang = String(infostring || '').trim().split(/\s+/)[0].toLowerCase()
  const highlighted = lang && hljs.getLanguage(lang)
    ? hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
    : hljs.highlightAuto(code).value
  const languageClass = lang ? ` language-${escapeAttribute(lang)}` : ''

  return `<pre class="ge-code-block"><code class="hljs${languageClass}">${highlighted}</code></pre>`
}

const marked = new Marked({
  breaks: true,
  gfm: true,
  renderer,
})

export function renderMarkdown(source, { inline = false, relaxedBackticks = true } = {}) {
  const text = normalizeMarkdownSource(source, { relaxedBackticks })
  if (!text.trim()) return ''
  const html = inline ? marked.parseInline(text) : marked.parse(text)
  return DOMPurify.sanitize(html)
}

function normalizeMarkdownSource(source, { relaxedBackticks }) {
  const text = String(source || '')
  return relaxedBackticks ? text.replace(/\\`/g, '`') : text
}

function escapeAttribute(value) {
  return String(value).replace(/[^a-z0-9_-]/gi, '')
}

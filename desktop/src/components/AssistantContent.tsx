/**
 * Assistant 正文渲染：react-markdown + remark-gfm + Shiki。
 *  - react-markdown 默认转义原始 HTML（安全渲染），remark-gfm 提供表格 / 任务列表 / 删除线。
 *  - Shiki 使用 TextMate grammar，视觉接近 VS Code；走纯 JS 正则引擎，Electron/Vite 无需 WASM。
 *  - 同步渲染 + 客户端异步高亮：SSR / 测试环境代码块回退为纯文本 <pre><code>。
 */

import { Children, isValidElement, memo, useEffect, useRef, useState } from 'react'
import type { ReactElement, ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { createHighlighterCore } from 'shiki/core'
import type { HighlighterCore } from 'shiki/core'
import { createJavaScriptRegexEngine } from '@shikijs/engine-javascript'

const THEME = 'github-dark'

/** 支持高亮的语言子路径 bundle（shiki 按需加载 grammar），含常用别名。 */
const LANG_BUNDLES: Record<string, () => Promise<unknown>> = {
  /** 执行 `typescript` 对应的界面或业务逻辑。 */
  typescript: () => import('@shikijs/langs/typescript'),
  /** 执行 `ts` 对应的界面或业务逻辑。 */
  ts: () => import('@shikijs/langs/typescript'),
  /** 执行 `javascript` 对应的界面或业务逻辑。 */
  javascript: () => import('@shikijs/langs/javascript'),
  /** 执行 `js` 对应的界面或业务逻辑。 */
  js: () => import('@shikijs/langs/javascript'),
  /** 执行 `jsx` 对应的界面或业务逻辑。 */
  jsx: () => import('@shikijs/langs/jsx'),
  /** 执行 `tsx` 对应的界面或业务逻辑。 */
  tsx: () => import('@shikijs/langs/tsx'),
  /** 执行 `python` 对应的界面或业务逻辑。 */
  python: () => import('@shikijs/langs/python'),
  /** 执行 `py` 对应的界面或业务逻辑。 */
  py: () => import('@shikijs/langs/python'),
  /** 执行 `bash` 对应的界面或业务逻辑。 */
  bash: () => import('@shikijs/langs/bash'),
  /** 执行 `shell` 对应的界面或业务逻辑。 */
  shell: () => import('@shikijs/langs/shellscript'),
  /** 执行 `sh` 对应的界面或业务逻辑。 */
  sh: () => import('@shikijs/langs/shellscript'),
  /** 执行 `shellscript` 对应的界面或业务逻辑。 */
  shellscript: () => import('@shikijs/langs/shellscript'),
  /** 执行 `json` 对应的界面或业务逻辑。 */
  json: () => import('@shikijs/langs/json'),
  /** 执行 `markdown` 对应的界面或业务逻辑。 */
  markdown: () => import('@shikijs/langs/markdown'),
  /** 执行 `md` 对应的界面或业务逻辑。 */
  md: () => import('@shikijs/langs/markdown'),
  /** 执行 `css` 对应的界面或业务逻辑。 */
  css: () => import('@shikijs/langs/css'),
  /** 执行 `html` 对应的界面或业务逻辑。 */
  html: () => import('@shikijs/langs/html'),
  /** 执行 `yaml` 对应的界面或业务逻辑。 */
  yaml: () => import('@shikijs/langs/yaml'),
  /** 执行 `sql` 对应的界面或业务逻辑。 */
  sql: () => import('@shikijs/langs/sql'),
  /** 执行 `rust` 对应的界面或业务逻辑。 */
  rust: () => import('@shikijs/langs/rust'),
  /** 执行 `go` 对应的界面或业务逻辑。 */
  go: () => import('@shikijs/langs/go'),
}

let highlighterPromise: Promise<HighlighterCore> | null = null

/** 获取 `highlighter` 对应的数据或流程。 */
function getHighlighter(): Promise<HighlighterCore> {
  if (!highlighterPromise) {
    const langs = Object.values(LANG_BUNDLES).map((load) => load()) as unknown as Parameters<
      typeof createHighlighterCore
    >[0]['langs']
    highlighterPromise = createHighlighterCore({
      themes: [import('@shikijs/themes/github-dark')],
      langs,
      engine: createJavaScriptRegexEngine(),
    })
  }
  return highlighterPromise
}

/** Shiki 代码块：先渲染纯文本，挂载后异步替换为高亮 HTML。
streaming=true（正文仍在流式增长）时跳过高亮，只显示纯文本 <pre><code>；
完成后由父组件以 streaming=false 重新渲染，再走 debounce 高亮。 */
function CodeBlock({
  code,
  lang,
  streaming,
}: {
  code: string
  lang: string
  streaming: boolean
}): ReactElement {
  const [html, setHtml] = useState<string | null>(null)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    if (streaming) return
    // 流式期间 code 会持续变化：做短 debounce，只在停顿后高亮一次，
    // 避免每个 delta 都跑一遍 TextMate 正则高亮（大代码块会卡顿）。
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
    }
    timerRef.current = window.setTimeout(() => {
      ;(async () => {
        try {
          const highlighter = await getHighlighter()
          const out = highlighter.codeToHtml(code, {
            lang,
            theme: THEME,
          })
          setHtml(out)
        } catch {
          // 高亮失败：保留纯文本 <pre><code>，不影响回复内容。
        }
      })()
    }, 120)
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current)
      }
      timerRef.current = null
    }
  }, [code, lang, streaming])

  if (html !== null) {
    return (
      <div
        className="assistant-code"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    )
  }
  return (
    <pre className="assistant-code">
      <code>{code}</code>
    </pre>
  )
}

/** 创建 `components` 对应的数据或流程。 */
const createComponents = (streaming: boolean): Components => ({
  // 块级代码由 pre 检测 language-* 后交给 Shiki；无语言的块级代码保留默认 <pre>。
  pre({ children }) {
    const child = Children.toArray(children)[0]
    if (isValidElement<{ className?: string; children?: ReactNode }>(child)) {
      const match = /language-(\w+)/.exec(child.props.className ?? '')
      if (match && match[1]) {
        const lang = match[1]
        const text = String(child.props.children ?? '').replace(/\n$/, '')
        if (lang in LANG_BUNDLES) {
          return <CodeBlock code={text} lang={lang} streaming={streaming} />
        }
        return (
          <pre className="assistant-code">
            <code>{text}</code>
          </pre>
        )
      }
    }
    return <pre>{children}</pre>
  },
  /** 执行 `code` 对应的界面或业务逻辑。 */
  code({ className, children }) {
    return <code className={className}>{children}</code>
  },
  /** 执行 `a` 对应的界面或业务逻辑。 */
  a({ href, children }) {
    const external = href?.startsWith('http://') || href?.startsWith('https://')
    return (
      <a
        href={href}
        {...(external ? { target: '_blank', rel: 'noreferrer' } : {})}
      >
        {children}
      </a>
    )
  },
})

/** Assistant 消息正文。memo：content 引用未变时跳过整块 markdown 解析，
避免父组件因流式事件频繁重渲染导致正文每秒几十次全量解析。
streaming=true 时不执行 Shiki 代码高亮。 */
export const AssistantContent = memo(/** 执行 `AssistantContent` 对应的界面或业务逻辑。 */ function AssistantContent({
  content,
  streaming = false,
}: {
  content: string
  streaming?: boolean
}): React.JSX.Element {
  return (
    <div className="message-assistant__body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={createComponents(streaming)}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
})

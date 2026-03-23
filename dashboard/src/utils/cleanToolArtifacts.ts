/**
 * Strip raw tool call/response blocks that the LLM may emit as inline text
 * when tools are passed directly to the streaming call (skip_tool_preresolution).
 * Handles complete blocks, partial/truncated tags, and orphaned JSON fragments.
 */
export function cleanToolArtifacts(text: string): string {
  let cleaned = text

  // 1. Remove complete paired blocks (with or without underscore):
  //    <tool_call>...</tool_call>, <toolcall>...</toolcall>, <tool_response>...</tool_response>, etc.
  cleaned = cleaned.replace(/<tool_?call>[\s\S]*?<\/tool_?call>/g, '')
  cleaned = cleaned.replace(/<tool_?response>[\s\S]*?<\/tool_?response>/g, '')

  // 2. Remove partial/truncated tool blocks: anything from a tool-like marker to a closing tag
  cleaned = cleaned.replace(/_?call>[\s\S]*?<\/tool[_\s>]/g, '')
  cleaned = cleaned.replace(/_?response>[\s\S]*?<\/tool[_\s>]/g, '')

  // 3. Remove orphaned opening/closing tags and fragments (with or without underscore)
  cleaned = cleaned.replace(/<\/?tool_?(?:call|response)?>/g, '')
  cleaned = cleaned.replace(/<\/tool\b[^>]*>/g, '')
  cleaned = cleaned.replace(/\b_?(?:call|response)>/g, '')

  // 4. Remove bare JSON tool invocations: {"name": "...", "parameters": {...}}
  cleaned = cleaned.replace(/\{"name":\s*"[^"]+",\s*"parameters":\s*\{[^}]*\}\s*\}/g, '')
  // Also handle broken ones missing the opening brace: "tool_name", "parameters": {...}}
  cleaned = cleaned.replace(/"[a-z_]+",\s*"parameters":\s*\{[^}]*\}\s*\}/g, '')

  // 5. Remove JSON array/object responses from tools
  cleaned = cleaned.replace(/\[\s*\{[^[\]]*?"type"\s*:\s*"(?:file|directory)"[^[\]]*?\}\s*\]/g, '')
  cleaned = cleaned.replace(/\{\s*"task_id"\s*:[\s\S]*?\}\s*/g, '')

  // 6. Collapse excessive whitespace left behind
  cleaned = cleaned.replace(/\n{3,}/g, '\n\n')
  cleaned = cleaned.replace(/[ \t]+\n/g, '\n')

  return cleaned.trim()
}

// Markers that signal a potential tool block is starting
const TOOL_OPENERS = ['<tool_call', '<tool_response', '_call>', 'call>']

/**
 * Returns the "safe" portion of streaming content — holds back any
 * partially-accumulated tool blocks so they never flash on screen.
 * Handles both XML-style (<tool_call>) and raw JSON ({"name":...}) tool patterns.
 */
export function getStableContent(raw: string): string {
  let holdBackFrom = -1

  // --- 1. XML tool block detection ---
  for (const marker of TOOL_OPENERS) {
    const pos = raw.lastIndexOf(marker)
    if (pos !== -1) {
      const hasClose = /<\/tool_(call|response)>/.test(raw.slice(pos))
      if (!hasClose) {
        holdBackFrom = holdBackFrom === -1 ? pos : Math.min(holdBackFrom, pos)
      }
    }
  }

  // Partial XML tags at end: <t, <to, <tool, <tool_, etc.
  const partialXml = raw.match(
    /<t(?:o(?:o(?:l(?:_(?:c(?:a(?:l(?:l)?)?)?|r(?:e(?:s(?:p(?:o(?:n(?:s(?:e)?)?)?)?)?)?)?)?)?)?)?)?$/,
  )
  if (partialXml) {
    const pos = partialXml.index!
    holdBackFrom = holdBackFrom === -1 ? pos : Math.min(holdBackFrom, pos)
  }

  // --- 2. JSON tool invocation detection ---
  // Unclosed {"  — likely a tool call or response JSON streaming in
  const lastJsonObj = raw.lastIndexOf('{"')
  if (lastJsonObj !== -1) {
    const tail = raw.slice(lastJsonObj)
    const opens = (tail.match(/{/g) || []).length
    const closes = (tail.match(/}/g) || []).length
    if (opens > closes) {
      holdBackFrom = holdBackFrom === -1 ? lastJsonObj : Math.min(holdBackFrom, lastJsonObj)
    }
  }

  // Lone { at the very end — might become {"
  if (raw.endsWith('{')) {
    const pos = raw.length - 1
    holdBackFrom = holdBackFrom === -1 ? pos : Math.min(holdBackFrom, pos)
  }

  // Unclosed JSON array containing objects: [\s*{ without ]
  const arrayMatch = raw.match(/\[\s*\{[^\[\]]*$/)
  if (arrayMatch) {
    const pos = arrayMatch.index!
    holdBackFrom = holdBackFrom === -1 ? pos : Math.min(holdBackFrom, pos)
  }

  // --- 3. Apply holdback ---
  if (holdBackFrom === -1) {
    return cleanToolArtifacts(raw)
  }

  return cleanToolArtifacts(raw.slice(0, holdBackFrom))
}

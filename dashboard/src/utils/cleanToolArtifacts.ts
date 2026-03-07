/**
 * Strip raw tool call/response blocks that the LLM may emit as inline text
 * when tools are passed directly to the streaming call (skip_tool_preresolution).
 * Handles complete blocks, partial/truncated tags, and orphaned JSON fragments.
 */
export function cleanToolArtifacts(text: string): string {
  let cleaned = text

  // 1. Remove complete paired blocks: <tool_call>...</tool_call>, <tool_response>...</tool_response>
  cleaned = cleaned.replace(/<tool_call>[\s\S]*?<\/tool_call>/g, '')
  cleaned = cleaned.replace(/<tool_response>[\s\S]*?<\/tool_response>/g, '')

  // 2. Remove partial/truncated tool blocks: anything from a tool-like marker to a closing tag
  //    Handles: _call>{...}</tool_call>, call>{...}</tool_call>, etc.
  cleaned = cleaned.replace(/_?call>[\s\S]*?<\/tool[_\s>]/g, '')
  cleaned = cleaned.replace(/_?response>[\s\S]*?<\/tool[_\s>]/g, '')

  // 3. Remove orphaned closing tags and fragments
  cleaned = cleaned.replace(/<\/tool_?(?:call|response)?>/g, '')
  cleaned = cleaned.replace(/<\/tool\b[^>]*>/g, '')
  cleaned = cleaned.replace(/<tool_(?:call|response)>/g, '')
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
 */
export function getStableContent(raw: string): string {
  // Find the latest unclosed tool-block opener
  let holdBackFrom = -1
  for (const marker of TOOL_OPENERS) {
    const pos = raw.lastIndexOf(marker)
    if (pos > holdBackFrom) holdBackFrom = pos
  }

  if (holdBackFrom === -1) {
    // Also check for partial tags being typed: <t, <to, <tool, <tool_, etc.
    const partialMatch = raw.match(
      /<t(?:o(?:o(?:l(?:_(?:c(?:a(?:l(?:l)?)?)?|r(?:e(?:s(?:p(?:o(?:n(?:s(?:e)?)?)?)?)?)?)?)?)?)?)?)?$/,
    )
    if (partialMatch) holdBackFrom = partialMatch.index!
  }

  if (holdBackFrom === -1) {
    // No tool markers — clean and return everything
    return cleanToolArtifacts(raw)
  }

  // Check if there's a closing tag after the opener (block is complete)
  const afterOpener = raw.slice(holdBackFrom)
  const hasClose = /<\/tool_(call|response)>/.test(afterOpener)

  if (hasClose) {
    // Complete block — clean everything
    return cleanToolArtifacts(raw)
  }

  // Unclosed block — only display content before it
  return cleanToolArtifacts(raw.slice(0, holdBackFrom))
}

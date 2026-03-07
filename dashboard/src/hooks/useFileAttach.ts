import { useCallback } from 'react'
import { useChatStore, type AttachedFile } from '../stores/chat-store'

const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']
const TEXT_EXTENSIONS = ['.py', '.js', '.ts', '.tsx', '.md', '.txt', '.json', '.csv', '.html', '.css', '.yaml', '.yml', '.toml', '.sh']
const MAX_IMAGE_SIZE = 5 * 1024 * 1024   // 5MB
const MAX_TEXT_SIZE = 10 * 1024 * 1024    // 10MB
const MAX_FILES = 5

function classifyFile(file: File): 'image' | 'text' | null {
  if (IMAGE_TYPES.includes(file.type)) return 'image'
  const ext = '.' + file.name.split('.').pop()?.toLowerCase()
  if (TEXT_EXTENSIONS.includes(ext)) return 'text'
  if (file.type.startsWith('text/')) return 'text'
  return null
}

export function useFileAttach() {
  const { pendingFiles, setPendingFiles } = useChatStore()

  const addFiles = useCallback((files: FileList | File[]) => {
    const incoming = Array.from(files)
    setPendingFiles(prev => {
      const available = MAX_FILES - prev.length
      if (available <= 0) return prev

      const valid: AttachedFile[] = []
      for (const file of incoming.slice(0, available)) {
        const fileType = classifyFile(file)
        if (!fileType) continue
        const maxSize = fileType === 'image' ? MAX_IMAGE_SIZE : MAX_TEXT_SIZE
        if (file.size > maxSize) continue

        valid.push({
          id: crypto.randomUUID(),
          file,
          previewUrl: fileType === 'image' ? URL.createObjectURL(file) : null,
          type: fileType,
        })
      }
      return [...prev, ...valid]
    })
  }, [setPendingFiles])

  const removeFile = useCallback((id: string) => {
    setPendingFiles(prev => {
      const file = prev.find(f => f.id === id)
      if (file?.previewUrl) URL.revokeObjectURL(file.previewUrl)
      return prev.filter(f => f.id !== id)
    })
  }, [setPendingFiles])

  const clearFiles = useCallback(() => {
    setPendingFiles(prev => {
      prev.forEach(f => { if (f.previewUrl) URL.revokeObjectURL(f.previewUrl) })
      return []
    })
  }, [setPendingFiles])

  const openFilePicker = useCallback(() => {
    const input = document.createElement('input')
    input.type = 'file'
    input.multiple = true
    input.accept = [...IMAGE_TYPES, ...TEXT_EXTENSIONS.map(e => e)].join(',')
    input.onchange = () => {
      if (input.files) addFiles(input.files)
    }
    input.click()
  }, [addFiles])

  return {
    pendingFiles,
    addFiles,
    removeFile,
    clearFiles,
    openFilePicker,
  }
}

import { describe, it, expect, beforeEach } from "vitest"
import { useChatStore } from "../chatStore"

beforeEach(() => {
  localStorage.clear()
  useChatStore.setState({
    conversationId: null,
    streamingContent: "",
    isStreaming: false,
  })
})

it("setConversation updates conversationId", () => {
  useChatStore.getState().setConversation("c1")
  expect(useChatStore.getState().conversationId).toBe("c1")
})

it("startStreaming sets isStreaming true and resets content", () => {
  useChatStore.getState().startStreaming()
  expect(useChatStore.getState().isStreaming).toBe(true)
  expect(useChatStore.getState().streamingContent).toBe("")
})

it("appendDelta accumulates streaming content", () => {
  useChatStore.getState().startStreaming()
  useChatStore.getState().appendDelta("Hello")
  useChatStore.getState().appendDelta(" World")
  expect(useChatStore.getState().streamingContent).toBe("Hello World")
})

it("finishStreaming clears isStreaming and content", () => {
  useChatStore.getState().startStreaming()
  useChatStore.getState().appendDelta("hi")
  useChatStore.getState().finishStreaming()
  expect(useChatStore.getState().isStreaming).toBe(false)
  expect(useChatStore.getState().streamingContent).toBe("")
})

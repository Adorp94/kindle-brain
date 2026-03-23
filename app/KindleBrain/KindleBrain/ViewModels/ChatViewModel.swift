import SwiftUI

@MainActor
class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var inputText = ""
    @Published var isLoading = false
    @Published var thinkingText = ""
    @Published var conversations: [Conversation] = []
    @Published var currentConversationId: String?

    private let api = APIService.shared
    private let store = ChatStore.shared
    private var streamTask: Task<Void, Never>?

    let suggestions = [
        "What did Steve Jobs think about design?",
        "Connecting ideas about leadership across books",
        "Filosofia estoica en mis lecturas",
        "What have I read about decision-making under uncertainty?",
    ]

    func loadConversations() async {
        conversations = await store.listConversations()
    }

    func newConversation() {
        currentConversationId = nil
        messages = []
    }

    func selectConversation(_ conv: Conversation) async {
        currentConversationId = conv.id
        messages = await store.loadMessages(conversationId: conv.id)
    }

    func deleteConversation(_ conv: Conversation) async {
        await store.deleteConversation(id: conv.id)
        if currentConversationId == conv.id {
            currentConversationId = nil
            messages = []
        }
        await loadConversations()
    }

    func stop() {
        streamTask?.cancel()
        streamTask = nil
        isLoading = false
        thinkingText = ""
        // Save whatever was generated so far
        if let last = messages.last, last.role == .assistant, !last.text.isEmpty,
           let convId = currentConversationId {
            let msg = last
            Task { await store.saveMessage(msg, conversationId: convId) }
        }
    }

    func send() async {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }

        // Create conversation if needed
        if currentConversationId == nil {
            let convId = UUID().uuidString
            let title = String(text.prefix(60))
            await store.createConversation(id: convId, title: title)
            currentConversationId = convId
        }

        let userMessage = ChatMessage(role: .user, text: text)
        messages.append(userMessage)
        inputText = ""
        isLoading = true
        thinkingText = ""

        // Save user message
        if let convId = currentConversationId {
            await store.saveMessage(userMessage, conversationId: convId)
        }

        let assistantMessage = ChatMessage(role: .assistant, text: "")
        messages.append(assistantMessage)
        let assistantIndex = messages.count - 1

        streamTask = Task {
            do {
                let stream = await api.chatStream(message: text, conversationId: currentConversationId)
                for try await event in stream {
                    if Task.isCancelled { break }
                    switch event {
                    case .sources(let sources):
                        messages[assistantIndex].sources = sources
                    case .toolCall(let info):
                        messages[assistantIndex].toolCalls.append(info)
                    case .thinking(let thought):
                        thinkingText = thought
                    case .token(let token):
                        // First token clears thinking state
                        if thinkingText != "" { thinkingText = "" }
                        messages[assistantIndex].text += token
                    case .done:
                        break
                    }
                }
            } catch {
                if !Task.isCancelled {
                    // Fallback to non-streaming
                    do {
                        let response = try await api.chat(message: text)
                        messages[assistantIndex].text = response.response
                        messages[assistantIndex].sources = response.sources
                    } catch {
                        messages[assistantIndex].text = "Error: Could not connect to the API server. Make sure it's running on localhost:8765."
                    }
                }
            }

            if !Task.isCancelled {
                if let convId = currentConversationId {
                    await store.saveMessage(messages[assistantIndex], conversationId: convId)
                }
            }

            isLoading = false
            thinkingText = ""
            streamTask = nil
            await loadConversations()
        }
    }

    func clearHistory() {
        if let convId = currentConversationId {
            Task { await store.deleteConversation(id: convId) }
        }
        currentConversationId = nil
        messages.removeAll()
        Task { await loadConversations() }
    }
}

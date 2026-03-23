import SwiftUI

@MainActor
class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var inputText = ""
    @Published var isLoading = false
    @Published var thinkingText = ""
    @Published var conversations: [Conversation] = []
    @Published var currentConversationId: String?

    private let data = DataService.shared
    private let gemini = GeminiService.shared
    private let store = ChatStore.shared
    private var streamTask: Task<Void, Never>?

    let suggestions = [
        "What did Steve Jobs think about design?",
        "Connecting ideas about leadership across books",
        "Filosofia estoica en mis lecturas",
        "What have I read about decision-making under uncertainty?",
    ]

    // MARK: - Library tools for Gemini

    private let libraryTools: [GeminiService.ToolDefinition] = [
        .init(
            name: "browse_library",
            description: """
                Browse the compact catalog of all books. ALWAYS call this FIRST.
                Returns descriptions, tags, and cross-book links for all books.
                Think LATERALLY: biographies teach about leadership, philosophy about business.
                Identify 5-8 relevant books, then call read_book for each.
                """,
            parameters: [:]
        ),
        .init(
            name: "read_book",
            description: """
                Read a book's full file with fingerprint, highlights, and chapter summaries.
                Call browse_library first to identify which books to read.
                """,
            parameters: ["book_title": ["type": "STRING", "description": "Partial title to match"]]
        )
    ]

    private let systemPrompt = """
        Eres un asistente de lectura profunda con acceso a la biblioteca personal del usuario.

        Tienes dos herramientas:
        1. browse_library() — Lee el catálogo compacto de TODOS los libros. SIEMPRE llama esto PRIMERO.
        2. read_book(book_title) — Lee el archivo completo de un libro con highlights y resúmenes.

        ESTRATEGIA:
        1. Llama browse_library() para ver todos los libros disponibles.
        2. Identifica 5-8 libros relevantes pensando LATERALMENTE.
        3. Llama read_book() para cada libro relevante.
        4. Sintetiza las ideas conectando highlights de múltiples libros.

        SÍNTESIS:
        - Usa las palabras exactas del autor — cita textualmente cuando sea poderoso.
        - Conecta ideas entre libros.
        - Cita siempre la fuente — formato: (*Libro — Autor, p. X*) en cursiva.
        - Responde en el idioma del usuario.
        - Sé profundo — conecta 3-5+ fuentes con profundidad.

        FORMATO:
        - Párrafos claros y separados.
        - **Negritas** para ideas clave, *cursivas* para citas.
        - Encabezados (## o ###) cuando toque múltiples temas.
        - Bloques de cita (> ) para citas textuales impactantes.
        - Fuentes en cursiva: (*Steve Jobs — Walter Isaacson, p. 450*)
        """

    // MARK: - Conversations

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
        if let last = messages.last, last.role == .assistant, !last.text.isEmpty,
           let convId = currentConversationId {
            let msg = last
            Task { await store.saveMessage(msg, conversationId: convId) }
        }
    }

    // MARK: - Send Message

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

        if let convId = currentConversationId {
            await store.saveMessage(userMessage, conversationId: convId)
        }

        let assistantMessage = ChatMessage(role: .assistant, text: "")
        messages.append(assistantMessage)
        let assistantIndex = messages.count - 1

        streamTask = Task {
            do {
                // Tool executor runs locally — reads files from disk
                let toolExecutor: GeminiService.ToolExecutor = { [data] name, args in
                    switch name {
                    case "browse_library":
                        let dataDir: URL
                        if let env = ProcessInfo.processInfo.environment["KINDLE_BRAIN_DATA"] {
                            dataDir = URL(filePath: env)
                        } else {
                            dataDir = FileManager.default.homeDirectoryForCurrentUser
                                .appendingPathComponent(".kindle-brain")
                        }
                        let catalogPath = dataDir.appendingPathComponent("books_md/CATALOG.md")
                        return (try? String(contentsOf: catalogPath, encoding: .utf8)) ?? "CATALOG.md not found"

                    case "read_book":
                        let title = args["book_title"] as? String ?? ""
                        let dataDir: URL
                        if let env = ProcessInfo.processInfo.environment["KINDLE_BRAIN_DATA"] {
                            dataDir = URL(filePath: env)
                        } else {
                            dataDir = FileManager.default.homeDirectoryForCurrentUser
                                .appendingPathComponent(".kindle-brain")
                        }
                        let booksDir = dataDir.appendingPathComponent("books_md")
                        guard let files = try? FileManager.default.contentsOfDirectory(at: booksDir, includingPropertiesForKeys: nil) else {
                            return "Books directory not found"
                        }
                        let skip: Set<String> = ["LIBRARY.md", "CATALOG.md"]
                        let matches = files.filter {
                            $0.pathExtension == "md"
                            && !skip.contains($0.lastPathComponent)
                            && $0.deletingPathExtension().lastPathComponent.lowercased().contains(title.lowercased())
                        }
                        guard let match = matches.first else {
                            return "No book found matching '\(title)'"
                        }
                        var content = (try? String(contentsOf: match, encoding: .utf8)) ?? ""
                        // Strip golden nuggets
                        if let regex = try? NSRegularExpression(
                            pattern: "<details>\\s*<summary>Golden Nugget \\(context\\)</summary>[\\s\\S]*?</details>\\s*"
                        ) {
                            content = regex.stringByReplacingMatches(
                                in: content, range: NSRange(content.startIndex..., in: content), withTemplate: ""
                            )
                        }
                        return content

                    default:
                        return "Unknown tool: \(name)"
                    }
                }

                let stream = await gemini.chatStream(
                    message: text,
                    systemPrompt: systemPrompt,
                    tools: libraryTools,
                    executeToolCall: toolExecutor
                )

                for try await event in stream {
                    if Task.isCancelled { break }
                    switch event {
                    case .toolCall(let info):
                        messages[assistantIndex].toolCalls.append(info)
                    case .token(let token):
                        if thinkingText != "" { thinkingText = "" }
                        messages[assistantIndex].text += token
                    case .done:
                        break
                    }
                }
            } catch {
                if !Task.isCancelled {
                    messages[assistantIndex].text = "Error: \(error.localizedDescription)"
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
